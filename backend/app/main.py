"""OMNICRAFT API entrypoint."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .auth import decode_token
from .config import settings
from .database import SessionLocal, init_models
from .security import SecurityHeadersMiddleware, limiter, rate_limit_handler
from .seed import run_all as seed_all
from .utils.files import STORAGE_ROOT, purge_expired
from .utils.jobs import reconcile_orphans
from .websocket import hub

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("omnicraft")


async def _janitor() -> None:
    """Hourly sweep of expired temporary files."""
    while True:
        try:
            await asyncio.sleep(3600)
            async with SessionLocal() as db:
                removed = await purge_expired(db)
            if removed:
                log.info("Cleared %d expired temporary files.", removed)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Cleanup sweep failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
    await init_models()
    await seed_all()

    # Anything left 'running' belongs to a process that no longer exists.
    async with SessionLocal() as db:
        stranded = await reconcile_orphans(db)
    if stranded:
        log.warning("Failed %d job(s) interrupted by the last shutdown; credits refunded.", stranded)

    task = asyncio.create_task(_janitor())
    log.info("%s is up on %s:%s", settings.APP_NAME, settings.HOST, settings.PORT)
    yield
    task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    description=settings.TAGLINE,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.ENVIRONMENT != "production" else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    max_age=600,
)

from .routes import (admin, auth, autopilot, download, narration, payments,  # noqa: E402
                     research, rights, storage, storyline, subtitles, system, tts, video)

for module in (system, auth, download, tts, narration, subtitles, storyline, rights,
               autopilot, research, storage, payments, video, admin):
    try:
        app.include_router(module.router)
    except Exception as exc:
        # FastAPI raises here when it can't build a request/response field for a
        # route. The default traceback doesn't say which module, so name it.
        log.error("=" * 72)
        log.error("ROUTER FAILED TO REGISTER: %s", module.__name__)
        log.error("%s: %s", type(exc).__name__, exc)
        log.error("=" * 72)
        raise


@app.get("/")
async def root():
    return {
        "name": settings.APP_NAME,
        "tagline": settings.TAGLINE,
        "version": "1.0.0",
        "docs": "/api/docs" if settings.ENVIRONMENT != "production" else None,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(default="")):
    claims = decode_token(token)
    if not claims:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    user_id = claims["sub"]
    await hub.connect(user_id, websocket)
    try:
        await websocket.send_json({"type": "connected", "user_id": user_id})
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("WebSocket closed unexpectedly", exc_info=True)
    finally:
        await hub.disconnect(user_id, websocket)


@app.exception_handler(500)
async def internal_error(request, exc):
    log.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something broke on our side. The error is logged and we're on it."},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
