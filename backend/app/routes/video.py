"""Feature 12 - AI video creation."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import VIDEO_CREDIT_TABLE
from ..database import SessionLocal, get_db
from ..deps import current_plan, get_current_user
from ..models import File, Job, JobStatus, SubscriptionPlan, User
from ..schemas import JobOut, VideoCreateIn
from ..security import limiter
from ..services import downloader, transcription, tts_service, video_service
from ..services import ffmpeg_service as ff
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.video")
router = APIRouter(prefix="/api/video", tags=["video"])

QUALITY_ORDER = ["480p", "720p", "1080p", "4K", "8K", "8K+"]


@router.get("/config")
async def config(plan: SubscriptionPlan = Depends(current_plan)):
    allowed = QUALITY_ORDER[: QUALITY_ORDER.index(plan.export_quality) + 1] \
        if plan.export_quality in QUALITY_ORDER else ["480p"]
    return {
        "max_duration_seconds": plan.max_video_length or 3600,
        "unlimited_length": plan.max_video_length == 0,
        "allowed_qualities": allowed,
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:5", "21:9"],
        "watermark": plan.watermark,
        "credit_table": VIDEO_CREDIT_TABLE,
        "visual_provider": video_service.visual_provider(),
        "voice_provider": tts_service.provider(),
    }


@router.post("/estimate")
async def estimate(payload: VideoCreateIn, user: User = Depends(get_current_user)):
    cost = credit_utils.with_priority(
        credit_utils.estimate_video(payload.duration_seconds, payload.quality), payload.priority
    )
    return {"credits": cost, "duration_seconds": payload.duration_seconds, "quality": payload.quality}


@router.post("/create", response_model=JobOut, status_code=202)
@limiter.limit("10/minute")
async def create(
    request: Request,
    payload: VideoCreateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    if not any([payload.prompt, payload.script, payload.source_url, payload.source_file_id]):
        raise HTTPException(400, "Describe the video, paste a script, or point at a source to adapt.")
    if plan.max_video_length and payload.duration_seconds > plan.max_video_length:
        raise HTTPException(
            403,
            f"Your plan tops out at {plan.max_video_length // 60} minute videos. "
            f"Upgrade to go longer.",
        )
    if payload.quality in QUALITY_ORDER and plan.export_quality in QUALITY_ORDER:
        if QUALITY_ORDER.index(payload.quality) > QUALITY_ORDER.index(plan.export_quality):
            raise HTTPException(403, f"Your plan exports up to {plan.export_quality}.")
    if payload.priority and not plan.priority_queue:
        raise HTTPException(403, "Priority processing unlocks on Pro and above.")
    if payload.source_file_id:
        record = await db.get(File, payload.source_file_id)
        if not record or record.user_id != user.id:
            raise HTTPException(404, "That source file isn't in your library.")

    cost = credit_utils.with_priority(
        credit_utils.estimate_video(payload.duration_seconds, payload.quality), payload.priority
    )
    await credit_utils.charge(db, user, cost, "video.create",
                              f"AI video, {payload.duration_seconds}s at {payload.quality}")
    job = await job_utils.create_job(db, user, "video.create", payload.model_dump(), cost, payload.priority)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.video.run", _run, job.id, user.id, payload.model_dump(), plan.watermark)
    return JobOut.model_validate(job)


async def _brief_from(db: AsyncSession, user_id: str, payload: dict) -> str:
    if payload.get("script"):
        return payload["script"]
    if payload.get("prompt"):
        return payload["prompt"]

    workdir = user_dir(user_id)
    if payload.get("source_file_id"):
        record = await db.get(File, payload["source_file_id"])
        path = Path(record.file_path)
        if record.kind == "text":
            return path.read_text(encoding="utf-8", errors="replace")[:20000]
        audio = workdir / unique_name("brief.wav")
        await ff.extract_audio(path, audio)
        result = await transcription.transcribe(audio)
        audio.unlink(missing_ok=True)
        return result["text"][:20000]

    fetched = await downloader.fetch(payload["source_url"], workdir, quality="audio", audio_only=True)
    audio = workdir / unique_name("brief.wav")
    await ff.extract_audio(fetched["path"], audio)
    result = await transcription.transcribe(audio)
    audio.unlink(missing_ok=True)
    Path(fetched["path"]).unlink(missing_ok=True)
    return result["text"][:20000]


async def _run(job_id: str, user_id: str, payload: dict, watermark: bool) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            await job_utils.update_progress(db, job, 3, "Reading the brief", JobStatus.running)
            await db.commit()
            brief = await _brief_from(db, user_id, payload)

            async def progress(pct: int, stage: str) -> None:
                async with SessionLocal() as inner:
                    inner_job = await inner.get(Job, job_id)
                    if inner_job:
                        await job_utils.update_progress(inner, inner_job, pct, stage)
                        await inner.commit()

            workdir = user_dir(user_id) / f"render-{job_id}"
            result = await video_service.create_video(
                brief=brief,
                workdir=workdir,
                duration_seconds=payload["duration_seconds"],
                quality=payload["quality"],
                aspect_ratio=payload["aspect_ratio"],
                voice_id=payload["voice_id"],
                captions=payload["captions"],
                watermark="OMNICRAFT" if watermark else None,
                on_progress=progress,
            )

            final = Path(result["path"])
            destination = user_dir(user_id) / unique_name("omnicraft-video.mp4")
            final.replace(destination)
            record = await register_file(db, user, destination, destination.name, "video/mp4", job_id=job.id)

            subtitle_id = None
            if result.get("subtitles") and Path(result["subtitles"]).exists():
                sub_dest = user_dir(user_id) / unique_name("captions.srt")
                Path(result["subtitles"]).replace(sub_dest)
                sub_record = await register_file(db, user, sub_dest, sub_dest.name, "text/plain", job_id=job.id)
                subtitle_id = sub_record.id

            import shutil
            shutil.rmtree(workdir, ignore_errors=True)

            await job_utils.complete_job(db, job, {
                "file_id": record.id,
                "filename": record.filename,
                "subtitle_file_id": subtitle_id,
                "duration": record.duration_seconds,
                "scene_count": len(result["scenes"]),
                "visual_provider": result["visual_provider"],
                "narration_provider": result["narration_provider"],
            })
            await db.commit()
        except Exception as exc:
            log.exception("Video job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: render failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()


@router.get("/{job_id}", response_model=JobOut)
async def status(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "No job with that id.")
    return JobOut.model_validate(job)
