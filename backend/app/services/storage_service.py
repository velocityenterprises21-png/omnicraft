"""Local disk and S3-compatible object storage."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger("omnicraft.storage")


def s3_configured() -> bool:
    return bool(
        settings.AWS_ACCESS_KEY_ID
        and settings.AWS_SECRET_ACCESS_KEY
        and settings.AWS_STORAGE_BUCKET_NAME
    )


def _client():
    import boto3

    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


async def push(local_path: Path, key: str) -> Optional[str]:
    """Upload to S3 and return the object key. Returns None when S3 is off."""
    if settings.STORAGE_BACKEND != "s3" or not s3_configured():
        return None

    def _run() -> str:
        _client().upload_file(str(local_path), settings.AWS_STORAGE_BUCKET_NAME, key)
        return key

    return await asyncio.to_thread(_run)


async def signed_url(key: str, expires_seconds: int = 3600) -> Optional[str]:
    if not s3_configured():
        return None

    def _run() -> str:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.AWS_STORAGE_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_seconds,
        )

    return await asyncio.to_thread(_run)


async def remove(key: str) -> None:
    if not s3_configured():
        return

    def _run() -> None:
        _client().delete_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=key)

    await asyncio.to_thread(_run)
