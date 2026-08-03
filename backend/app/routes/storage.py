"""Feature 10 - the file library."""
# NOTE: deliberately no `from __future__ import annotations` here.
# It turns annotations into strings, and FastAPI cannot resolve UploadFile
# from a string - it fails at startup with
# `Invalid args for response field! ... ForwardRef('UploadFile')`.
# Python 3.10+ evaluates `str | None` natively, so nothing else needs it.

import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File as UploadField, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..deps import current_plan, get_current_user
from ..models import File, SubscriptionPlan, User
from ..schemas import FileOut, ShareIn
from ..security import limiter, scan_bytes, validate_upload
from ..utils.files import check_quota, delete_file, register_file, safe_join, unique_name

log = logging.getLogger("omnicraft.routes.storage")
router = APIRouter(prefix="/api/storage", tags=["storage"])

CHUNK = 1024 * 1024


@router.get("/usage")
async def usage(
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    count = (
        await db.execute(select(func.count()).select_from(File).where(File.user_id == user.id))
    ).scalar_one()
    limit = plan.storage_limit or 0
    return {
        "used_bytes": user.storage_used,
        "limit_bytes": limit,
        "percent": round(user.storage_used / limit * 100, 2) if limit else 0,
        "file_count": count,
        "backend": settings.STORAGE_BACKEND,
    }


@router.post("/upload", response_model=FileOut, status_code=201)
@limiter.limit("60/hour")
async def upload(
    request: Request,
    file: UploadFile = UploadField(...),
    user: User = Depends(get_current_user),
    plan: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    declared = int(request.headers.get("content-length", 0))
    safe_name, mime = validate_upload(file.filename or "upload", file.content_type or "", declared)
    await check_quota(db, user, plan, declared)

    destination = safe_join(user.id, unique_name(safe_name))
    written = 0
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024

    try:
        with destination.open("wb") as out:
            first = True
            while chunk := await file.read(CHUNK):
                if first:
                    scan_bytes(chunk[:16])
                    first = False
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(413, f"That file is over the {settings.MAX_UPLOAD_MB} MB limit.")
                out.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    await check_quota(db, user, plan, written)
    record = await register_file(db, user, destination, safe_name, mime)
    await db.commit()
    return FileOut.model_validate(record)


@router.get("/files")
async def list_files(
    kind: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(File).where(File.user_id == user.id)
    if kind:
        stmt = stmt.where(File.kind == kind)
    stmt = stmt.order_by(desc(File.created_at)).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return {"files": [FileOut.model_validate(r) for r in rows], "offset": offset, "limit": limit}


@router.get("/files/{file_id}/download")
async def download_file(file_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    path = Path(record.file_path)
    if not path.exists():
        raise HTTPException(410, "That file is no longer on disk.")
    return FileResponse(path, filename=record.filename, media_type=record.file_type)


@router.delete("/files/{file_id}", status_code=204)
async def remove(file_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    await delete_file(db, user, record)
    await db.commit()


@router.post("/share/{file_id}")
async def create_share(
    file_id: str,
    payload: ShareIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    record.share_token = secrets.token_urlsafe(24)
    record.share_expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    await db.commit()
    return {
        "share_token": record.share_token,
        "url": f"{settings.PUBLIC_BASE_URL}/api/storage/shared/{record.share_token}",
        "expires_at": record.share_expires_at,
    }


@router.delete("/share/{file_id}", status_code=204)
async def revoke_share(file_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    record = await db.get(File, file_id)
    if not record or record.user_id != user.id:
        raise HTTPException(404, "That file isn't in your library.")
    record.share_token = None
    record.share_expires_at = None
    await db.commit()


@router.get("/shared/{token}")
async def open_share(token: str, db: AsyncSession = Depends(get_db)):
    record = (
        await db.execute(select(File).where(File.share_token == token))
    ).scalar_one_or_none()
    if not record:
        raise HTTPException(404, "That share link isn't valid.")
    if record.share_expires_at and record.share_expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, "That share link has expired.")
    path = Path(record.file_path)
    if not path.exists():
        raise HTTPException(410, "The shared file is no longer available.")
    return FileResponse(path, filename=record.filename, media_type=record.file_type)
