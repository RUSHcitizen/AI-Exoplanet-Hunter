"""Demo API tests that run everywhere, including CI without the cached
Pi Mensae FITS file.

``test_demo_api.py`` validates the real observation's known numbers but
skips entirely when that file is absent. These tests instead point the
fixed-path dependency at a small synthetic FITS file (built in
``tmp_path``) to exercise response shape, error handling, compression,
caching headers, and quality-bit decoding. The synthetic file is a test
fixture only; nothing here asserts anything about real TESS data.
"""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from app.api.demo import get_demo_fits_path
from app.main import create_app
from app.services.demo_pipeline import _cache

_SUMMARY_URL = "/api/v1/demo/pi-mensae"
_LIGHT_CURVE_URL = "/api/v1/demo/pi-mensae/light-curve"


def _make_synthetic_fits(path: Path) -> Path:
    """Two 40-cadence segments separated by a gap, with a few cadences
    rejected by quality bits 8 (Earth point) and 128 (manual exclude)
    and one strong high outlier."""
    rng = np.random.default_rng(0)
    first = np.arange(40, dtype=np.float64) * 0.01
    second = 2.0 + np.arange(40, dtype=np.float64) * 0.01
    time = np.concatenate([first, second])
    flux = 1000.0 + rng.normal(0.0, 0.1, time.size)
    flux[10] = 1010.0
    quality = np.zeros(time.size, dtype=np.int32)
    quality[3] = 8
    quality[50] = 128
    quality[51] = 128 | 8

    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = 261136679
    primary.header["SECTOR"] = 1
    primary.header["CAMERA"] = 4
    primary.header["CCD"] = 2
    primary.header["PROCVER"] = "spoc-3.3.37-20181201"
    columns = [
        fits.Column(name="TIME", format="D", array=time),
        fits.Column(name="QUALITY", format="J", array=quality),
        fits.Column(name="PDCSAP_FLUX", format="D", array=flux),
        fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=np.ones(time.size)),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    lc_hdu.header["TIMESYS"] = "TDB"
    lc_hdu.header["TIMEDEL"] = 0.01
    fits.HDUList([primary, lc_hdu]).writeto(path)
    return path


@pytest.fixture
def fits_path(tmp_path: Path) -> Path:
    return _make_synthetic_fits(tmp_path / "synthetic-lc.fits")


@pytest.fixture
def client(fits_path: Path) -> Iterator[TestClient]:
    _cache.clear()
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: fits_path
    with TestClient(app) as test_client:
        yield test_client
    _cache.clear()


def test_summary_reports_camera_and_ccd(client: TestClient) -> None:
    identity = client.get(_SUMMARY_URL).json()["identity"]
    assert identity["camera"] == 4
    assert identity["ccd"] == 2


def test_summary_decodes_matched_quality_bits(client: TestClient) -> None:
    quality = client.get(_SUMMARY_URL).json()["quality_filter"]
    bits = {entry["bit_value"]: entry for entry in quality["matched_quality_bits"]}
    assert set(bits) == {8, 128}
    assert bits[8]["bit_number"] == 4
    assert bits[8]["description"] == "Spacecraft is in Earth Point"
    assert bits[8]["rejected_cadence_count"] == 2
    assert bits[128]["bit_number"] == 8
    assert bits[128]["rejected_cadence_count"] == 2
    # The legacy count map stays in sync with the detailed list.
    assert quality["matched_quality_bit_counts"] == {"8": 2, "128": 2}


def test_light_curve_keeps_segments_separate(client: TestClient) -> None:
    body = client.get(_LIGHT_CURVE_URL).json()
    assert len(body["segments"]) == 2
    assert len(body["gaps"]) == 1
    outliers = [p for s in body["segments"] for p in s["points"] if p["is_high_outlier"]]
    assert len(outliers) == 1


def test_successful_responses_are_briefly_cacheable(client: TestClient) -> None:
    for url in (_SUMMARY_URL, _LIGHT_CURVE_URL):
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "public, max-age=300"


def test_error_responses_are_not_marked_cacheable(tmp_path: Path) -> None:
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: tmp_path / "missing.fits"
    with TestClient(app) as test_client:
        response = test_client.get(_SUMMARY_URL)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "demo_fits_missing"
    assert "public" not in response.headers.get("cache-control", "")


def test_invalid_fits_is_reported_as_422(tmp_path: Path) -> None:
    bad = tmp_path / "bad.fits"
    bad.write_bytes(b"not a fits file")
    _cache.clear()
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: bad
    with TestClient(app) as test_client:
        response = test_client.get(_LIGHT_CURVE_URL)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "demo_fits_invalid"


def test_large_responses_are_gzip_compressed(client: TestClient) -> None:
    response = client.get(_LIGHT_CURVE_URL, headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"
