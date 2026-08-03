"""Filesystem helpers, quota accounting and media probing."""
from __future__ import annotations

import asyncio
import json
import mimetypes
import secrets
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import File, SubscriptionPlan, User
from .errors import QuotaExceeded

STORAGE_ROOT = Path(settings.LOCAL_STORAGE_PATH).resolve()


def user_dir(user_id: str) -> Path:
    path = STORAGE_ROOT / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_join(user_id: str, filename: str) -> Path:
    base = user_dir(user_id).resolve()
    candidate = (base / Path(filename).name).resolve()
    if not str(candidate).startswith(str(base)):
        raise ValueError("Path escapes the user directory.")
    return candidate


def unique_name(filename: str) -> str:
    stem = Path(filename).stem[:80] or "file"
    suffix = Path(filename).suffix.lower()
    return f"{stem}-{secrets.token_hex(4)}{suffix}"


def classify(mime: str, filename: str = "") -> str:
    mime = (mime or "").lower()
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or filename.endswith((".srt", ".vtt", ".txt", ".md", ".json")):
        return "text"
    return "other"


async def probe_media(path: Path) -> dict:
    """Return duration/dimensions using ffprobe when it is installed."""
    if not shutil.which(settings.FFPROBE_BIN):
        return {}
    proc = await asyncio.create_subprocess_exec(
        settings.FFPROBE_BIN, "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(out.decode())
    except json.JSONDecodeError:
        return {}
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "width": video.get("width"),
        "height": video.get("height"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "video_codec": video.get("codec_name"),
    }


async def check_quota(db: AsyncSession, user: User, plan: SubscriptionPlan, incoming_bytes: int) -> None:
    if plan.storage_limit and user.storage_used + incoming_bytes > plan.storage_limit:
        gb = plan.storage_limit / (1024 ** 3)
        raise QuotaExceeded(
            f"That would push you past your {gb:.0f} GB storage limit. Delete files or upgrade your plan.",
            plan.storage_limit,
        )


async def register_file(
    db: AsyncSession,
    user: User,
    path: Path,
    original_name: str,
    mime: Optional[str] = None,
    is_temp: bool = False,
    job_id: Optional[str] = None,
) -> File:
    size = path.stat().st_size
    mime = mime or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    media = await probe_media(path)
    record = File(
        user_id=user.id,
        filename=original_name,
        file_path=str(path),
        file_size=size,
        file_type=mime,
        kind=classify(mime, original_name),
        storage_type=settings.STORAGE_BACKEND,
        duration_seconds=media.get("duration") or None,
        is_temp=is_temp,
        job_id=job_id,
        expires_at=(
            datetime.now(timezone.utc) + timedelta(hours=settings.TEMP_FILE_TTL_HOURS)
            if is_temp else None
        ),
    )
    user.storage_used += size
    db.add(record)
    await db.flush()
    return record


async def delete_file(db: AsyncSession, user: User, record: File) -> None:
    try:
        Path(record.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    user.storage_used = max(0, user.storage_used - record.file_size)
    await db.delete(record)


async def purge_expired(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(select(File).where(File.is_temp.is_(True), File.expires_at < now))
    removed = 0
    for record in result.scalars().all():
        user = await db.get(User, record.user_id)
        if user:
            await delete_file(db, user, record)
            removed += 1
    await db.commit()
    return removed
