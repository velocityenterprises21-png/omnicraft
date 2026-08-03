"""Feature 1 - source retrieval."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import SessionLocal, get_db
from ..deps import current_plan, get_current_user
from ..models import Job, JobStatus, SubscriptionPlan, User
from ..schemas import DownloadIn, JobOut
from ..security import limiter
from ..services import downloader
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import check_quota, register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.download")
router = APIRouter(prefix="/api/download", tags=["download"])


@router.post("/probe")
@limiter.limit("30/minute")
async def probe(request: Request, payload: DownloadIn, user: User = Depends(get_current_user)):
    if not downloader.host_supported(payload.url):
        raise HTTPException(400, "That host isn't in the supported list. Check the URL and try again.")
    try:
        info = await downloader.probe(payload.url)
    except Exception as exc:
        raise HTTPException(422, f"Couldn't read that link: {str(exc)[:200]}")
    info["estimated_credits"] = credit_utils.with_priority(
        credit_utils.estimate_download(info.get("duration"), payload.quality), payload.priority
    )
    return info


@router.post("", response_model=JobOut, status_code=202)
@limiter.limit("30/minute")
async def start_download(
    request: Request,
    payload: DownloadIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    if not downloader.host_supported(payload.url):
        raise HTTPException(400, "That host isn't in the supported list.")
    if payload.priority and not plan.priority_queue:
        raise HTTPException(403, "Priority processing unlocks on Pro and above.")

    try:
        info = await downloader.probe(payload.url)
    except Exception as exc:
        raise HTTPException(422, f"Couldn't read that link: {str(exc)[:200]}")

    if info.get("is_live"):
        raise HTTPException(400, "Live streams can't be captured. Wait for the recording to be posted.")

    duration = info.get("duration")
    if plan.max_video_length and duration and duration > plan.max_video_length:
        raise HTTPException(
            403,
            f"That source runs {int(duration // 60)} minutes. Your plan caps downloads at "
            f"{plan.max_video_length // 60} minutes.",
        )

    cost = credit_utils.with_priority(
        credit_utils.estimate_download(duration, payload.quality), payload.priority
    )
    await credit_utils.charge(db, user, cost, "download", f"Download: {info.get('title', payload.url)[:80]}")
    job = await job_utils.create_job(
        db, user, "download",
        {"url": payload.url, "quality": payload.quality, "audio_only": payload.audio_only,
         "title": info.get("title"), "duration": duration},
        credits_charged=cost, priority=payload.priority,
    )
    await db.commit()

    job_utils.dispatch(background, "omnicraft.download.run", _run_download, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run_download(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            await job_utils.update_progress(db, job, 5, "Connecting to source", JobStatus.running)
            await db.commit()

            async def progress(pct: int, stage: str) -> None:
                async with SessionLocal() as inner:
                    inner_job = await inner.get(Job, job_id)
                    if inner_job:
                        await job_utils.update_progress(inner, inner_job, pct, stage)
                        await inner.commit()

            result = await downloader.fetch(
                payload["url"], user_dir(user_id),
                quality=payload["quality"], audio_only=payload["audio_only"],
                on_progress=progress,
            )

            path = result["path"]
            plan = (
                await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == user.tier))
            ).scalar_one_or_none()
            if plan:
                await check_quota(db, user, plan, path.stat().st_size)

            renamed = path.with_name(unique_name(path.name))
            path.rename(renamed)
            record = await register_file(db, user, renamed, result["title"] + renamed.suffix, job_id=job.id)

            await job_utils.complete_job(db, job, {
                "file_id": record.id,
                "filename": record.filename,
                "size": record.file_size,
                "duration": record.duration_seconds,
                "source": result.get("extractor"),
            })
            await db.commit()
        except Exception as exc:
            log.exception("Download job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: download failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()


@router.get("/supported")
async def supported_hosts():
    return {"hosts": sorted(downloader.SUPPORTED_HOSTS)}


@router.get("/{job_id}", response_model=JobOut)
async def job_status(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "No job with that id.")
    return JobOut.model_validate(job)
