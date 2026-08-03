"""Tests for robust per-segment statistical outlier flagging (Phase 3D).

Segments are built directly as ``NormalizedSegment``/``NormalizedLightCurve``
objects, the same way ``test_normalization.py`` builds ``LightCurveSegment``/
``SegmentedLightCurve`` objects: it keeps the suite fast and is the only way
to reach structurally-invalid or defensively-handled states (like a nonfinite
``normalized_flux``) that upstream stages don't normally produce.
"""

import math
import statistics

import pytest

from app.data.exceptions import InvalidLightCurveError, InvalidOutlierDetectionConfigError
from app.data.models import (
    DetectedGap,
    FileProvenance,
    FitsMetadata,
    GapDetectionConfig,
    GapDetectionStep,
    GapReason,
    LightCurveSegment,
    NormalizationConfig,
    NormalizationStats,
    NormalizationStep,
    NormalizedLightCurve,
    NormalizedSegment,
    OutlierAnalysisStatus,
    OutlierDetectionConfig,
    OutlierDetectionStep,
    OutlierDirection,
    OutlierReason,
    ProcessingStep,
    QualityFilterConfig,
    ReferenceIssue,
    SegmentNormalizationStats,
)
from app.data.outlier_detection import flag_outliers
from app.data.quality_flags import QualityPolicy

CHECKSUM = "a" * 64
# Nine values with ordinary jitter around 1.0 -- unlike a constant
# background, this keeps MAD (and thus robust_scale) nonzero once a
# tenth, wildly different value is appended, so appending a spike
# actually reaches OutlierAnalysisStatus.VALID instead of ZERO_SCALE.
_JITTER = (0.98, 0.99, 1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06)


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
        object_name="TIC 261136679", time_system="TDB", cadence_seconds=86400.0, header={}
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


def _normalization_step(n: int, segment_count: int, normalized_count: int) -> NormalizationStep:
    return NormalizationStep(
        step="flux_normalization",
        code_version="0.1.0",
        config=NormalizationConfig(),
        input_cadences=n,
        input_segment_count=segment_count,
        normalized_segment_count=normalized_count,
        input_checksum_sha256=CHECKSUM,
    )


def _lc_segment(
    *,
    segment_number: int,
    time: tuple[float, ...],
    flux: tuple[float, ...],
    start_position: int = 0,
    source_indices: tuple[int, ...] | None = None,
) -> LightCurveSegment:
    n = len(time)
    flux_err = tuple(1.0 for _ in range(n))
    quality = tuple(0 for _ in range(n))
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


def _normalized_segment(
    *,
    segment_number: int,
    normalized_flux: tuple[float, ...] | None,
    time: tuple[float, ...] | None = None,
    start_position: int = 0,
    source_indices: tuple[int, ...] | None = None,
    reference_valid: bool = True,
    reference_issue: ReferenceIssue | None = None,
) -> NormalizedSegment:
    """Build a ``NormalizedSegment`` directly from a ``normalized_flux``
    tuple, since Phase 3D only ever reads that array (and TIME/segment
    metadata) -- the underlying raw flux is irrelevant here."""
    n = len(normalized_flux) if normalized_flux is not None else 0
    time = time if time is not None else tuple(float(i) for i in range(n))
    segment = _lc_segment(
        segment_number=segment_number,
        time=time,
        flux=tuple(100.0 for _ in range(n)),
        start_position=start_position,
        source_indices=source_indices,
    )
    stats = SegmentNormalizationStats(
        reference=100.0 if reference_valid else None,
        finite_flux_count=n,
        reference_valid=reference_valid,
        reference_issue=reference_issue,
    )
    return NormalizedSegment(
        segment=segment,
        normalized_flux=normalized_flux,
        normalized_flux_err=None,
        stats=stats,
    )


def _normalized(
    segments: tuple[NormalizedSegment, ...], gaps: tuple[DetectedGap, ...] = ()
) -> NormalizedLightCurve:
    total = sum(entry.segment.cadence_count for entry in segments)
    normalized_count = sum(1 for entry in segments if entry.normalized_flux is not None)
    n_stats = NormalizationStats(
        total_cadences=total,
        segment_count=len(segments),
        normalized_segment_count=normalized_count,
        invalid_segment_count=len(segments) - normalized_count,
        invalid_by_issue={},
    )
    return NormalizedLightCurve(
        segments=segments,
        gaps=gaps,
        stats=n_stats,
        flux_column="PDCSAP_FLUX",
        provenance=_provenance(),
        metadata=_metadata(),
        history=(
            _quality_step(total),
            _gap_step(total, len(segments), len(gaps)),
            _normalization_step(total, len(segments), normalized_count),
        ),
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
# Baseline: robust statistics on an ordinary segment
# --------------------------------------------------------------------------


def test_ordinary_segment_computes_expected_center_mad_and_scale() -> None:
    values = (0.98, 0.99, 1.0, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    stats = result.segments[0].stats

    expected_center = statistics.median(values)
    expected_mad = statistics.median(abs(v - expected_center) for v in values)
    assert stats.status is OutlierAnalysisStatus.VALID
    assert stats.center == pytest.approx(expected_center)
    assert stats.raw_mad == pytest.approx(expected_mad)
    assert stats.robust_scale == pytest.approx(1.4826 * expected_mad)
    assert stats.finite_values_analyzed == 10


def test_no_outliers_when_all_values_within_threshold() -> None:
    values = tuple(1.0 + 0.001 * i for i in range(10))
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.high_outlier_count == 0
    assert entry.stats.low_outlier_count == 0
    assert entry.outlier_mask == (False,) * 10
    assert entry.flagged_cadences == ()


def test_positive_spike_is_flagged_as_high_outlier_by_default() -> None:
    values = (*_JITTER, 50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.VALID
    assert entry.stats.high_outlier_count == 1
    assert entry.high_outlier_mask[9] is True
    assert entry.outlier_mask[9] is True
    assert all(not flag for flag in entry.high_outlier_mask[:9])
    record = entry.flagged_cadences[0]
    assert record.reason is OutlierReason.HIGH_STATISTICAL_OUTLIER
    assert record.direction is OutlierDirection.HIGH
    assert record.position_in_segment == 9
    assert record.threshold == pytest.approx(5.0)
    assert record.robust_score is not None
    assert record.robust_score > 5.0


# --------------------------------------------------------------------------
# Lower-side detection: disabled by default, transit-safety guarantee
# --------------------------------------------------------------------------


def test_downward_dip_never_flagged_when_lower_detection_disabled() -> None:
    """A transit-like downward dip must never be flagged as a low outlier
    while lower-side detection is off (the default)."""
    values = (*_JITTER, -50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.VALID
    assert entry.stats.low_outlier_count == 0
    assert entry.low_outlier_mask is None
    assert entry.outlier_mask[9] is False
    assert all(
        record.reason is not OutlierReason.LOW_STATISTICAL_OUTLIER
        for record in entry.flagged_cadences
    )


def test_lower_threshold_none_is_the_default_config() -> None:
    assert OutlierDetectionConfig().lower_threshold is None


def test_low_outlier_flagged_only_when_explicitly_enabled() -> None:
    values = (*_JITTER, -50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(lower_threshold=5.0)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]

    assert entry.stats.low_outlier_count == 1
    assert entry.low_outlier_mask is not None
    assert entry.low_outlier_mask[9] is True
    assert entry.outlier_mask[9] is True
    record = next(
        r for r in entry.flagged_cadences if r.reason is OutlierReason.LOW_STATISTICAL_OUTLIER
    )
    assert record.direction is OutlierDirection.LOW
    assert record.threshold == pytest.approx(5.0)
    assert record.robust_score is not None
    assert record.robust_score < -5.0


# --------------------------------------------------------------------------
# Direction preservation
# --------------------------------------------------------------------------


def test_value_below_center_never_classified_as_high_outlier() -> None:
    values = (*_JITTER, -50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(lower_threshold=5.0)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.VALID
    assert entry.high_outlier_mask[9] is False
    center = entry.stats.center
    assert center is not None
    for i, value in enumerate(values):
        if value < center:
            assert entry.high_outlier_mask[i] is False


def test_value_above_center_never_classified_as_low_outlier() -> None:
    values = (*_JITTER, 50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(lower_threshold=5.0)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]
    assert entry.stats.status is OutlierAnalysisStatus.VALID
    assert entry.low_outlier_mask is not None

    center = entry.stats.center
    assert center is not None
    for i, value in enumerate(values):
        if value > center:
            assert entry.low_outlier_mask[i] is False


# --------------------------------------------------------------------------
# Threshold comparison: strict, not inclusive
# --------------------------------------------------------------------------


def test_score_at_or_just_below_upper_threshold_is_not_an_outlier() -> None:
    """(0.0, 0.0, 1.0, 1.0, x) has center=1.0 and MAD=1.0 exactly for any
    x >= 2.0 -- the median's breakdown point means adding one point past
    the other four never moves either statistic. That makes
    ``score = (x - 1.0) / 1.4826`` solvable in closed form, so the
    boundary can be tested without float round-trip risk in the
    center/MAD computation itself."""
    center, mad = 1.0, 1.0
    robust_scale = 1.4826 * mad
    just_below = center + robust_scale * 4.999999
    segment = _normalized_segment(
        segment_number=1, normalized_flux=(0.0, 0.0, 1.0, 1.0, just_below)
    )

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.center == pytest.approx(1.0)
    assert entry.stats.robust_scale == pytest.approx(robust_scale)
    assert entry.high_outlier_mask[-1] is False
    assert entry.outlier_mask[-1] is False


def test_score_just_above_upper_threshold_is_an_outlier() -> None:
    center, mad = 1.0, 1.0
    robust_scale = 1.4826 * mad
    just_above = center + robust_scale * 5.000001
    segment = _normalized_segment(
        segment_number=1, normalized_flux=(0.0, 0.0, 1.0, 1.0, just_above)
    )

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.center == pytest.approx(1.0)
    assert entry.high_outlier_mask[-1] is True
    assert entry.outlier_mask[-1] is True


# --------------------------------------------------------------------------
# Segment analysis statuses
# --------------------------------------------------------------------------


def test_insufficient_data_for_short_segment_preserves_cadences() -> None:
    values = (1.0, 2.0, 3.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.INSUFFICIENT_DATA
    assert entry.outlier_mask == (False, False, False)
    assert entry.high_outlier_mask == (False, False, False)
    assert entry.normalized.segment.cadence_count == 3
    assert entry.normalized.normalized_flux == values


def test_one_cadence_segment_is_insufficient_data_not_an_error() -> None:
    segment = _normalized_segment(segment_number=1, normalized_flux=(1.0,))

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.INSUFFICIENT_DATA
    assert entry.outlier_mask == (False,)


def test_minimum_finite_cadences_is_configurable() -> None:
    values = (1.0, 2.0, 3.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(minimum_finite_cadences=3)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.VALID


def test_constant_segment_is_zero_scale_not_an_error() -> None:
    values = (5.0,) * 10
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.ZERO_SCALE
    assert entry.stats.center == pytest.approx(5.0)
    assert entry.stats.raw_mad == pytest.approx(0.0)
    assert entry.stats.robust_scale == pytest.approx(0.0)
    assert entry.outlier_mask == (False,) * 10
    assert entry.normalized.segment.cadence_count == 10


def test_near_zero_scale_is_zero_scale_when_minimum_configured() -> None:
    values = (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0 + 1e-10)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(minimum_robust_scale=1e-6)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.ZERO_SCALE


def test_normalization_unavailable_segment_is_preserved() -> None:
    segment = _normalized_segment(
        segment_number=1,
        normalized_flux=None,
        time=(0.0, 1.0, 2.0),
        reference_valid=False,
        reference_issue=ReferenceIssue.NEGATIVE_REFERENCE,
    )

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.NORMALIZATION_UNAVAILABLE
    assert entry.outlier_mask == (False, False, False)
    assert entry.high_outlier_mask == (False, False, False)
    assert entry.flagged_cadences == ()
    assert entry.stats.finite_values_analyzed == 0
    assert entry.stats.center is None
    assert entry.normalized.stats.reference_issue is ReferenceIssue.NEGATIVE_REFERENCE
    assert entry.normalized.segment.cadence_count == 3


# --------------------------------------------------------------------------
# Nonfinite normalized positions
# --------------------------------------------------------------------------


def test_nonfinite_value_is_never_a_statistical_outlier() -> None:
    values = (1.0, 1.01, 0.99, 1.02, 0.98, 1.0, 1.01, 0.99, math.nan, 1.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert entry.stats.status is OutlierAnalysisStatus.VALID
    assert entry.stats.finite_values_analyzed == 9
    assert entry.high_outlier_mask[8] is False
    assert entry.outlier_mask[8] is False
    record = next(r for r in entry.flagged_cadences if r.position_in_segment == 8)
    assert record.reason is OutlierReason.NONFINITE_NORMALIZED_FLUX
    assert record.robust_score is None
    assert record.direction is None
    assert record.threshold is None
    assert math.isnan(record.normalized_flux)


def test_nonfinite_flagging_can_be_disabled() -> None:
    values = (1.0, 1.01, 0.99, 1.02, 0.98, 1.0, 1.01, 0.99, math.inf, 1.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)
    config = OutlierDetectionConfig(flag_nonfinite_normalized_flux=False)

    result = flag_outliers(_normalized((segment,)), config)
    entry = result.segments[0]

    assert entry.stats.nonfinite_flagged_count == 0
    assert all(
        record.reason is not OutlierReason.NONFINITE_NORMALIZED_FLUX
        for record in entry.flagged_cadences
    )
    # still excluded from analysis and never mislabeled
    assert entry.stats.finite_values_analyzed == 9
    assert entry.outlier_mask[8] is False


def test_nonfinite_positions_never_omitted_from_masks() -> None:
    values = (math.nan, math.inf, -math.inf, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]

    assert len(entry.outlier_mask) == 10
    assert len(entry.high_outlier_mask) == 10
    assert entry.stats.nonfinite_flagged_count == 3
    assert entry.stats.finite_values_analyzed == 7


# --------------------------------------------------------------------------
# Preservation and invariants
# --------------------------------------------------------------------------


def test_no_cadence_removed_duplicated_reordered_or_moved_between_segments() -> None:
    seg_a = _normalized_segment(segment_number=1, normalized_flux=(1.0, 1.01, 0.99))
    seg_b = _normalized_segment(segment_number=2, normalized_flux=(1.0, 1.0), start_position=3)
    seg_c = _normalized_segment(
        segment_number=3, normalized_flux=(1.0, 1.02, 0.98), start_position=5
    )
    normalized = _normalized((seg_a, seg_b, seg_c))

    result = flag_outliers(normalized)

    assert [entry.normalized.segment.segment_number for entry in result.segments] == [1, 2, 3]
    assert result.stats.segment_count == 3
    assert result.stats.total_cadences == normalized.cadence_count == 8
    assert result.cadence_count == 8
    for original, entry in zip(normalized.segments, result.segments, strict=True):
        assert entry.normalized.segment.time == original.segment.time
        assert entry.normalized.segment.flux == original.segment.flux
        assert entry.normalized.normalized_flux == original.normalized_flux
        assert entry.normalized.segment.source_indices == original.segment.source_indices
        assert len(entry.outlier_mask) == entry.normalized.segment.cadence_count


def test_every_true_outlier_mask_position_has_a_detailed_record() -> None:
    values = (*_JITTER, 50.0)
    segment = _normalized_segment(segment_number=1, normalized_flux=values)

    result = flag_outliers(_normalized((segment,)))
    entry = result.segments[0]
    assert entry.stats.status is OutlierAnalysisStatus.VALID

    flagged_positions = {
        r.position_in_segment
        for r in entry.flagged_cadences
        if r.reason is OutlierReason.HIGH_STATISTICAL_OUTLIER
        or r.reason is OutlierReason.LOW_STATISTICAL_OUTLIER
    }
    mask_true_positions = {i for i, flagged in enumerate(entry.outlier_mask) if flagged}
    assert flagged_positions == mask_true_positions


def test_source_indices_and_filtered_positions_round_trip() -> None:
    values = (*_JITTER, 50.0)
    segment = _normalized_segment(
        segment_number=2,
        normalized_flux=values,
        start_position=7,
        source_indices=tuple(range(107, 117)),
    )

    result = flag_outliers(_normalized((segment,)))
    record = result.segments[0].flagged_cadences[0]

    assert record.segment_number == 2
    assert record.position_in_segment == 9
    assert record.filtered_position == 7 + 9
    assert record.source_index == 116


def test_gap_records_and_earlier_history_are_unchanged() -> None:
    seg_a = _normalized_segment(segment_number=1, normalized_flux=(1.0, 1.0))
    seg_b = _normalized_segment(segment_number=2, normalized_flux=(1.0, 1.0), start_position=2)
    gaps = (_gap(1, 2),)
    normalized = _normalized((seg_a, seg_b), gaps=gaps)

    result = flag_outliers(normalized)

    assert result.gaps == normalized.gaps == gaps
    assert result.history[:3] == normalized.history
    assert len(result.history) == len(normalized.history) + 1
    step = result.history[-1]
    assert isinstance(step, OutlierDetectionStep)
    assert step.step == "outlier_flagging"
    assert step.input_cadences == 4
    assert step.input_segment_count == 2
    assert step.input_checksum_sha256 == CHECKSUM


def test_outlier_detection_step_has_no_timestamp_field() -> None:
    segment = _normalized_segment(segment_number=1, normalized_flux=(1.0, 1.0, 1.0, 1.0, 1.0))
    step = flag_outliers(_normalized((segment,))).history[-1]

    assert not any("time" in name or "date" in name for name in type(step).model_fields)


def test_unanalyzed_by_status_sums_to_unanalyzed_segment_count() -> None:
    valid = _normalized_segment(
        segment_number=1, normalized_flux=tuple(1.0 + 0.01 * i for i in range(10))
    )
    insufficient = _normalized_segment(
        segment_number=2, normalized_flux=(1.0, 2.0), start_position=10
    )
    zero_scale = _normalized_segment(
        segment_number=3, normalized_flux=(5.0,) * 6, start_position=12
    )
    unavailable = _normalized_segment(
        segment_number=4,
        normalized_flux=None,
        time=(0.0,),
        start_position=18,
        reference_valid=False,
        reference_issue=ReferenceIssue.ZERO_REFERENCE,
    )

    result = flag_outliers(_normalized((valid, insufficient, zero_scale, unavailable)))

    assert result.stats.analyzed_segment_count == 1
    assert sum(result.stats.unanalyzed_by_status.values()) == 3
    assert result.stats.unanalyzed_by_status[OutlierAnalysisStatus.INSUFFICIENT_DATA] == 1
    assert result.stats.unanalyzed_by_status[OutlierAnalysisStatus.ZERO_SCALE] == 1
    assert result.stats.unanalyzed_by_status[OutlierAnalysisStatus.NORMALIZATION_UNAVAILABLE] == 1
    assert OutlierAnalysisStatus.VALID not in result.stats.unanalyzed_by_status


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------


def test_empty_normalized_light_curve_returns_zero_segments() -> None:
    result = flag_outliers(_normalized(()))

    assert result.segments == ()
    assert result.stats.total_cadences == 0
    assert result.stats.segment_count == 0
    assert result.cadence_count == 0


# --------------------------------------------------------------------------
# Immutability and determinism
# --------------------------------------------------------------------------


def test_normalized_light_curve_is_not_mutated() -> None:
    segment = _normalized_segment(segment_number=1, normalized_flux=(1.0,) * 9 + (50.0,))
    normalized = _normalized((segment,))
    before = normalized.model_dump()

    flag_outliers(normalized)

    assert normalized.model_dump() == before


def test_outlier_flagged_light_curve_is_frozen() -> None:
    segment = _normalized_segment(segment_number=1, normalized_flux=(1.0, 1.0))
    result = flag_outliers(_normalized((segment,)))

    with pytest.raises(Exception, match="frozen"):
        result.segments = ()  # type: ignore[misc]


def test_repeated_runs_produce_byte_identical_results() -> None:
    seg_a = _normalized_segment(segment_number=1, normalized_flux=(1.0,) * 9 + (50.0,))
    seg_b = _normalized_segment(segment_number=2, normalized_flux=(1.0, 2.0), start_position=10)
    normalized = _normalized((seg_a, seg_b))

    first = flag_outliers(normalized)
    second = flag_outliers(normalized)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


# --------------------------------------------------------------------------
# Config validation and structural validation
# --------------------------------------------------------------------------


def test_nonpositive_upper_threshold_raises() -> None:
    with pytest.raises(InvalidOutlierDetectionConfigError, match="upper_threshold"):
        OutlierDetectionConfig(upper_threshold=0.0)


def test_nonpositive_lower_threshold_raises_when_enabled() -> None:
    with pytest.raises(InvalidOutlierDetectionConfigError, match="lower_threshold"):
        OutlierDetectionConfig(lower_threshold=-1.0)


def test_nonpositive_minimum_finite_cadences_raises() -> None:
    with pytest.raises(InvalidOutlierDetectionConfigError, match="minimum_finite_cadences"):
        OutlierDetectionConfig(minimum_finite_cadences=0)


def test_negative_minimum_robust_scale_raises() -> None:
    with pytest.raises(InvalidOutlierDetectionConfigError, match="minimum_robust_scale"):
        OutlierDetectionConfig(minimum_robust_scale=-1.0)


def test_mismatched_normalized_flux_length_raises() -> None:
    segment = _lc_segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 100.0, 100.0))
    bad_entry = NormalizedSegment(
        segment=segment,
        normalized_flux=(1.0, 1.0),
        normalized_flux_err=None,
        stats=SegmentNormalizationStats(
            reference=100.0, finite_flux_count=3, reference_valid=True, reference_issue=None
        ),
    )

    with pytest.raises(InvalidLightCurveError, match="normalized_flux"):
        flag_outliers(_normalized((bad_entry,)))


def test_mismatched_normalized_flux_err_length_raises() -> None:
    segment = _lc_segment(segment_number=1, time=(0.0, 1.0, 2.0), flux=(100.0, 100.0, 100.0))
    bad_entry = NormalizedSegment(
        segment=segment,
        normalized_flux=(1.0, 1.0, 1.0),
        normalized_flux_err=(0.1, 0.1),
        stats=SegmentNormalizationStats(
            reference=100.0, finite_flux_count=3, reference_valid=True, reference_issue=None
        ),
    )

    with pytest.raises(InvalidLightCurveError, match="normalized_flux_err"):
        flag_outliers(_normalized((bad_entry,)))
