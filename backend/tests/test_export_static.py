"""Tests for the static export used by the Cloudflare deployment.

The whole premise of serving this API from a CDN is that a precomputed
file is indistinguishable from a live response. These tests pin that:
the exported bytes must equal what the running FastAPI app returns for
the same input, or the deployed site is serving something the backend
would not.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.demo import get_demo_fits_path
from app.deploy.export_static import (
    LIGHT_CURVE_FILENAME,
    LIGHT_CURVE_ROUTE,
    MANIFEST_FILENAME,
    SUMMARY_FILENAME,
    SUMMARY_ROUTE,
    ExportError,
    export_static_payloads,
)
from app.main import create_app


def test_missing_fits_raises_export_error(tmp_path: Path) -> None:
    with pytest.raises(ExportError):
        export_static_payloads(tmp_path / "absent.fits", tmp_path / "out")


def test_writes_all_three_files(synthetic_fits_path: Path, tmp_path: Path) -> None:
    written = export_static_payloads(synthetic_fits_path, tmp_path / "out")

    names = {entry.path.name for entry in written}
    assert names == {SUMMARY_FILENAME, LIGHT_CURVE_FILENAME, MANIFEST_FILENAME}
    for entry in written:
        assert entry.path.is_file()
        assert entry.byte_count > 0
        assert len(entry.sha256) == 64


def test_creates_the_output_directory(synthetic_fits_path: Path, tmp_path: Path) -> None:
    output_dir = tmp_path / "nested" / "does-not-exist-yet"
    export_static_payloads(synthetic_fits_path, output_dir)
    assert (output_dir / SUMMARY_FILENAME).is_file()


def test_exported_summary_matches_the_live_api(synthetic_fits_path: Path, tmp_path: Path) -> None:
    """The point of the whole exercise: a static file the CDN serves must
    be byte-identical to what the running backend would have returned."""
    output_dir = tmp_path / "out"
    export_static_payloads(synthetic_fits_path, output_dir)

    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: synthetic_fits_path
    with TestClient(app) as client:
        live = client.get(SUMMARY_ROUTE)

    exported = json.loads((output_dir / SUMMARY_FILENAME).read_text())
    assert exported == live.json()


def test_exported_light_curve_matches_the_live_api(
    synthetic_fits_path: Path, tmp_path: Path
) -> None:
    output_dir = tmp_path / "out"
    export_static_payloads(synthetic_fits_path, output_dir)

    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: synthetic_fits_path
    with TestClient(app) as client:
        live = client.get(LIGHT_CURVE_ROUTE)

    exported = json.loads((output_dir / LIGHT_CURVE_FILENAME).read_text())
    assert exported == live.json()


def test_manifest_maps_every_route_to_a_written_file(
    synthetic_fits_path: Path, tmp_path: Path
) -> None:
    """The Worker resolves request paths through this mapping, so a route
    naming a file that was never written would 404 in production."""
    output_dir = tmp_path / "out"
    export_static_payloads(synthetic_fits_path, output_dir)

    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text())
    assert set(manifest["routes"]) == {SUMMARY_ROUTE, LIGHT_CURVE_ROUTE}
    for filename in manifest["routes"].values():
        assert (output_dir / filename).is_file()


def test_manifest_records_the_source_checksum(synthetic_fits_path: Path, tmp_path: Path) -> None:
    """Provenance has to survive the hop to static hosting -- otherwise a
    deployed page could not say which observation it is showing."""
    output_dir = tmp_path / "out"
    export_static_payloads(synthetic_fits_path, output_dir)

    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text())
    summary = json.loads((output_dir / SUMMARY_FILENAME).read_text())
    assert manifest["source_checksum_sha256"] == summary["identity"]["source_checksum_sha256"]
    assert len(manifest["source_checksum_sha256"]) == 64


def test_manifest_digests_match_the_written_bytes(
    synthetic_fits_path: Path, tmp_path: Path
) -> None:
    import hashlib

    output_dir = tmp_path / "out"
    export_static_payloads(synthetic_fits_path, output_dir)

    manifest = json.loads((output_dir / MANIFEST_FILENAME).read_text())
    for filename, meta in manifest["payloads"].items():
        raw = (output_dir / filename).read_bytes()
        assert meta["bytes"] == len(raw)
        assert meta["sha256"] == hashlib.sha256(raw).hexdigest()


def test_export_is_deterministic(synthetic_fits_path: Path, tmp_path: Path) -> None:
    """Two builds of the same commit must produce identical artifacts, or
    the deployment's cache headers would be lying."""
    first = export_static_payloads(synthetic_fits_path, tmp_path / "a")
    second = export_static_payloads(synthetic_fits_path, tmp_path / "b")

    by_name_first = {entry.path.name: entry.sha256 for entry in first}
    by_name_second = {entry.path.name: entry.sha256 for entry in second}
    assert by_name_first == by_name_second


def test_export_does_not_modify_the_source_fits(synthetic_fits_path: Path, tmp_path: Path) -> None:
    before = synthetic_fits_path.read_bytes()
    export_static_payloads(synthetic_fits_path, tmp_path / "out")
    assert synthetic_fits_path.read_bytes() == before
