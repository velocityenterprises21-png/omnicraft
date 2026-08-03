"""Pydantic request/response models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth -----------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginIn(BaseModel):
    identifier: str
    password: str
    totp_code: Optional[str] = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class TwoFactorSetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    recovery_codes: list[str]


class TwoFactorVerifyIn(BaseModel):
    code: str


class UserOut(ORMBase):
    id: str
    email: EmailStr
    username: str
    role: str
    tier: str
    billing_interval: str
    credits_balance: int
    storage_used: int
    twofa_enabled: bool
    subscription_status: str
    subscription_renews_at: Optional[datetime] = None
    created_at: datetime


# --- Jobs -----------------------------------------------------------------
class JobOut(ORMBase):
    id: str
    job_type: str
    status: str
    progress: int
    stage: str
    credits_charged: int
    input_data: Optional[dict[str, Any]] = None
    output_data: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


# --- Feature payloads -----------------------------------------------------
class DownloadIn(BaseModel):
    url: str
    quality: str = Field(default="best", pattern="^(best|2160p|1440p|1080p|720p|480p|audio)$")
    audio_only: bool = False
    priority: bool = False


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voice_id: str = "default"
    language: str = "en"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stability: float = Field(default=0.5, ge=0.0, le=1.0)
    priority: bool = False


class NarrationIn(BaseModel):
    video_file_id: str
    script: Optional[str] = None
    audio_file_id: Optional[str] = None
    voice_id: str = "default"
    mode: str = Field(default="mix", pattern="^(replace|mix|duck)$")
    original_volume: float = Field(default=0.2, ge=0.0, le=1.0)
    narration_volume: float = Field(default=1.0, ge=0.0, le=1.5)
    priority: bool = False


class SubtitleExtractIn(BaseModel):
    file_id: Optional[str] = None
    url: Optional[str] = None
    language: str = "auto"
    format: str = Field(default="srt", pattern="^(srt|vtt|txt|json)$")
    priority: bool = False


class SubtitleTranslateIn(BaseModel):
    file_id: str
    target_language: str
    format: str = Field(default="srt", pattern="^(srt|vtt|txt)$")


class StorylineIn(BaseModel):
    source_file_id: Optional[str] = None
    url: Optional[str] = None
    text: Optional[str] = None
    mode: str = Field(default="summary", pattern="^(summary|bullets|clean|script|chapters)$")
    tone: str = "neutral"
    target_words: int = Field(default=250, ge=40, le=4000)


class RightsScanIn(BaseModel):
    file_id: str


class RightsRemediateIn(BaseModel):
    file_id: str
    action: str = Field(default="mute", pattern="^(mute|remove_music|replace)$")
    replacement_track_id: Optional[str] = None
    segments: Optional[list[dict[str, float]]] = None


class ResearchIn(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    depth: str = Field(default="basic", pattern="^(basic|deep)$")
    max_sources: int = Field(default=8, ge=1, le=40)


class VideoCreateIn(BaseModel):
    prompt: Optional[str] = None
    script: Optional[str] = None
    source_url: Optional[str] = None
    source_file_id: Optional[str] = None
    duration_seconds: int = Field(default=60, ge=15, le=3600)
    quality: str = Field(default="1080p", pattern="^(480p|720p|1080p|4K|8K)$")
    aspect_ratio: str = Field(default="16:9", pattern="^(16:9|9:16|1:1|4:5|21:9)$")
    voice_id: str = "default"
    captions: bool = True
    music: bool = True
    priority: bool = False


class AutopilotIn(BaseModel):
    command: str = Field(min_length=3, max_length=4000)
    dry_run: bool = False


class ShareIn(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=720)


class CheckoutIn(BaseModel):
    plan: Optional[str] = None
    interval: str = Field(default="monthly", pattern="^(monthly|yearly)$")
    credit_pack: Optional[str] = None


class PlanOut(ORMBase):
    name: str
    display_name: str
    price_monthly: float
    price_yearly: float
    credits_included: int
    storage_limit: int
    max_video_length: int
    export_quality: str
    features: Optional[list[str]] = None
    priority_queue: bool
    api_access: bool
    white_label: bool
    watermark: bool
    sort_order: int


class FileOut(ORMBase):
    id: str
    filename: str
    file_size: int
    file_type: str
    kind: str
    storage_type: str
    duration_seconds: Optional[float] = None
    is_temp: bool
    expires_at: Optional[datetime] = None
    share_token: Optional[str] = None
    created_at: datetime


class TransactionOut(ORMBase):
    id: str
    amount: int
    balance_after: int
    type: str
    description: str
    feature_used: Optional[str] = None
    created_at: datetime
