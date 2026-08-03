"""Feature 2 - text to speech."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal, get_db
from ..deps import current_plan, get_current_user
from ..models import Job, JobStatus, SubscriptionPlan, User
from ..schemas import JobOut, TTSIn
from ..security import limiter
from ..services import tts_service
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.tts")
router = APIRouter(prefix="/api/tts", tags=["tts"])


@router.get("/voices")
async def voices(user: User = Depends(get_current_user)):
    return await tts_service.list_voices()


@router.post("/estimate")
async def estimate(payload: TTSIn, user: User = Depends(get_current_user)):
    cost = credit_utils.with_priority(credit_utils.estimate_tts(len(payload.text)), payload.priority)
    return {"characters": len(payload.text), "credits": cost, "provider": tts_service.provider()}


@router.post("/generate", response_model=JobOut, status_code=202)
@limiter.limit("40/minute")
async def generate(
    request: Request,
    payload: TTSIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    if payload.priority and not plan.priority_queue:
        raise HTTPException(403, "Priority processing unlocks on Pro and above.")
    if tts_service.provider() == "none":
        from ..utils.errors import FeatureUnavailable
        raise FeatureUnavailable("Text to speech", "ELEVENLABS_API_KEY")

    cost = credit_utils.with_priority(credit_utils.estimate_tts(len(payload.text)), payload.priority)
    await credit_utils.charge(db, user, cost, "tts", f"Voiceover, {len(payload.text)} characters")
    job = await job_utils.create_job(db, user, "tts", payload.model_dump(), cost, payload.priority)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.tts.run", _run_tts, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run_tts(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            await job_utils.update_progress(db, job, 15, "Sending text to the voice engine", JobStatus.running)
            await db.commit()

            dest = user_dir(user_id) / unique_name("voiceover.mp3")
            await tts_service.synthesise(
                payload["text"], dest,
                voice_id=payload["voice_id"], language=payload["language"],
                speed=payload["speed"], stability=payload["stability"],
            )

            await job_utils.update_progress(db, job, 80, "Saving audio")
            record = await register_file(db, user, dest, "voiceover.mp3", "audio/mpeg", job_id=job.id)
            await job_utils.complete_job(db, job, {
                "file_id": record.id, "filename": record.filename,
                "duration": record.duration_seconds, "provider": tts_service.provider(),
            })
            await db.commit()
        except Exception as exc:
            log.exception("TTS job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: voiceover failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()
