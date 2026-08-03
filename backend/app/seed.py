"""Idempotent seeding of the plan catalog and the bootstrap admin account."""
from __future__ import annotations

import logging
import os

from sqlalchemy import select

from .auth import hash_password
from .config import PLAN_CATALOG
from .database import SessionLocal
from .models import Role, SubscriptionPlan, TransactionType, User
from .utils.credits import grant

log = logging.getLogger("omnicraft.seed")


async def seed_plans() -> None:
    async with SessionLocal() as db:
        for spec in PLAN_CATALOG:
            existing = (
                await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == spec["name"]))
            ).scalar_one_or_none()
            price_env = spec["name"].upper()
            monthly_price_id = os.getenv(f"STRIPE_PRICE_{price_env}_MONTHLY", "")
            yearly_price_id = os.getenv(f"STRIPE_PRICE_{price_env}_YEARLY", "")
            if existing:
                for key, value in spec.items():
                    setattr(existing, key, value)
                existing.stripe_price_id_monthly = monthly_price_id or existing.stripe_price_id_monthly
                existing.stripe_price_id_yearly = yearly_price_id or existing.stripe_price_id_yearly
            else:
                db.add(SubscriptionPlan(
                    **spec,
                    stripe_price_id_monthly=monthly_price_id,
                    stripe_price_id_yearly=yearly_price_id,
                ))
        await db.commit()
    log.info("Plan catalog seeded (%d plans).", len(PLAN_CATALOG))


async def seed_admin() -> None:
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")
    if not email or not password:
        return
    async with SessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing:
            return
        admin = User(
            email=email,
            username=os.getenv("ADMIN_USERNAME", "admin"),
            password_hash=hash_password(password),
            role=Role.admin,
            tier="ultimate",
            is_verified=True,
        )
        db.add(admin)
        await db.flush()
        await grant(db, admin, 12000, TransactionType.grant, "Admin bootstrap allowance")
        await db.commit()
    log.info("Admin account created for %s", email)


async def run_all() -> None:
    await seed_plans()
    await seed_admin()
