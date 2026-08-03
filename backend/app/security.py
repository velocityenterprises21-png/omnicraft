"""Rate limiting, security headers and upload validation."""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])

ALLOWED_UPLOAD_TYPES = {
    "video/mp4", "video/quicktime", "video/x-matroska", "video/webm", "video/x-msvideo",
    "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/aac", "audio/ogg", "audio/flac",
    "image/jpeg", "image/png", "image/webp",
    "text/plain", "text/vtt", "application/x-subrip", "application/json",
}

ALLOWED_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac",
    ".jpg", ".jpeg", ".png", ".webp",
    ".txt", ".srt", ".vtt", ".json",
}

# Executables and archives are rejected outright - this service never needs them.
BLOCKED_EXTENSIONS = {
    ".exe", ".dll", ".so", ".bat", ".cmd", ".sh", ".ps1", ".jar", ".msi",
    ".scr", ".com", ".vbs", ".js", ".php", ".py", ".zip", ".rar", ".7z",
}


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "detail": "Too many requests. Slow down and try again in a moment.",
            "limit": str(exc.detail),
        },
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Conservative defaults. No third-party origins are permitted."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data: blob:; "
            "media-src 'self' blob:; "
            "connect-src 'self' ws: wss:; "
            "font-src 'self'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "base-uri 'self'; "
            "object-src 'none'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=(), interest-cohort=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if settings.ENVIRONMENT == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def validate_upload(filename: str, content_type: str, size_bytes: int) -> tuple[str, str]:
    """Return (safe_filename, resolved_mime). Raises HTTPException when rejected."""
    safe = Path(filename).name.replace("\x00", "")
    if not safe or safe.startswith("."):
        raise HTTPException(400, "That filename isn't usable. Rename the file and try again.")

    ext = Path(safe).suffix.lower()
    if ext in BLOCKED_EXTENSIONS:
        raise HTTPException(415, f"{ext} files aren't accepted here.")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, f"{ext or 'That file type'} isn't supported. Upload video, audio, image or subtitle files.")

    mime = content_type or mimetypes.guess_type(safe)[0] or "application/octet-stream"
    if mime not in ALLOWED_UPLOAD_TYPES:
        guessed = mimetypes.guess_type(safe)[0]
        if guessed in ALLOWED_UPLOAD_TYPES:
            mime = guessed
        else:
            raise HTTPException(415, f"{mime} isn't a supported content type.")

    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(413, f"That file is larger than the {settings.MAX_UPLOAD_MB} MB limit.")

    return safe, mime


MAGIC_SIGNATURES = {
    b"MZ": "windows executable",
    b"\x7fELF": "linux executable",
    b"PK\x03\x04": "archive",
    b"\xca\xfe\xba\xbe": "java class",
}


def scan_bytes(head: bytes) -> None:
    """Cheap content sniff. Wire a real AV engine (ClamAV) in front of this in production."""
    for sig, label in MAGIC_SIGNATURES.items():
        if head.startswith(sig):
            raise HTTPException(415, f"That file looks like a {label}, which isn't allowed.")
