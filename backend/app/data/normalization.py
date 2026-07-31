"""Per-segment flux normalization for an already gap-segmented TESS light
curve (Phase 3C).

This is the first slice of the ``Light-curve preprocessing
(normalization, sigma clipping)`` stage in ``docs/architecture.md``: it
places each ``LightCurveSegment``'s flux on a consistent relative scale,
independently of every other segment, and never alters TIME, QUALITY,
source indices, or gap records. Sigma clipping, outlier rejection,
detrending, smoothing, interpolation, gap filling, sector stitching,
transit search, and machine learning are all out of scope here and
remain later milestones.

Method
------
Median-ratio normalization is the only supported algorithm::

    normalized_flux = flux / segment_reference

where ``segment_reference`` is the **median** of the segment's finite
flux values. There is no method selector: a single documented algorithm,
pinned by ``code_version``, is enough for this phase -- the same reason
``GapDetectionStep`` (Phase 3B) has no "gap rule" field. Median, not
mean, for the same robustness reason Phase 3B measures cadence with a
median: a brief transit or a handful of outlying flux values would bias
a mean, but cannot move a median by more than its own magnitude allows.

The expected baseline for a successfully normalized segment is
``normalized_flux ~= 1.0``. ``relative_flux = normalized_flux - 1`` is
intentionally **not** stored anywhere: it is a lossless, one-line
derivation of ``normalized_flux``, so persisting it would duplicate
scientific data for no new information.

Why normalization never crosses a gap
--------------------------------------
Each segment's reference is computed **only** from that segment's own
``flux`` tuple -- ``LightCurveSegment.flux`` is already gap-isolated by
Phase 3B's construction (sliced from the parent ``FilteredLightCurve``
at segment boundaries), and this module never reads two segments'
arrays together. There is no code path by which one segment's flux can
influence another segment's reference or normalized values.

Why negative and nonpositive references are not normalized
------------------------------------------------------------
Dividing by a negative reference reverses the direction of every flux
variation in the segment: a downward change in raw flux would become an
upward normalized feature, which would be unsafe for later transit
analysis (a real transit dip could appear as a normalized brightening).
A reference of zero (or within ``NormalizationConfig.zero_reference_tolerance``
of zero) makes the ratio undefined or numerically meaningless. Both
conditions are recorded as a ``ReferenceIssue`` and left un-normalized --
the segment's original data is fully preserved either way, and
processing continues for every other segment.

Mixed finite/nonfinite flux within a segment
----------------------------------------------
Phase 3A's default configuration (``require_finite_flux=True``) already
removes nonfinite flux before a light curve ever reaches Phase 3B or
3C, so this case does not arise under standard configuration. It
remains explicitly handled here for light curves quality-filtered with
``require_finite_flux=False``, or ``LightCurveSegment``/
``SegmentedLightCurve`` objects constructed directly.

Chosen behavior: **the reference is calculated from the segment's
finite flux values only, and every cadence -- finite or not -- is
still normalized.** No cadence is silently dropped from the output, and
none is silently "fixed": a cadence whose original flux is NaN or
+/-inf divides through to a nonfinite ``normalized_flux`` value at that
position, via ordinary IEEE-754 floating-point division
(``float('nan') / reference`` is ``nan``; ``float('inf') / reference``
is ``+inf`` for a positive reference). No special-casing is needed for
this -- it is the natural result of dividing whatever value is present
by the reference, and it keeps ``normalized_flux`` the same length as
``segment.flux`` in every case where the segment has *any* finite flux
to compute a reference from.

Edge cases
----------
* Empty ``SegmentedLightCurve`` (zero segments): zero segments out. Not
  an error.
* One-cadence segments: the median of one value is that value, so
  ``normalized_flux == (1.0,)`` whenever that value is itself finite,
  positive, and outside the zero tolerance. No special-cased code path
  is needed -- this falls out of the general algorithm.
* A segment with no finite flux at all: ``ReferenceIssue.NO_FINITE_FLUX``;
  ``normalized_flux``/``normalized_flux_err`` are ``None``.

Flux-error propagation
-----------------------
For a successfully normalized segment::

    normalized_flux_err = flux_err / abs(segment_reference)

This treats the computed reference as an **exact** scaling constant.
The median estimator's own sampling uncertainty is not propagated into
``normalized_flux_err`` -- this is a deliberate simplification (also
made by, e.g., Lightkurve's own ``.normalize()``), not an oversight.
When the input has no ``flux_err`` column at all, ``normalized_flux_err``
remains ``None`` for every segment -- never fabricated.

Guarantees
----------
* No cadence is ever removed, reordered, or duplicated by this module,
  including cadences in a segment whose reference is invalid.
* The input ``SegmentedLightCurve`` is never mutated (frozen models,
  tuple fields).
* ``gaps`` and every prior ``history`` entry are carried through
  unchanged.
* The result is a pure function of ``(segmented, config)`` -- no
  timestamps, no randomness -- so reruns are reproducible byte-for-byte.
* This module is not detrending (no time-varying baseline is fit or
  removed) and not outlier rejection (no cadence is ever excluded from
  the output because of its flux value). Sigma clipping remains a
  later milestone.
"""

import statistics
from importlib.metadata import PackageNotFoundError, version
from math import isfinite

from app.core.logging import get_logger
from app.data.exceptions import InvalidLightCurveError
from app.data.models import (
    LightCurveSegment,
    NormalizationConfig,
    NormalizationStats,
    NormalizationStep,
    NormalizedLightCurve,
    NormalizedSegment,
    ReferenceIssue,
    SegmentedLightCurve,
    SegmentNormalizationStats,
)

logger = get_logger(__name__)

_STEP_NAME = "flux_normalization"
_DISTRIBUTION = "exoplanet-hunter-backend"


def normalize_light_curve(
    segmented: SegmentedLightCurve,
    config: NormalizationConfig | None = None,
) -> NormalizedLightCurve:
    """Normalize every segment of ``segmented`` independently.

    Returns a new ``NormalizedLightCurve``; ``segmented`` is left
    untouched. A segment whose median reference is zero, negative, or
    otherwise unusable never raises -- it is recorded with a
    ``ReferenceIssue`` and left un-normalized while every other segment
    is still processed. Empty input (zero segments) is returned
    normally with zero segments, not as an error.

    Raises:
        InvalidLightCurveError: a segment has mismatched column lengths.
        InvalidNormalizationConfigError: the configuration is unusable
            (raised when the ``NormalizationConfig`` is constructed).
    """
    active_config = config if config is not None else NormalizationConfig()

    for segment in segmented.segments:
        _validate_structure(segment)

    normalized_segments = tuple(
        _normalize_segment(segment, active_config) for segment in segmented.segments
    )

    normalized_count = sum(1 for result in normalized_segments if result.stats.reference_valid)
    invalid_by_issue: dict[ReferenceIssue, int] = {}
    for result in normalized_segments:
        if result.stats.reference_issue is not None:
            invalid_by_issue[result.stats.reference_issue] = (
                invalid_by_issue.get(result.stats.reference_issue, 0) + 1
            )

    total_cadences = segmented.cadence_count
    stats = NormalizationStats(
        total_cadences=total_cadences,
        segment_count=len(normalized_segments),
        normalized_segment_count=normalized_count,
        invalid_segment_count=len(normalized_segments) - normalized_count,
        invalid_by_issue=invalid_by_issue,
    )
    step = NormalizationStep(
        step=_STEP_NAME,
        code_version=_code_version(),
        config=active_config,
        input_cadences=total_cadences,
        input_segment_count=len(normalized_segments),
        normalized_segment_count=normalized_count,
        input_checksum_sha256=segmented.provenance.source_checksum_sha256,
    )

    logger.info(
        "flux_normalization_completed",
        total_cadences=total_cadences,
        segment_count=stats.segment_count,
        normalized_segment_count=normalized_count,
        invalid_segment_count=stats.invalid_segment_count,
        source=segmented.provenance.source_filename,
    )
    if stats.invalid_segment_count:
        logger.warning(
            "flux_normalization_segments_not_normalized",
            invalid_segment_count=stats.invalid_segment_count,
            invalid_by_issue={issue.value: count for issue, count in invalid_by_issue.items()},
            source=segmented.provenance.source_filename,
        )

    return NormalizedLightCurve(
        segments=normalized_segments,
        gaps=segmented.gaps,
        stats=stats,
        flux_column=segmented.flux_column,
        provenance=segmented.provenance,
        metadata=segmented.metadata,
        history=(*segmented.history, step),
    )


def _normalize_segment(
    segment: LightCurveSegment, config: NormalizationConfig
) -> NormalizedSegment:
    """Compute one segment's median reference and, if it is usable,
    divide every cadence's flux (and flux error) by it."""
    finite_values = [value for value in segment.flux if isfinite(value)]
    finite_flux_count = len(finite_values)

    if finite_flux_count == 0:
        stats = SegmentNormalizationStats(
            reference=None,
            finite_flux_count=0,
            reference_valid=False,
            reference_issue=ReferenceIssue.NO_FINITE_FLUX,
        )
        return NormalizedSegment(
            segment=segment, normalized_flux=None, normalized_flux_err=None, stats=stats
        )

    reference = statistics.median(finite_values)
    issue = _classify_reference(reference, config)

    stats = SegmentNormalizationStats(
        reference=reference,
        finite_flux_count=finite_flux_count,
        reference_valid=issue is None,
        reference_issue=issue,
    )

    if issue is not None:
        return NormalizedSegment(
            segment=segment, normalized_flux=None, normalized_flux_err=None, stats=stats
        )

    normalized_flux = tuple(value / reference for value in segment.flux)
    normalized_flux_err = (
        tuple(err / abs(reference) for err in segment.flux_err)
        if segment.flux_err is not None
        else None
    )
    return NormalizedSegment(
        segment=segment,
        normalized_flux=normalized_flux,
        normalized_flux_err=normalized_flux_err,
        stats=stats,
    )


def _classify_reference(reference: float, config: NormalizationConfig) -> ReferenceIssue | None:
    """Which (if any) ``ReferenceIssue`` applies to an already-computed
    median reference, in the fixed order documented on ``ReferenceIssue``."""
    if not isfinite(reference):
        return ReferenceIssue.NONFINITE_REFERENCE
    if abs(reference) <= config.zero_reference_tolerance:
        return ReferenceIssue.ZERO_REFERENCE
    if reference < 0:
        return ReferenceIssue.NEGATIVE_REFERENCE
    return None


def _validate_structure(segment: LightCurveSegment) -> None:
    """Guard against a structurally invalid segment.

    ``segment_light_curve`` already produces internally consistent
    segments, but this defends against a ``LightCurveSegment``
    constructed directly, the same way ``gap_segmentation._validate_structure``
    defends ``FilteredLightCurve``.
    """
    lengths = {
        "time": len(segment.time),
        "flux": len(segment.flux),
        "quality": len(segment.quality),
        "source_indices": len(segment.source_indices),
    }
    if segment.flux_err is not None:
        lengths["flux_err"] = len(segment.flux_err)
    if len(set(lengths.values())) > 1:
        raise InvalidLightCurveError(
            f"Segment #{segment.segment_number} columns have mismatched lengths: "
            f"{lengths}. Every column must have one entry per retained cadence."
        )


def _code_version() -> str:
    """Version of the backend package, recorded in processing history."""
    try:
        return version(_DISTRIBUTION)
    except PackageNotFoundError:  # pragma: no cover - package is installed in all envs
        return "unknown"
