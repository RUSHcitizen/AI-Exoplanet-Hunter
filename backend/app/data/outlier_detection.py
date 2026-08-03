"""Robust per-segment statistical outlier *flagging* for an already
normalized TESS light curve (Phase 3D).

This is the ``Sigma clipping (per-segment outlier rejection)`` stage's
non-destructive slice: it identifies statistically unusual normalized
flux measurements and attaches transparent, traceable flags -- it never
deletes, replaces, interpolates, or reorders a cadence. Every cadence
that enters this module leaves it, in the same order, with the same
values. Later stages remain free to decide whether or how to use the
flags; nothing here commits to excluding a cadence from anything.

Why this stage flags rather than removes
------------------------------------------
A possible exoplanet transit appears as a *downward* brightness change.
A generic two-sided sigma-clipping rule would erase exactly the signal
this project searches for. Consequently:

* Downward (``OutlierDirection.LOW``) detection is **disabled by
  default** (``OutlierDetectionConfig.lower_threshold=None``).
* Upward (``OutlierDirection.HIGH``) detection -- positive spikes such as
  cosmic rays or momentum-dump artifacts -- is flagged by default and
  cannot be disabled, since a positive spike can never be mistaken for a
  transit.
* No cadence is ever removed automatically, regardless of configuration.
* A caller may explicitly set ``lower_threshold``, but doing so can flag
  possible transits along with genuine artifacts -- see
  ``OutlierDetectionConfig``'s docstring.

Method
------
Independently within every successfully normalized segment, using only
that segment's own finite ``normalized_flux`` values::

    center = median(finite normalized flux values)
    MAD = median(abs(value - center))
    robust_scale = 1.4826 * MAD
    robust_score = (value - center) / robust_scale

``1.4826`` is the conventional Gaussian-consistency scaling factor for
MAD: it makes ``robust_scale`` an unbiased estimator of the standard
deviation *if* the underlying distribution were exactly Gaussian. TESS
photometric noise is not claimed to be Gaussian -- the factor is used
only as a documented, deterministic convention, the same way Lightkurve
and other pipelines use it.

A value is a high outlier when ``robust_score > upper_threshold``. A
value is a low outlier only when ``lower_threshold`` is not ``None`` and
``robust_score < -lower_threshold``. Equality with a threshold is never
an outlier (strict comparison only). This module never iterates --
scores are computed once, from the whole segment, with no clipping loop.

Why this never crosses a gap or mixes segments
-------------------------------------------------
Each segment's ``center``/``MAD``/``robust_scale`` are computed **only**
from that segment's own ``normalized_flux`` tuple -- this module never
reads two segments' arrays together, the same guarantee
``app.data.normalization`` makes for the segment reference.

Segment analysis statuses
----------------------------
A segment's cadences are always preserved and its masks are always
present and aligned, but ``robust_score`` is only computed -- and
``high_outlier_mask``/``low_outlier_mask`` can only be ``True`` -- when
``SegmentOutlierStats.status is OutlierAnalysisStatus.VALID``:

* ``INSUFFICIENT_DATA`` -- fewer finite normalized-flux values than
  ``OutlierDetectionConfig.minimum_finite_cadences`` (e.g. a one-cadence
  segment). A median/MAD from too few points is not trustworthy enough
  to score anything against.
* ``ZERO_SCALE`` -- ``robust_scale`` is not finite, or is at or below
  ``OutlierDetectionConfig.minimum_robust_scale`` (e.g. a constant or
  near-constant segment). No division by zero, no invented scores.
* ``NORMALIZATION_UNAVAILABLE`` -- the embedded ``NormalizedSegment``
  itself has ``normalized_flux is None`` (Phase 3C could not normalize
  it; see ``ReferenceIssue``). There is nothing to analyze.

Nonfinite normalized positions
----------------------------------
Phase 3A's default configuration (``require_finite_flux=True``) already
removes nonfinite flux before a light curve ever reaches Phase 3D, so a
nonfinite ``normalized_flux`` value does not arise under standard
configuration. It remains explicitly handled here for light curves
quality-filtered with ``require_finite_flux=False``, or
``NormalizedSegment``/``NormalizedLightCurve`` objects constructed
directly: such a position is excluded from ``center``/``MAD``, is never
classified as a high or low statistical outlier, never sets
``high_outlier_mask``/``low_outlier_mask``, and -- when
``OutlierDetectionConfig.flag_nonfinite_normalized_flux`` is ``True``
(the default) -- gets its own ``FlaggedCadence`` record with a reason
(``NONFINITE_NORMALIZED_FLUX``) distinct from both statistical-outlier
reasons. Every mask position still exists; nothing is silently omitted
from the aligned output.

Guarantees
----------
* No cadence is ever removed, reordered, or duplicated by this module.
* The input ``NormalizedLightCurve`` is never mutated (frozen models,
  tuple fields).
* ``gaps`` and every prior ``history`` entry are carried through
  unchanged.
* The result is a pure function of ``(normalized, config)`` -- no
  timestamps, no randomness, no iterative reweighting -- so reruns are
  reproducible byte-for-byte.
* This module is not detrending, not smoothing, not sector stitching,
  and not transit detection: it computes one robust score per finite
  cadence, once, and compares it to a fixed threshold.
"""

import statistics
from importlib.metadata import PackageNotFoundError, version
from math import isfinite

from app.core.logging import get_logger
from app.data.exceptions import InvalidLightCurveError
from app.data.models import (
    FlaggedCadence,
    LightCurveSegment,
    NormalizedLightCurve,
    NormalizedSegment,
    OutlierAnalysisStatus,
    OutlierDetectionConfig,
    OutlierDetectionStats,
    OutlierDetectionStep,
    OutlierDirection,
    OutlierFlaggedLightCurve,
    OutlierFlaggedSegment,
    OutlierReason,
    SegmentOutlierStats,
)

logger = get_logger(__name__)

_STEP_NAME = "outlier_flagging"
_DISTRIBUTION = "exoplanet-hunter-backend"
_MAD_GAUSSIAN_SCALE = 1.4826
"""Gaussian-consistency scaling convention for MAD -- see the module
docstring's "Method" section. Not a claim that TESS noise is Gaussian."""


def flag_outliers(
    normalized: NormalizedLightCurve,
    config: OutlierDetectionConfig | None = None,
) -> OutlierFlaggedLightCurve:
    """Analyze every segment of ``normalized`` independently for
    statistically unusual normalized flux values.

    Returns a new ``OutlierFlaggedLightCurve``; ``normalized`` is left
    untouched. No cadence is ever removed, replaced, interpolated, or
    reordered -- this is a flagging stage. A segment that cannot be
    trusted for scoring (too few finite values, an unusable robust
    scale, or an unavailable Phase 3C normalization) never raises -- it
    is recorded with an ``OutlierAnalysisStatus`` and left with an
    all-``False`` statistical-outlier mask while every other segment is
    still processed. Empty input (zero segments) is returned normally
    with zero segments, not as an error.

    Raises:
        InvalidLightCurveError: a segment's ``normalized_flux`` length
            does not match its cadence count.
        InvalidOutlierDetectionConfigError: the configuration is unusable
            (raised when the ``OutlierDetectionConfig`` is constructed).
    """
    active_config = config if config is not None else OutlierDetectionConfig()

    for entry in normalized.segments:
        _validate_structure(entry)

    flagged_segments = tuple(
        _analyze_segment(entry, active_config) for entry in normalized.segments
    )

    analyzed_count = sum(
        1 for result in flagged_segments if result.stats.status is OutlierAnalysisStatus.VALID
    )
    unanalyzed_by_status: dict[OutlierAnalysisStatus, int] = {}
    for result in flagged_segments:
        if result.stats.status is not OutlierAnalysisStatus.VALID:
            unanalyzed_by_status[result.stats.status] = (
                unanalyzed_by_status.get(result.stats.status, 0) + 1
            )

    total_cadences = normalized.cadence_count
    stats = OutlierDetectionStats(
        total_cadences=total_cadences,
        segment_count=len(flagged_segments),
        analyzed_segment_count=analyzed_count,
        unanalyzed_by_status=unanalyzed_by_status,
        total_high_outliers=sum(result.stats.high_outlier_count for result in flagged_segments),
        total_low_outliers=sum(result.stats.low_outlier_count for result in flagged_segments),
        total_nonfinite_flagged=sum(
            result.stats.nonfinite_flagged_count for result in flagged_segments
        ),
    )
    step = OutlierDetectionStep(
        step=_STEP_NAME,
        code_version=_code_version(),
        config=active_config,
        input_cadences=total_cadences,
        input_segment_count=len(flagged_segments),
        analyzed_segment_count=analyzed_count,
        flagged_cadence_count=sum(len(result.flagged_cadences) for result in flagged_segments),
        input_checksum_sha256=normalized.provenance.source_checksum_sha256,
    )

    logger.info(
        "outlier_flagging_completed",
        total_cadences=total_cadences,
        segment_count=stats.segment_count,
        analyzed_segment_count=analyzed_count,
        total_high_outliers=stats.total_high_outliers,
        total_low_outliers=stats.total_low_outliers,
        lower_threshold_enabled=active_config.lower_threshold is not None,
        source=normalized.provenance.source_filename,
    )
    if unanalyzed_by_status:
        logger.warning(
            "outlier_flagging_segments_not_analyzed",
            unanalyzed_by_status={
                status.value: count for status, count in unanalyzed_by_status.items()
            },
            source=normalized.provenance.source_filename,
        )

    return OutlierFlaggedLightCurve(
        segments=flagged_segments,
        gaps=normalized.gaps,
        stats=stats,
        flux_column=normalized.flux_column,
        provenance=normalized.provenance,
        metadata=normalized.metadata,
        history=(*normalized.history, step),
    )


def _analyze_segment(
    entry: NormalizedSegment, config: OutlierDetectionConfig
) -> OutlierFlaggedSegment:
    """Classify one segment's status and, if usable, compute
    ``center``/``raw_mad``/``robust_scale`` from its finite
    ``normalized_flux`` values."""
    normalized_flux = entry.normalized_flux

    if normalized_flux is None:
        return _build_result(
            entry,
            config,
            status=OutlierAnalysisStatus.NORMALIZATION_UNAVAILABLE,
            center=None,
            raw_mad=None,
            robust_scale=None,
            finite_count=0,
        )

    finite_values = [value for value in normalized_flux if isfinite(value)]
    finite_count = len(finite_values)

    center = statistics.median(finite_values) if finite_count else None
    raw_mad = (
        statistics.median(abs(value - center) for value in finite_values)
        if center is not None
        else None
    )
    robust_scale = _MAD_GAUSSIAN_SCALE * raw_mad if raw_mad is not None else None

    if finite_count < config.minimum_finite_cadences:
        status = OutlierAnalysisStatus.INSUFFICIENT_DATA
    elif (
        robust_scale is None
        or not isfinite(robust_scale)
        or robust_scale <= config.minimum_robust_scale
    ):
        status = OutlierAnalysisStatus.ZERO_SCALE
    else:
        status = OutlierAnalysisStatus.VALID

    return _build_result(
        entry,
        config,
        status=status,
        center=center,
        raw_mad=raw_mad,
        robust_scale=robust_scale,
        finite_count=finite_count,
    )


def _build_result(
    entry: NormalizedSegment,
    config: OutlierDetectionConfig,
    *,
    status: OutlierAnalysisStatus,
    center: float | None,
    raw_mad: float | None,
    robust_scale: float | None,
    finite_count: int,
) -> OutlierFlaggedSegment:
    """Walk every cadence position once, building aligned masks and
    detailed records for whichever conditions actually apply at
    ``status``."""
    segment = entry.segment
    normalized_flux = entry.normalized_flux
    n = segment.cadence_count
    lower_threshold = config.lower_threshold
    lower_enabled = lower_threshold is not None
    is_valid = status is OutlierAnalysisStatus.VALID

    high_mask = [False] * n
    low_mask: list[bool] | None = [False] * n if lower_enabled else None
    records: list[FlaggedCadence] = []
    high_count = 0
    low_count = 0
    nonfinite_count = 0

    if normalized_flux is not None:
        for position in range(n):
            value = normalized_flux[position]
            if not isfinite(value):
                if config.flag_nonfinite_normalized_flux:
                    nonfinite_count += 1
                    records.append(
                        _flagged_cadence(
                            segment,
                            position,
                            value=value,
                            robust_score=None,
                            direction=None,
                            threshold=None,
                            reason=OutlierReason.NONFINITE_NORMALIZED_FLUX,
                        )
                    )
                continue

            if not is_valid:
                continue
            assert center is not None and robust_scale is not None  # guaranteed by VALID status

            score = (value - center) / robust_scale
            if score > config.upper_threshold:
                high_mask[position] = True
                high_count += 1
                records.append(
                    _flagged_cadence(
                        segment,
                        position,
                        value=value,
                        robust_score=score,
                        direction=OutlierDirection.HIGH,
                        threshold=config.upper_threshold,
                        reason=OutlierReason.HIGH_STATISTICAL_OUTLIER,
                    )
                )
            elif lower_enabled and lower_threshold is not None and score < -lower_threshold:
                assert low_mask is not None
                low_mask[position] = True
                low_count += 1
                records.append(
                    _flagged_cadence(
                        segment,
                        position,
                        value=value,
                        robust_score=score,
                        direction=OutlierDirection.LOW,
                        threshold=lower_threshold,
                        reason=OutlierReason.LOW_STATISTICAL_OUTLIER,
                    )
                )

    outlier_mask = tuple(
        high_mask[i] or (low_mask[i] if low_mask is not None else False) for i in range(n)
    )
    stats = SegmentOutlierStats(
        status=status,
        finite_values_analyzed=finite_count,
        center=center,
        raw_mad=raw_mad,
        robust_scale=robust_scale,
        high_outlier_count=high_count,
        low_outlier_count=low_count,
        nonfinite_flagged_count=nonfinite_count,
    )
    return OutlierFlaggedSegment(
        normalized=entry,
        outlier_mask=outlier_mask,
        high_outlier_mask=tuple(high_mask),
        low_outlier_mask=(tuple(low_mask) if low_mask is not None else None),
        flagged_cadences=tuple(records),
        stats=stats,
    )


def _flagged_cadence(
    segment: LightCurveSegment,
    position: int,
    *,
    value: float,
    robust_score: float | None,
    direction: OutlierDirection | None,
    threshold: float | None,
    reason: OutlierReason,
) -> FlaggedCadence:
    return FlaggedCadence(
        segment_number=segment.segment_number,
        position_in_segment=position,
        filtered_position=segment.start_position + position,
        source_index=segment.source_indices[position],
        time=segment.time[position],
        normalized_flux=value,
        robust_score=robust_score,
        direction=direction,
        threshold=threshold,
        reason=reason,
    )


def _validate_structure(entry: NormalizedSegment) -> None:
    """Guard against a structurally invalid normalized segment.

    ``normalize_light_curve`` already produces internally consistent
    output, but this defends against a ``NormalizedSegment`` constructed
    directly, the same way ``normalization._validate_structure`` defends
    ``LightCurveSegment``.
    """
    if (
        entry.normalized_flux is not None
        and len(entry.normalized_flux) != entry.segment.cadence_count
    ):
        raise InvalidLightCurveError(
            f"Segment #{entry.segment.segment_number} has {len(entry.normalized_flux)} "
            f"normalized_flux value(s) but {entry.segment.cadence_count} cadence(s). "
            "Every cadence must have exactly one normalized_flux entry."
        )
    if (
        entry.normalized_flux_err is not None
        and len(entry.normalized_flux_err) != entry.segment.cadence_count
    ):
        raise InvalidLightCurveError(
            f"Segment #{entry.segment.segment_number} has {len(entry.normalized_flux_err)} "
            f"normalized_flux_err value(s) but {entry.segment.cadence_count} cadence(s). "
            "Every cadence must have exactly one normalized_flux_err entry."
        )


def _code_version() -> str:
    """Version of the backend package, recorded in processing history."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - package is installed in all envs
        return "unknown"
