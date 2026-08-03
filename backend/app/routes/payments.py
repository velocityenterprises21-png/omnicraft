"""Feature 11 - subscriptions and credit packs."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS, CREDIT_PACKAGES, settings
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import CreditTransaction, SubscriptionPlan, SubscriptionStatus, TransactionType, User
from ..schemas import CheckoutIn, PlanOut, TransactionOut
from ..security import limiter
from ..services import stripe_service
from ..utils.credits import grant

log = logging.getLogger("omnicraft.routes.payments")
router = APIRouter(prefix="/api/payments", tags=["payments"])


@router.get("/plans")
async def plans(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order))
    ).scalars().all()
    return {
        "plans": [PlanOut.model_validate(r) for r in rows],
        "credit_packages": CREDIT_PACKAGES,
        "credit_costs": CREDIT_COSTS,
        "billing_enabled": stripe_service.configured(),
        "publishable_key": settings.STRIPE_PUBLISHABLE_KEY or None,
    }


@router.get("/transactions")
async def transactions(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(CreditTransaction).where(CreditTransaction.user_id == user.id)
            .order_by(desc(CreditTransaction.created_at)).limit(100)
        )
    ).scalars().all()
    return {
        "balance": user.credits_balance,
        "transactions": [
            TransactionOut.model_validate({**t.__dict__, "type": t.type.value}) for t in rows
        ],
    }


@router.post("/create-checkout")
@limiter.limit("20/hour")
async def create_checkout(
    request: Request,
    payload: CheckoutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not stripe_service.configured():
        from ..utils.errors import FeatureUnavailable
        raise FeatureUnavailable(
            "Stripe", "STRIPE_SECRET_KEY",
            "Everything except billing runs without it. Accounts stay on the Free tier.",
        )

    customer_id = await stripe_service.ensure_customer(user.email, user.username, user.stripe_customer_id)
    if customer_id != user.stripe_customer_id:
        user.stripe_customer_id = customer_id
        await db.commit()

    if payload.credit_pack:
        pack = stripe_service.pack_by_code(payload.credit_pack)
        if not pack:
            raise HTTPException(400, "That credit package doesn't exist.")
        return await stripe_service.credit_pack_checkout(customer_id, pack, user.id)

    if not payload.plan:
        raise HTTPException(400, "Choose a plan or a credit package.")

    plan = (
        await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == payload.plan))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "That plan doesn't exist.")
    if plan.name == "free":
        raise HTTPException(400, "The Free tier doesn't need checkout.")

    amount = plan.price_yearly if payload.interval == "yearly" else plan.price_monthly
    price_id = plan.stripe_price_id_yearly if payload.interval == "yearly" else plan.stripe_price_id_monthly
    return await stripe_service.subscription_checkout(
        customer_id, plan.name, price_id or None, payload.interval,
        int(round(amount * 100)), plan.display_name, user.id,
    )


@router.post("/portal")
async def portal(user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(400, "There's no billing account on file yet.")
    return {"url": await stripe_service.billing_portal(user.stripe_customer_id)}


@router.post("/cancel")
async def cancel(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if not user.stripe_subscription_id:
        raise HTTPException(400, "There's no active subscription to cancel.")
    await stripe_service.cancel_subscription(user.stripe_subscription_id)
    return {"message": "Your plan stays active until the end of the current period."}


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, stripe_signature: str = Header(default="", alias="Stripe-Signature")):
    payload = await request.body()
    try:
        event = stripe_service.verify_webhook(payload, stripe_signature)
    except Exception as exc:
        log.warning("Rejected Stripe webhook: %s", exc)
        raise HTTPException(400, "Signature verification failed.")

    kind = event["type"]
    data = event["data"]["object"]

    async with SessionLocal() as db:
        if kind == "checkout.session.completed":
            await _handle_checkout(db, data)
        elif kind in {"customer.subscription.updated", "customer.subscription.created"}:
            await _handle_subscription(db, data)
        elif kind == "customer.subscription.deleted":
            await _handle_cancellation(db, data)
        elif kind == "invoice.paid":
            await _handle_renewal(db, data)
        await db.commit()

    return {"received": True}


async def _user_by_customer(db: AsyncSession, customer_id: str) -> User | None:
    return (
        await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    ).scalar_one_or_none()


async def _already_granted(db: AsyncSession, reference: str | None) -> bool:
    """Stripe guarantees at-least-once delivery, so the same event can arrive
    twice. Every grant records the Stripe object id as its reference; if we've
    seen it, don't pay out again."""
    if not reference:
        return False
    existing = (
        await db.execute(
            select(CreditTransaction.id)
            .where(CreditTransaction.reference == reference)
            .where(CreditTransaction.type.in_([TransactionType.grant, TransactionType.purchase]))
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        log.info("Ignoring duplicate Stripe delivery for %s", reference)
        return True
    return False


async def _handle_checkout(db: AsyncSession, session: dict) -> None:
    meta = session.get("metadata") or {}
    user = await db.get(User, meta.get("user_id", "")) or await _user_by_customer(db, session.get("customer"))
    if not user:
        return

    if await _already_granted(db, session.get("id")):
        return

    if meta.get("kind") == "credits":
        amount = int(meta.get("credits", 0))
        if amount:
            await grant(db, user, amount, TransactionType.purchase,
                        f"Credit pack: {amount:,} credits", session.get("id"))
        return

    plan_name = meta.get("plan")
    if plan_name:
        plan = (
            await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == plan_name))
        ).scalar_one_or_none()
        if plan:
            user.tier = plan.name
            user.billing_interval = meta.get("interval", "monthly")
            user.subscription_status = SubscriptionStatus.active
            user.stripe_subscription_id = session.get("subscription")
            await grant(db, user, plan.credits_included, TransactionType.grant,
                        f"{plan.display_name} plan credits", session.get("id"))


async def _handle_subscription(db: AsyncSession, subscription: dict) -> None:
    user = await _user_by_customer(db, subscription.get("customer"))
    if not user:
        return
    status_map = {
        "active": SubscriptionStatus.active,
        "trialing": SubscriptionStatus.trialing,
        "past_due": SubscriptionStatus.past_due,
        "canceled": SubscriptionStatus.canceled,
        "unpaid": SubscriptionStatus.past_due,
    }
    user.subscription_status = status_map.get(subscription.get("status"), SubscriptionStatus.none)
    user.stripe_subscription_id = subscription.get("id")
    period_end = subscription.get("current_period_end")
    if period_end:
        user.subscription_renews_at = datetime.fromtimestamp(period_end, tz=timezone.utc)
    plan_name = (subscription.get("metadata") or {}).get("plan")
    if plan_name and user.subscription_status in {SubscriptionStatus.active, SubscriptionStatus.trialing}:
        user.tier = plan_name


async def _handle_cancellation(db: AsyncSession, subscription: dict) -> None:
    user = await _user_by_customer(db, subscription.get("customer"))
    if not user:
        return
    user.subscription_status = SubscriptionStatus.canceled
    user.tier = "free"
    user.stripe_subscription_id = None


async def _handle_renewal(db: AsyncSession, invoice: dict) -> None:
    if invoice.get("billing_reason") != "subscription_cycle":
        return
    user = await _user_by_customer(db, invoice.get("customer"))
    if not user:
        return
    if await _already_granted(db, invoice.get("id")):
        return
    plan = (
        await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == user.tier))
    ).scalar_one_or_none()
    if plan and plan.credits_included:
        await grant(db, user, plan.credits_included, TransactionType.grant,
                    f"{plan.display_name} renewal credits", invoice.get("id"))
