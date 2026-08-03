"""Feature 8 - web research."""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import CREDIT_COSTS
from ..database import SessionLocal, get_db
from ..deps import get_current_user
from ..models import JobStatus, ResearchTask, User
from ..schemas import ResearchIn
from ..security import limiter
from ..services import research_service
from ..utils import credits as credit_utils
from ..utils import jobs as job_utils
from ..utils.files import register_file, unique_name, user_dir
from ..websocket import hub

log = logging.getLogger("omnicraft.routes.research")
router = APIRouter(prefix="/api/research", tags=["research"])


@router.post("", status_code=202)
@limiter.limit("15/minute")
async def start(
    request: Request,
    payload: ResearchIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cost = CREDIT_COSTS["research.deep" if payload.depth == "deep" else "research.basic"]
    await credit_utils.charge(db, user, cost, f"research.{payload.depth}", payload.query[:120])

    task = ResearchTask(user_id=user.id, query=payload.query, depth=payload.depth)
    db.add(task)
    await db.flush()
    await db.commit()

    job_utils.dispatch(background, "omnicraft.research.run", _run, task.id, user.id, payload.model_dump(), cost)
    return {"task_id": task.id, "status": "queued", "credits_charged": cost}


async def _run(task_id: str, user_id: str, payload: dict, cost: int) -> None:
    async with SessionLocal() as db:
        task = await db.get(ResearchTask, task_id)
        user = await db.get(User, user_id)
        if not task or not user:
            return
        try:
            task.status = JobStatus.running
            await db.commit()
            await hub.publish(user_id, {"type": "research.progress", "task_id": task_id,
                                        "stage": "Searching", "progress": 20})

            result = await research_service.run_research(
                payload["query"], payload["depth"], payload["max_sources"]
            )
            await hub.publish(user_id, {"type": "research.progress", "task_id": task_id,
                                        "stage": "Writing the briefing", "progress": 80})

            report_path = user_dir(user_id) / unique_name("research-report.md")
            lines = [f"# {payload['query']}", "", result["report"], "", "## Sources"]
            lines += [f"{i+1}. [{s['title']}]({s['url']})" for i, s in enumerate(result["sources"])]
            report_path.write_text("\n".join(lines), encoding="utf-8")
            record = await register_file(db, user, report_path, report_path.name, "text/markdown")

            task.status = JobStatus.completed
            task.results = {**result, "file_id": record.id}
            task.report_path = str(report_path)
            await db.commit()
            await hub.publish(user_id, {"type": "research.completed", "task_id": task_id,
                                        "result": task.results})
        except Exception as exc:
            log.exception("Research task %s failed", task_id)
            task.status = JobStatus.failed
            task.error_message = str(exc)[:500]
            await credit_utils.refund(db, user, cost, "Refund: research failed", task_id)
            await db.commit()
            await hub.publish(user_id, {"type": "research.failed", "task_id": task_id,
                                        "error": task.error_message})


@router.get("")
async def history(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(ResearchTask).where(ResearchTask.user_id == user.id)
            .order_by(desc(ResearchTask.created_at)).limit(50)
        )
    ).scalars().all()
    return {
        "tasks": [
            {"id": t.id, "query": t.query, "depth": t.depth, "status": t.status.value,
             "created_at": t.created_at, "has_report": bool(t.report_path)}
            for t in rows
        ]
    }


@router.get("/{task_id}")
async def detail(task_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    task = await db.get(ResearchTask, task_id)
    if not task or task.user_id != user.id:
        raise HTTPException(404, "No research task with that id.")
    return {
        "id": task.id, "query": task.query, "depth": task.depth, "status": task.status.value,
        "results": task.results, "error_message": task.error_message, "created_at": task.created_at,
    }
