"""Tests for the CLI presentation layer.

The CLI is exercised directly via ``run_search_target``/``main`` with an
injected fake ``MastClient`` (or a monkeypatched ``run_search_target``),
so no network access or real astroquery calls happen here.
"""

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from astropy.io import fits

from app import cli
from app.data.exceptions import (
    DownloadError,
    InvalidTargetError,
    MastServiceError,
    RetryExhaustedError,
    TargetNotFoundError,
)
from app.data.models import CachedArtifact, SelectedProduct, TargetSearchResult, TessObservation


class FakeClient:
    def __init__(
        self, result: TargetSearchResult | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error

    def search_target(self, target: str) -> TargetSearchResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _sample_result() -> TargetSearchResult:
    return TargetSearchResult(
        query="TIC 261136679",
        resolved_target="TIC 261136679",
        tic_id=261136679,
        observations=(
            TessObservation(
                obs_id="obs-1",
                target_name="261136679",
                mission="TESS",
                dataproduct_type="timeseries",
                sector=37,
                author="SPOC",
                cadence_seconds=120.0,
                calib_level=3,
            ),
        ),
    )


def test_run_search_target_success_prints_report(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.run_search_target("TIC 261136679", client=FakeClient(result=_sample_result()))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Resolved target:       TIC 261136679" in out
    assert "Matching observations: 1" in out
    assert "sector=37" in out
    assert "author=SPOC" in out


def test_run_search_target_invalid_target_returns_exit_code_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "???", client=FakeClient(error=InvalidTargetError("bad target"))
    )

    assert exit_code == 2
    assert "Invalid target: bad target" in capsys.readouterr().err


def test_run_search_target_not_found_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "TIC 1", client=FakeClient(error=TargetNotFoundError("no observations"))
    )

    assert exit_code == 1
    assert "Target not found: no observations" in capsys.readouterr().err


def test_run_search_target_service_error_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "TIC 1", client=FakeClient(error=MastServiceError("timed out"))
    )

    assert exit_code == 3
    assert "MAST service error: timed out" in capsys.readouterr().err


def test_main_dispatches_search_target_with_parsed_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_run_search_target(target: str, client: object = None) -> int:
        captured["target"] = target
        return 0

    monkeypatch.setattr(cli, "run_search_target", fake_run_search_target)

    exit_code = cli.main(["search-target", "--target", "TIC 261136679"])

    assert exit_code == 0
    assert captured["target"] == "TIC 261136679"


def test_main_requires_target_argument() -> None:
    with pytest.raises(SystemExit):
        cli.main(["search-target"])


class FakeDownloader:
    def __init__(
        self,
        products: list[dict[str, Any]] | None = None,
        artifact: CachedArtifact | None = None,
        download_error: Exception | None = None,
    ) -> None:
        self.products = products or []
        self.artifact = artifact
        self.download_error = download_error
        self.download_calls: list[tuple[SelectedProduct, bool]] = []

    def list_products(self, obs_id: str) -> list[dict[str, Any]]:
        return self.products

    def download(self, product: SelectedProduct, *, force: bool = False) -> CachedArtifact:
        self.download_calls.append((product, force))
        if self.download_error is not None:
            raise self.download_error
        assert self.artifact is not None
        return self.artifact


def _sample_download_search_result() -> TargetSearchResult:
    return TargetSearchResult(
        query="TIC 261136679",
        resolved_target="TIC 261136679",
        tic_id=261136679,
        observations=(
            TessObservation(
                obs_id="obs-1",
                target_name="261136679",
                mission="TESS",
                dataproduct_type="timeseries",
                sector=1,
                author="SPOC",
                cadence_seconds=120.0,
                calib_level=3,
            ),
        ),
    )


def _sample_selected_product() -> SelectedProduct:
    return SelectedProduct(
        obs_id="obs-1",
        tic_id=261136679,
        sector=1,
        author="SPOC",
        cadence_seconds=120.0,
        filename="tess-s0001-lc.fits",
        data_uri="mast:TESS/product/tess-s0001-lc.fits",
        size_bytes=100,
        description="Light curves",
    )


def _sample_lc_product_row() -> dict[str, Any]:
    return {
        "productFilename": "tess-s0001-lc.fits",
        "productSubGroupDescription": "LC",
        "dataURI": "mast:TESS/product/tess-s0001-lc.fits",
        "size": 100,
        "description": "Light curves",
    }


def test_run_download_target_success_prints_report(capsys: pytest.CaptureFixture[str]) -> None:
    artifact = CachedArtifact(
        product=_sample_selected_product(),
        local_path="/tmp/cache/sector_001/tess-s0001-lc.fits",
        size_bytes=100,
        sha256="deadbeef",
        was_downloaded=True,
    )
    downloader = FakeDownloader(products=[_sample_lc_product_row()], artifact=artifact)

    exit_code = cli.run_download_target(
        "TIC 261136679",
        client=FakeClient(result=_sample_download_search_result()),
        downloader=downloader,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Selected product: tess-s0001-lc.fits" in out
    assert "Source:           downloaded" in out
    assert "SHA-256:          deadbeef" in out


def test_run_download_target_invalid_target_returns_exit_code_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_download_target(
        "???",
        client=FakeClient(error=InvalidTargetError("bad target")),
        downloader=FakeDownloader(),
    )

    assert exit_code == 2
    assert "Invalid target: bad target" in capsys.readouterr().err


def test_run_download_target_search_not_found_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_download_target(
        "TIC 1",
        client=FakeClient(error=TargetNotFoundError("no observations")),
        downloader=FakeDownloader(),
    )

    assert exit_code == 1
    assert "Target not found: no observations" in capsys.readouterr().err


def test_run_download_target_search_service_error_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_download_target(
        "TIC 1", client=FakeClient(error=MastServiceError("timed out")), downloader=FakeDownloader()
    )

    assert exit_code == 3
    assert "MAST service error: timed out" in capsys.readouterr().err


def test_run_download_target_no_matching_product_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    downloader = FakeDownloader(products=[])  # no light-curve products at all

    exit_code = cli.run_download_target(
        "TIC 261136679",
        client=FakeClient(result=_sample_download_search_result()),
        downloader=downloader,
    )

    assert exit_code == 1
    assert "Target not found" in capsys.readouterr().err


def test_run_download_target_download_error_returns_exit_code_4(
    capsys: pytest.CaptureFixture[str],
) -> None:
    downloader = FakeDownloader(
        products=[_sample_lc_product_row()],
        download_error=RetryExhaustedError("network kept failing"),
    )

    exit_code = cli.run_download_target(
        "TIC 261136679",
        client=FakeClient(result=_sample_download_search_result()),
        downloader=downloader,
    )

    assert exit_code == 4
    assert "Download error: network kept failing" in capsys.readouterr().err


def test_run_download_target_download_error_base_class_also_caught(
    capsys: pytest.CaptureFixture[str],
) -> None:
    downloader = FakeDownloader(
        products=[_sample_lc_product_row()], download_error=DownloadError("boom")
    )

    exit_code = cli.run_download_target(
        "TIC 261136679",
        client=FakeClient(result=_sample_download_search_result()),
        downloader=downloader,
    )

    assert exit_code == 4


def _make_light_curve_fits(path: Path) -> Path:
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = 261136679
    primary.header["SECTOR"] = 1
    primary.header["CAMERA"] = 2
    primary.header["CCD"] = 3
    primary.header["ORIGIN"] = "NASA/Ames"
    primary.header["PROCVER"] = "spoc-5.0.10-20200904"
    primary.header["OBJECT"] = "TIC 261136679"

    columns = [
        fits.Column(name="TIME", format="D", array=np.arange(5, dtype=np.float64)),
        fits.Column(name="QUALITY", format="J", array=np.zeros(5, dtype=np.int32)),
        fits.Column(name="PDCSAP_FLUX", format="D", array=np.full(5, 100.0, dtype=np.float64)),
        fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=np.full(5, 1.0, dtype=np.float64)),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    lc_hdu.header["TIMESYS"] = "TDB"
    lc_hdu.header["TIMEDEL"] = 120.0 / 86400.0
    fits.HDUList([primary, lc_hdu]).writeto(path)
    return path


def test_run_inspect_fits_success_prints_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_light_curve_fits(tmp_path / "test-lc.fits")

    exit_code = cli.run_inspect_fits(str(path))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Target (TIC):        261136679" in out
    assert "Sector:              1" in out
    assert "Cadences:            5" in out
    assert "Flux column:         PDCSAP_FLUX" in out


def test_run_inspect_fits_missing_file_returns_exit_code_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.run_inspect_fits(str(tmp_path / "does-not-exist.fits"))

    assert exit_code == 5
    assert "FITS file not found" in capsys.readouterr().err


def test_run_inspect_fits_invalid_file_returns_exit_code_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = tmp_path / "bad.fits"
    bad_path.write_bytes(b"not a fits file")

    exit_code = cli.run_inspect_fits(str(bad_path))

    assert exit_code == 5
    assert "Invalid FITS file" in capsys.readouterr().err


def test_main_dispatches_download_target_with_parsed_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_download_target(target: str, **kwargs: Any) -> int:
        captured["target"] = target
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "run_download_target", fake_run_download_target)

    exit_code = cli.main(
        [
            "download-target",
            "--target",
            "TIC 261136679",
            "--sector",
            "1",
            "--author",
            "SPOC",
            "--force",
        ]
    )

    assert exit_code == 0
    assert captured["target"] == "TIC 261136679"
    assert captured["kwargs"]["sector"] == 1
    assert captured["kwargs"]["author"] == "SPOC"
    assert captured["kwargs"]["force"] is True


def test_main_dispatches_inspect_fits_with_parsed_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_run_inspect_fits(fits_path: str) -> int:
        captured["fits_path"] = fits_path
        return 0

    monkeypatch.setattr(cli, "run_inspect_fits", fake_run_inspect_fits)

    exit_code = cli.main(["inspect-fits", "data/raw/tess/sample.fits"])

    assert exit_code == 0
    assert captured["fits_path"] == "data/raw/tess/sample.fits"


def _make_mixed_quality_fits(path: Path) -> Path:
    """A light curve with one clean cadence, one NaN flux, one cadence
    flagged 4096 (Scattered Light Exclude) and one flagged 128."""
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = 261136679
    primary.header["SECTOR"] = 1
    primary.header["CAMERA"] = 2
    primary.header["CCD"] = 3
    primary.header["PROCVER"] = "spoc-5.0.10-20200904"
    primary.header["OBJECT"] = "TIC 261136679"

    columns = [
        fits.Column(name="TIME", format="D", array=np.arange(4, dtype=np.float64)),
        fits.Column(name="QUALITY", format="J", array=np.array([0, 0, 4096, 128], dtype=np.int32)),
        fits.Column(
            name="PDCSAP_FLUX",
            format="D",
            array=np.array([100.0, np.nan, 100.0, 100.0], dtype=np.float64),
        ),
        fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=np.full(4, 1.0, dtype=np.float64)),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    lc_hdu.header["TIMESYS"] = "TDB"
    lc_hdu.header["TIMEDEL"] = 120.0 / 86400.0
    fits.HDUList([primary, lc_hdu]).writeto(path)
    return path


def test_run_filter_quality_success_prints_policy_and_resolved_mask(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Quality policy:      mast" in out
    assert "Resolved bitmask:    21183 (0x52BF)" in out
    assert "Total cadences:      4" in out
    assert "Retained cadences:   1" in out
    assert "Rejected cadences:   3" in out
    assert "nonfinite_flux: 1" in out
    assert "matched_quality_bits: 2" in out
    assert "Scattered Light Exclude" in out
    assert "The source FITS file was not modified." in out


def test_run_filter_quality_does_not_modify_the_source_file(tmp_path: Path) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    assert cli.run_filter_quality(str(path)) == 0

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_run_filter_quality_default_policy_keeps_scattered_light(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path), quality_policy="default")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Quality policy:      default" in out
    assert "Resolved bitmask:    17087 (0x42BF)" in out
    assert "Retained cadences:   2" in out


def test_run_filter_quality_custom_bitmask(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path), quality_policy="custom", quality_bitmask=128)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Quality policy:      custom" in out
    assert "Resolved bitmask:    128 (0x0080)" in out
    assert "Retained cadences:   2" in out


def test_run_filter_quality_hardest_policy_rejects_the_corrected_cadence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path), quality_policy="hardest")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Resolved bitmask:    65535 (0xFFFF)" in out
    assert "Retained cadences:   1" in out


def test_run_filter_quality_all_rejected_warns_and_still_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "all-flagged.fits"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = 261136679
    primary.header["SECTOR"] = 1
    columns = [
        fits.Column(name="TIME", format="D", array=np.arange(3, dtype=np.float64)),
        fits.Column(name="QUALITY", format="J", array=np.full(3, 128, dtype=np.int32)),
        fits.Column(name="PDCSAP_FLUX", format="D", array=np.full(3, 100.0, dtype=np.float64)),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    fits.HDUList([primary, lc_hdu]).writeto(path)

    exit_code = cli.run_filter_quality(str(path))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Retained cadences:   0 (0.0%)" in out
    assert "Rejected cadences:   3" in out
    assert "WARNING: every cadence was rejected" in out


def test_run_filter_quality_invalid_policy_returns_exit_code_6(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path), quality_policy="aggressive")

    assert exit_code == 6
    assert "Invalid filter configuration" in capsys.readouterr().err


def test_run_filter_quality_negative_custom_mask_returns_exit_code_6(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _make_mixed_quality_fits(tmp_path / "mixed-lc.fits")

    exit_code = cli.run_filter_quality(str(path), quality_policy="custom", quality_bitmask=-1)

    assert exit_code == 6
    assert "Invalid filter configuration" in capsys.readouterr().err


def test_run_filter_quality_missing_file_returns_exit_code_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.run_filter_quality(str(tmp_path / "nope.fits"))

    assert exit_code == 5
    assert "FITS file not found" in capsys.readouterr().err


def test_run_filter_quality_invalid_file_returns_exit_code_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = tmp_path / "bad.fits"
    bad_path.write_bytes(b"not a fits file")

    exit_code = cli.run_filter_quality(str(bad_path))

    assert exit_code == 5
    assert "Invalid FITS file" in capsys.readouterr().err


def test_main_dispatches_filter_quality_with_parsed_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run_filter_quality(fits_path: str, **kwargs: Any) -> int:
        captured["fits_path"] = fits_path
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "run_filter_quality", fake_run_filter_quality)

    exit_code = cli.main(
        [
            "filter-quality",
            "data/raw/tess/sample.fits",
            "--quality-policy",
            "custom",
            "--quality-bitmask",
            "128",
            "--allow-nonfinite-flux-err",
        ]
    )

    assert exit_code == 0
    assert captured["fits_path"] == "data/raw/tess/sample.fits"
    assert captured["kwargs"]["quality_policy"] == "custom"
    assert captured["kwargs"]["quality_bitmask"] == 128
    assert captured["kwargs"]["allow_nonfinite_flux_err"] is True
    assert captured["kwargs"]["allow_nonfinite_time"] is False


def test_main_filter_quality_defaults_to_mast_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_filter_quality(fits_path: str, **kwargs: Any) -> int:
        captured["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(cli, "run_filter_quality", fake_run_filter_quality)

    assert cli.main(["filter-quality", "sample.fits"]) == 0
    assert captured["kwargs"]["quality_policy"] == "mast"


def test_main_filter_quality_rejects_unknown_policy_choice() -> None:
    with pytest.raises(SystemExit):
        cli.main(["filter-quality", "sample.fits", "--quality-policy", "aggressive"])
