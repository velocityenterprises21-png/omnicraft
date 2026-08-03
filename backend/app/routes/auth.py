"""Registration, login, token refresh and two-factor authentication."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import (ACCESS, REFRESH, create_access_token, create_refresh_token, decode_token,
                    generate_api_key, generate_recovery_codes, generate_totp_secret, hash_password,
                    hash_token, password_problems, totp_provisioning_uri, verify_password, verify_totp)
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import AuditLog, RefreshToken, SubscriptionPlan, TransactionType, User
from ..schemas import (LoginIn, RefreshIn, RegisterIn, TokenPair, TwoFactorSetupOut,
                       TwoFactorVerifyIn, UserOut)
from ..security import limiter
from ..utils.credits import grant

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id, user.role.value, user.tier),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


async def _store_refresh(db: AsyncSession, user: User, token: str, request: Request) -> None:
    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    ))


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def register(request: Request, payload: RegisterIn, db: AsyncSession = Depends(get_db)):
    problems = password_problems(payload.password)
    if problems:
        raise HTTPException(400, " ".join(problems))

    clash = await db.execute(
        select(User).where(or_(User.email == payload.email.lower(), User.username == payload.username))
    )
    if clash.scalar_one_or_none():
        raise HTTPException(409, "That email or username is already registered.")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        tier="free",
    )
    db.add(user)
    await db.flush()

    free_plan = (
        await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == "free"))
    ).scalar_one_or_none()
    await grant(db, user, free_plan.credits_included if free_plan else 5,
                TransactionType.grant, "Welcome credits")

    tokens = _pair(user)
    await _store_refresh(db, user, tokens.refresh_token, request)
    db.add(AuditLog(user_id=user.id, action="auth.register",
                    ip_address=request.client.host if request.client else None))
    await db.commit()
    return tokens


@router.post("/login", response_model=TokenPair)
@limiter.limit("20/hour")
async def login(request: Request, payload: LoginIn, db: AsyncSession = Depends(get_db)):
    identifier = payload.identifier.strip().lower()
    result = await db.execute(
        select(User).where(or_(User.email == identifier, User.username == payload.identifier.strip()))
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    if not user.is_active:
        raise HTTPException(403, "This account is suspended. Contact support to restore access.")

    if user.twofa_enabled:
        if not payload.totp_code:
            raise HTTPException(
                428, {"code": "totp_required", "message": "Enter the 6-digit code from your authenticator app."}
            )
        codes = user.twofa_recovery_codes or []
        if verify_totp(user.twofa_secret or "", payload.totp_code):
            pass
        elif payload.totp_code in codes:
            user.twofa_recovery_codes = [c for c in codes if c != payload.totp_code]
        else:
            raise HTTPException(401, "That code didn't match. Try the next one your app shows.")

    user.last_login_at = datetime.now(timezone.utc)
    tokens = _pair(user)
    await _store_refresh(db, user, tokens.refresh_token, request)
    db.add(AuditLog(user_id=user.id, action="auth.login",
                    ip_address=request.client.host if request.client else None))
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh(request: Request, payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    claims = decode_token(payload.refresh_token, expected_type=REFRESH)
    if not claims:
        raise HTTPException(401, "That session has expired. Sign in again.")

    stored = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token))
        )
    ).scalar_one_or_none()
    if not stored or stored.revoked or stored.expires_at < datetime.now(timezone.utc):
        raise HTTPException(401, "That session has expired. Sign in again.")

    user = await db.get(User, claims["sub"])
    if not user or not user.is_active:
        raise HTTPException(401, "That session is no longer valid.")

    stored.revoked = True  # rotate
    tokens = _pair(user)
    await _store_refresh(db, user, tokens.refresh_token, request)
    await db.commit()
    return tokens


@router.post("/logout", status_code=204)
async def logout(payload: RefreshIn, db: AsyncSession = Depends(get_db)):
    stored = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(payload.refresh_token))
        )
    ).scalar_one_or_none()
    if stored:
        stored.revoked = True
        await db.commit()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate({
        **user.__dict__,
        "role": user.role.value,
        "subscription_status": user.subscription_status.value,
    })


@router.post("/2fa/setup", response_model=TwoFactorSetupOut)
async def twofa_setup(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if user.twofa_enabled:
        raise HTTPException(409, "Two-factor is already on. Turn it off first to re-enrol.")
    secret = generate_totp_secret()
    codes = generate_recovery_codes()
    user.twofa_secret = secret
    user.twofa_recovery_codes = codes
    await db.commit()
    return TwoFactorSetupOut(
        secret=secret,
        otpauth_uri=totp_provisioning_uri(secret, user.email),
        recovery_codes=codes,
    )


@router.post("/2fa/enable", status_code=204)
async def twofa_enable(
    payload: TwoFactorVerifyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.twofa_secret:
        raise HTTPException(400, "Start the setup step first.")
    if not verify_totp(user.twofa_secret, payload.code):
        raise HTTPException(400, "That code didn't match. Check your device clock and try again.")
    user.twofa_enabled = True
    await db.commit()


@router.post("/2fa/disable", status_code=204)
async def twofa_disable(
    payload: TwoFactorVerifyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.twofa_enabled:
        return
    if not verify_totp(user.twofa_secret or "", payload.code):
        raise HTTPException(400, "That code didn't match.")
    user.twofa_enabled = False
    user.twofa_secret = None
    user.twofa_recovery_codes = None
    await db.commit()


@router.post("/api-key")
async def rotate_api_key(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    plan = (
        await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == user.tier))
    ).scalar_one_or_none()
    if not plan or not plan.api_access:
        raise HTTPException(403, "API keys unlock on Business and above.")
    user.api_key = generate_api_key()
    await db.commit()
    return {"api_key": user.api_key}
