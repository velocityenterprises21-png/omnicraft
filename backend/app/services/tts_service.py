"""Text to speech. ElevenLabs first, OpenAI second, local espeak-ng as a fallback."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..utils.errors import FeatureUnavailable

log = logging.getLogger("omnicraft.tts")

BUILTIN_VOICES = [
    {"id": "rachel", "name": "Rachel", "gender": "female", "accent": "American", "tone": "warm narration"},
    {"id": "adam", "name": "Adam", "gender": "male", "accent": "American", "tone": "deep documentary"},
    {"id": "bella", "name": "Bella", "gender": "female", "accent": "British", "tone": "bright explainer"},
    {"id": "antoni", "name": "Antoni", "gender": "male", "accent": "American", "tone": "conversational"},
    {"id": "elli", "name": "Elli", "gender": "female", "accent": "American", "tone": "youthful"},
    {"id": "josh", "name": "Josh", "gender": "male", "accent": "American", "tone": "trailer"},
]

OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


def provider() -> str:
    if settings.ELEVENLABS_API_KEY:
        return "elevenlabs"
    if settings.OPENAI_API_KEY:
        return "openai"
    if shutil.which("espeak-ng") or shutil.which("espeak"):
        return "espeak"
    return "none"


async def list_voices() -> dict[str, Any]:
    active = provider()
    if active == "elevenlabs":
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://api.elevenlabs.io/v1/voices",
                    headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
                )
                resp.raise_for_status()
                voices = [
                    {
                        "id": v["voice_id"],
                        "name": v["name"],
                        "gender": v.get("labels", {}).get("gender", "unknown"),
                        "accent": v.get("labels", {}).get("accent", ""),
                        "tone": v.get("labels", {}).get("description", ""),
                        "preview_url": v.get("preview_url"),
                    }
                    for v in resp.json().get("voices", [])
                ]
                return {"provider": "elevenlabs", "voices": voices}
        except httpx.HTTPError as exc:
            log.warning("ElevenLabs voice list failed: %s", exc)

    if active == "openai":
        return {
            "provider": "openai",
            "voices": [{"id": v, "name": v.title(), "gender": "neutral", "tone": "studio"} for v in OPENAI_VOICES],
        }

    if active == "espeak":
        return {
            "provider": "espeak",
            "voices": [{"id": "espeak-en", "name": "System voice", "gender": "neutral", "tone": "robotic preview"}],
            "notice": "Running on the offline system voice. Add ELEVENLABS_API_KEY for production audio.",
        }

    return {
        "provider": "none",
        "voices": BUILTIN_VOICES,
        "notice": "No speech provider connected. Add ELEVENLABS_API_KEY or OPENAI_API_KEY to generate audio.",
    }


#: Longest text sent to a provider in one request. OpenAI's speech endpoint
#: hard-caps around 4096 characters; ElevenLabs degrades on very long input.
CHUNK_LIMIT = 3500


def split_for_synthesis(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Break long copy on sentence boundaries so joins land in natural pauses."""
    text = text.strip()
    if len(text) <= limit:
        return [text]

    import re
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # A single sentence longer than the limit still has to be cut somewhere.
        while len(sentence) > limit:
            if current:
                chunks.append(current.strip())
                current = ""
            cut = sentence.rfind(" ", 0, limit)
            cut = cut if cut > limit // 2 else limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].lstrip()
        if len(current) + len(sentence) + 1 > limit:
            chunks.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


async def synthesise(
    text: str,
    dest: Path,
    voice_id: str = "default",
    language: str = "en",
    speed: float = 1.0,
    stability: float = 0.5,
) -> Path:
    active = provider()
    dest.parent.mkdir(parents=True, exist_ok=True)

    chunks = split_for_synthesis(text)
    if len(chunks) > 1:
        log.info("Script is %d characters; rendering in %d passes.", len(text), len(chunks))
        from .ffmpeg_service import concat_audio
        parts: list[Path] = []
        try:
            for index, chunk in enumerate(chunks):
                part = dest.with_name(f"{dest.stem}-part{index:03d}{dest.suffix}")
                await _one(active, chunk, part, voice_id, language, speed, stability)
                parts.append(part)
            await concat_audio(parts, dest)
        finally:
            for part in parts:
                part.unlink(missing_ok=True)
        return dest

    return await _one(active, chunks[0] if chunks else text, dest,
                      voice_id, language, speed, stability)


async def _one(
    active: str, text: str, dest: Path, voice_id: str,
    language: str, speed: float, stability: float,
) -> Path:
    if active == "elevenlabs":
        return await _elevenlabs(text, dest, voice_id, stability, speed)
    if active == "openai":
        return await _openai(text, dest, voice_id, speed)
    if active == "espeak":
        return await _espeak(text, dest, language, speed)

    raise FeatureUnavailable(
        "Text to speech",
        "ELEVENLABS_API_KEY",
        "Install espeak-ng on the server for an offline preview voice.",
    )


async def _elevenlabs(text: str, dest: Path, voice_id: str, stability: float, speed: float) -> Path:
    resolved = voice_id if voice_id and voice_id != "default" else "21m00Tcm4TlvDq8ikWAM"
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{resolved}",
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY, "accept": "audio/mpeg"},
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": 0.75,
                    "style": 0.15,
                    "use_speaker_boost": True,
                    "speed": speed,
                },
            },
        )
        if resp.status_code == 401:
            raise FeatureUnavailable("ElevenLabs", "ELEVENLABS_API_KEY")
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


async def _openai(text: str, dest: Path, voice_id: str, speed: float) -> Path:
    voice = voice_id if voice_id in OPENAI_VOICES else "alloy"
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": "tts-1-hd", "voice": voice, "input": text,
                  "response_format": "mp3", "speed": max(0.25, min(4.0, speed))},
        )
        resp.raise_for_status()
        dest.write_bytes(resp.content)
    return dest


async def _espeak(text: str, dest: Path, language: str, speed: float) -> Path:
    binary = shutil.which("espeak-ng") or shutil.which("espeak")
    wav = dest.with_suffix(".wav")
    proc = await asyncio.create_subprocess_exec(
        binary, "-v", language, "-s", str(int(175 * speed)), "-w", str(wav), text[:20000],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Offline speech failed: {err.decode(errors='replace')[:300]}")
    from .ffmpeg_service import to_mp3
    await to_mp3(wav, dest)
    wav.unlink(missing_ok=True)
    return dest
