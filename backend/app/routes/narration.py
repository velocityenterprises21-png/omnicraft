"""Feature 3 - lay narration over an existing video."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..database import SessionLocal, get_db
from ..deps import current_plan, get_current_user
from ..models import File, Job, JobStatus, SubscriptionPlan, User
from ..schemas import JobOut, NarrationIn
from ..security import limiter
from ..services import ffmpeg_service as ff
from ..services import tts_service
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.narration")
router = APIRouter(prefix="/api/narrate", tags=["narration"])


async def _owned(db: AsyncSession, user: User, file_id: str) -> File:
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    if not Path(record.file_path).exists():
        raise HTTPException(410, "That file is no longer on disk. Upload it again.")
    return record


@router.post("", response_model=JobOut, status_code=202)
@limiter.limit("20/minute")
async def narrate(
    request: Request,
    payload: NarrationIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    video = await _owned(db, user, payload.video_file_id)
    if video.kind != "video":
        raise HTTPException(400, "Pick a video file to narrate.")
    if not payload.script and not payload.audio_file_id:
        raise HTTPException(400, "Add a script to speak, or pick an audio file to lay over the video.")
    if payload.audio_file_id:
        await _owned(db, user, payload.audio_file_id)
    if payload.priority and not plan.priority_queue:
        raise HTTPException(403, "Priority processing unlocks on Pro and above.")

    cost = credit_utils.with_priority(CREDIT_COSTS["narration"], payload.priority)
    if payload.script:
        cost += credit_utils.estimate_tts(len(payload.script))
    await credit_utils.charge(db, user, cost, "narration", f"Narration over {video.filename[:60]}")
    job = await job_utils.create_job(db, user, "narration", payload.model_dump(), cost, payload.priority)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.narration.run", _run, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            video = await db.get(File, payload["video_file_id"])
            await job_utils.update_progress(db, job, 10, "Preparing narration", JobStatus.running)
            await db.commit()

            workdir = user_dir(user_id)
            if payload.get("audio_file_id"):
                narration_file = await db.get(File, payload["audio_file_id"])
                narration_path = Path(narration_file.file_path)
            else:
                narration_path = workdir / unique_name("narration.mp3")
                await tts_service.synthesise(payload["script"], narration_path, voice_id=payload["voice_id"])

            await job_utils.update_progress(db, job, 55, "Mixing audio into the timeline")
            await db.commit()

            dest = workdir / unique_name(f"narrated-{Path(video.filename).stem}.mp4")
            await ff.mix_narration(
                Path(video.file_path), narration_path, dest,
                mode=payload["mode"],
                original_volume=payload["original_volume"],
                narration_volume=payload["narration_volume"],
            )

            await job_utils.update_progress(db, job, 90, "Saving output")
            record = await register_file(db, user, dest, dest.name, "video/mp4", job_id=job.id)
            await job_utils.complete_job(db, job, {
                "file_id": record.id, "filename": record.filename, "mode": payload["mode"],
            })
            await db.commit()
        except Exception as exc:
            log.exception("Narration job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: narration failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()


@router.get("/{job_id}", response_model=JobOut)
async def status(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "No job with that id.")
    return JobOut.model_validate(job)
