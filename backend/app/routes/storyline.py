"""Feature 5 - transcript extraction and rewriting."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..database import get_db
from ..deps import get_current_user
from ..models import File, User
from ..schemas import StorylineIn
from ..security import limiter
from ..services import downloader, transcription
from ..services import ffmpeg_service as ff
from ..services.llm import llm, offline_bullets, offline_summarise
from ..utils import credits as credit_utils
from ..utils.files import unique_name, user_dir

log = logging.getLogger("omnicraft.routes.storyline")
router = APIRouter(prefix="/api/storyline", tags=["storyline"])

MODE_PROMPTS = {
    "summary": "Rewrite this as a clear prose summary. Keep the argument and drop the filler.",
    "bullets": "Turn this into scannable bullet points, one idea per line, strongest first.",
    "clean": "Clean this transcript up: remove filler words and false starts, fix punctuation, keep every idea and the speaker's voice.",
    "script": "Rewrite this as a narration script that reads well aloud. Short sentences, natural rhythm.",
    "chapters": "Break this into chapters. Give each a timestamp-friendly title and a one-line description.",
}


async def _resolve_text(db: AsyncSession, user: User, payload: StorylineIn) -> tuple[str, str]:
    if payload.text:
        return payload.text, "pasted text"

    if payload.source_file_id:
        record = await db.get(File, payload.source_file_id)
        if not record or record.user_id != user.id:
            raise HTTPException(404, "That file isn't in your library.")
        path = Path(record.file_path)
        if record.kind == "text":
            return path.read_text(encoding="utf-8", errors="replace"), record.filename
        audio = user_dir(user.id) / unique_name("storyline.wav")
        await ff.extract_audio(path, audio)
        result = await transcription.transcribe(audio)
        audio.unlink(missing_ok=True)
        return result["text"], record.filename

    if payload.url:
        if not downloader.host_supported(payload.url):
            raise HTTPException(400, "That host isn't in the supported list.")
        fetched = await downloader.fetch(payload.url, user_dir(user.id), quality="audio", audio_only=True)
        audio = user_dir(user.id) / unique_name("storyline.wav")
        await ff.extract_audio(fetched["path"], audio)
        result = await transcription.transcribe(audio)
        audio.unlink(missing_ok=True)
        Path(fetched["path"]).unlink(missing_ok=True)
        return result["text"], fetched["title"]

    raise HTTPException(400, "Give me text to work from: paste it, pick a file, or add a link.")


@router.post("/generate")
@limiter.limit("30/minute")
async def generate(
    request: Request,
    payload: StorylineIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cost = CREDIT_COSTS["storyline"]
    await credit_utils.charge(db, user, cost, "storyline", f"Storyline: {payload.mode}")
    await db.commit()

    try:
        source_text, label = await _resolve_text(db, user, payload)
    except HTTPException:
        await credit_utils.refund(db, user, cost, "Refund: nothing to process")
        await db.commit()
        raise

    if not source_text.strip():
        await credit_utils.refund(db, user, cost, "Refund: empty transcript")
        await db.commit()
        raise HTTPException(422, "No speech was found in that source.")

    trimmed = source_text[:40000]

    if llm.available:
        try:
            output = await llm.complete(
                f"{MODE_PROMPTS[payload.mode]}\n\nTone: {payload.tone}. "
                f"Target length: about {payload.target_words} words.\n\nSource:\n{trimmed}",
                system="You are a script editor. Preserve meaning. Never invent facts that aren't in the source.",
                max_tokens=min(4000, payload.target_words * 3),
            )
        except Exception as exc:
            # A provider outage shouldn't cost the user a credit.
            log.exception("Storyline generation failed")
            await credit_utils.refund(db, user, cost, "Refund: rewrite failed")
            await db.commit()
            raise HTTPException(502, f"The language model didn't respond: {str(exc)[:200]}")
        engine = llm.provider
    else:
        if payload.mode == "bullets":
            output = "\n".join(f"- {b}" for b in offline_bullets(trimmed))
        else:
            output = offline_summarise(trimmed, sentences=max(4, payload.target_words // 25))
        engine = "offline extractive"

    return {
        "mode": payload.mode,
        "source": label,
        "engine": engine,
        "word_count": len(output.split()),
        "source_word_count": len(source_text.split()),
        "transcript": trimmed,
        "output": output,
        "credits_charged": cost,
    }


@router.post("/rephrase")
@limiter.limit("30/minute")
async def rephrase(
    request: Request,
    payload: StorylineIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.text:
        raise HTTPException(400, "Paste the text you want rewritten.")
    return await generate(request, payload, user, db)
