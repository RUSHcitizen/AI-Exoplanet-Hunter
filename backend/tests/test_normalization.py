"""Tests for per-segment flux normalization (Phase 3C).

Segments are built directly as ``LightCurveSegment``/``SegmentedLightCurve``
objects, the same way ``test_gap_segmentation.py`` builds
``FilteredLightCurve`` objects: it keeps the suite fast and is the only
way to reach structurally-invalid states that ``LightCurveSegment``
itself does not cross-validate.
"""

import math
import statistics

import pytest

from app.data.exceptions import InvalidLightCurveError, InvalidNormalizationConfigError
from app.data.models import (
    DetectedGap,
    FileProvenance,
    FitsMetadata,
    GapDetectionConfig,
    GapDetectionStep,
    GapReason,
    LightCurveSegment,
    NormalizationConfig,
    NormalizationStep,
    ProcessingStep,
    QualityFilterConfig,
    ReferenceIssue,
    SegmentationStats,
    SegmentedLightCurve,
)
from app.data.normalization import normalize_light_curve
from app.data.quality_flags import QualityPolicy

CHECKSUM = "a" * 64


def _provenance() -> FileProvenance:
    return FileProvenance(
        source_filename="test-lc.fits",
        source_checksum_sha256=CHECKSUM,
        tic_id=261136679,
        sector=1,
        camera=2,
        ccd=3,
        author="SPOC",
        mission="TESS",
        telescope="TESS",
    )


def _metadata() -> FitsMetadata:
    return FitsMetadata(
        object_name="TIC 261136679",
        time_system="TDB",
        cadence_seconds=86400.0,
        header={},
    )


def _quality_step(n: int) -> ProcessingStep:
    return ProcessingStep(
        step="quality_filter",
        code_version="0.1.0",
        quality_policy=QualityPolicy.MAST,
        active_quality_bitmask=21183,
        config=QualityFilterConfig(),
        input_cadences=n,
        output_cadences=n,
        input_checksum_sha256=CHECKSUM,
    )


def _gap_step(n: int, segment_count: int, gap_count: int) -> GapDetectionStep:
    return GapDetectionStep(
        step="gap_segmentation",
        code_version="0.1.0",
        config=GapDetectionConfig(),
        input_cadences=n,
        output_segment_count=segment_count,
        output_gap_count=gap_count,
        input_checksum_sha256=CHECKSUM,
    )


def _segment(
    *,
    segment_number: int,
    time: tuple[float, ...],
    flux: tuple[float, ...],
    include_flux_err: bool = True,
    flux_err: tuple[float, ...] | None = None,
    quality: tuple[int, ...] | None = None,
    start_position: int = 0,
    source_indices: tuple[int, ...] | None = None,
) -> LightCurveSegment:
    n = len(time)
    if flux_err is None and include_flux_err:
        flux_err = tuple(1.0 for _ in range(n))
    if not include_flux_err:
        flux_err = None
    quality = quality if quality is not None else tuple(0 for _ in range(n))
    source_indices = (
        source_indices
        if source_indices is not None
        else tuple(range(start_position, start_position + n))
    )
    return LightCurveSegment(
        segment_number=segment_number,
        start_position=start_position,
        end_position=start_position + n - 1,
        start_source_index=source_indices[0],
        end_source_index=source_indices[-1],
        time=time,
        flux=flux,
        flux_err=flux_err,
        quality=quality,
        source_indices=source_indices,
    )


def _segmented(
    segments: tuple[LightCurveSegment, ...],
    gaps: tuple[DetectedGap, ...] = (),
) -> SegmentedLightCurve:
    total = sum(segment.cadence_count for segment in segments)
    stats = SegmentationStats(
        total_cadences=total,
        segment_count=len(segments),
        gap_count=len(gaps),
        measured_nominal_cadence=1.0,
        metadata_cadence_seconds=86400.0,
        metadata_cadence_native=1.0,
        cadence_sources_agree=True,
        total_estimated_missing_cadences=0,
    )
    return SegmentedLightCurve(
        segments=segments,
        gaps=gaps,
        stats=stats,
        flux_column="PDCSAP_FLUX",
        provenance=_provenance(),
        metadata=_metadata(),
        history=(_quality_step(total), _gap_step(total, len(segments), len(gaps))),
    )


def _gap(before_position: int, after_position: int) -> DetectedGap:
    return DetectedGap(
        before_position=before_position,
        after_position=after_position,
        before_source_index=before_position,
        after_source_index=after_position,
        time_before=float(before_position),
        time_after=float(after_position),
        actual_interval=float(after_position - before_position),
        nominal_cadence=1.0,
        threshold=5.000001,
        interval_to_cadence_ratio=float(after_position - before_position),
        reasons=(GapReason.OBSERVATION_GAP,),
        skipped_source_rows=0,
        estimated_missing_cadences=None,
    )


# --------------------------------------------------------------------------
# Baseline: ordinary segments, ratio values, independence
# --------------------------------------------------------------------------


def test_ordinary_segment_normalizes_around_one() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(90.0, 100.0, 110.0))
    result = normalize_light_curve(_segmented((segment,)))

    normalized = result.segments[0]
    assert normalized.stats.reference == pytest.approx(100.0)
    assert normalized.stats.reference_valid is True
    assert normalized.stats.reference_issue is None
    assert normalized.normalized_flux == pytest.approx((0.9, 1.0, 1.1))


def test_several_segments_normalize_independently() -> None:
    seg_a = _segment(segment_number=1, time=(0.0, 1.0), flux=(100.0, 100.0))
    seg_b = _segment(segment_number=2, time=(10.0, 11.0), flux=(50.0, 50.0), start_position=2)
    seg_c = _segment(segment_number=3, time=(20.0, 21.0), flux=(200.0, 200.0), start_position=4)
    result = normalize_light_curve(_segmented((seg_a, seg_b, seg_c)))

    assert [s.stats.reference for s in result.segments] == pytest.approx([100.0, 50.0, 200.0])
    assert result.segments[0].normalized_flux == pytest.approx((1.0, 1.0))
    assert result.segments[1].normalized_flux == pytest.approx((1.0, 1.0))
    assert result.segments[2].normalized_flux == pytest.approx((1.0, 1.0))


def test_different_baseline_flux_levels_each_normalize_to_one() -> None:
    """Segments at wildly different absolute flux levels (e.g. different
    pointing/systematics baselines) each land near 1.0 independently."""
    low = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 105.0, 95.0))
    high = _segment(
        segment_number=2, time=(10.0, 11.0, 12.0), flux=(5000.0, 5250.0, 4750.0), start_position=3
    )
    result = normalize_light_curve(_segmented((low, high)))

    for segment in result.segments:
        assert segment.normalized_flux is not None
        assert statistics.median(segment.normalized_flux) == pytest.approx(1.0)


# --------------------------------------------------------------------------
# Leakage: a segment's reference/normalization never depends on another
# --------------------------------------------------------------------------


def test_segment_boundaries_prevent_normalization_leakage() -> None:
    """Changing one segment's flux must not change another segment's
    normalized result, proving the reference is computed independently."""
    seg_a = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 100.0, 100.0))
    seg_b_original = _segment(
        segment_number=2, time=(10.0, 11.0, 12.0), flux=(500.0, 500.0, 500.0), start_position=3
    )
    seg_b_changed = _segment(
        segment_number=2, time=(10.0, 11.0, 12.0), flux=(9999.0, 1.0, 500.0), start_position=3
    )

    baseline = normalize_light_curve(_segmented((seg_a, seg_b_original)))
    changed = normalize_light_curve(_segmented((seg_a, seg_b_changed)))

    assert baseline.segments[0].normalized_flux == changed.segments[0].normalized_flux
    assert baseline.segments[0].stats.reference == changed.segments[0].stats.reference


def test_negative_segment_beside_valid_segment_neither_affects_the_other() -> None:
    valid = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 110.0, 90.0))
    negative = _segment(
        segment_number=2, time=(10.0, 11.0, 12.0), flux=(-100.0, -90.0, -110.0), start_position=3
    )

    result = normalize_light_curve(_segmented((valid, negative)))

    valid_result, negative_result = result.segments
    assert valid_result.stats.reference_valid is True
    assert valid_result.normalized_flux == pytest.approx((100 / 100, 110 / 100, 90 / 100))

    assert negative_result.stats.reference_valid is False
    assert negative_result.stats.reference_issue is ReferenceIssue.NEGATIVE_REFERENCE
    assert negative_result.normalized_flux is None
    assert negative_result.normalized_flux_err is None
    # the valid segment is identical to a run without the negative segment at all
    solo = normalize_light_curve(_segmented((valid,)))
    assert result.segments[0].normalized_flux == solo.segments[0].normalized_flux


# --------------------------------------------------------------------------
# Required revision: negative, zero, and near-zero references
# --------------------------------------------------------------------------


def test_negative_reference_is_never_normalized() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(-100.0, -110.0, -90.0))
    original_flux = segment.flux
    original_flux_err = segment.flux_err

    result = normalize_light_curve(_segmented((segment,)))
    normalized = result.segments[0]

    assert normalized.normalized_flux is None
    assert normalized.normalized_flux_err is None
    assert normalized.stats.reference_issue is ReferenceIssue.NEGATIVE_REFERENCE
    assert normalized.stats.reference_valid is False
    assert normalized.stats.reference == pytest.approx(-100.0)
    # original data fully preserved
    assert normalized.segment.flux == original_flux
    assert normalized.segment.flux_err == original_flux_err
    assert normalized.segment.time == segment.time
    assert normalized.segment.quality == segment.quality
    assert normalized.segment.source_indices == segment.source_indices
    assert normalized.segment.cadence_count == 3


def test_zero_reference_withholds_normalization_but_keeps_all_cadences() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(0.0, 0.0, 0.0))

    result = normalize_light_curve(_segmented((segment,)))
    normalized = result.segments[0]

    assert normalized.normalized_flux is None
    assert normalized.normalized_flux_err is None
    assert normalized.stats.reference_issue is ReferenceIssue.ZERO_REFERENCE
    assert normalized.stats.reference == pytest.approx(0.0)
    assert normalized.segment.cadence_count == 3
    assert normalized.segment.flux == (0.0, 0.0, 0.0)


def test_positive_reference_below_tolerance_is_withheld_deterministically() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(1e-9, 1e-9, 1e-9))
    config = NormalizationConfig(zero_reference_tolerance=1e-6)

    first = normalize_light_curve(_segmented((segment,)), config)
    second = normalize_light_curve(_segmented((segment,)), config)

    assert first.segments[0].stats.reference_issue is ReferenceIssue.ZERO_REFERENCE
    assert first.segments[0].normalized_flux is None
    assert first.model_dump_json() == second.model_dump_json()


def test_positive_reference_above_tolerance_succeeds() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(1e-5, 1e-5, 1e-5))
    config = NormalizationConfig(zero_reference_tolerance=1e-6)

    result = normalize_light_curve(_segmented((segment,)), config)

    assert result.segments[0].stats.reference_valid is True
    assert result.segments[0].stats.reference_issue is None
    assert result.segments[0].normalized_flux == pytest.approx((1.0, 1.0, 1.0))


def test_very_small_positive_reference_is_valid_under_default_zero_tolerance() -> None:
    """Default zero_reference_tolerance is 0.0 -- only exact zero is
    invalid; a tiny but nonzero reference normalizes normally."""
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(1e-300, 1e-300, 1e-300))

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].stats.reference_valid is True
    assert result.segments[0].normalized_flux == pytest.approx((1.0, 1.0, 1.0))


def test_exact_zero_is_zero_reference_regardless_of_tolerance() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0), flux=(0.0, 0.0))

    result = normalize_light_curve(
        _segmented((segment,)), NormalizationConfig(zero_reference_tolerance=0.0)
    )

    assert result.segments[0].stats.reference_issue is ReferenceIssue.ZERO_REFERENCE


# --------------------------------------------------------------------------
# Nonfinite reference (reachable only via floating-point overflow)
# --------------------------------------------------------------------------


def test_nonfinite_reference_via_overflow_is_recorded() -> None:
    """The median of an even-length segment averages its two central
    values; two values near float-max overflow to +inf on summation,
    yielding a nonfinite (but computed, not absent) reference."""
    huge = 1.7e308
    segment = _segment(segment_number=1, time=(0.0, 1.0), flux=(huge, huge))

    result = normalize_light_curve(_segmented((segment,)))
    stats = result.segments[0].stats

    assert stats.reference is not None
    assert math.isinf(stats.reference)
    assert stats.reference_issue is ReferenceIssue.NONFINITE_REFERENCE
    assert result.segments[0].normalized_flux is None


# --------------------------------------------------------------------------
# Mixed finite/nonfinite flux within a segment
# --------------------------------------------------------------------------


def test_reference_computed_from_finite_subset_when_segment_has_nonfinite_flux() -> None:
    segment = _segment(
        segment_number=1, time=(0.0, 1.0, 2.0, 3.0), flux=(100.0, math.nan, 100.0, 100.0)
    )

    result = normalize_light_curve(_segmented((segment,)))
    normalized = result.segments[0]

    assert normalized.stats.finite_flux_count == 3
    assert normalized.stats.reference == pytest.approx(100.0)
    assert normalized.stats.reference_valid is True


def test_nonfinite_cadences_remain_nonfinite_in_normalized_output() -> None:
    """No cadence is silently dropped: the segment still has 4 normalized
    values, and the nonfinite positions stay nonfinite rather than being
    replaced or removed. Reference is the median of the two finite
    values (100.0, 110.0) = 105.0; math.inf is itself nonfinite and is
    excluded from that median the same way math.nan is."""
    segment = _segment(
        segment_number=1, time=(0.0, 1.0, 2.0, 3.0), flux=(100.0, math.nan, 110.0, math.inf)
    )

    result = normalize_light_curve(_segmented((segment,)))
    normalized = result.segments[0]
    normalized_flux = normalized.normalized_flux

    assert normalized.stats.finite_flux_count == 2
    assert normalized.stats.reference == pytest.approx(105.0)
    assert normalized_flux is not None
    assert len(normalized_flux) == 4
    assert normalized_flux[0] == pytest.approx(100.0 / 105.0)
    assert math.isnan(normalized_flux[1])
    assert normalized_flux[2] == pytest.approx(110.0 / 105.0)
    assert math.isinf(normalized_flux[3])
    assert normalized_flux[3] > 0  # +inf / positive reference stays +inf


def test_all_nonfinite_flux_yields_no_finite_flux_issue() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(math.nan, math.inf, -math.inf))

    result = normalize_light_curve(_segmented((segment,)))
    normalized = result.segments[0]

    assert normalized.stats.reference is None
    assert normalized.stats.finite_flux_count == 0
    assert normalized.stats.reference_issue is ReferenceIssue.NO_FINITE_FLUX
    assert normalized.normalized_flux is None
    assert normalized.normalized_flux_err is None
    # original (nonfinite) flux is still fully preserved
    assert math.isnan(normalized.segment.flux[0])
    assert math.isinf(normalized.segment.flux[1])
    assert normalized.segment.cadence_count == 3


# --------------------------------------------------------------------------
# Direction preservation: a downward change stays downward
# --------------------------------------------------------------------------


def test_downward_flux_change_remains_downward_after_normalization() -> None:
    """For every successfully normalized segment, the sign of
    consecutive differences must be preserved -- a positive reference
    can only scale, never invert, the direction of a change."""
    flux = (100.0, 105.0, 95.0, 90.0, 110.0)
    segment = _segment(segment_number=1, time=tuple(float(i) for i in range(5)), flux=flux)

    result = normalize_light_curve(_segmented((segment,)))
    normalized_flux = result.segments[0].normalized_flux
    assert normalized_flux is not None

    for i in range(1, len(flux)):
        raw_direction = flux[i] - flux[i - 1]
        normalized_direction = normalized_flux[i] - normalized_flux[i - 1]
        assert (raw_direction > 0) == (normalized_direction > 0)
        assert (raw_direction < 0) == (normalized_direction < 0)


# --------------------------------------------------------------------------
# Flux-error propagation
# --------------------------------------------------------------------------


def test_flux_error_propagation_divides_by_absolute_reference() -> None:
    segment = _segment(
        segment_number=1,
        time=(0.0, 1.0, 2.0),
        flux=(90.0, 100.0, 110.0),
        flux_err=(5.0, 5.0, 5.0),
    )

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].normalized_flux_err == pytest.approx((0.05, 0.05, 0.05))


def test_flux_err_none_on_input_stays_none_on_output() -> None:
    segment = _segment(
        segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 100.0, 100.0), include_flux_err=False
    )

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].normalized_flux is not None
    assert result.segments[0].normalized_flux_err is None
    assert result.segments[0].segment.flux_err is None


def test_flux_err_stays_none_when_reference_invalid() -> None:
    segment = _segment(
        segment_number=1,
        time=(0.0, 1.0, 2.0),
        flux=(-100.0, -110.0, -90.0),
        flux_err=(5.0, 5.0, 5.0),
    )

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].normalized_flux_err is None


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------


def test_empty_segmented_light_curve_returns_zero_segments() -> None:
    result = normalize_light_curve(_segmented(()))

    assert result.segments == ()
    assert result.stats.total_cadences == 0
    assert result.stats.segment_count == 0
    assert result.stats.normalized_segment_count == 0
    assert result.stats.invalid_segment_count == 0
    assert result.cadence_count == 0


def test_one_cadence_segment_normalizes_to_exactly_one() -> None:
    segment = _segment(segment_number=1, time=(5.0,), flux=(123.45,))

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].normalized_flux == pytest.approx((1.0,))
    assert result.segments[0].stats.reference == pytest.approx(123.45)


def test_one_cadence_segment_with_zero_flux_is_zero_reference() -> None:
    segment = _segment(segment_number=1, time=(5.0,), flux=(0.0,))

    result = normalize_light_curve(_segmented((segment,)))

    assert result.segments[0].stats.reference_issue is ReferenceIssue.ZERO_REFERENCE
    assert result.segments[0].normalized_flux is None


# --------------------------------------------------------------------------
# Preservation: cadence counts, ordering, gaps, history
# --------------------------------------------------------------------------


def test_no_cadence_removed_duplicated_reordered_or_moved_between_segments() -> None:
    seg_a = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 101.0, 99.0))
    seg_b = _segment(segment_number=2, time=(10.0, 11.0), flux=(-5.0, -5.0), start_position=3)
    seg_c = _segment(
        segment_number=3, time=(20.0, 21.0, 22.0), flux=(50.0, 51.0, 49.0), start_position=5
    )
    segmented = _segmented((seg_a, seg_b, seg_c))

    result = normalize_light_curve(segmented)

    assert [s.segment.segment_number for s in result.segments] == [1, 2, 3]
    assert result.stats.segment_count == 3
    assert result.stats.total_cadences == segmented.cadence_count == 8
    assert result.cadence_count == 8
    for original, normalized in zip(segmented.segments, result.segments, strict=True):
        assert normalized.segment.time == original.time
        assert normalized.segment.flux == original.flux
        assert normalized.segment.quality == original.quality
        assert normalized.segment.source_indices == original.source_indices


def test_gap_records_and_earlier_history_are_unchanged() -> None:
    seg_a = _segment(segment_number=1, time=(0.0, 1.0), flux=(100.0, 100.0))
    seg_b = _segment(segment_number=2, time=(20.0, 21.0), flux=(200.0, 200.0), start_position=2)
    gaps = (_gap(1, 2),)
    segmented = _segmented((seg_a, seg_b), gaps=gaps)

    result = normalize_light_curve(segmented)

    assert result.gaps == segmented.gaps == gaps
    assert result.history[:2] == segmented.history
    assert len(result.history) == len(segmented.history) + 1
    step = result.history[-1]
    assert isinstance(step, NormalizationStep)
    assert step.step == "flux_normalization"
    assert step.input_cadences == 4
    assert step.input_segment_count == 2
    assert step.normalized_segment_count == 2
    assert step.input_checksum_sha256 == CHECKSUM


def test_normalization_step_has_no_timestamp_field() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0), flux=(100.0, 100.0))
    step = normalize_light_curve(_segmented((segment,))).history[-1]

    assert not any("time" in name or "date" in name for name in type(step).model_fields)


def test_invalid_by_issue_sums_to_invalid_segment_count() -> None:
    valid = _segment(segment_number=1, time=(0.0, 1.0), flux=(100.0, 100.0))
    zero = _segment(segment_number=2, time=(10.0, 11.0), flux=(0.0, 0.0), start_position=2)
    negative = _segment(segment_number=3, time=(20.0, 21.0), flux=(-10.0, -10.0), start_position=4)

    result = normalize_light_curve(_segmented((valid, zero, negative)))

    assert result.stats.normalized_segment_count == 1
    assert result.stats.invalid_segment_count == 2
    assert sum(result.stats.invalid_by_issue.values()) == 2
    assert result.stats.invalid_by_issue[ReferenceIssue.ZERO_REFERENCE] == 1
    assert result.stats.invalid_by_issue[ReferenceIssue.NEGATIVE_REFERENCE] == 1


# --------------------------------------------------------------------------
# Immutability and determinism
# --------------------------------------------------------------------------


def test_segmented_light_curve_is_not_mutated() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(90.0, 100.0, 110.0))
    segmented = _segmented((segment,))
    before = segmented.model_dump()

    normalize_light_curve(segmented)

    assert segmented.model_dump() == before


def test_normalized_light_curve_is_frozen() -> None:
    segment = _segment(segment_number=1, time=(0.0, 1.0), flux=(100.0, 100.0))
    result = normalize_light_curve(_segmented((segment,)))

    with pytest.raises(Exception, match="frozen"):
        result.segments = ()  # type: ignore[misc]


def test_repeated_runs_produce_byte_identical_results() -> None:
    seg_a = _segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(90.0, 100.0, 110.0))
    seg_b = _segment(segment_number=2, time=(20.0, 21.0), flux=(-5.0, -5.0), start_position=3)
    segmented = _segmented((seg_a, seg_b))

    first = normalize_light_curve(segmented)
    second = normalize_light_curve(segmented)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


# --------------------------------------------------------------------------
# Config validation and structural validation
# --------------------------------------------------------------------------


def test_negative_zero_reference_tolerance_raises() -> None:
    with pytest.raises(InvalidNormalizationConfigError, match="must be >= 0"):
        NormalizationConfig(zero_reference_tolerance=-1.0)


def test_mismatched_segment_column_lengths_raise() -> None:
    bad_segment = LightCurveSegment(
        segment_number=1,
        start_position=0,
        end_position=2,
        start_source_index=0,
        end_source_index=2,
        time=(0.0, 1.0, 2.0),
        flux=(100.0, 100.0),
        flux_err=None,
        quality=(0, 0, 0),
        source_indices=(0, 1, 2),
    )

    with pytest.raises(InvalidLightCurveError, match="mismatched lengths"):
        normalize_light_curve(_segmented((bad_segment,)))
