"""Tests for the read-only Phase 4A Pi Mensae demo API.

These exercise the fixed local cached SPOC product (TIC 261136679,
sector 1) end-to-end through the real FastAPI app, asserting the same
validation numbers recorded in ``docs/architecture.md``'s Phase 3A-3D
real-data sanity checks. A handful of tests use a synthetic/missing FITS
file (via dependency override) to exercise error paths without touching
the real cache.
"""

import hashlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.demo import get_demo_fits_path
from app.core.config import get_settings
from app.main import create_app
from app.services.demo_pipeline import _cache

_REAL_FITS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "raw"
    / "tess"
    / "sector_001"
    / "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
)

_EXPECTED_CHECKSUM = "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609"


def _require_real_fixture() -> None:
    if not _REAL_FITS_PATH.is_file():
        pytest.skip(f"Cached Pi Mensae fixture not present at {_REAL_FITS_PATH}")


@pytest.fixture
def client() -> Iterator[TestClient]:
    _cache.clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    _cache.clear()


@pytest.fixture(autouse=True)
def _check_fixture_present() -> None:
    _require_real_fixture()


def test_summary_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/api/v1/demo/pi-mensae")
    assert response.status_code == 200


def test_light_curve_endpoint_returns_200(client: TestClient) -> None:
    response = client.get("/api/v1/demo/pi-mensae/light-curve")
    assert response.status_code == 200


def test_target_identity(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae").json()
    identity = body["identity"]
    assert identity["target_name"] == "Pi Mensae"
    assert identity["tic_id"] == 261136679
    assert identity["sector"] == 1


def test_raw_cadence_count(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae").json()
    assert body["raw"]["raw_cadence_count"] == 20076


def test_retained_and_rejected_counts(client: TestClient) -> None:
    qf = client.get("/api/v1/demo/pi-mensae").json()["quality_filter"]
    assert qf["retained_cadence_count"] == 18264
    assert qf["rejected_cadence_count"] == 1812


def test_quality_policy_is_mast(client: TestClient) -> None:
    qf = client.get("/api/v1/demo/pi-mensae").json()["quality_filter"]
    assert qf["quality_policy"] == "mast"


def test_resolved_quality_mask(client: TestClient) -> None:
    qf = client.get("/api/v1/demo/pi-mensae").json()["quality_filter"]
    assert qf["quality_bitmask_decimal"] == 21183
    assert qf["quality_bitmask_hex"] == "0x52BF"


def test_segment_and_gap_counts(client: TestClient) -> None:
    seg = client.get("/api/v1/demo/pi-mensae").json()["segmentation"]
    assert seg["segment_count"] == 46
    assert seg["gap_count"] == 45


def test_normalized_segment_count(client: TestClient) -> None:
    norm = client.get("/api/v1/demo/pi-mensae").json()["normalization"]
    assert norm["normalized_segment_count"] == 46


def test_invalid_reference_segment_count(client: TestClient) -> None:
    norm = client.get("/api/v1/demo/pi-mensae").json()["normalization"]
    assert norm["invalid_reference_segment_count"] == 0


def test_outlier_analysis_statuses(client: TestClient) -> None:
    outliers = client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["valid_segment_count"] == 33
    assert outliers["insufficient_data_segment_count"] == 13


def test_high_outlier_count(client: TestClient) -> None:
    outliers = client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["high_outlier_count"] == 2


def test_low_outlier_count_is_zero(client: TestClient) -> None:
    outliers = client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["low_outlier_count"] == 0


def test_lower_side_detection_disabled(client: TestClient) -> None:
    outliers = client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["lower_detection_enabled"] is False
    assert outliers["lower_threshold"] is None


def test_processing_history_contains_completed_stages(client: TestClient) -> None:
    history = client.get("/api/v1/demo/pi-mensae").json()["provenance"]["processing_history"]
    steps = [entry["step"] for entry in history]
    assert steps == [
        "quality_filter",
        "gap_segmentation",
        "flux_normalization",
        "outlier_flagging",
    ]


def test_scientific_limitations_are_non_empty(client: TestClient) -> None:
    limitations = client.get("/api/v1/demo/pi-mensae").json()["scientific_limitations"]
    assert len(limitations) > 0
    assert any("not" in item.lower() and "planet" in item.lower() for item in limitations)


def test_chart_response_has_46_segments(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert len(body["segments"]) == 46


def test_chart_point_counts_sum_to_18264(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    total = sum(len(segment["points"]) for segment in body["segments"])
    assert total == 18264


def test_chart_has_exactly_two_high_outlier_points(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    flagged = [
        point
        for segment in body["segments"]
        for point in segment["points"]
        if point["is_high_outlier"]
    ]
    assert len(flagged) == 2


def test_chart_has_no_low_outlier_points_by_default(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in body["segments"]:
        for point in segment["points"]:
            if point["robust_score"] is not None:
                assert not (point["robust_score"] < 0 and point["is_high_outlier"])


def test_chart_points_have_correct_segment_number(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in body["segments"]:
        assert segment["cadence_count"] == len(segment["points"])


def test_chart_source_indices_ordered_within_segment(client: TestClient) -> None:
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in body["segments"]:
        indices = [point["source_index"] for point in segment["points"]]
        assert indices == sorted(indices)
        assert len(indices) == len(set(indices))


def test_no_segment_connected_across_a_gap(client: TestClient) -> None:
    """The response is segment-grouped -- consecutive segments are separate
    arrays, never merged into one flat series that a naive chart could
    draw a single connected line through."""
    body = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert len(body["segments"]) == len(body["gaps"]) + 1
    for gap, before, after in zip(
        body["gaps"], body["segments"][:-1], body["segments"][1:], strict=True
    ):
        assert gap["before_segment_number"] == before["segment_number"]
        assert gap["after_segment_number"] == after["segment_number"]


def test_repeated_requests_are_deterministic(client: TestClient) -> None:
    first = client.get("/api/v1/demo/pi-mensae").json()
    second = client.get("/api/v1/demo/pi-mensae").json()
    assert first == second

    first_chart = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    second_chart = client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert first_chart == second_chart


def test_source_fits_file_unchanged_by_repeated_requests(client: TestClient) -> None:
    before_stat = _REAL_FITS_PATH.stat()
    before_checksum = hashlib.sha256(_REAL_FITS_PATH.read_bytes()).hexdigest()

    client.get("/api/v1/demo/pi-mensae")
    client.get("/api/v1/demo/pi-mensae/light-curve")
    client.get("/api/v1/demo/pi-mensae")

    after_stat = _REAL_FITS_PATH.stat()
    after_checksum = hashlib.sha256(_REAL_FITS_PATH.read_bytes()).hexdigest()

    assert before_checksum == after_checksum == _EXPECTED_CHECKSUM
    assert before_stat.st_size == after_stat.st_size
    assert before_stat.st_mtime_ns == after_stat.st_mtime_ns


def test_endpoint_accepts_no_arbitrary_filesystem_path(client: TestClient) -> None:
    response = client.get("/api/v1/demo/pi-mensae", params={"path": "/etc/passwd"})
    assert response.status_code == 200
    body = response.json()
    assert body["identity"]["tic_id"] == 261136679


def test_health_endpoint_remains_unchanged(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- Error paths, using dependency overrides so the real cache is untouched ---


def test_missing_fits_file_returns_structured_404(tmp_path: Path) -> None:
    app = create_app()
    missing_path = tmp_path / "does-not-exist.fits"
    app.dependency_overrides[get_demo_fits_path] = lambda: missing_path
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/pi-mensae")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "demo_fits_missing"


def test_invalid_fits_data_returns_structured_error(tmp_path: Path) -> None:
    app = create_app()
    bad_path = tmp_path / "not-a-fits-file.fits"
    bad_path.write_bytes(b"this is not a FITS file")
    app.dependency_overrides[get_demo_fits_path] = lambda: bad_path
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/pi-mensae")
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "demo_fits_invalid"


def test_settings_default_resolves_to_real_fixture_path() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.pi_mensae_demo_fits_path.endswith(
        "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
    )
