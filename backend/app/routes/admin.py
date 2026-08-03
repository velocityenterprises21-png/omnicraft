"""Feature 9 - operator console."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import require_admin
from ..models import (AuditLog, CreditTransaction, File, Job, JobStatus, SubscriptionPlan,
                      TransactionType, User)
from ..schemas import UserOut
from ..utils.credits import grant
from ..websocket import hub

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def stats(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    total_users = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    new_users = (
        await db.execute(select(func.count()).select_from(User).where(User.created_at >= week_ago))
    ).scalar_one()
    paying = (
        await db.execute(select(func.count()).select_from(User).where(User.tier != "free"))
    ).scalar_one()
    total_jobs = (await db.execute(select(func.count()).select_from(Job))).scalar_one()
    failed_jobs = (
        await db.execute(select(func.count()).select_from(Job).where(Job.status == JobStatus.failed))
    ).scalar_one()
    storage = (await db.execute(select(func.coalesce(func.sum(File.file_size), 0)))).scalar_one()
    credits_spent = (
        await db.execute(
            select(func.coalesce(func.sum(CreditTransaction.amount), 0))
            .where(CreditTransaction.type == TransactionType.spend)
        )
    ).scalar_one()

    by_tier = (
        await db.execute(select(User.tier, func.count()).group_by(User.tier))
    ).all()
    by_feature = (
        await db.execute(
            select(CreditTransaction.feature_used, func.count())
            .where(CreditTransaction.feature_used.is_not(None))
            .group_by(CreditTransaction.feature_used)
            .order_by(desc(func.count())).limit(15)
        )
    ).all()

    return {
        "users": {"total": total_users, "new_this_week": new_users, "paying": paying},
        "jobs": {"total": total_jobs, "failed": failed_jobs,
                 "failure_rate": round(failed_jobs / total_jobs * 100, 2) if total_jobs else 0},
        "storage_bytes": int(storage),
        "credits_spent": abs(int(credits_spent)),
        "live_connections": hub.connection_count,
        "users_by_tier": {tier: count for tier, count in by_tier},
        "usage_by_feature": {feature: count for feature, count in by_feature},
    }


@router.get("/revenue")
async def revenue(admin: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    plans = {
        p.name: p for p in
        (await db.execute(select(SubscriptionPlan))).scalars().all()
    }
    rows = (await db.execute(select(User.tier, User.billing_interval, func.count()).group_by(
        User.tier, User.billing_interval))).all()

    mrr = 0.0
    breakdown = []
    for tier, interval, count in rows:
        plan = plans.get(tier)
        if not plan or tier == "free":
            continue
        monthly = plan.price_yearly / 12 if interval == "yearly" else plan.price_monthly
        line = round(monthly * count, 2)
        mrr += line
        breakdown.append({"tier": tier, "interval": interval, "subscribers": count, "mrr": line})

    pack_revenue = (
        await db.execute(
            select(func.coalesce(func.sum(CreditTransaction.amount), 0))
            .where(CreditTransaction.type == TransactionType.purchase)
        )
    ).scalar_one()

    return {
        "mrr": round(mrr, 2),
        "arr": round(mrr * 12, 2),
        "breakdown": breakdown,
        "credits_purchased": int(pack_revenue),
        "note": "Figures are derived from local records. Reconcile against Stripe before reporting.",
    }


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User)
    if q:
        pattern = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.email).like(pattern), func.lower(User.username).like(pattern)))
    stmt = stmt.order_by(desc(User.created_at)).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "users": [
            UserOut.model_validate({**u.__dict__, "role": u.role.value,
                                    "subscription_status": u.subscription_status.value})
            for u in rows
        ],
        "offset": offset,
    }


@router.post("/users/{user_id}/credits")
async def adjust_credits(
    user_id: str,
    amount: int = Query(..., description="Positive to add, negative to remove"),
    reason: str = Query(default="Manual adjustment"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "No account with that id.")
    await grant(db, target, amount, TransactionType.adjustment, reason, admin.id)
    db.add(AuditLog(user_id=admin.id, action="admin.credits",
                    detail={"target": user_id, "amount": amount, "reason": reason}))
    await db.commit()
    return {"user_id": user_id, "balance": target.credits_balance}


@router.post("/users/{user_id}/suspend")
async def suspend(
    user_id: str,
    active: bool = Query(default=False),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(404, "No account with that id.")
    if target.id == admin.id:
        raise HTTPException(400, "You can't suspend your own account.")
    target.is_active = active
    db.add(AuditLog(user_id=admin.id, action="admin.suspend",
                    detail={"target": user_id, "active": active}))
    await db.commit()
    return {"user_id": user_id, "is_active": target.is_active}


@router.get("/jobs")
async def recent_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Job).order_by(desc(Job.created_at)).limit(limit)
    if status:
        stmt = stmt.where(Job.status == status)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "jobs": [
            {"id": j.id, "user_id": j.user_id, "type": j.job_type, "status": j.status.value,
             "progress": j.progress, "credits": j.credits_charged, "error": j.error_message,
             "created_at": j.created_at}
            for j in rows
        ]
    }


@router.get("/audit")
async def audit(
    limit: int = Query(default=100, le=500),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit))
    ).scalars().all()
    return {"entries": [
        {"id": a.id, "user_id": a.user_id, "action": a.action, "detail": a.detail,
         "ip": a.ip_address, "at": a.created_at}
        for a in rows
    ]}
