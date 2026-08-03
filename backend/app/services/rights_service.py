"""Music rights screening and clearance.

Scope note
----------
This module identifies third-party recordings in an upload and offers lawful
clearance paths: mute the flagged range, strip the music bed, or swap in a
track the account is licensed to use. It deliberately does not implement
detection-evasion transforms (pitch or tempo shifting applied to keep a
protected recording in place), because the point of a rights tool is to
resolve a claim, not to hide one.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Any

import httpx

from ..config import settings

log = logging.getLogger("omnicraft.rights")

CLEARANCE_ACTIONS = [
    {
        "id": "mute",
        "label": "Mute the flagged range",
        "detail": "Silences only the seconds that matched. The rest of the audio is untouched.",
    },
    {
        "id": "remove_music",
        "label": "Remove the music bed",
        "detail": "Separates speech from music and keeps the dialogue. Needs a source separation model.",
    },
    {
        "id": "replace",
        "label": "Swap in a licensed track",
        "detail": "Mutes the match and lays one of your own library tracks underneath.",
    },
]


def fingerprint_available() -> bool:
    return bool(settings.ACOUSTID_API_KEY) and bool(shutil.which("fpcalc"))


async def scan(audio_path: Path, duration_hint: float | None = None) -> dict[str, Any]:
    """Fingerprint the audio and report any recording matches with timings."""
    if not fingerprint_available():
        return {
            "status": "unavailable",
            "matches": [],
            "message": (
                "Recording identification isn't configured. Add ACOUSTID_API_KEY and install "
                "the Chromaprint `fpcalc` binary to screen uploads automatically."
            ),
            "manual_guidance": (
                "Until then, check the flagged range by ear and confirm your licence before publishing."
            ),
        }

    fingerprint, duration = await _fingerprint(audio_path)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            "https://api.acoustid.org/v2/lookup",
            params={
                "client": settings.ACOUSTID_API_KEY,
                "meta": "recordings releasegroups",
                "duration": int(duration or duration_hint or 0),
                "fingerprint": fingerprint,
            },
        )
    resp.raise_for_status()
    payload = resp.json()

    matches = []
    for result in payload.get("results", []):
        for recording in result.get("recordings", []) or []:
            matches.append({
                "title": recording.get("title"),
                "artists": [a.get("name") for a in recording.get("artists", []) or []],
                "confidence": round(result.get("score", 0), 3),
                "recording_id": recording.get("id"),
                "duration": recording.get("duration"),
                "start": 0.0,
                "end": float(duration or duration_hint or 0),
            })

    return {
        "status": "matched" if matches else "clear",
        "matches": matches[:10],
        "message": (
            f"Identified {len(matches)} commercial recording(s). Clear the rights or pick a remedy below."
            if matches else
            "No commercial recording matched. Keep your own licence records for anything you added."
        ),
    }


async def _fingerprint(audio_path: Path) -> tuple[str, float]:
    proc = await asyncio.create_subprocess_exec(
        "fpcalc", "-json", str(audio_path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Fingerprinting failed: {err.decode(errors='replace')[:200]}")
    import json
    data = json.loads(out.decode())
    return data["fingerprint"], float(data.get("duration", 0))


async def separate_speech(source: Path, dest: Path) -> Path:
    """Keep dialogue, drop the music bed, using Demucs when it is installed."""
    if shutil.which("demucs") is None:
        raise RuntimeError(
            "Source separation isn't installed. Run `pip install demucs` on the worker, "
            "or choose 'Mute the flagged range' instead."
        )
    workdir = dest.parent / "separated"
    proc = await asyncio.create_subprocess_exec(
        "demucs", "--two-stems", "vocals", "-o", str(workdir), str(source),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"Separation failed: {err.decode(errors='replace')[:300]}")
    vocals = next(workdir.rglob("vocals.wav"), None)
    if not vocals:
        raise RuntimeError("Separation produced no vocal stem.")
    shutil.move(str(vocals), dest)
    shutil.rmtree(workdir, ignore_errors=True)
    return dest
