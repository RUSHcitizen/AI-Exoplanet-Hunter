"""Parsing supported TESS light-curve FITS files into typed raw models
(Phase 2B).

Only the standard SPOC / TESS-SPOC light-curve product format is
supported: a FITS file with a ``LIGHTCURVE`` binary-table extension
containing at least ``TIME`` and ``QUALITY``, plus one of ``PDCSAP_FLUX``
or ``SAP_FLUX`` (``PDCSAP_FLUX`` is preferred when both are present,
since it is the pipeline's own systematics-corrected flux). QLP light
curves use a different column schema and are not parsed by this module
yet -- see ``docs/architecture.md``'s known limitations.

No preprocessing happens here: values are copied out of the FITS file
exactly as stored (aside from safe conversion to plain Python floats/ints
and FITS "undefined value" handling), with no NaN removal, quality
filtering, normalization, detrending, or sector stitching.
"""

import hashlib
from pathlib import Path
from typing import Any

from app.data.exceptions import (
    InvalidFitsError,
    MissingColumnError,
    MissingExtensionError,
    UnsupportedProductError,
)
from app.data.models import FileProvenance, FitsMetadata, RawLightCurve

_SUPPORTED_TELESCOPE = "TESS"
_LIGHTCURVE_EXTENSION = "LIGHTCURVE"
_FLUX_COLUMN_PREFERENCE = ("PDCSAP_FLUX", "SAP_FLUX")
_REQUIRED_COLUMNS = ("TIME", "QUALITY")
_CHUNK_SIZE = 1024 * 1024
_SECONDS_PER_DAY = 86400.0


def parse_light_curve(path: Path) -> RawLightCurve:
    """Parse ``path`` into a ``RawLightCurve``, or raise a ``FitsError``
    subclass describing exactly what was invalid or unsupported."""
    from astropy.io import fits

    checksum = _sha256_of(path)

    try:
        hdul = fits.open(path, memmap=False)
    except OSError as exc:
        raise InvalidFitsError(f"{path} is not a readable FITS file: {exc}") from exc

    try:
        return _parse_opened(hdul, path=path, checksum=checksum)
    finally:
        hdul.close()


def _parse_opened(hdul: Any, *, path: Path, checksum: str) -> RawLightCurve:
    primary_header = hdul[0].header
    telescope = str(primary_header.get("TELESCOP", "")).strip()
    if telescope.upper() != _SUPPORTED_TELESCOPE:
        raise UnsupportedProductError(
            f"{path} has TELESCOP={telescope!r}; only {_SUPPORTED_TELESCOPE} "
            "light-curve products are supported."
        )

    try:
        lc_hdu = hdul[_LIGHTCURVE_EXTENSION]
    except KeyError as exc:
        raise MissingExtensionError(
            f"{path} has no {_LIGHTCURVE_EXTENSION!r} extension; only SPOC/TESS-SPOC "
            "light-curve products are supported (not target-pixel files, "
            "data-validation reports, or QLP light curves)."
        ) from exc

    lc_header = lc_hdu.header
    data = lc_hdu.data
    columns = set(data.columns.names) if data is not None else set()

    missing = [col for col in _REQUIRED_COLUMNS if col not in columns]
    if missing:
        raise MissingColumnError(
            f"{path} is missing required column(s) {missing} in the "
            f"{_LIGHTCURVE_EXTENSION} extension."
        )

    flux_column = next((col for col in _FLUX_COLUMN_PREFERENCE if col in columns), None)
    if flux_column is None:
        raise MissingColumnError(
            f"{path} has none of {_FLUX_COLUMN_PREFERENCE} in the "
            f"{_LIGHTCURVE_EXTENSION} extension."
        )

    time_values = _to_float_tuple(data["TIME"])
    flux_values = _to_float_tuple(data[flux_column])
    quality_values = _to_int_tuple(data["QUALITY"])

    err_column = f"{flux_column}_ERR"
    flux_err_values = _to_float_tuple(data[err_column]) if err_column in columns else None

    _assert_consistent_lengths(
        time=time_values,
        flux=flux_values,
        quality=quality_values,
        flux_err=flux_err_values,
        flux_column=flux_column,
        err_column=err_column,
        path=path,
    )

    provenance = FileProvenance(
        source_filename=path.name,
        source_checksum_sha256=checksum,
        tic_id=_clean_int(primary_header.get("TICID")),
        sector=_clean_int(primary_header.get("SECTOR")),
        camera=_clean_int(primary_header.get("CAMERA")),
        ccd=_clean_int(primary_header.get("CCD")),
        author=_pipeline_from_procver(primary_header),
        mission=_clean_str(primary_header.get("TELESCOP")),
        telescope=_clean_str(primary_header.get("TELESCOP")),
    )
    metadata = FitsMetadata(
        object_name=_clean_str(primary_header.get("OBJECT")),
        time_system=_clean_str(lc_header.get("TIMESYS")),
        cadence_seconds=_cadence_seconds(lc_header),
        header=_flatten_header(primary_header, lc_header),
    )

    return RawLightCurve(
        time=time_values,
        flux=flux_values,
        flux_err=flux_err_values,
        quality=quality_values,
        flux_column=flux_column,
        provenance=provenance,
        metadata=metadata,
    )


def _assert_consistent_lengths(
    *,
    time: tuple[float, ...],
    flux: tuple[float, ...],
    quality: tuple[int, ...],
    flux_err: tuple[float, ...] | None,
    flux_column: str,
    err_column: str,
    path: Path,
) -> None:
    """Validate that all extracted columns have the same row count.

    A single real FITS binary table cannot itself hold columns of
    different lengths, so this defends against future extraction bugs
    (e.g. reading two different HDUs) rather than malformed files; it is
    unit-tested directly with plain tuples for that reason.
    """
    lengths = {len(time), len(flux), len(quality)}
    if flux_err is not None:
        lengths.add(len(flux_err))
    if len(lengths) > 1:
        raise InvalidFitsError(
            f"{path} has inconsistent array lengths across TIME/{flux_column}"
            f"/QUALITY{f'/{err_column}' if flux_err is not None else ''}: {lengths}."
        )
    if not time:
        raise InvalidFitsError(f"{path} has an empty {_LIGHTCURVE_EXTENSION} table.")


def _cadence_seconds(lc_header: Any) -> float | None:
    """Nominal cadence, derived from the ``LIGHTCURVE`` extension's
    ``TIMEDEL`` header keyword (the frame time-resolution, in days, per
    the FITS/TESS data-product standard). Note this lives in the
    ``LIGHTCURVE`` header, not the primary header."""
    timedel = lc_header.get("TIMEDEL")
    if timedel is None:
        return None
    try:
        return float(timedel) * _SECONDS_PER_DAY
    except (TypeError, ValueError):
        return None


def _pipeline_from_procver(primary_header: Any) -> str | None:
    """Derive the producing pipeline (e.g. ``SPOC``) from the ``PROCVER``
    header keyword (e.g. ``"spoc-5.0.10-20200904"``).

    ``ORIGIN`` is the *institution* that created the file (e.g.
    "NASA/Ames"), not the pipeline, so it is not used for this.
    """
    procver = _clean_str(primary_header.get("PROCVER"))
    if procver is None:
        return None
    pipeline = procver.split("-")[0].strip()
    return pipeline.upper() or None


def _flatten_header(*headers: Any) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for header in headers:
        for key, value in header.items():
            if not key or key in {"COMMENT", "HISTORY"}:
                continue
            flattened[key] = str(value)
    return flattened


def _to_float_tuple(column: Any) -> tuple[float, ...]:
    return tuple(float(v) for v in column)


def _to_int_tuple(column: Any) -> tuple[int, ...]:
    return tuple(int(v) for v in column)


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
