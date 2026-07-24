"""Tests for parsing supported TESS light-curve FITS files.

Fixtures are built programmatically with astropy so no binary FITS files
are committed to the repository.
"""

import hashlib
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from app.data.exceptions import (
    InvalidFitsError,
    MissingColumnError,
    MissingExtensionError,
    UnsupportedProductError,
)
from app.data.fits_parser import _assert_consistent_lengths, parse_light_curve


def _make_light_curve_fits(
    tmp_path: Path,
    *,
    filename: str = "test-lc.fits",
    telescope: str = "TESS",
    extname: str = "LIGHTCURVE",
    flux_column: str = "PDCSAP_FLUX",
    include_sap_flux: bool = False,
    include_flux_err: bool = True,
    include_quality: bool = True,
    n_rows: int = 5,
) -> Path:
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = telescope
    primary.header["TICID"] = 261136679
    primary.header["SECTOR"] = 1
    primary.header["CAMERA"] = 2
    primary.header["CCD"] = 3
    primary.header["ORIGIN"] = "NASA/Ames"
    primary.header["PROCVER"] = "spoc-5.0.10-20200904"
    primary.header["OBJECT"] = "TIC 261136679"

    columns = [
        fits.Column(name="TIME", format="D", array=np.arange(n_rows, dtype=np.float64)),
    ]
    if include_quality:
        columns.append(
            fits.Column(name="QUALITY", format="J", array=np.zeros(n_rows, dtype=np.int32))
        )
    columns.append(
        fits.Column(name=flux_column, format="D", array=np.full(n_rows, 100.0, dtype=np.float64))
    )
    if include_flux_err:
        columns.append(
            fits.Column(
                name=f"{flux_column}_ERR", format="D", array=np.full(n_rows, 1.0, dtype=np.float64)
            )
        )
    if include_sap_flux and flux_column != "SAP_FLUX":
        columns.append(
            fits.Column(name="SAP_FLUX", format="D", array=np.full(n_rows, 200.0, dtype=np.float64))
        )

    lc_hdu = fits.BinTableHDU.from_columns(columns, name=extname)
    lc_hdu.header["TIMESYS"] = "TDB"
    lc_hdu.header["TIMEDEL"] = 120.0 / 86400.0
    hdul = fits.HDUList([primary, lc_hdu])
    path = tmp_path / filename
    hdul.writeto(path)
    return path


def test_parses_valid_light_curve_with_pdcsap_flux(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path)

    result = parse_light_curve(path)

    assert result.flux_column == "PDCSAP_FLUX"
    assert len(result.time) == 5
    assert result.flux == (100.0,) * 5
    assert result.flux_err == (1.0,) * 5
    assert result.quality == (0,) * 5
    assert result.provenance.tic_id == 261136679
    assert result.provenance.sector == 1
    assert result.provenance.camera == 2
    assert result.provenance.ccd == 3
    assert result.provenance.author == "SPOC"
    assert result.metadata.time_system == "TDB"
    assert result.metadata.cadence_seconds is not None
    assert abs(result.metadata.cadence_seconds - 120.0) < 1e-6


def test_prefers_pdcsap_flux_over_sap_flux_when_both_present(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, flux_column="PDCSAP_FLUX", include_sap_flux=True)

    result = parse_light_curve(path)

    assert result.flux_column == "PDCSAP_FLUX"
    assert result.flux == (100.0,) * 5


def test_uses_sap_flux_when_pdcsap_flux_absent(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, flux_column="SAP_FLUX")

    result = parse_light_curve(path)

    assert result.flux_column == "SAP_FLUX"


def test_flux_err_is_none_when_error_column_absent(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, include_flux_err=False)

    result = parse_light_curve(path)

    assert result.flux_err is None


def test_source_checksum_matches_sha256_of_file_bytes(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path)

    result = parse_light_curve(path)

    assert result.provenance.source_checksum_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.provenance.source_filename == path.name


def test_raises_unsupported_product_for_non_tess_telescope(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, telescope="KEPLER")

    with pytest.raises(UnsupportedProductError):
        parse_light_curve(path)


def test_raises_missing_extension_when_no_lightcurve_hdu(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, extname="TARGETTABLES")

    with pytest.raises(MissingExtensionError):
        parse_light_curve(path)


def test_raises_missing_column_when_quality_absent(tmp_path: Path) -> None:
    path = _make_light_curve_fits(tmp_path, include_quality=False)

    with pytest.raises(MissingColumnError):
        parse_light_curve(path)


def test_raises_missing_column_when_no_supported_flux_column(tmp_path: Path) -> None:
    path = tmp_path / "no-flux.fits"
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    columns = [
        fits.Column(name="TIME", format="D", array=np.arange(5, dtype=np.float64)),
        fits.Column(name="QUALITY", format="J", array=np.zeros(5, dtype=np.int32)),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    fits.HDUList([primary, lc_hdu]).writeto(path)

    with pytest.raises(MissingColumnError):
        parse_light_curve(path)


def test_raises_invalid_fits_for_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "not-a-fits-file.fits"
    path.write_bytes(b"this is not a FITS file")

    with pytest.raises(InvalidFitsError):
        parse_light_curve(path)


def test_assert_consistent_lengths_raises_for_mismatched_lengths() -> None:
    with pytest.raises(InvalidFitsError, match="inconsistent array lengths"):
        _assert_consistent_lengths(
            time=(1.0, 2.0, 3.0),
            flux=(1.0, 2.0),
            quality=(0, 0, 0),
            flux_err=None,
            flux_column="PDCSAP_FLUX",
            err_column="PDCSAP_FLUX_ERR",
            path=Path("dummy.fits"),
        )


def test_assert_consistent_lengths_raises_for_empty_arrays() -> None:
    with pytest.raises(InvalidFitsError, match="empty"):
        _assert_consistent_lengths(
            time=(),
            flux=(),
            quality=(),
            flux_err=None,
            flux_column="PDCSAP_FLUX",
            err_column="PDCSAP_FLUX_ERR",
            path=Path("dummy.fits"),
        )


def test_assert_consistent_lengths_passes_for_matching_lengths() -> None:
    _assert_consistent_lengths(
        time=(1.0, 2.0),
        flux=(1.0, 2.0),
        quality=(0, 0),
        flux_err=(0.1, 0.1),
        flux_column="PDCSAP_FLUX",
        err_column="PDCSAP_FLUX_ERR",
        path=Path("dummy.fits"),
    )
