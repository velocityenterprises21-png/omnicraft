"""Shared FastAPI dependencies."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import decode_token
from .database import get_db
from .models import Role, SubscriptionPlan, User

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> User:
    user: Optional[User] = None

    if creds and creds.scheme.lower() == "bearer":
        payload = decode_token(creds.credentials)
        if payload:
            user = await db.get(User, payload["sub"])
    elif x_api_key:
        result = await db.execute(select(User).where(User.api_key == x_api_key))
        user = result.scalar_one_or_none()
        if user:
            plan = await get_plan_for(db, user.tier)
            if not plan or not plan.api_access:
                raise HTTPException(403, "API keys are available on Business and above.")

    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(403, "This account is suspended. Contact support to restore access.")
    return user


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not creds:
        return None
    payload = decode_token(creds.credentials)
    if not payload:
        return None
    return await db.get(User, payload["sub"])


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.admin:
        raise HTTPException(403, "Admin access only.")
    return user


async def get_plan_for(db: AsyncSession, tier: str) -> Optional[SubscriptionPlan]:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == tier))
    return result.scalar_one_or_none()


async def current_plan(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> SubscriptionPlan:
    plan = await get_plan_for(db, user.tier)
    if not plan:
        plan = await get_plan_for(db, "free")
    if not plan:
        raise HTTPException(500, "Plan catalog is missing. Run the seed step.")
    return plan
