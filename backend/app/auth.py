"""Password hashing, JWT issuing/validation and TOTP two-factor helpers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from .config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS = "access"
REFRESH = "refresh"


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------
def hash_password(raw: str) -> str:
    return pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(raw, hashed)
    except Exception:
        return False


def password_problems(raw: str) -> list[str]:
    issues = []
    if len(raw) < 10:
        issues.append("Use at least 10 characters.")
    if raw.isalpha():
        issues.append("Add a number or symbol.")
    if raw.lower() in {"password12", "omnicraft1", "1234567890"}:
        issues.append("That password is too common.")
    return issues


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def _encode(payload: dict[str, Any], ttl: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "type": token_type,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(body, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, role: str, tier: str) -> str:
    return _encode(
        {"sub": user_id, "role": role, "tier": tier},
        timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES),
        ACCESS,
    )


def create_refresh_token(user_id: str) -> str:
    return _encode({"sub": user_id}, timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS), REFRESH)


def decode_token(token: str, expected_type: str = ACCESS) -> Optional[dict[str, Any]]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_api_key() -> str:
    return "omc_" + secrets.token_urlsafe(32)


# --------------------------------------------------------------------------
# TOTP (RFC 6238) - no third-party dependency needed
# --------------------------------------------------------------------------
def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8").rstrip("=")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret.upper() + padding)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def verify_totp(secret: str, code: str, window: int = 1, period: int = 30) -> bool:
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    if not code.isdigit():
        return False
    counter = int(time.time()) // period
    for drift in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret, counter + drift), code):
            return True
    return False


def totp_provisioning_uri(secret: str, account: str, issuer: str = "OMNICRAFT") -> str:
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"


def generate_recovery_codes(count: int = 8) -> list[str]:
    return [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(count)]
