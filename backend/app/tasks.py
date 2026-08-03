"""Optional Celery worker.

FastAPI BackgroundTasks handle jobs out of the box, which is enough for a single
node. Set REDIS_URL and run a worker to move rendering onto separate machines:

    celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
"""
from __future__ import annotations

import asyncio
import logging

from .config import settings

log = logging.getLogger("omnicraft.tasks")

celery_app = None

if settings.REDIS_URL:
    try:
        from celery import Celery

        celery_app = Celery("omnicraft", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
        celery_app.conf.update(
            task_serializer="json",
            accept_content=["json"],
            result_serializer="json",
            timezone="UTC",
            enable_utc=True,
            task_track_started=True,
            task_time_limit=7200,
            task_soft_time_limit=6900,
            worker_max_tasks_per_child=20,
            task_routes={
                "omnicraft.video.*": {"queue": "render"},
                "omnicraft.download.*": {"queue": "fetch"},
            },
        )
    except ImportError:
        log.warning("REDIS_URL is set but celery isn't installed. Staying on in-process jobs.")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if celery_app:

    @celery_app.task(name="omnicraft.download.run", bind=True, max_retries=2)
    def run_download(self, job_id: str, user_id: str, payload: dict):
        from .routes.download import _run_download
        return _run(_run_download(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.tts.run", bind=True, max_retries=2)
    def run_tts(self, job_id: str, user_id: str, payload: dict):
        from .routes.tts import _run_tts
        return _run(_run_tts(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.video.run", bind=True, max_retries=1)
    def run_video(self, job_id: str, user_id: str, payload: dict, watermark: bool):
        from .routes.video import _run as render
        return _run(render(job_id, user_id, payload, watermark))

    @celery_app.task(name="omnicraft.subtitles.run", bind=True, max_retries=2)
    def run_subtitles(self, job_id: str, user_id: str, payload: dict):
        from .routes.subtitles import _run_extract
        return _run(_run_extract(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.narration.run", bind=True, max_retries=2)
    def run_narration(self, job_id: str, user_id: str, payload: dict):
        from .routes.narration import _run as mix
        return _run(mix(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.subtitles.translate", bind=True, max_retries=2)
    def run_translate(self, job_id: str, user_id: str, payload: dict):
        from .routes.subtitles import _run_translate
        return _run(_run_translate(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.rights.run", bind=True, max_retries=1)
    def run_rights(self, job_id: str, user_id: str, payload: dict):
        from .routes.rights import _run as clear
        return _run(clear(job_id, user_id, payload))

    @celery_app.task(name="omnicraft.research.run", bind=True, max_retries=2)
    def run_research(self, task_id: str, user_id: str, payload: dict, cost: int):
        from .routes.research import _run as research
        return _run(research(task_id, user_id, payload, cost))

    @celery_app.task(name="omnicraft.maintenance.purge")
    def purge():
        from .database import SessionLocal
        from .utils.files import purge_expired

        async def _job():
            async with SessionLocal() as db:
                return await purge_expired(db)

        return _run(_job())

    celery_app.conf.beat_schedule = {
        "purge-temp-files": {"task": "omnicraft.maintenance.purge", "schedule": 3600.0},
    }
