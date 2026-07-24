"""Quality-flag and finite-value filtering for parsed TESS light curves
(Phase 3A).

This is the ``Quality filtering (TESS quality flags)`` stage of the data
flow in ``docs/architecture.md``: it *selects* cadences and never alters
a value. No normalization, detrending, sigma clipping, smoothing,
brightness-based outlier rejection, or sector stitching happens here --
those belong to later phases.

Rules
-----
A cadence at index ``i`` is rejected when any of the following hold. All
four are evaluated independently for every cadence -- nothing
short-circuits -- so a cadence with several problems records *all* of
them and the result does not depend on rule ordering:

===========================  ==============================================
``NONFINITE_TIME``           ``not isfinite(time[i])``   (NaN, +inf, -inf)
``NONFINITE_FLUX``           ``not isfinite(flux[i])``
``NONFINITE_FLUX_ERR``       ``not isfinite(flux_err[i])`` (skipped when
                             the file had no flux-error column)
``MATCHED_QUALITY_BITS``     ``quality[i] & active_bitmask != 0``
===========================  ==============================================

Each check can be disabled individually via ``QualityFilterConfig``; the
quality mask is chosen by named policy (``none``/``default``/``mast``/
``hard``/``hardest``) or a custom integer. See ``app.data.quality_flags``
for the verified bit table, the mask values, and their citations.

Deliberately **not** rejection criteria: a flux error of exactly ``0.0``
(unusual, but it is a reported measurement rather than a missing one),
and negative or unusually large flux values (brightness-based outlier
rejection is out of scope).

Guarantees
----------
* The input ``RawLightCurve`` is never mutated. It is frozen with tuple
  fields, so this is enforced by the type rather than by convention.
* ``retained + rejected == total`` always: no cadence is dropped without
  an attributable, documented reason recorded in the result.
* Every retained cadence keeps its original row index in
  ``source_indices``, so correspondence with the source FITS file
  survives filtering.
* The result is a pure function of ``(raw, config)`` -- no timestamps, no
  randomness -- so reruns are reproducible byte-for-byte.
"""

from importlib.metadata import PackageNotFoundError, version
from math import isfinite

from app.core.logging import get_logger
from app.data.exceptions import InvalidLightCurveError
from app.data.models import (
    FilteredLightCurve,
    ProcessingStep,
    QualityFilterConfig,
    QualityFilterStats,
    RawLightCurve,
    RejectedCadence,
    RejectionReason,
)

logger = get_logger(__name__)

_STEP_NAME = "quality_filter"
_DISTRIBUTION = "exoplanet-hunter-backend"


def filter_quality(
    raw: RawLightCurve,
    config: QualityFilterConfig | None = None,
) -> FilteredLightCurve:
    """Select the cadences of ``raw`` that pass ``config``.

    Returns a new ``FilteredLightCurve``; ``raw`` is left untouched. When
    every cadence is rejected the result is returned normally with empty
    arrays and complete statistics -- an unusable sector is a meaningful
    scientific outcome, and raising would discard the counts that explain
    why. Callers downstream are responsible for refusing to search an
    empty curve.

    Raises:
        InvalidLightCurveError: the light curve has mismatched column
            lengths or no cadences.
        InvalidFilterConfigError: the configuration is unusable (raised
            when the ``QualityFilterConfig`` is constructed).
    """
    active_config = config if config is not None else QualityFilterConfig()
    _validate_input(raw)

    bitmask = active_config.active_bitmask

    retained_indices: list[int] = []
    rejected: list[RejectedCadence] = []
    by_reason: dict[RejectionReason, int] = {}
    by_bit: dict[int, int] = {}

    for index in range(len(raw.time)):
        quality = raw.quality[index]
        matched_bits = quality & bitmask
        reasons = _reasons_for_cadence(
            time=raw.time[index],
            flux=raw.flux[index],
            flux_err=raw.flux_err[index] if raw.flux_err is not None else None,
            matched_bits=matched_bits,
            config=active_config,
        )
        if not reasons:
            retained_indices.append(index)
            continue

        rejected.append(
            RejectedCadence(
                index=index,
                time=raw.time[index],
                quality=quality,
                matched_quality_bits=matched_bits,
                reasons=reasons,
            )
        )
        for reason in reasons:
            by_reason[reason] = by_reason.get(reason, 0) + 1
        for bit_index in range(matched_bits.bit_length()):
            bit_value = 1 << bit_index
            if matched_bits & bit_value:
                by_bit[bit_value] = by_bit.get(bit_value, 0) + 1

    stats = QualityFilterStats(
        total_cadences=len(raw.time),
        retained_cadences=len(retained_indices),
        rejected_cadences=len(rejected),
        rejected_by_reason=by_reason,
        rejected_by_quality_bit=by_bit,
    )
    step = ProcessingStep(
        step=_STEP_NAME,
        code_version=_code_version(),
        quality_policy=active_config.quality_policy,
        active_quality_bitmask=bitmask,
        config=active_config,
        input_cadences=len(raw.time),
        output_cadences=len(retained_indices),
        input_checksum_sha256=raw.provenance.source_checksum_sha256,
    )

    logger.info(
        "quality_filter_completed",
        policy=active_config.quality_policy.value,
        bitmask=bitmask,
        total=stats.total_cadences,
        retained=stats.retained_cadences,
        rejected=stats.rejected_cadences,
        source=raw.provenance.source_filename,
    )
    if stats.retained_cadences == 0:
        logger.warning(
            "quality_filter_rejected_all_cadences",
            policy=active_config.quality_policy.value,
            bitmask=bitmask,
            source=raw.provenance.source_filename,
        )

    return FilteredLightCurve(
        time=tuple(raw.time[i] for i in retained_indices),
        flux=tuple(raw.flux[i] for i in retained_indices),
        flux_err=(
            tuple(raw.flux_err[i] for i in retained_indices) if raw.flux_err is not None else None
        ),
        quality=tuple(raw.quality[i] for i in retained_indices),
        source_indices=tuple(retained_indices),
        flux_column=raw.flux_column,
        provenance=raw.provenance,
        metadata=raw.metadata,
        stats=stats,
        rejected=tuple(rejected),
        history=(step,),
    )


def _reasons_for_cadence(
    *,
    time: float,
    flux: float,
    flux_err: float | None,
    matched_bits: int,
    config: QualityFilterConfig,
) -> tuple[RejectionReason, ...]:
    """Every rejection reason applying to one cadence, in a fixed order.

    Returns an empty tuple when the cadence is retained. No check
    short-circuits another, so simultaneous problems are all recorded.
    """
    reasons: list[RejectionReason] = []
    if config.require_finite_time and not isfinite(time):
        reasons.append(RejectionReason.NONFINITE_TIME)
    if config.require_finite_flux and not isfinite(flux):
        reasons.append(RejectionReason.NONFINITE_FLUX)
    if config.require_finite_flux_err and flux_err is not None and not isfinite(flux_err):
        reasons.append(RejectionReason.NONFINITE_FLUX_ERR)
    if matched_bits:
        reasons.append(RejectionReason.MATCHED_QUALITY_BITS)
    return tuple(reasons)


def _validate_input(raw: RawLightCurve) -> None:
    """Guard against structurally invalid light curves.

    ``parse_light_curve`` already rejects both conditions, but
    ``RawLightCurve`` validates each field independently and does not
    cross-check column lengths, so a light curve built directly in code
    can still reach here malformed.
    """
    lengths = {
        "time": len(raw.time),
        "flux": len(raw.flux),
        "quality": len(raw.quality),
    }
    if raw.flux_err is not None:
        lengths["flux_err"] = len(raw.flux_err)
    if len(set(lengths.values())) > 1:
        raise InvalidLightCurveError(
            f"Light curve columns have mismatched lengths: {lengths}. "
            "Every column must have one entry per cadence."
        )
    if not raw.time:
        raise InvalidLightCurveError("Light curve has no cadences; nothing to filter.")


def _code_version() -> str:
    """Version of the backend package, recorded in processing history."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - package is installed in all envs
        return "unknown"
