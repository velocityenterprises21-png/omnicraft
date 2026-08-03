"""AI video assembly.

Pipeline: brief -> scene plan -> narration audio -> visuals -> render -> captions.
Visuals come from a generative provider when one is configured, otherwise from
Pexels stock, otherwise from generated typographic cards so the pipeline always
produces a finished file.
"""
from __future__ import annotations

import asyncio
import logging
import math
import textwrap
from pathlib import Path
from typing import Any, Callable, Optional

import httpx

from ..config import settings
from . import ffmpeg_service as ff
from . import tts_service
from .llm import llm

log = logging.getLogger("omnicraft.video")

PALETTE = ["#12172b", "#1b2340", "#232c52", "#2b1f45", "#3a2340", "#16263f"]


def visual_provider() -> str:
    if settings.REPLICATE_API_KEY:
        return "replicate"
    if settings.RUNWAY_API_KEY:
        return "runway"
    if settings.PEXELS_API_KEY:
        return "pexels"
    return "generated"


async def build_scene_plan(brief: str, duration_seconds: int, scenes: int) -> list[dict[str, Any]]:
    per_scene = duration_seconds / scenes
    fallback = {
        "scenes": [
            {
                "narration": line.strip(),
                "visual": line.strip()[:120],
                "seconds": round(per_scene, 1),
            }
            for line in textwrap.wrap(brief, width=max(80, len(brief) // scenes + 1))[:scenes]
        ]
    }
    if not llm.available:
        return fallback["scenes"] or [{"narration": brief, "visual": brief[:120], "seconds": duration_seconds}]

    plan = await llm.json_complete(
        f"Write a {duration_seconds} second video from this brief:\n\n{brief}\n\n"
        f"Produce exactly {scenes} scenes of about {per_scene:.0f} seconds each. For each scene give "
        f"the narration line (spoken aloud, roughly {int(per_scene * 2.6)} words) and a short visual "
        f"description for a stock or generative image search.",
        system=(
            "You are a video director. Return "
            "{\"scenes\":[{\"narration\":str,\"visual\":str,\"seconds\":number}]}."
        ),
        fallback=fallback,
    )
    result = plan.get("scenes") if isinstance(plan, dict) else plan
    if not result:
        return fallback["scenes"]
    for scene in result:
        scene.setdefault("seconds", per_scene)
    return result[:scenes]


async def fetch_visual(description: str, dest: Path, index: int, aspect_ratio: str) -> Path:
    provider = visual_provider()
    try:
        if provider == "pexels":
            return await _pexels(description, dest, aspect_ratio)
        if provider == "replicate":
            return await _replicate(description, dest, aspect_ratio)
    except Exception as exc:  # provider outage must not kill the render
        log.warning("Visual provider %s failed (%s); using a generated card.", provider, exc)
    return await _generated_card(description, dest, index, aspect_ratio)


async def _pexels(query: str, dest: Path, aspect_ratio: str) -> Path:
    orientation = "portrait" if aspect_ratio in {"9:16", "4:5"} else "landscape"
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": settings.PEXELS_API_KEY},
            params={"query": query[:100], "per_page": 1, "orientation": orientation},
        )
        resp.raise_for_status()
        photos = resp.json().get("photos", [])
        if not photos:
            raise RuntimeError("No stock match")
        image_url = photos[0]["src"]["large2x"]
        img = await client.get(image_url)
        img.raise_for_status()
        dest.write_bytes(img.content)
    return dest


async def _replicate(prompt: str, dest: Path, aspect_ratio: str) -> Path:
    async with httpx.AsyncClient(timeout=300) as client:
        create = await client.post(
            "https://api.replicate.com/v1/models/black-forest-labs/flux-schnell/predictions",
            headers={
                "Authorization": f"Bearer {settings.REPLICATE_API_KEY}",
                "Content-Type": "application/json",
                "Prefer": "wait",
            },
            json={"input": {"prompt": prompt[:900], "aspect_ratio": aspect_ratio, "output_format": "jpg"}},
        )
        create.raise_for_status()
        payload = create.json()
        for _ in range(60):
            if payload.get("status") in {"succeeded", "failed", "canceled"}:
                break
            await asyncio.sleep(2)
            poll = await client.get(
                payload["urls"]["get"],
                headers={"Authorization": f"Bearer {settings.REPLICATE_API_KEY}"},
            )
            payload = poll.json()
        if payload.get("status") != "succeeded":
            raise RuntimeError(f"Generation {payload.get('status')}")
        output = payload["output"]
        url = output[0] if isinstance(output, list) else output
        img = await client.get(url)
        img.raise_for_status()
        dest.write_bytes(img.content)
    return dest


async def _generated_card(text: str, dest: Path, index: int, aspect_ratio: str) -> Path:
    """Typographic slide rendered by ffmpeg. Always available, no keys required."""
    width, height = ff.ASPECT_DIMENSIONS.get(aspect_ratio, (1920, 1080))
    colour = PALETTE[index % len(PALETTE)]
    wrapped = "\n".join(textwrap.wrap(text[:180], width=28)[:5]).replace(":", r"\:").replace("'", "")
    await ff.run([
        "-f", "lavfi", "-i", f"color=c={colour}:s={width}x{height}",
        "-vf", (
            f"drawbox=x=0:y=0:w={width}:h={height}:color=black@0.18:t=fill,"
            f"drawtext=text='{wrapped}':fontcolor=white:fontsize={int(height * 0.055)}:"
            f"x=(w-tw)/2:y=(h-th)/2:line_spacing=18"
        ),
        "-frames:v", "1", str(dest),
    ])
    return dest


async def create_video(
    brief: str,
    workdir: Path,
    duration_seconds: int,
    quality: str,
    aspect_ratio: str,
    voice_id: str,
    captions: bool,
    watermark: Optional[str],
    on_progress: Optional[Callable[[int, str], Any]] = None,
) -> dict[str, Any]:
    async def report(pct: int, stage: str) -> None:
        if on_progress:
            await on_progress(pct, stage)

    workdir.mkdir(parents=True, exist_ok=True)
    scene_count = max(3, min(40, math.ceil(duration_seconds / 8)))

    await report(6, "Writing the scene plan")
    scenes = await build_scene_plan(brief, duration_seconds, scene_count)

    await report(18, "Recording narration")
    narration_parts: list[Path] = []
    for idx, scene in enumerate(scenes):
        part = workdir / f"vo-{idx:03d}.mp3"
        line = (scene.get("narration") or "").strip()
        try:
            if line:
                await tts_service.synthesise(line, part, voice_id=voice_id)
            else:
                await ff.silence(float(scene.get("seconds", 4)), part)
        except Exception as exc:
            log.warning("Narration for scene %s failed (%s); inserting silence.", idx, exc)
            await ff.silence(float(scene.get("seconds", 4)), part)
        narration_parts.append(part)
        await report(18 + int(22 * (idx + 1) / len(scenes)), f"Recording narration {idx + 1}/{len(scenes)}")

    voiceover = workdir / "narration.mp3"
    if len(narration_parts) > 1:
        await ff.concat_audio(narration_parts, voiceover)
    else:
        narration_parts[0].replace(voiceover)

    await report(45, "Sourcing visuals")
    images: list[Path] = []
    for idx, scene in enumerate(scenes):
        image = workdir / f"scene-{idx:03d}.jpg"
        await fetch_visual(scene.get("visual") or brief, image, idx, aspect_ratio)
        images.append(image)
        await report(45 + int(25 * (idx + 1) / len(scenes)), f"Sourcing visuals {idx + 1}/{len(scenes)}")

    await report(74, "Rendering the timeline")
    probe = await _duration_of(voiceover)
    seconds_per_image = max(2.0, (probe or duration_seconds) / len(images))
    raw = workdir / "raw.mp4"
    await ff.slideshow(images, voiceover, raw, seconds_per_image, aspect_ratio, quality)

    subtitle_path: Optional[Path] = None
    current = raw
    if captions:
        await report(86, "Adding captions")
        try:
            from . import transcription
            audio = workdir / "caption-src.wav"
            await ff.extract_audio(raw, audio)
            result = await transcription.transcribe(audio)
            subtitle_path = workdir / "captions.srt"
            subtitle_path.write_text(transcription.to_srt(result["segments"]), encoding="utf-8")
            burned = workdir / "captioned.mp4"
            await ff.burn_subtitles(raw, subtitle_path, burned)
            current = burned
        except Exception as exc:
            log.warning("Captioning skipped: %s", exc)

    await report(93, "Encoding the final export")
    final = workdir / "omnicraft-video.mp4"
    await ff.transcode(current, final, quality=quality, watermark_text=watermark)

    return {
        "path": final,
        "subtitles": subtitle_path,
        "scenes": scenes,
        "visual_provider": visual_provider(),
        "narration_provider": tts_service.provider(),
        "duration": await _duration_of(final),
    }


async def _duration_of(path: Path) -> float:
    from ..utils.files import probe_media
    info = await probe_media(path)
    return float(info.get("duration") or 0)
