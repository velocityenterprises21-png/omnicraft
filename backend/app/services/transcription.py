"""Speech to text plus subtitle formatting."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx

from ..config import settings
from ..utils.errors import FeatureUnavailable

log = logging.getLogger("omnicraft.stt")


def provider() -> str:
    try:
        import faster_whisper  # noqa: F401
        return "faster-whisper"
    except ImportError:
        pass
    if settings.OPENAI_API_KEY:
        return "openai-whisper-api"
    return "none"


async def transcribe(audio_path: Path, language: str = "auto") -> dict[str, Any]:
    """Return {language, text, segments:[{start,end,text}]}."""
    active = provider()
    if active == "faster-whisper":
        return await asyncio.to_thread(_local_whisper, audio_path, language)
    if active == "openai-whisper-api":
        return await _openai_whisper(audio_path, language)
    raise FeatureUnavailable(
        "Transcription",
        "OPENAI_API_KEY",
        "Or `pip install faster-whisper` on the server to transcribe locally with no API key.",
    )


def _local_whisper(audio_path: Path, language: str) -> dict[str, Any]:
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="auto", compute_type="int8")
    segments, info = model.transcribe(
        str(audio_path),
        language=None if language == "auto" else language,
        vad_filter=True,
        beam_size=5,
    )
    collected = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
    return {
        "language": info.language,
        "text": " ".join(s["text"] for s in collected),
        "segments": collected,
        "engine": "faster-whisper/base",
    }


async def _openai_whisper(audio_path: Path, language: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=600) as client:
        with audio_path.open("rb") as fh:
            data = {"model": "whisper-1", "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment"}
            if language != "auto":
                data["language"] = language
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
                files={"file": (audio_path.name, fh, "application/octet-stream")},
                data=data,
            )
    resp.raise_for_status()
    payload = resp.json()
    segments = [
        {"start": s["start"], "end": s["end"], "text": s["text"].strip()}
        for s in payload.get("segments", [])
    ]
    if not segments and payload.get("text"):
        segments = [{"start": 0.0, "end": 0.0, "text": payload["text"]}]
    return {
        "language": payload.get("language", language),
        "text": payload.get("text", ""),
        "segments": segments,
        "engine": "whisper-1",
    }


def _stamp(seconds: float, comma: bool = True) -> str:
    td = timedelta(seconds=max(0.0, seconds))
    total = int(td.total_seconds())
    ms = int((td.total_seconds() - total) * 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    sep = "," if comma else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(segments: list[dict[str, Any]]) -> str:
    lines = []
    for idx, seg in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_stamp(seg['start'])} --> {_stamp(seg['end'])}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments: list[dict[str, Any]]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        lines.append(f"{_stamp(seg['start'], comma=False)} --> {_stamp(seg['end'], comma=False)}")
        lines.append(seg["text"].strip())
        lines.append("")
    return "\n".join(lines)


def to_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(seg["text"].strip() for seg in segments)


def to_json(segments: list[dict[str, Any]]) -> str:
    import json as _json
    return _json.dumps(segments, ensure_ascii=False, indent=2)


def render(segments: list[dict[str, Any]], fmt: str) -> str:
    return {"srt": to_srt, "vtt": to_vtt, "txt": to_txt, "json": to_json}.get(fmt, to_srt)(segments)


def parse_srt(content: str) -> list[dict[str, Any]]:
    blocks, segments = content.strip().split("\n\n"), []
    for block in blocks:
        rows = [r for r in block.splitlines() if r.strip()]
        if len(rows) < 2:
            continue
        timing = next((r for r in rows if "-->" in r), None)
        if not timing:
            continue
        start_raw, end_raw = [t.strip() for t in timing.split("-->")]
        text = " ".join(rows[rows.index(timing) + 1:])
        segments.append({"start": _parse_stamp(start_raw), "end": _parse_stamp(end_raw), "text": text})
    return segments


def _parse_stamp(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    h, m, s = (parts + ["0", "0", "0"])[:3]
    return int(h) * 3600 + int(m) * 60 + float(s)
