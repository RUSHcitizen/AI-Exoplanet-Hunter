"""Tests for the read-only Phase 4A Pi Mensae demo API.

Two tiers, deliberately separated:

* **Structural** tests run against the synthetic multi-segment fixture in
  ``conftest.py`` and therefore run everywhere -- a fresh clone, CI, a
  machine that has never downloaded a FITS file. They assert the response
  contract and the scientific invariants that must hold for *any* input:
  segment grouping, gap alignment, determinism, source-file immutability,
  and the guarantee that no caller-supplied path is ever honored.
* **Real-data** tests are marked ``realdata`` and assert the exact
  measured numbers recorded in ``docs/architecture.md``'s Phase 3A-3D
  sanity checks. They need the cached SPOC product (TIC 261136679,
  sector 1) and skip with an actionable message when it is absent.

The split exists because the previous single tier required the cached
file for *every* assertion, so the entire Phase 4A/4B surface silently
skipped wherever that file was missing -- which is everywhere except a
developer machine that had run the downloader.
"""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.demo import get_demo_fits_path
from app.core.config import get_settings
from app.main import create_app
from app.services.demo_pipeline import _cache

from .conftest import (
    REAL_PI_MENSAE_FITS_PATH,
    REAL_PI_MENSAE_SHA256,
    requires_real_fits,
)

# --- Structural tier: synthetic fixture, always runs ------------------------


def test_summary_endpoint_returns_200(synthetic_demo_client: TestClient) -> None:
    assert synthetic_demo_client.get("/api/v1/demo/pi-mensae").status_code == 200


def test_light_curve_endpoint_returns_200(synthetic_demo_client: TestClient) -> None:
    assert synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").status_code == 200


def test_summary_exposes_every_documented_top_level_section(
    synthetic_demo_client: TestClient,
) -> None:
    body = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    assert set(body) == {
        "identity",
        "raw",
        "quality_filter",
        "segmentation",
        "normalization",
        "outliers",
        "provenance",
        "scientific_limitations",
    }


def test_target_identity_is_reported(synthetic_demo_client: TestClient) -> None:
    identity = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["identity"]
    assert identity["target_name"] == "Pi Mensae"
    assert identity["tic_id"] == 261136679
    assert identity["sector"] == 1
    assert identity["flux_column"] == "PDCSAP_FLUX"
    assert len(identity["source_checksum_sha256"]) == 64


def test_quality_policy_defaults_to_mast(synthetic_demo_client: TestClient) -> None:
    qf = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["quality_filter"]
    assert qf["quality_policy"] == "mast"
    assert qf["quality_bitmask_decimal"] == 21183
    assert qf["quality_bitmask_hex"] == "0x52BF"


def test_retained_and_rejected_counts_partition_the_raw_cadences(
    synthetic_demo_client: TestClient,
) -> None:
    body = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    raw_count = body["raw"]["raw_cadence_count"]
    qf = body["quality_filter"]
    assert qf["retained_cadence_count"] + qf["rejected_cadence_count"] == raw_count
    # The fixture flags cadences both by QUALITY bit and by nonfiniteness,
    # so this stage must actually have rejected something.
    assert qf["rejected_cadence_count"] > 0


def test_segment_count_is_one_more_than_gap_count(synthetic_demo_client: TestClient) -> None:
    seg = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["segmentation"]
    assert seg["segment_count"] == seg["gap_count"] + 1
    assert seg["gap_count"] > 0


def test_outlier_status_counts_partition_the_segments(
    synthetic_demo_client: TestClient,
) -> None:
    body = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    outliers = body["outliers"]
    total = (
        outliers["valid_segment_count"]
        + outliers["insufficient_data_segment_count"]
        + outliers["zero_scale_segment_count"]
        + outliers["normalization_unavailable_segment_count"]
    )
    assert total == body["segmentation"]["segment_count"]


def test_short_segment_is_reported_as_insufficient_data(
    synthetic_demo_client: TestClient,
) -> None:
    """The fixture's final block is shorter than the minimum finite
    cadence count, so Phase 3D must classify it rather than score it."""
    outliers = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["insufficient_data_segment_count"] >= 1


def test_instrumental_spikes_are_flagged_as_high_outliers(
    synthetic_demo_client: TestClient,
) -> None:
    outliers = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["high_outlier_count"] > 0


def test_lower_side_detection_is_disabled_by_default(
    synthetic_demo_client: TestClient,
) -> None:
    """A transit is itself a downward dip, so low-side flagging must stay
    off unless explicitly requested -- see Phase 3D in the README."""
    outliers = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["lower_detection_enabled"] is False
    assert outliers["lower_threshold"] is None
    assert outliers["low_outlier_count"] == 0


def test_processing_history_records_every_completed_stage(
    synthetic_demo_client: TestClient,
) -> None:
    history = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()["provenance"][
        "processing_history"
    ]
    assert [entry["step"] for entry in history] == [
        "quality_filter",
        "gap_segmentation",
        "flux_normalization",
        "outlier_flagging",
    ]


def test_scientific_limitations_are_non_empty(synthetic_demo_client: TestClient) -> None:
    limitations = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()[
        "scientific_limitations"
    ]
    assert len(limitations) > 0
    assert any("not" in item.lower() and "planet" in item.lower() for item in limitations)


def test_chart_segment_count_matches_the_summary(synthetic_demo_client: TestClient) -> None:
    summary = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert len(chart["segments"]) == summary["segmentation"]["segment_count"]


def test_chart_point_counts_sum_to_the_retained_cadence_count(
    synthetic_demo_client: TestClient,
) -> None:
    summary = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    total = sum(len(segment["points"]) for segment in chart["segments"])
    assert total == summary["quality_filter"]["retained_cadence_count"]


def test_chart_cadence_count_matches_points_per_segment(
    synthetic_demo_client: TestClient,
) -> None:
    chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in chart["segments"]:
        assert segment["cadence_count"] == len(segment["points"])


def test_chart_source_indices_ordered_and_unique_within_segment(
    synthetic_demo_client: TestClient,
) -> None:
    chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in chart["segments"]:
        indices = [point["source_index"] for point in segment["points"]]
        assert indices == sorted(indices)
        assert len(indices) == len(set(indices))


def test_chart_times_increase_within_every_segment(synthetic_demo_client: TestClient) -> None:
    chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in chart["segments"]:
        times = [point["time"] for point in segment["points"]]
        assert times == sorted(times)


def test_no_segment_connected_across_a_gap(synthetic_demo_client: TestClient) -> None:
    """The response is segment-grouped -- consecutive segments are separate
    arrays, never merged into one flat series that a naive chart could
    draw a single connected line through."""
    body = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert len(body["segments"]) == len(body["gaps"]) + 1
    for gap, before, after in zip(
        body["gaps"], body["segments"][:-1], body["segments"][1:], strict=True
    ):
        assert gap["before_segment_number"] == before["segment_number"]
        assert gap["after_segment_number"] == after["segment_number"]
        assert gap["end_time"] > gap["start_time"]


def test_no_low_outlier_points_are_marked_high(synthetic_demo_client: TestClient) -> None:
    body = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    for segment in body["segments"]:
        for point in segment["points"]:
            if point["robust_score"] is not None:
                assert not (point["robust_score"] < 0 and point["is_high_outlier"])


def test_repeated_requests_are_deterministic(synthetic_demo_client: TestClient) -> None:
    first = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    second = synthetic_demo_client.get("/api/v1/demo/pi-mensae").json()
    assert first == second

    first_chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    second_chart = synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert first_chart == second_chart


def test_source_fits_file_unchanged_by_repeated_requests(
    synthetic_demo_client: TestClient, synthetic_fits_path: Path
) -> None:
    before_stat = synthetic_fits_path.stat()
    before_checksum = hashlib.sha256(synthetic_fits_path.read_bytes()).hexdigest()

    synthetic_demo_client.get("/api/v1/demo/pi-mensae")
    synthetic_demo_client.get("/api/v1/demo/pi-mensae/light-curve")
    synthetic_demo_client.get("/api/v1/demo/pi-mensae")

    after_stat = synthetic_fits_path.stat()
    after_checksum = hashlib.sha256(synthetic_fits_path.read_bytes()).hexdigest()

    assert before_checksum == after_checksum
    assert before_stat.st_size == after_stat.st_size
    assert before_stat.st_mtime_ns == after_stat.st_mtime_ns


def test_endpoint_ignores_a_caller_supplied_path(synthetic_demo_client: TestClient) -> None:
    """The demo path comes from typed settings only. A ``path`` query
    parameter must be inert, not an arbitrary-file-read primitive."""
    response = synthetic_demo_client.get("/api/v1/demo/pi-mensae", params={"path": "/etc/passwd"})
    assert response.status_code == 200
    assert response.json()["identity"]["tic_id"] == 261136679


def test_health_endpoint_remains_unchanged(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# --- Error paths, using dependency overrides so no real cache is touched ----


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


def test_missing_fits_file_also_reported_on_light_curve_endpoint(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: tmp_path / "absent.fits"
    with TestClient(app) as client:
        response = client.get("/api/v1/demo/pi-mensae/light-curve")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "demo_fits_missing"


def test_settings_default_resolves_to_real_fixture_path() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.pi_mensae_demo_fits_path.endswith(
        "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
    )


# --- Real-data tier: the recorded Phase 3A-3D validation numbers -----------


@pytest.fixture
def real_demo_client() -> TestClient:
    _cache.clear()
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: REAL_PI_MENSAE_FITS_PATH
    with TestClient(app) as test_client:
        yield test_client
    _cache.clear()


@requires_real_fits
@pytest.mark.realdata
def test_real_raw_cadence_count(real_demo_client: TestClient) -> None:
    body = real_demo_client.get("/api/v1/demo/pi-mensae").json()
    assert body["raw"]["raw_cadence_count"] == 20076


@requires_real_fits
@pytest.mark.realdata
def test_real_retained_and_rejected_counts(real_demo_client: TestClient) -> None:
    qf = real_demo_client.get("/api/v1/demo/pi-mensae").json()["quality_filter"]
    assert qf["retained_cadence_count"] == 18264
    assert qf["rejected_cadence_count"] == 1812


@requires_real_fits
@pytest.mark.realdata
def test_real_segment_and_gap_counts(real_demo_client: TestClient) -> None:
    seg = real_demo_client.get("/api/v1/demo/pi-mensae").json()["segmentation"]
    assert seg["segment_count"] == 46
    assert seg["gap_count"] == 45


@requires_real_fits
@pytest.mark.realdata
def test_real_normalization_counts(real_demo_client: TestClient) -> None:
    norm = real_demo_client.get("/api/v1/demo/pi-mensae").json()["normalization"]
    assert norm["normalized_segment_count"] == 46
    assert norm["invalid_reference_segment_count"] == 0


@requires_real_fits
@pytest.mark.realdata
def test_real_outlier_analysis_statuses(real_demo_client: TestClient) -> None:
    outliers = real_demo_client.get("/api/v1/demo/pi-mensae").json()["outliers"]
    assert outliers["valid_segment_count"] == 33
    assert outliers["insufficient_data_segment_count"] == 13
    assert outliers["high_outlier_count"] == 2
    assert outliers["low_outlier_count"] == 0


@requires_real_fits
@pytest.mark.realdata
def test_real_chart_shape(real_demo_client: TestClient) -> None:
    body = real_demo_client.get("/api/v1/demo/pi-mensae/light-curve").json()
    assert len(body["segments"]) == 46
    assert sum(len(segment["points"]) for segment in body["segments"]) == 18264
    flagged = [
        point
        for segment in body["segments"]
        for point in segment["points"]
        if point["is_high_outlier"]
    ]
    assert len(flagged) == 2


@requires_real_fits
@pytest.mark.realdata
def test_real_source_file_matches_pinned_checksum() -> None:
    """The recorded validation numbers above are only meaningful for the
    exact product they were measured from."""
    checksum = hashlib.sha256(REAL_PI_MENSAE_FITS_PATH.read_bytes()).hexdigest()
    assert checksum == REAL_PI_MENSAE_SHA256
