"""Domain errors that map onto friendly HTTP responses."""
from __future__ import annotations

from fastapi import HTTPException


class FeatureUnavailable(HTTPException):
    """A provider key is missing. The UI shows this verbatim."""

    def __init__(self, provider: str, env_var: str, workaround: str | None = None):
        detail = {
            "code": "provider_not_configured",
            "provider": provider,
            "env_var": env_var,
            "message": f"{provider} isn't connected yet. Add {env_var} to your .env and restart the API.",
        }
        if workaround:
            detail["workaround"] = workaround
        super().__init__(status_code=503, detail=detail)


class InsufficientCredits(HTTPException):
    def __init__(self, needed: int, balance: int):
        super().__init__(
            status_code=402,
            detail={
                "code": "insufficient_credits",
                "needed": needed,
                "balance": balance,
                "message": f"This run costs {needed} credits and you have {balance}. Top up or upgrade to continue.",
            },
        )


class QuotaExceeded(HTTPException):
    def __init__(self, message: str, limit: int | None = None):
        super().__init__(
            status_code=403,
            detail={"code": "quota_exceeded", "limit": limit, "message": message},
        )


class ToolMissing(HTTPException):
    def __init__(self, binary: str):
        super().__init__(
            status_code=503,
            detail={
                "code": "tool_missing",
                "message": f"{binary} isn't installed on the server. Install it and restart the API.",
            },
        )
