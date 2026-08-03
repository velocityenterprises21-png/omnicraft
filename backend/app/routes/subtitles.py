"""Feature 4 - subtitle extraction and translation."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import File, Job, JobStatus, User
from ..schemas import JobOut, SubtitleExtractIn, SubtitleTranslateIn
from ..security import limiter
from ..services import downloader, transcription, translation
from ..services import ffmpeg_service as ff
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir

log = logging.getLogger("omnicraft.routes.subtitles")
router = APIRouter(prefix="/api/subtitles", tags=["subtitles"])


@router.get("/languages")
async def languages():
    return {
        "languages": [{"code": c, "name": n} for c, n in sorted(translation.LANGUAGES.items(), key=lambda x: x[1])],
        "engine": transcription.provider(),
    }


@router.post("/extract", response_model=JobOut, status_code=202)
@limiter.limit("20/minute")
async def extract(
    request: Request,
    payload: SubtitleExtractIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.file_id and not payload.url:
        raise HTTPException(400, "Pick a file from your library or paste a link.")
    if payload.file_id:
        record = await db.get(File, payload.file_id)
        if not record or record.user_id != user.id:
            raise HTTPException(404, "That file isn't in your library.")
    if payload.url and not downloader.host_supported(payload.url):
        raise HTTPException(400, "That host isn't in the supported list.")

    cost = credit_utils.with_priority(CREDIT_COSTS["subtitles.extract"], payload.priority)
    await credit_utils.charge(db, user, cost, "subtitles.extract", "Subtitle extraction")
    job = await job_utils.create_job(db, user, "subtitles.extract", payload.model_dump(), cost, payload.priority)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.subtitles.run", _run_extract, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run_extract(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            workdir = user_dir(user_id)
            fetched_source = None
            await job_utils.update_progress(db, job, 8, "Locating media", JobStatus.running)
            await db.commit()

            if payload.get("file_id"):
                record = await db.get(File, payload["file_id"])
                source = Path(record.file_path)
                label = Path(record.filename).stem
            else:
                await job_utils.update_progress(db, job, 18, "Fetching audio from the link")
                await db.commit()
                result = await downloader.fetch(payload["url"], workdir, quality="audio", audio_only=True)
                source = result["path"]
                label = result["title"]
                fetched_source = source  # temporary; removed once transcribed

            await job_utils.update_progress(db, job, 40, "Extracting the audio track")
            await db.commit()
            audio = workdir / unique_name("stt.wav")
            await ff.extract_audio(source, audio)

            await job_utils.update_progress(db, job, 55, "Transcribing speech")
            await db.commit()
            result = await transcription.transcribe(audio, payload["language"])
            audio.unlink(missing_ok=True)
            if fetched_source:
                Path(fetched_source).unlink(missing_ok=True)

            await job_utils.update_progress(db, job, 88, "Writing the subtitle file")
            body = transcription.render(result["segments"], payload["format"])
            dest = workdir / unique_name(f"{label}.{payload['format']}")
            dest.write_text(body, encoding="utf-8")
            record = await register_file(db, user, dest, dest.name, "text/plain", job_id=job.id)

            await job_utils.complete_job(db, job, {
                "file_id": record.id,
                "filename": record.filename,
                "language": result["language"],
                "segments": len(result["segments"]),
                "engine": result.get("engine"),
                "preview": body[:2000],
                "transcript": result["text"][:20000],
            })
            await db.commit()
        except Exception as exc:
            log.exception("Subtitle job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: extraction failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()


@router.post("/translate", response_model=JobOut, status_code=202)
@limiter.limit("20/minute")
async def translate(
    request: Request,
    payload: SubtitleTranslateIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(File, payload.file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That subtitle file isn't in your library.")
    if payload.target_language not in translation.LANGUAGES:
        raise HTTPException(400, "That language code isn't in the supported list.")

    cost = CREDIT_COSTS["subtitles.translate"]
    await credit_utils.charge(db, user, cost, "subtitles.translate",
                              f"Translate subtitles to {translation.LANGUAGES[payload.target_language]}")
    job = await job_utils.create_job(db, user, "subtitles.translate", payload.model_dump(), cost)
    await db.commit()

    job_utils.dispatch(background, "omnicraft.subtitles.translate", _run_translate, job.id, user.id, payload.model_dump())
    return JobOut.model_validate(job)


async def _run_translate(job_id: str, user_id: str, payload: dict) -> None:
    async with SessionLocal() as db:
        job = await db.get(Job, job_id)
        user = await db.get(User, user_id)
        if not job or not user:
            return
        try:
            record = await db.get(File, payload["file_id"])
            await job_utils.update_progress(db, job, 20, "Reading subtitles", JobStatus.running)
            await db.commit()

            content = Path(record.file_path).read_text(encoding="utf-8", errors="replace")
            segments = transcription.parse_srt(content)
            if not segments:
                raise ValueError("No timed lines found in that file. Upload an SRT or VTT.")

            await job_utils.update_progress(db, job, 45, "Translating lines")
            await db.commit()
            translated = await translation.translate_segments(segments, payload["target_language"])

            body = transcription.render(translated, payload["format"])
            dest = user_dir(user_id) / unique_name(
                f"{Path(record.filename).stem}.{payload['target_language']}.{payload['format']}"
            )
            dest.write_text(body, encoding="utf-8")
            saved = await register_file(db, user, dest, dest.name, "text/plain", job_id=job.id)

            await job_utils.complete_job(db, job, {
                "file_id": saved.id, "filename": saved.filename,
                "language": payload["target_language"], "lines": len(translated),
                "preview": body[:2000],
            })
            await db.commit()
        except Exception as exc:
            log.exception("Translation job %s failed", job_id)
            await credit_utils.refund(db, user, job.credits_charged, "Refund: translation failed", job.id)
            await job_utils.fail_job(db, job, str(exc)[:500])
            await db.commit()
