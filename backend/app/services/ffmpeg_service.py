"""ffmpeg wrappers for every audio/video transform in the platform."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..config import settings
from ..utils.errors import ToolMissing

log = logging.getLogger("omnicraft.ffmpeg")

QUALITY_PRESETS = {
    "480p": {"scale": "854:480", "crf": "26", "bitrate": "1200k"},
    "720p": {"scale": "1280:720", "crf": "24", "bitrate": "2500k"},
    "1080p": {"scale": "1920:1080", "crf": "22", "bitrate": "5000k"},
    "4K": {"scale": "3840:2160", "crf": "20", "bitrate": "18000k"},
    "8K": {"scale": "7680:4320", "crf": "18", "bitrate": "60000k"},
    "8K+": {"scale": "7680:4320", "crf": "16", "bitrate": "90000k"},
}

ASPECT_DIMENSIONS = {
    "16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080),
    "4:5": (1080, 1350), "21:9": (2560, 1080),
}


def ensure_ffmpeg() -> None:
    if not shutil.which(settings.FFMPEG_BIN):
        raise ToolMissing("ffmpeg")


async def run(args: Sequence[str], timeout: int = 3600) -> str:
    ensure_ffmpeg()
    cmd = [settings.FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("The render took too long and was stopped.")
    if proc.returncode != 0:
        message = err.decode(errors="replace")[-600:]
        log.error("ffmpeg failed: %s", message)
        raise RuntimeError(f"Render failed: {message}")
    return err.decode(errors="replace")


async def extract_audio(source: Path, dest: Path, sample_rate: int = 16000) -> Path:
    await run(["-i", str(source), "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dest)])
    return dest


async def to_mp3(source: Path, dest: Path) -> Path:
    await run(["-i", str(source), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(dest)])
    return dest


async def mix_narration(
    video: Path,
    narration: Path,
    dest: Path,
    mode: str = "mix",
    original_volume: float = 0.2,
    narration_volume: float = 1.0,
) -> Path:
    """mode: replace (drop original audio) | mix (static blend) | duck (sidechain)."""
    if mode == "replace":
        await run([
            "-i", str(video), "-i", str(narration),
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(dest),
        ])
        return dest

    if mode == "duck":
        filt = (
            f"[0:a]volume={original_volume + 0.5}[base];"
            f"[1:a]volume={narration_volume},asplit=2[voice][key];"
            f"[base][key]sidechaincompress=threshold=0.03:ratio=12:attack=20:release=350[ducked];"
            f"[ducked][voice]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )
    else:
        filt = (
            f"[0:a]volume={original_volume}[base];"
            f"[1:a]volume={narration_volume}[voice];"
            f"[base][voice]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

    await run([
        "-i", str(video), "-i", str(narration),
        "-filter_complex", filt,
        "-map", "0:v:0", "-map", "[out]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(dest),
    ])
    return dest


async def burn_subtitles(video: Path, subtitles: Path, dest: Path) -> Path:
    escaped = str(subtitles).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    style = "FontName=DejaVu Sans,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3"
    await run([
        "-i", str(video),
        "-vf", f"subtitles='{escaped}':force_style='{style}'",
        "-c:a", "copy", str(dest),
    ])
    return dest


async def mute_ranges(source: Path, dest: Path, ranges: Iterable[tuple[float, float]]) -> Path:
    """Silence the given [start, end] second ranges. Video is copied untouched."""
    clauses = [f"volume=enable='between(t,{start:.3f},{end:.3f})':volume=0" for start, end in ranges]
    if not clauses:
        shutil.copy2(source, dest)
        return dest
    await run(["-i", str(source), "-af", ",".join(clauses), "-c:v", "copy", "-c:a", "aac", str(dest)])
    return dest


async def replace_audio_ranges(
    source: Path, replacement: Path, dest: Path, ranges: Iterable[tuple[float, float]]
) -> Path:
    """Mute the flagged ranges, then lay a licensed bed under the whole timeline."""
    tmp = dest.with_name(dest.stem + "-muted" + dest.suffix)
    await mute_ranges(source, tmp, ranges)
    await run([
        "-i", str(tmp), "-stream_loop", "-1", "-i", str(replacement),
        "-filter_complex", "[1:a]volume=0.35[bed];[0:a][bed]amix=inputs=2:duration=first[out]",
        "-map", "0:v:0", "-map", "[out]",
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(dest),
    ])
    tmp.unlink(missing_ok=True)
    return dest


async def strip_audio(source: Path, dest: Path) -> Path:
    await run(["-i", str(source), "-an", "-c:v", "copy", str(dest)])
    return dest


async def transcode(source: Path, dest: Path, quality: str = "1080p", watermark_text: Optional[str] = None) -> Path:
    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["1080p"])
    vf = [f"scale={preset['scale']}:force_original_aspect_ratio=decrease",
          f"pad={preset['scale']}:(ow-iw)/2:(oh-ih)/2:color=black"]
    if watermark_text:
        safe = watermark_text.replace(":", r"\:").replace("'", "")
        vf.append(
            f"drawtext=text='{safe}':fontcolor=white@0.55:fontsize=28:x=w-tw-28:y=h-th-28:"
            f"box=1:boxcolor=black@0.25:boxborderw=8"
        )
    await run([
        "-i", str(source), "-vf", ",".join(vf),
        "-c:v", "libx264", "-preset", "medium", "-crf", preset["crf"],
        "-maxrate", preset["bitrate"], "-bufsize", preset["bitrate"],
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest),
    ])
    return dest


async def slideshow(
    images: Sequence[Path],
    audio: Optional[Path],
    dest: Path,
    seconds_per_image: float,
    aspect_ratio: str = "16:9",
    quality: str = "1080p",
) -> Path:
    """Build a video from stills with cross dissolves. Used by the AI video builder."""
    ensure_ffmpeg()
    width, height = ASPECT_DIMENSIONS.get(aspect_ratio, (1920, 1080))
    args: list[str] = []
    for image in images:
        args += ["-loop", "1", "-t", f"{seconds_per_image:.2f}", "-i", str(image)]
    if audio:
        args += ["-i", str(audio)]

    scale = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},zoompan=z='min(zoom+0.0008,1.12)':d={int(seconds_per_image * 25)}:"
        f"s={width}x{height}:fps=25,setsar=1"
    )
    chains = [f"[{i}:v]{scale}[v{i}]" for i in range(len(images))]
    concat_inputs = "".join(f"[v{i}]" for i in range(len(images)))
    chains.append(f"{concat_inputs}concat=n={len(images)}:v=1:a=0[vout]")
    filt = ";".join(chains)

    preset = QUALITY_PRESETS.get(quality, QUALITY_PRESETS["1080p"])
    cmd = [*args, "-filter_complex", filt, "-map", "[vout]"]
    if audio:
        cmd += ["-map", f"{len(images)}:a:0", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", preset["crf"],
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dest),
    ]
    await run(cmd)
    return dest


async def concat_audio(parts: Sequence[Path], dest: Path) -> Path:
    listing = dest.with_suffix(".txt")
    listing.write_text("\n".join(f"file '{p.resolve()}'" for p in parts), encoding="utf-8")
    await run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(dest)])
    listing.unlink(missing_ok=True)
    return dest


async def silence(duration: float, dest: Path) -> Path:
    await run([
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo", "-t", f"{duration:.2f}",
        "-c:a", "libmp3lame", str(dest),
    ])
    return dest
