"""Health, capability discovery and the shared job feed."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS, CREDIT_PACKAGES, VIDEO_CREDIT_TABLE, settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Job, User
from ..schemas import JobOut
from ..services import research_service, rights_service, stripe_service, transcription
from ..services import tts_service, video_service
from ..services.llm import llm

router = APIRouter(tags=["system"])


@router.get("/api/health")
async def health(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.APP_NAME,
        "environment": settings.ENVIRONMENT,
        "database": database_ok,
        "ffmpeg": bool(shutil.which(settings.FFMPEG_BIN)),
    }


@router.get("/api/capabilities")
async def capabilities():
    """What actually works right now, given the keys and binaries present."""
    ffmpeg = bool(shutil.which(settings.FFMPEG_BIN))
    try:
        import yt_dlp  # noqa: F401
        ytdlp = True
    except ImportError:
        ytdlp = False

    modules = {
        "download": {
            "ready": ytdlp,
            "note": "" if ytdlp else "Install yt-dlp on the server to enable retrieval.",
        },
        "tts": {
            "ready": tts_service.provider() != "none",
            "provider": tts_service.provider(),
            "note": "" if tts_service.provider() != "none"
            else "Add ELEVENLABS_API_KEY or OPENAI_API_KEY for narration.",
        },
        "narration": {
            "ready": ffmpeg and tts_service.provider() != "none",
            "note": "" if ffmpeg else "ffmpeg isn't installed on the server.",
        },
        "subtitles": {
            "ready": transcription.provider() != "none" and ffmpeg,
            "provider": transcription.provider(),
            "note": "" if transcription.provider() != "none"
            else "Add OPENAI_API_KEY, or pip install faster-whisper to run locally.",
        },
        "translation": {
            "ready": llm.available,
            "provider": llm.provider,
            "note": "" if llm.available else "Add OPENAI_API_KEY or ANTHROPIC_API_KEY.",
        },
        "storyline": {
            "ready": True,
            "provider": llm.provider,
            "note": "" if llm.available
            else "Running the offline extractive summariser. Add a model key for rewriting.",
        },
        "rights": {
            "ready": ffmpeg,
            "identification": rights_service.fingerprint_available(),
            "note": "" if rights_service.fingerprint_available()
            else "Add ACOUSTID_API_KEY and the fpcalc binary to identify recordings automatically.",
        },
        "autopilot": {
            "ready": True,
            "provider": llm.provider,
            "note": "" if llm.available else "Falls back to keyword planning without a model key.",
        },
        "research": {
            "ready": True,
            "engine": "serper" if settings.SERPER_API_KEY else "duckduckgo",
            "note": "" if settings.SERPER_API_KEY
            else "Using the fallback search engine. Add SERPER_API_KEY for better coverage.",
        },
        "storage": {
            "ready": True,
            "backend": settings.STORAGE_BACKEND,
            "note": "",
        },
        "payments": {
            "ready": stripe_service.configured(),
            "note": "" if stripe_service.configured()
            else "Add STRIPE_SECRET_KEY to sell plans and credit packs.",
        },
        "video": {
            "ready": ffmpeg,
            "visuals": video_service.visual_provider(),
            "note": "" if ffmpeg else "ffmpeg isn't installed on the server.",
        },
    }
    return {
        "modules": modules,
        "ffmpeg": ffmpeg,
        "credit_costs": CREDIT_COSTS,
        "credit_packages": CREDIT_PACKAGES,
        "video_credit_table": VIDEO_CREDIT_TABLE,
        "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY or None,
    }


@router.get("/api/jobs", response_model=dict)
async def my_jobs(
    limit: int = 40,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Job).where(Job.user_id == user.id).order_by(desc(Job.created_at)).limit(min(limit, 100))
        )
    ).scalars().all()
    return {"jobs": [JobOut.model_validate(j) for j in rows]}


@router.get("/api/jobs/{job_id}", response_model=JobOut)
async def job_detail(job_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "No job with that id.")
    return JobOut.model_validate(job)


@router.get("/api/languages")
async def languages():
    from ..services.translation import LANGUAGES
    return {"languages": [{"code": c, "name": n} for c, n in sorted(LANGUAGES.items(), key=lambda x: x[1])]}
