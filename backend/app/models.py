"""SQLAlchemy ORM models."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, enum.Enum):
    user = "user"
    moderator = "moderator"
    admin = "admin"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SubscriptionStatus(str, enum.Enum):
    none = "none"
    active = "active"
    trialing = "trialing"
    past_due = "past_due"
    canceled = "canceled"


class TransactionType(str, enum.Enum):
    grant = "grant"          # plan renewal / signup bonus
    purchase = "purchase"    # one-off credit pack
    spend = "spend"
    refund = "refund"
    adjustment = "adjustment"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.user, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    twofa_secret: Mapped[Optional[str]] = mapped_column(String(64))
    twofa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    twofa_recovery_codes: Mapped[Optional[Any]] = mapped_column(JSON)

    credits_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    storage_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(16), default="monthly", nullable=False)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.none, nullable=False
    )
    subscription_renews_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    api_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    files: Mapped[list["File"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[list["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[list["CreditTransaction"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class RefreshToken(Base, TimestampMixin):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))


class File(Base, TimestampMixin):
    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    file_type: Mapped[str] = mapped_column(String(64), default="application/octet-stream")
    kind: Mapped[str] = mapped_column(String(32), default="other")  # video | audio | text | image | other
    storage_type: Mapped[str] = mapped_column(String(16), default="local")  # local | s3
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)
    is_temp: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    share_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    job_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)

    user: Mapped[User] = relationship(back_populates="files")


class CreditTransaction(Base, TimestampMixin):
    __tablename__ = "credit_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # negative = spend
    balance_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    type: Mapped[TransactionType] = mapped_column(Enum(TransactionType), nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="")
    feature_used: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    reference: Mapped[Optional[str]] = mapped_column(String(128))  # stripe id / job id

    user: Mapped[User] = relationship(back_populates="transactions")


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_type: Mapped[str] = mapped_column(String(48), index=True, nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stage: Mapped[str] = mapped_column(String(120), default="Queued")
    priority: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    input_data: Mapped[Optional[Any]] = mapped_column(JSON)
    output_data: Mapped[Optional[Any]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="jobs")


class ResearchTask(Base, TimestampMixin):
    __tablename__ = "research_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[str] = mapped_column(String(16), default="basic")
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    results: Mapped[Optional[Any]] = mapped_column(JSON)
    report_path: Mapped[Optional[str]] = mapped_column(String(1024))
    error_message: Mapped[Optional[str]] = mapped_column(Text)


class SubscriptionPlan(Base, TimestampMixin):
    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    price_monthly: Mapped[float] = mapped_column(Float, default=0.0)
    price_yearly: Mapped[float] = mapped_column(Float, default=0.0)
    credits_included: Mapped[int] = mapped_column(Integer, default=0)
    storage_limit: Mapped[int] = mapped_column(BigInteger, default=0)
    max_video_length: Mapped[int] = mapped_column(Integer, default=60)  # seconds, 0 = unlimited
    export_quality: Mapped[str] = mapped_column(String(16), default="480p")
    features: Mapped[Optional[Any]] = mapped_column(JSON)
    priority_queue: Mapped[bool] = mapped_column(Boolean, default=False)
    api_access: Mapped[bool] = mapped_column(Boolean, default=False)
    white_label: Mapped[bool] = mapped_column(Boolean, default=False)
    watermark: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    stripe_price_id_monthly: Mapped[Optional[str]] = mapped_column(String(64))
    stripe_price_id_yearly: Mapped[Optional[str]] = mapped_column(String(64))


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"
    __table_args__ = (UniqueConstraint("id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[Optional[Any]] = mapped_column(JSON)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
