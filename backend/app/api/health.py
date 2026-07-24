"""Health-check endpoint.

This is intentionally the very first endpoint in the system: it lets
the frontend, Docker Compose, and CI all verify "is the backend up and
correctly configured" without touching the database or any external
service. Later phases can extend this into a richer
``/system/status`` endpoint (queue depth, worker health, DB
connectivity) without changing this contract.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Response body for the health-check endpoint."""

    status: str
    app_name: str
    environment: str
    timestamp: datetime


@router.get("/health", response_model=HealthResponse)
def get_health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Report basic liveness and configuration of the API process."""
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        environment=settings.environment,
        timestamp=datetime.now(UTC),
    )
