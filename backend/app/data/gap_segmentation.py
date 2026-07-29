"""Gap detection and contiguous light-curve segmentation for an
already quality-filtered TESS light curve (Phase 3B).

This is the ``Light-curve preprocessing`` stage's gap-handling slice: it
divides a ``FilteredLightCurve`` into scientifically traceable
contiguous segments, at every TIME discontinuity large enough to be a
meaningful gap rather than ordinary cadence jitter. No value is ever
changed, invented, or interpolated -- normalization, detrending,
sigma clipping, smoothing, gap filling, and sector stitching all remain
out of scope for later phases.

Units
-----
Every duration in this module (nominal cadence, gap thresholds, actual
intervals) is expressed in the same unit as ``FilteredLightCurve.time``:
TESS BJD **days**. ``app.data.fits_parser`` reads the FITS ``TIMEDEL``
keyword in days and only converts it to seconds for
``FitsMetadata.cadence_seconds``; this module converts that seconds
value back to days (dividing by 86400) purely to compare it against the
measured, day-native cadence. See ``GapDetectionConfig`` for the exact
fields this applies to.

Nominal cadence estimation
---------------------------
The nominal cadence is the median of every consecutive, strictly
positive TIME difference (a robust statistic, resistant to the handful
of outlying intervals a real gap produces). It is estimable whenever at
least two retained cadences exist, because duplicate and decreasing
TIME values are rejected before reaching this step (see
``NonMonotonicTimeError``), which guarantees every difference actually
computed is strictly positive. It is recorded as ``None`` only when
fewer than two cadences remain -- not an error; see the edge-case
handling below.

The FITS metadata cadence (when available) is recorded alongside the
measured cadence, and whether the two agree within
``GapDetectionConfig.cadence_disagreement_fraction`` is reported in
``SegmentationStats.cadence_sources_agree``. Metadata is never used to
compute gap thresholds and never silently overrides a measured
disagreement: gap detection always uses the measured cadence, because
it reflects this file's own actual TIME sampling, while the metadata
value is a single per-file header constant that may not hold for every
interval (and is absent for some products entirely). A disagreement is
therefore surfaced, not resolved.

Gap rule
--------
An interval between two consecutive retained cadences is a gap when::

    actual_interval > nominal_cadence * gap_multiplier + gap_tolerance

``gap_tolerance`` (a small absolute value, in days) exists specifically
so ordinary floating-point cadence jitter is never misclassified as a
gap; ``gap_multiplier`` must exceed 1.0 for the same reason. Both are
configurable via ``GapDetectionConfig``.

Gap-origin classification
--------------------------
Classification uses only ``source_indices`` and the retained TIME
values -- nothing is inferred beyond what those two arrays can prove:

* ``skipped_source_rows == 0`` (the two retained cadences were adjacent
  in the original FITS table): the time jump was already present
  between neighbouring source rows, so the gap is a genuine
  interruption in the observation itself. Reason: ``OBSERVATION_GAP``.
* ``skipped_source_rows > 0``: an earlier step (typically Phase 3A's
  quality filter) removed one or more rows in between. Reason:
  ``SOURCE_ROWS_REJECTED``. If the actual interval still exceeds what
  those skipped rows alone would account for at the nominal cadence
  (``nominal_cadence * (skipped_source_rows + 1)``, beyond
  ``gap_tolerance``), the gap *also* carries ``OBSERVATION_GAP``: the
  skipped rows explain part of the interval, but not all of it.

Missing-cadence estimation
---------------------------
``DetectedGap.estimated_missing_cadences`` is
``round(actual_interval / nominal_cadence) - 1`` (floored at zero),
reported only when that ratio is within
``GapDetectionConfig.missing_cadence_residual_tolerance`` of a whole
number. An interval that doesn't land close to an integer multiple of
the nominal cadence gets ``None`` instead of a falsely precise guess.

Edge cases
----------
* No gaps: one segment containing every retained cadence.
* Zero retained cadences (an entirely rejected input): zero segments,
  zero gaps, ``measured_nominal_cadence=None``. Not an error.
* One retained cadence: one one-cadence segment,
  ``measured_nominal_cadence=None`` (nothing to estimate cadence from,
  which is not itself an error).
* Every interval exceeding the threshold: one single-cadence segment
  per retained cadence, with a gap between every consecutive pair.

Guarantees
----------
* The input ``FilteredLightCurve`` is never mutated (frozen, tuple
  fields).
* Every retained cadence appears in exactly one segment; none are lost
  or duplicated.
* Duplicate or decreasing consecutive TIME values raise
  ``NonMonotonicTimeError`` rather than being silently sorted or
  merged.
* The result is a pure function of ``(filtered, config)`` -- no
  timestamps, no randomness -- so reruns are reproducible byte-for-byte.
"""

import statistics
from importlib.metadata import PackageNotFoundError, version
from itertools import pairwise
from math import isfinite

from app.core.logging import get_logger
from app.data.exceptions import (
    InvalidLightCurveError,
    NonFiniteTimeError,
    NonMonotonicTimeError,
)
from app.data.models import (
    DetectedGap,
    FilteredLightCurve,
    GapDetectionConfig,
    GapDetectionStep,
    GapReason,
    LightCurveSegment,
    SegmentationStats,
    SegmentedLightCurve,
)

logger = get_logger(__name__)

_STEP_NAME = "gap_segmentation"
_DISTRIBUTION = "exoplanet-hunter-backend"
_SECONDS_PER_DAY = 86400.0


def segment_light_curve(
    filtered: FilteredLightCurve,
    config: GapDetectionConfig | None = None,
) -> SegmentedLightCurve:
    """Divide ``filtered`` into contiguous segments at every detected gap.

    Returns a new ``SegmentedLightCurve``; ``filtered`` is left
    untouched. Empty input is returned normally as a documented empty
    result (zero segments, zero gaps) rather than raising -- see the
    module docstring's edge-case handling.

    Raises:
        InvalidLightCurveError: the filtered light curve has mismatched
            column lengths.
        NonFiniteTimeError: a retained cadence has a nonfinite TIME
            value.
        NonMonotonicTimeError: TIME is not strictly increasing (a
            duplicate or decreasing consecutive value was found).
        InvalidGapDetectionConfigError: the configuration is unusable
            (raised when the ``GapDetectionConfig`` is constructed).
    """
    active_config = config if config is not None else GapDetectionConfig()
    _validate_structure(filtered)

    total_cadences = filtered.cadence_count
    if total_cadences == 0:
        segments: tuple[LightCurveSegment, ...] = ()
        gaps: tuple[DetectedGap, ...] = ()
        nominal_cadence: float | None = None
    else:
        _validate_finite_time(filtered)
        if total_cadences >= 2:
            _validate_monotonic_time(filtered)
        nominal_cadence = _measure_nominal_cadence(filtered.time)
        segments, gaps = _build_segments_and_gaps(filtered, nominal_cadence, active_config)

    metadata_cadence_seconds = filtered.metadata.cadence_seconds
    metadata_cadence_native = (
        metadata_cadence_seconds / _SECONDS_PER_DAY
        if metadata_cadence_seconds is not None
        else None
    )
    cadence_sources_agree = _cadence_agreement(
        nominal_cadence, metadata_cadence_native, active_config
    )

    stats = SegmentationStats(
        total_cadences=total_cadences,
        segment_count=len(segments),
        gap_count=len(gaps),
        measured_nominal_cadence=nominal_cadence,
        metadata_cadence_seconds=metadata_cadence_seconds,
        metadata_cadence_native=metadata_cadence_native,
        cadence_sources_agree=cadence_sources_agree,
        total_estimated_missing_cadences=sum(
            gap.estimated_missing_cadences
            for gap in gaps
            if gap.estimated_missing_cadences is not None
        ),
    )
    step = GapDetectionStep(
        step=_STEP_NAME,
        code_version=_code_version(),
        config=active_config,
        input_cadences=total_cadences,
        output_segment_count=len(segments),
        output_gap_count=len(gaps),
        input_checksum_sha256=filtered.provenance.source_checksum_sha256,
    )

    logger.info(
        "gap_segmentation_completed",
        total_cadences=total_cadences,
        segment_count=len(segments),
        gap_count=len(gaps),
        nominal_cadence=nominal_cadence,
        source=filtered.provenance.source_filename,
    )
    if nominal_cadence is None and total_cadences > 0:
        logger.warning(
            "gap_segmentation_nominal_cadence_not_estimable",
            total_cadences=total_cadences,
            source=filtered.provenance.source_filename,
        )

    return SegmentedLightCurve(
        segments=segments,
        gaps=gaps,
        stats=stats,
        flux_column=filtered.flux_column,
        provenance=filtered.provenance,
        metadata=filtered.metadata,
        history=(*filtered.history, step),
    )


def _build_segments_and_gaps(
    filtered: FilteredLightCurve,
    nominal_cadence: float | None,
    config: GapDetectionConfig,
) -> tuple[tuple[LightCurveSegment, ...], tuple[DetectedGap, ...]]:
    """Walk the retained cadences once, splitting into segments at every
    interval that exceeds the gap threshold."""
    time = filtered.time
    total = len(time)
    threshold = (
        nominal_cadence * config.gap_multiplier + config.gap_tolerance
        if (nominal_cadence is not None)
        else None
    )

    gaps: list[DetectedGap] = []
    boundaries = [0]
    for position in range(1, total):
        interval = time[position] - time[position - 1]
        if threshold is not None and interval > threshold:
            assert nominal_cadence is not None  # threshold implies a measured cadence
            gaps.append(
                _build_gap(
                    filtered,
                    before_position=position - 1,
                    after_position=position,
                    actual_interval=interval,
                    nominal_cadence=nominal_cadence,
                    threshold=threshold,
                    config=config,
                )
            )
            boundaries.append(position)
    boundaries.append(total)

    segments = tuple(
        _build_segment(filtered, segment_number=segment_number, start=start, end=end)
        for segment_number, (start, end) in enumerate(pairwise(boundaries), start=1)
    )
    return segments, tuple(gaps)


def _build_segment(
    filtered: FilteredLightCurve, *, segment_number: int, start: int, end: int
) -> LightCurveSegment:
    return LightCurveSegment(
        segment_number=segment_number,
        start_position=start,
        end_position=end - 1,
        start_source_index=filtered.source_indices[start],
        end_source_index=filtered.source_indices[end - 1],
        time=filtered.time[start:end],
        flux=filtered.flux[start:end],
        flux_err=(filtered.flux_err[start:end] if filtered.flux_err is not None else None),
        quality=filtered.quality[start:end],
        source_indices=filtered.source_indices[start:end],
    )


def _build_gap(
    filtered: FilteredLightCurve,
    *,
    before_position: int,
    after_position: int,
    actual_interval: float,
    nominal_cadence: float,
    threshold: float,
    config: GapDetectionConfig,
) -> DetectedGap:
    before_source_index = filtered.source_indices[before_position]
    after_source_index = filtered.source_indices[after_position]
    skipped_source_rows = after_source_index - before_source_index - 1

    reasons: list[GapReason] = []
    if skipped_source_rows > 0:
        reasons.append(GapReason.SOURCE_ROWS_REJECTED)
        expected_if_only_rejection = nominal_cadence * (skipped_source_rows + 1)
        if actual_interval - expected_if_only_rejection > config.gap_tolerance:
            reasons.append(GapReason.OBSERVATION_GAP)
    else:
        reasons.append(GapReason.OBSERVATION_GAP)

    return DetectedGap(
        before_position=before_position,
        after_position=after_position,
        before_source_index=before_source_index,
        after_source_index=after_source_index,
        time_before=filtered.time[before_position],
        time_after=filtered.time[after_position],
        actual_interval=actual_interval,
        nominal_cadence=nominal_cadence,
        threshold=threshold,
        interval_to_cadence_ratio=actual_interval / nominal_cadence,
        reasons=tuple(reasons),
        skipped_source_rows=skipped_source_rows,
        estimated_missing_cadences=_estimate_missing_cadences(
            actual_interval, nominal_cadence, config
        ),
    )


def _estimate_missing_cadences(
    actual_interval: float, nominal_cadence: float, config: GapDetectionConfig
) -> int | None:
    """``round(actual_interval / nominal_cadence) - 1``, only when the
    ratio is close enough to a whole number to avoid false precision."""
    raw_count = actual_interval / nominal_cadence
    nearest = round(raw_count)
    if nearest < 1:
        return None
    if abs(raw_count - nearest) > config.missing_cadence_residual_tolerance:
        return None
    return max(nearest - 1, 0)


def _measure_nominal_cadence(time: tuple[float, ...]) -> float | None:
    """Median of consecutive TIME differences; ``None`` when fewer than
    two cadences exist. Every difference is guaranteed strictly positive
    by ``_validate_monotonic_time``, which runs first."""
    if len(time) < 2:
        return None
    diffs = [time[i] - time[i - 1] for i in range(1, len(time))]
    return statistics.median(diffs)


def _cadence_agreement(
    measured: float | None, metadata_native: float | None, config: GapDetectionConfig
) -> bool | None:
    if measured is None or not metadata_native:
        return None
    return abs(measured - metadata_native) / metadata_native <= config.cadence_disagreement_fraction


def _validate_structure(filtered: FilteredLightCurve) -> None:
    """Guard against a structurally invalid filtered light curve.

    ``filter_quality`` already produces internally consistent output,
    but this defends against a ``FilteredLightCurve`` constructed
    directly, the same way ``quality_filter._validate_input`` defends
    ``RawLightCurve``. Unlike that check, an empty light curve is valid
    here (see the module docstring's edge-case handling) and is not
    rejected.
    """
    lengths = {
        "time": len(filtered.time),
        "flux": len(filtered.flux),
        "quality": len(filtered.quality),
        "source_indices": len(filtered.source_indices),
    }
    if filtered.flux_err is not None:
        lengths["flux_err"] = len(filtered.flux_err)
    if len(set(lengths.values())) > 1:
        raise InvalidLightCurveError(
            f"Filtered light curve columns have mismatched lengths: {lengths}. "
            "Every column must have one entry per retained cadence."
        )


def _validate_finite_time(filtered: FilteredLightCurve) -> None:
    bad = [
        (position, filtered.source_indices[position], value)
        for position, value in enumerate(filtered.time)
        if not isfinite(value)
    ]
    if not bad:
        return
    position, source_index, value = bad[0]
    raise NonFiniteTimeError(
        f"Filtered light curve contains {len(bad)} nonfinite TIME value(s); the first "
        f"is at retained position {position} (source index {source_index}), TIME={value}. "
        "Gap detection cannot compute an interval against a nonfinite TIME; re-run "
        "quality filtering with require_finite_time=True (the project default)."
    )


def _validate_monotonic_time(filtered: FilteredLightCurve) -> None:
    time = filtered.time
    source_indices = filtered.source_indices
    for position in range(1, len(time)):
        diff = time[position] - time[position - 1]
        if diff == 0:
            raise NonMonotonicTimeError(
                f"Duplicate consecutive TIME value {time[position]} at retained positions "
                f"{position - 1} and {position} (source indices {source_indices[position - 1]} "
                f"and {source_indices[position]}). Phase 3B never silently discards or merges "
                "duplicate measurements."
            )
        if diff < 0:
            raise NonMonotonicTimeError(
                f"TIME decreases from {time[position - 1]} to {time[position]} between retained "
                f"positions {position - 1} and {position} (source indices "
                f"{source_indices[position - 1]} and {source_indices[position]}). Phase 3B never "
                "reorders measurements automatically."
            )


def _code_version() -> str:
    """Version of the backend package, recorded in processing history."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - package is installed in all envs
        return "unknown"
