"""Feature 6 - music rights screening and clearance.

Screens uploads for third-party recordings and offers lawful remedies: mute the
match, lift the music bed off the dialogue, or swap in a track the account is
licensed to use. Evasion transforms are intentionally not offered - the aim is
to clear a claim, not to disguise one.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import File, Job, JobStatus, User
from ..schemas import JobOut, RightsRemediateIn, RightsScanIn
from ..security import limiter
from ..services import ffmpeg_service as ff
from ..services import rights_service
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.rights")
router = APIRouter(prefix="/api/rights", tags=["rights"])


@router.get("/actions")
async def actions():
    return {
        "actions": rights_service.CLEARANCE_ACTIONS,
        "identification_ready": rights_service.fingerprint_available(),
        "note": (
            "Clearance means removing or replacing material you don't hold rights to. "
            "If you do hold a licence, keep the record with the project and publish as is."
        ),
    }


async def _owned(db: AsyncSession, user: User, file_id: str) -> File:
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    return record


@router.post("/scan")
@limiter.limit("20/minute")
async def scan(
    request: Request,
    payload: RightsScanIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await _owned(db, user, payload.file_id)
    if record.kind not in {"video", "audio"}:
        raise HTTPException(400, "Pick a video or audio file to screen.")

    cost = CREDIT_COSTS["rights.scan"]
    await credit_utils.charge(db, user, cost, "rights.scan", f"Rights scan: {record.filename[:60]}")
    await db.commit()

    workdir = user_dir(user.id)
    probe_audio = workdir / unique_name("rights.wav")
    try:
        await ff.extract_audio(Path(record.file_path), probe_audio)
        result = await rights_service.scan(probe_audio, record.duration_seconds)
    except Exception as exc:
        await credit_utils.refund(db, user, cost, "Refund: scan failed")
        await db.commit()
        raise HTTPException(500, f"Screening failed: {str(exc)[:200]}")
    finally:
        probe_audio.unlink(missing_ok=True)

    return {**result, "file_id": record.id, "credits_charged": cost,
            "available_actions": rights_service.CLEARANCE_ACTIONS}


@router.post("/remediate", response_model=JobOut, status_code=202)
@limiter.limit("20/minute")
async def remediate(
    request: Request,
    payload: RightsRemediateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await _owned(db, user, payload.file_id)
    if payload.action == "replace":
        if not payload.replacement_track_id:
            raise HTTPException(400, "Pick a licensed track from your library to lay underneath.")
        await _owned(db, user, payload.replacement_track_id)

    cost = CREDIT_COSTS["rights.remediate"]
    await credit_utils.charge(db, user, cost, "rights.remediate", f"Clearance: {payload.action}")
    job = await job_utils.create_job(db, user, "rights.remediate", payload.model_dump(), cost)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.rights.run", _run, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            record = await db.get(File, payload["file_id"])
            source = Path(record.file_path)
            workdir = user_dir(user_id)
            dest = workdir / unique_name(f"cleared-{Path(record.filename).stem}{source.suffix}")

            await job_utils.update_progress(db, job, 20, "Applying clearance", JobStatus.running)
            await db.commit()

            ranges = [
                (float(s.get("start", 0)), float(s.get("end", 0)))
                for s in (payload.get("segments") or [])
                if float(s.get("end", 0)) > float(s.get("start", 0))
            ]
            if not ranges:
                ranges = [(0.0, float(record.duration_seconds or 0))]

            action = payload["action"]
            if action == "mute":
                await ff.mute_ranges(source, dest, ranges)
            elif action == "remove_music":
                stem = workdir / unique_name("dialogue.wav")
                await rights_service.separate_speech(source, stem)
                await ff.mix_narration(source, stem, dest, mode="replace")
                stem.unlink(missing_ok=True)
            else:
                replacement = await db.get(File, payload["replacement_track_id"])
                await ff.replace_audio_ranges(source, Path(replacement.file_path), dest, ranges)

            await job_utils.update_progress(db, job, 85, "Saving cleared version")
            saved = await register_file(db, user, dest, dest.name, record.file_type, job_id=job.id)
            await job_utils.complete_job(db, job, {
                "file_id": saved.id, "filename": saved.filename, "action": action,
                "ranges": ranges,
            })
            await db.commit()
        except Exception as exc:
            log.exception("Clearance job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: clearance failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()
