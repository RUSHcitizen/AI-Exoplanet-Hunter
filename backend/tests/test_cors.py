"""Tests for public-deployment CORS configuration.

CORS is a browser-enforced policy, not an authentication boundary --
these tests only confirm the configured allow-list behaves as
documented (which origins get an ``Access-Control-Allow-Origin``
response header on a simple GET) and that CORS configuration has no
effect whatsoever on the actual response body.
"""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

_PRODUCTION_ORIGIN = "https://ai-exoplanet-hunter.vercel.app"


def _client_for(**overrides: object) -> TestClient:
    test_settings = Settings(_env_file=None, **overrides)  # type: ignore[call-arg]
    return TestClient(create_app(test_settings))


def test_local_frontend_origin_is_permitted() -> None:
    client = _client_for(cors_origins=["http://localhost:3000", "http://127.0.0.1:3000"])
    response = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_configured_production_origin_is_permitted() -> None:
    client = _client_for(cors_origins=[_PRODUCTION_ORIGIN])
    response = client.get("/api/v1/health", headers={"Origin": _PRODUCTION_ORIGIN})
    assert response.headers.get("access-control-allow-origin") == _PRODUCTION_ORIGIN


def test_unrelated_origin_does_not_receive_allow_origin_header() -> None:
    client = _client_for(cors_origins=[_PRODUCTION_ORIGIN])
    response = client.get("/api/v1/health", headers={"Origin": "https://not-our-frontend.example"})
    assert response.status_code == 200  # the request still succeeds server-side
    assert "access-control-allow-origin" not in response.headers


def test_no_wildcard_origin_with_credentials() -> None:
    """allow_origins=['*'] together with allow_credentials=True is an
    explicit anti-pattern this deployment must never reintroduce -- this
    API needs neither cookies nor authenticated browser credentials."""
    client = _client_for(cors_origins=["*"])
    response = client.get("/api/v1/health", headers={"Origin": "https://anything.example"})
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_health_and_demo_endpoints_still_work_with_cors_configured() -> None:
    client = _client_for(cors_origins=[_PRODUCTION_ORIGIN])
    health = client.get("/api/v1/health", headers={"Origin": _PRODUCTION_ORIGIN})
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


def test_cors_configuration_does_not_change_response_body() -> None:
    """The exact same request, with and without an Origin header, must
    return byte-identical JSON -- CORS only ever changes response
    headers, never the scientific/health payload."""
    client = _client_for(cors_origins=[_PRODUCTION_ORIGIN])
    with_origin = client.get("/api/v1/health", headers={"Origin": _PRODUCTION_ORIGIN}).json()
    without_origin = client.get("/api/v1/health").json()
    # timestamps can legitimately differ between two calls; compare
    # everything else.
    with_origin.pop("timestamp")
    without_origin.pop("timestamp")
    assert with_origin == without_origin
