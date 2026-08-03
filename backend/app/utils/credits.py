"""Credit ledger. Every debit and credit goes through here."""
from __future__ import annotations

import math
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..models import CreditTransaction, TransactionType, User
from .errors import InsufficientCredits


def estimate_download(duration_seconds: float | None, quality: str) -> int:
    if quality in {"2160p", "4K", "8K"}:
        return CREDIT_COSTS["download.hires"]
    if duration_seconds is None:
        return CREDIT_COSTS["download.short"]
    if duration_seconds / 60 < 5:
        return CREDIT_COSTS["download.short"]
    return CREDIT_COSTS["download.long"]


def estimate_tts(characters: int) -> int:
    """Roughly 900 characters of narration per spoken minute."""
    minutes = max(1, math.ceil(characters / 900))
    return minutes * CREDIT_COSTS["tts.per_minute"]


def estimate_video(duration_seconds: int, quality: str) -> int:
    minutes = max(1, math.ceil(duration_seconds / 60))
    anchors = {(1, "720p"): 15, (5, "1080p"): 50, (20, "4K"): 200, (60, "4K"): 600, (60, "8K"): 900}
    if (minutes, quality) in anchors:
        return anchors[(minutes, quality)]
    per_minute = {"480p": 12, "720p": 15, "1080p": 10, "4K": 10, "8K": 15}.get(quality, 15)
    return minutes * per_minute


def with_priority(base: int, priority: bool) -> int:
    return base + (CREDIT_COSTS["priority_surcharge"] if priority else 0)


async def ensure_balance(user: User, needed: int) -> None:
    if user.credits_balance < needed:
        raise InsufficientCredits(needed, user.credits_balance)


async def charge(
    db: AsyncSession,
    user: User,
    amount: int,
    feature: str,
    description: str,
    reference: Optional[str] = None,
) -> CreditTransaction:
    await ensure_balance(user, amount)
    user.credits_balance -= amount
    tx = CreditTransaction(
        user_id=user.id,
        amount=-amount,
        balance_after=user.credits_balance,
        type=TransactionType.spend,
        description=description,
        feature_used=feature,
        reference=reference,
    )
    db.add(tx)
    await db.flush()
    return tx


async def grant(
    db: AsyncSession,
    user: User,
    amount: int,
    tx_type: TransactionType,
    description: str,
    reference: Optional[str] = None,
) -> CreditTransaction:
    user.credits_balance += amount
    tx = CreditTransaction(
        user_id=user.id,
        amount=amount,
        balance_after=user.credits_balance,
        type=tx_type,
        description=description,
        reference=reference,
    )
    db.add(tx)
    await db.flush()
    return tx


async def refund(db: AsyncSession, user: User, amount: int, reason: str, reference: Optional[str] = None):
    if amount <= 0:
        return None
    return await grant(db, user, amount, TransactionType.refund, reason, reference)
