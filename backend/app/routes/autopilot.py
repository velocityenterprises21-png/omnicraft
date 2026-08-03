"""Feature 7 - natural language orchestration across the other modules."""
from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..deps import current_plan, get_current_user
from ..models import SubscriptionPlan, User
from ..schemas import (AutopilotIn, DownloadIn, ResearchIn, StorylineIn, SubtitleExtractIn,
                       TTSIn, VideoCreateIn)
from ..security import limiter
from ..services.llm import llm
from ..utils import credits as credit_utils
from . import download as download_routes
from . import research as research_routes
from . import storyline as storyline_routes
from . import subtitles as subtitle_routes
from . import tts as tts_routes
from . import video as video_routes

log = logging.getLogger("omnicraft.routes.autopilot")
router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])

CAPABILITIES = {
    "download": "Fetch a video or audio track from a supported link.",
    "tts": "Turn written text into a voiceover.",
    "subtitles": "Transcribe speech into a subtitle file.",
    "translate": "Translate an existing subtitle file.",
    "storyline": "Summarise, clean up or restructure a transcript.",
    "research": "Search the web and write a sourced briefing.",
    "video": "Generate a narrated video from a brief or script.",
}

URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")


def _heuristic_plan(command: str) -> dict[str, Any]:
    text = command.lower()
    urls = URL_PATTERN.findall(command)
    steps: list[dict[str, Any]] = []

    if urls and any(w in text for w in ("download", "grab", "fetch", "save", "rip", "pull")):
        steps.append({"action": "download", "args": {"url": urls[0], "quality": "best"}})
    if any(w in text for w in ("subtitle", "caption", "transcribe", "transcript", "srt")):
        steps.append({"action": "subtitles", "args": {"url": urls[0] if urls else None, "language": "auto"}})
    if any(w in text for w in ("summar", "rephrase", "rewrite", "bullet", "clean up")):
        mode = "bullets" if "bullet" in text else "summary"
        steps.append({"action": "storyline", "args": {"url": urls[0] if urls else None, "mode": mode}})
    if any(w in text for w in ("research", "look up", "find out", "investigate")):
        depth = "deep" if "deep" in text or "thorough" in text else "basic"
        steps.append({"action": "research", "args": {"query": command, "depth": depth}})
    if any(w in text for w in ("voiceover", "narrate", "read this", "speak", "voice over")):
        steps.append({"action": "tts", "args": {"text": command}})
    if any(w in text for w in ("make a video", "create a video", "generate a video", "produce a video")):
        steps.append({"action": "video", "args": {"prompt": command, "duration_seconds": 60,
                                                  "quality": "1080p"}})

    if not steps:
        steps.append({"action": "research", "args": {"query": command, "depth": "basic"}})
    return {"steps": steps, "planner": "keyword"}


async def build_plan(command: str) -> dict[str, Any]:
    fallback = _heuristic_plan(command)
    if not llm.available:
        return fallback

    catalogue = "\n".join(f"- {name}: {desc}" for name, desc in CAPABILITIES.items())
    plan = await llm.json_complete(
        f"Available actions:\n{catalogue}\n\nUser request: {command}\n\n"
        "Break the request into ordered steps. Only use listed actions. "
        "Args may include: url, text, query, depth, mode, language, prompt, duration_seconds, quality, voice_id.",
        system=(
            "You plan media production jobs. Return "
            "{\"steps\":[{\"action\":str,\"args\":object,\"why\":str}]}. "
            "If the request needs no action, return an empty steps array."
        ),
        fallback=fallback,
    )
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not steps:
        return fallback
    valid = [s for s in steps if isinstance(s, dict) and s.get("action") in CAPABILITIES]
    return {"steps": valid or fallback["steps"], "planner": llm.provider}


def _estimate(steps: list[dict[str, Any]]) -> int:
    from ..config import CREDIT_COSTS
    total = 0
    for step in steps:
        action, args = step.get("action"), step.get("args") or {}
        if action == "download":
            total += CREDIT_COSTS["download.short"]
        elif action == "tts":
            total += credit_utils.estimate_tts(len(args.get("text", "")))
        elif action == "subtitles":
            total += CREDIT_COSTS["subtitles.extract"]
        elif action == "translate":
            total += CREDIT_COSTS["subtitles.translate"]
        elif action == "storyline":
            total += CREDIT_COSTS["storyline"]
        elif action == "research":
            total += CREDIT_COSTS["research.deep" if args.get("depth") == "deep" else "research.basic"]
        elif action == "video":
            total += credit_utils.estimate_video(
                int(args.get("duration_seconds", 60)), args.get("quality", "1080p")
            )
    return total


@router.get("/capabilities")
async def capabilities():
    return {"capabilities": CAPABILITIES, "planner": llm.provider}


@router.post("/plan")
@limiter.limit("30/minute")
async def plan_only(request: Request, payload: AutopilotIn, user: User = Depends(get_current_user)):
    plan = await build_plan(payload.command)
    return {**plan, "estimated_credits": _estimate(plan["steps"]), "balance": user.credits_balance}


@router.post("/run")
@limiter.limit("15/minute")
async def run(
    request: Request,
    payload: AutopilotIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    plan_row: SubscriptionPlan = Depends(current_plan),
    db: AsyncSession = Depends(get_db),
):
    plan = await build_plan(payload.command)
    estimated = _estimate(plan["steps"])

    if payload.dry_run:
        return {**plan, "estimated_credits": estimated, "dispatched": [], "dry_run": True}

    await credit_utils.ensure_balance(user, estimated)

    dispatched: list[dict[str, Any]] = []
    for step in plan["steps"]:
        action, args = step["action"], step.get("args") or {}
        try:
            if action == "download" and args.get("url"):
                job = await download_routes.start_download(
                    request, DownloadIn(url=args["url"], quality=args.get("quality", "best")),
                    background, user, plan_row, db,
                )
                dispatched.append({"action": action, "job_id": job.id, "kind": "job"})

            elif action == "tts" and args.get("text"):
                job = await tts_routes.generate(
                    request, TTSIn(text=args["text"], voice_id=args.get("voice_id", "default")),
                    background, user, plan_row, db,
                )
                dispatched.append({"action": action, "job_id": job.id, "kind": "job"})

            elif action == "subtitles":
                job = await subtitle_routes.extract(
                    request,
                    SubtitleExtractIn(url=args.get("url"), file_id=args.get("file_id"),
                                      language=args.get("language", "auto")),
                    background, user, db,
                )
                dispatched.append({"action": action, "job_id": job.id, "kind": "job"})

            elif action == "storyline":
                result = await storyline_routes.generate(
                    request,
                    StorylineIn(url=args.get("url"), text=args.get("text"),
                                source_file_id=args.get("file_id"), mode=args.get("mode", "summary")),
                    user, db,
                )
                dispatched.append({"action": action, "result": result, "kind": "inline"})

            elif action == "research":
                result = await research_routes.start(
                    request, ResearchIn(query=args.get("query", payload.command),
                                        depth=args.get("depth", "basic")),
                    background, user, db,
                )
                dispatched.append({"action": action, "task_id": result["task_id"], "kind": "research"})

            elif action == "video":
                job = await video_routes.create(
                    request,
                    VideoCreateIn(prompt=args.get("prompt", payload.command),
                                  script=args.get("script"),
                                  duration_seconds=int(args.get("duration_seconds", 60)),
                                  quality=args.get("quality", "1080p")),
                    background, user, plan_row, db,
                )
                dispatched.append({"action": action, "job_id": job.id, "kind": "job"})

            else:
                dispatched.append({"action": action, "kind": "skipped",
                                   "reason": "That step was missing the input it needed."})
        except Exception as exc:
            detail = getattr(exc, "detail", str(exc))
            dispatched.append({"action": action, "kind": "error", "reason": detail})

    return {**plan, "estimated_credits": estimated, "dispatched": dispatched,
            "balance": user.credits_balance}
