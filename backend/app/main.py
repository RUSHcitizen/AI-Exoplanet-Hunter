"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.demo import router as demo_router
from app.api.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log process startup/shutdown so process lifecycle is auditable."""
    logger.info("application_startup", environment=settings.environment)
    yield
    logger.info("application_shutdown")


def create_app(app_settings: Settings | None = None) -> FastAPI:
    """Application factory, so tests can build a fresh app instance.

    ``app_settings`` defaults to the process-wide cached settings;
    passing an explicit instance (as CORS tests do) builds an app whose
    CORS configuration reflects that instance instead, without touching
    global process state.
    """
    resolved_settings = app_settings or settings
    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    # This API is public and read-only: no cookies, no browser-stored
    # credentials, no auth headers. CORS here is purely a browser-side
    # convenience to let the deployed Vercel frontend call this backend;
    # it is not, and must never be treated as, an authentication boundary.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_origin_regex=resolved_settings.cors_origin_regex,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(health_router, prefix=resolved_settings.api_v1_prefix)
    app.include_router(health_router)  # unversioned alias for infra probes
    app.include_router(demo_router, prefix=resolved_settings.api_v1_prefix)

    return app


app = create_app()
