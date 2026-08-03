"""Job lifecycle helpers with WebSocket progress fan-out."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Job, JobStatus, User
from ..websocket import hub


async def create_job(
    db: AsyncSession,
    user: User,
    job_type: str,
    input_data: dict[str, Any],
    credits_charged: int = 0,
    priority: bool = False,
) -> Job:
    job = Job(
        user_id=user.id,
        job_type=job_type,
        input_data=input_data,
        credits_charged=credits_charged,
        priority=priority,
        status=JobStatus.queued,
        stage="Queued",
    )
    db.add(job)
    await db.flush()
    await hub.publish(user.id, {"type": "job.created", "job": _snapshot(job)})
    return job


async def update_progress(
    db: AsyncSession, job: Job, progress: int, stage: str, status: JobStatus | None = None
) -> None:
    job.progress = max(0, min(100, int(progress)))
    job.stage = stage
    if status:
        job.status = status
    if job.status == JobStatus.running and job.started_at is None:
        job.started_at = datetime.now(timezone.utc)
    await db.flush()
    await hub.publish(job.user_id, {"type": "job.progress", "job": _snapshot(job)})


async def complete_job(db: AsyncSession, job: Job, output: dict[str, Any]) -> None:
    job.status = JobStatus.completed
    job.progress = 100
    job.stage = "Done"
    job.output_data = output
    job.finished_at = datetime.now(timezone.utc)
    await db.flush()
    await hub.publish(job.user_id, {"type": "job.completed", "job": _snapshot(job)})


async def fail_job(db: AsyncSession, job: Job, message: str) -> None:
    job.status = JobStatus.failed
    job.stage = "Failed"
    job.error_message = message
    job.finished_at = datetime.now(timezone.utc)
    await db.flush()
    await hub.publish(job.user_id, {"type": "job.failed", "job": _snapshot(job)})


def dispatch(background, task_name: str, fallback, *args) -> str:
    """Hand work to a Celery worker when a broker is configured.

    Falls back to FastAPI BackgroundTasks (in the API process) when REDIS_URL
    is unset or celery isn't installed, so single-node installs need no queue.
    """
    celery_app = None
    try:
        from ..tasks import celery_app as configured
        celery_app = configured
    except Exception:  # pragma: no cover - tasks module is optional
        celery_app = None

    if celery_app is not None:
        try:
            celery_app.send_task(task_name, args=list(args))
            return "celery"
        except Exception:
            # Broker unreachable: better to run it here than lose the job.
            pass

    background.add_task(fallback, *args)
    return "inline"


async def reconcile_orphans(db: AsyncSession) -> int:
    """Fail jobs left mid-flight by a restart and refund their credits.

    In-process background tasks die with the API. Without this, those jobs sit
    at 'running' forever and the user is never refunded.
    """
    from sqlalchemy import select

    from .credits import refund

    rows = (
        await db.execute(
            select(Job).where(Job.status.in_([JobStatus.running, JobStatus.queued]))
        )
    ).scalars().all()

    for job in rows:
        user = await db.get(User, job.user_id)
        if user and job.credits_charged:
            await refund(db, user, job.credits_charged,
                         "Refund: interrupted by a server restart", job.id)
        job.status = JobStatus.failed
        job.stage = "Interrupted"
        job.error_message = "The server restarted while this job was running. Credits were refunded."
        job.finished_at = datetime.now(timezone.utc)

    if rows:
        await db.commit()
    return len(rows)


def _snapshot(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "progress": job.progress,
        "stage": job.stage,
        "credits_charged": job.credits_charged,
        "output_data": job.output_data,
        "error_message": job.error_message,
    }


def snapshot(job: Job) -> dict[str, Any]:
    return _snapshot(job)
