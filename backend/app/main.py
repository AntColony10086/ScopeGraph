"""FastAPI application entry point."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import auth, chat, data, health, profile
from app.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _install_minimax_payload_logger() -> None:
    """Patch httpx so any non-2xx response from MiniMax dumps the request body.

    This is invaluable for diagnosing intermittent `invalid chat setting (2013)`:
    we need to see WHICH payload triggers the rejection.
    """
    try:
        import httpx, json
        if getattr(httpx.AsyncClient, "_minimax_logger_installed", False):
            return
        original = httpx.AsyncClient.send

        async def patched(self, request, **kwargs):
            url = str(request.url)
            req_body = None
            if "minimaxi" in url and request.content:
                try:
                    req_body = json.loads(request.content.decode())
                except Exception:
                    req_body = None
            response = await original(self, request, **kwargs)
            if req_body and response.status_code >= 400:
                try:
                    text = response.text[:400]
                except Exception:
                    text = "(could not read response body)"
                msgs = req_body.get("messages") or []
                summary = [
                    f"{m.get('role')}:len={len(str(m.get('content','')))}"
                    for m in msgs
                ]
                logging.getLogger("minimax").warning(
                    "[MiniMax %d] tools=%s response_format=%s msgs=%s body=%s\nresp=%s",
                    response.status_code,
                    bool(req_body.get("tools")),
                    req_body.get("response_format"),
                    summary,
                    json.dumps(req_body, ensure_ascii=False)[:1500],
                    text,
                )
            return response

        httpx.AsyncClient.send = patched
        httpx.AsyncClient._minimax_logger_installed = True
        logger.info("MiniMax payload logger installed")
    except Exception as e:
        logger.warning("MiniMax payload logger failed to install: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Starting AI Customer Service backend...")
    _install_minimax_payload_logger()

    # Initialize MySQL tables
    try:
        from app.models.database import init_db
        await init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning(f"Database init skipped: {e}")

    yield

    # Cleanup
    logger.info("Shutting down...")
    try:
        from app.memory.session_manager import close_session
        await close_session()
    except Exception:
        pass
    try:
        from app.knowledge.neo4j_client import close_connections
        await close_connections()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="AI Customer Service System",
        description="Multi-Agent e-commerce intelligent customer service powered by LangGraph",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS — allow frontend dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(profile.router)
    app.include_router(data.router)

    # Static: avatars + uploads
    uploads_dir = Path(__file__).parent.parent / "uploads"
    avatars_dir = uploads_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/static/avatars", StaticFiles(directory=str(avatars_dir)), name="avatars")
    app.mount("/static/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
