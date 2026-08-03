"""Stripe checkout, billing portal and webhook verification."""
from __future__ import annotations

import logging
from typing import Any, Optional

from ..config import CREDIT_PACKAGES, settings
from ..utils.errors import FeatureUnavailable

log = logging.getLogger("omnicraft.stripe")


def configured() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def _stripe():
    if not configured():
        raise FeatureUnavailable(
            "Stripe",
            "STRIPE_SECRET_KEY",
            "Everything except billing works without it. Plans stay on the Free tier.",
        )
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.max_network_retries = 2
    return stripe


def pack_by_code(code: str) -> Optional[dict[str, Any]]:
    return next((p for p in CREDIT_PACKAGES if p["code"] == code), None)


async def ensure_customer(email: str, username: str, existing_id: Optional[str]) -> str:
    stripe = _stripe()
    if existing_id:
        try:
            customer = stripe.Customer.retrieve(existing_id)
            if not customer.get("deleted"):
                return existing_id
        except Exception as exc:
            log.warning("Stripe customer lookup failed: %s", exc)
    customer = stripe.Customer.create(email=email, name=username, metadata={"platform": "omnicraft"})
    return customer["id"]


async def subscription_checkout(
    customer_id: str, plan_name: str, price_id: Optional[str], interval: str,
    amount_cents: int, display_name: str, user_id: str,
) -> dict[str, Any]:
    stripe = _stripe()
    if price_id:
        line_item: dict[str, Any] = {"price": price_id, "quantity": 1}
    else:
        line_item = {
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": amount_cents,
                "recurring": {"interval": "year" if interval == "yearly" else "month"},
                "product_data": {
                    "name": f"OMNICRAFT {display_name}",
                    "description": f"{display_name} plan, billed {interval}",
                },
            },
        }
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[line_item],
        success_url=f"{settings.FRONTEND_BASE_URL}/?billing=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.FRONTEND_BASE_URL}/?billing=cancelled",
        allow_promotion_codes=True,
        subscription_data={"metadata": {"user_id": user_id, "plan": plan_name, "interval": interval}},
        metadata={"user_id": user_id, "plan": plan_name, "interval": interval, "kind": "subscription"},
    )
    return {"url": session["url"], "session_id": session["id"]}


async def credit_pack_checkout(customer_id: str, pack: dict[str, Any], user_id: str) -> dict[str, Any]:
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        customer=customer_id,
        line_items=[{
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": int(round(pack["price_usd"] * 100)),
                "product_data": {
                    "name": f"{pack['credits']:,} OMNICRAFT credits",
                    "description": "One-time credit top up. Credits never expire.",
                },
            },
        }],
        success_url=f"{settings.FRONTEND_BASE_URL}/?billing=credits&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.FRONTEND_BASE_URL}/?billing=cancelled",
        metadata={"user_id": user_id, "kind": "credits", "credits": str(pack["credits"]),
                  "pack": pack["code"]},
    )
    return {"url": session["url"], "session_id": session["id"]}


async def billing_portal(customer_id: str) -> str:
    stripe = _stripe()
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=settings.FRONTEND_BASE_URL
    )
    return session["url"]


async def cancel_subscription(subscription_id: str) -> None:
    stripe = _stripe()
    stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)


def verify_webhook(payload: bytes, signature: str) -> dict[str, Any]:
    stripe = _stripe()
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise FeatureUnavailable("Stripe webhooks", "STRIPE_WEBHOOK_SECRET")
    return stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
