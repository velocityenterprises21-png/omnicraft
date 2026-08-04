"""Application configuration. Every secret is read from the environment."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- Server -----------------------------------------------------------
    APP_NAME: str = "OMNICRAFT"
    TAGLINE: str = "One System. All Media. Infinite Possibilities."
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = False

    # --- Security ---------------------------------------------------------
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_TTL_MINUTES: int = 30
    REFRESH_TOKEN_TTL_DAYS: int = 30
    JWT_ALGORITHM: str = "HS256"
    RATE_LIMIT: str = "100/minute"
    CORS_ORIGINS: str =  "http://localhost:3000,http://localhost:5173,https://omnicraft-three.vercel.app,https://omnicraft-pen44wess-velocity-project.vercel.app,https://omnicraft.vercel.app"
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    FRONTEND_BASE_URL: str = "http://localhost:3000"

    # --- Data -------------------------------------------------------------
    DATABASE_URL: str = "sqlite+aiosqlite:///./omnicraft.db"
    REDIS_URL: str = ""

    # --- Storage ----------------------------------------------------------
    STORAGE_BACKEND: str = "local"  # local | s3
    LOCAL_STORAGE_PATH: str = "./storage"
    MAX_UPLOAD_MB: int = 2048
    TEMP_FILE_TTL_HOURS: int = 48
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_STORAGE_BUCKET_NAME: str = ""
    AWS_REGION: str = "us-east-1"

    # --- Third-party AI providers ----------------------------------------
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    RUNWAY_API_KEY: str = ""
    REPLICATE_API_KEY: str = ""
    PEXELS_API_KEY: str = ""
    SERPER_API_KEY: str = ""
    ACOUSTID_API_KEY: str = ""

    # --- Payments ---------------------------------------------------------
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # --- Binaries ---------------------------------------------------------
    FFMPEG_BIN: str = "ffmpeg"
    FFPROBE_BIN: str = "ffprobe"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


# ---------------------------------------------------------------------------
# Credit pricing. Single source of truth shared by the API and the UI.
# ---------------------------------------------------------------------------
CREDIT_COSTS = {
    "download.short": 1,       # under 5 minutes
    "download.long": 2,        # 5 - 30 minutes
    "download.hires": 3,       # 4K / 8K source
    "tts.per_minute": 2,
    "narration": 5,
    "subtitles.extract": 2,
    "subtitles.translate": 3,
    "storyline": 1,
    "rights.scan": 2,
    "rights.remediate": 3,
    "research.basic": 5,
    "research.deep": 20,
    "video.720p_per_min": 15,
    "video.1080p_per_min": 10,
    "video.4k_per_min": 10,
    "video.8k_per_min": 15,
    "priority_surcharge": 5,
}

# Explicit table for AI video generation, matching the published price list.
VIDEO_CREDIT_TABLE = [
    {"minutes": 1, "quality": "720p", "credits": 15},
    {"minutes": 5, "quality": "1080p", "credits": 50},
    {"minutes": 20, "quality": "4K", "credits": 200},
    {"minutes": 60, "quality": "4K", "credits": 600},
    {"minutes": 60, "quality": "8K", "credits": 900},
]

CREDIT_PACKAGES = [
    {"code": "pack_50", "credits": 50, "price_usd": 4.99},
    {"code": "pack_100", "credits": 100, "price_usd": 8.99},
    {"code": "pack_250", "credits": 250, "price_usd": 19.99},
    {"code": "pack_500", "credits": 500, "price_usd": 34.99},
    {"code": "pack_1000", "credits": 1000, "price_usd": 59.99},
    {"code": "pack_5000", "credits": 5000, "price_usd": 249.99},
    {"code": "pack_10000", "credits": 10000, "price_usd": 449.99},
]

GB = 1024 ** 3
TB = 1024 ** 4

PLAN_CATALOG = [
    {
        "name": "free", "display_name": "Free", "price_monthly": 0.0, "price_yearly": 0.0,
        "credits_included": 5, "storage_limit": 1 * GB, "max_video_length": 60,
        "export_quality": "480p", "priority_queue": False, "api_access": False,
        "white_label": False, "watermark": True, "sort_order": 0,
        "features": ["5 starter credits, one time", "1 GB storage", "1 minute clips",
                     "480p exports", "OMNICRAFT watermark"],
    },
    {
        "name": "starter", "display_name": "Starter", "price_monthly": 9.99, "price_yearly": 95.88,
        "credits_included": 100, "storage_limit": 10 * GB, "max_video_length": 600,
        "export_quality": "720p", "priority_queue": False, "api_access": False,
        "white_label": False, "watermark": False, "sort_order": 1,
        "features": ["100 credits a month", "10 GB storage", "10 minute videos",
                     "720p exports", "Every module unlocked", "No watermark"],
    },
    {
        "name": "pro", "display_name": "Pro", "price_monthly": 24.99, "price_yearly": 239.88,
        "credits_included": 350, "storage_limit": 50 * GB, "max_video_length": 1800,
        "export_quality": "1080p", "priority_queue": True, "api_access": False,
        "white_label": False, "watermark": False, "sort_order": 2,
        "features": ["350 credits a month", "50 GB storage", "30 minute videos",
                     "1080p exports", "Priority queue"],
    },
    {
        "name": "business", "display_name": "Business", "price_monthly": 59.99, "price_yearly": 575.88,
        "credits_included": 1200, "storage_limit": 200 * GB, "max_video_length": 3600,
        "export_quality": "4K", "priority_queue": True, "api_access": True,
        "white_label": False, "watermark": False, "sort_order": 3,
        "features": ["1,200 credits a month", "200 GB storage", "60 minute videos",
                     "4K exports", "Priority queue", "REST API keys"],
    },
    {
        "name": "enterprise", "display_name": "Enterprise", "price_monthly": 149.99, "price_yearly": 1439.88,
        "credits_included": 4000, "storage_limit": 1 * TB, "max_video_length": 0,
        "export_quality": "8K", "priority_queue": True, "api_access": True,
        "white_label": True, "watermark": False, "sort_order": 4,
        "features": ["4,000 credits a month", "1 TB storage", "Unlimited length",
                     "8K exports", "White label", "Named support contact"],
    },
    {
        "name": "ultimate", "display_name": "Ultimate", "price_monthly": 299.99, "price_yearly": 2879.88,
        "credits_included": 12000, "storage_limit": 5 * TB, "max_video_length": 0,
        "export_quality": "8K+", "priority_queue": True, "api_access": True,
        "white_label": True, "watermark": False, "sort_order": 5,
        "features": ["12,000 credits a month", "5 TB storage", "Unlimited length",
                     "8K+ exports", "Custom model fine tunes", "Dedicated worker pool",
                     "99.9% uptime SLA"],
    },
]
