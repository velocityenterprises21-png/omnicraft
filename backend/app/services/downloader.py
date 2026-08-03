"""Media retrieval built on yt-dlp.

Only fetch material you own or are licensed to use. The service records the
requesting account against every job so operators can answer takedown requests.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

from ..utils.errors import ToolMissing

log = logging.getLogger("omnicraft.downloader")

SUPPORTED_HOSTS = {
    "youtube.com", "youtu.be", "m.youtube.com", "music.youtube.com",
    "instagram.com", "www.instagram.com",
    "tiktok.com", "www.tiktok.com", "vm.tiktok.com",
    "facebook.com", "www.facebook.com", "fb.watch",
    "twitter.com", "x.com", "www.twitter.com",
    "vimeo.com", "player.vimeo.com",
    "dailymotion.com", "twitch.tv", "soundcloud.com", "reddit.com",
}

FORMAT_MAP = {
    "best": "bestvideo+bestaudio/best",
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1440p": "bestvideo[height<=1440]+bestaudio/best[height<=1440]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "audio": "bestaudio/best",
}


def host_supported(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(host == h or host.endswith("." + h) for h in SUPPORTED_HOSTS)


def _ytdlp():
    try:
        import yt_dlp  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover
        raise ToolMissing("yt-dlp") from exc
    return yt_dlp


async def probe(url: str) -> dict[str, Any]:
    """Fetch metadata without downloading."""
    yt_dlp = _ytdlp()

    def _run() -> dict[str, Any]:
        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "width": info.get("width"),
            "height": info.get("height"),
            "extractor": info.get("extractor_key"),
            "webpage_url": info.get("webpage_url"),
            "is_live": bool(info.get("is_live")),
            "license": info.get("license"),
        }

    return await asyncio.to_thread(_run)


async def fetch(
    url: str,
    dest_dir: Path,
    quality: str = "best",
    audio_only: bool = False,
    on_progress: Optional[Callable[[int, str], Any]] = None,
) -> dict[str, Any]:
    yt_dlp = _ytdlp()
    dest_dir.mkdir(parents=True, exist_ok=True)
    loop = asyncio.get_running_loop()

    def _hook(status: dict[str, Any]) -> None:
        if not on_progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes", 0)
            pct = int(done / total * 90) if total else 10
            asyncio.run_coroutine_threadsafe(on_progress(pct, "Downloading source"), loop)
        elif status.get("status") == "finished":
            asyncio.run_coroutine_threadsafe(on_progress(92, "Remuxing"), loop)

    def _run() -> dict[str, Any]:
        opts: dict[str, Any] = {
            "outtmpl": str(dest_dir / "%(title).80s-%(id)s.%(ext)s"),
            "format": FORMAT_MAP["audio"] if audio_only else FORMAT_MAP.get(quality, FORMAT_MAP["best"]),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "progress_hooks": [_hook],
            "retries": 3,
            "socket_timeout": 30,
            "merge_output_format": "mp4",
        }
        if audio_only:
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
            opts.pop("merge_output_format", None)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info))
            if audio_only:
                path = path.with_suffix(".mp3")
            elif not path.exists():
                path = path.with_suffix(".mp4")
        return {
            "path": path,
            "title": info.get("title") or path.stem,
            "duration": info.get("duration"),
            "width": info.get("width"),
            "height": info.get("height"),
            "extractor": info.get("extractor_key"),
        }

    return await asyncio.to_thread(_run)
