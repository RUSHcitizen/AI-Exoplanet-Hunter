"""Tests for gap detection and contiguous light-curve segmentation
(Phase 3B).

Light curves are built directly as ``FilteredLightCurve`` objects, the
same way ``test_quality_filter.py`` builds ``RawLightCurve`` objects: it
keeps the suite fast and is the only way to reach structurally-invalid
states that ``FilteredLightCurve`` itself does not cross-validate.
"""

import math

import pytest

from app.data.exceptions import (
    InvalidGapDetectionConfigError,
    InvalidLightCurveError,
    NonFiniteTimeError,
    NonMonotonicTimeError,
)
from app.data.gap_segmentation import _build_segments_and_gaps, segment_light_curve
from app.data.models import (
    FileProvenance,
    FilteredLightCurve,
    FitsMetadata,
    GapDetectionConfig,
    GapDetectionStep,
    GapReason,
    ProcessingStep,
    QualityFilterConfig,
    QualityFilterStats,
)
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


def _metadata(cadence_seconds: float | None) -> FitsMetadata:
    return FitsMetadata(
        object_name="TIC 261136679",
        time_system="TDB",
        cadence_seconds=cadence_seconds,
        header={},
    )


def _stats(n: int) -> QualityFilterStats:
    return QualityFilterStats(
        total_cadences=n,
        retained_cadences=n,
        rejected_cadences=0,
        rejected_by_reason={},
        rejected_by_quality_bit={},
    )


def _step(n: int) -> ProcessingStep:
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


def _filtered(
    *,
    time: tuple[float, ...],
    flux: tuple[float, ...] | None = None,
    quality: tuple[int, ...] | None = None,
    source_indices: tuple[int, ...] | None = None,
    include_flux_err: bool = True,
    metadata_cadence_seconds: float | None = 86400.0,
) -> FilteredLightCurve:
    """A minimal ``FilteredLightCurve`` with a nominal cadence of one day
    (``metadata_cadence_seconds=86400.0``) unless overridden, and
    source-index-adjacent retained cadences unless overridden."""
    n = len(time)
    flux = flux if flux is not None else tuple(100.0 for _ in range(n))
    flux_err = tuple(1.0 for _ in range(n)) if include_flux_err else None
    quality = quality if quality is not None else tuple(0 for _ in range(n))
    source_indices = source_indices if source_indices is not None else tuple(range(n))

    return FilteredLightCurve(
        time=time,
        flux=flux,
        flux_err=flux_err,
        quality=quality,
        source_indices=source_indices,
        flux_column="PDCSAP_FLUX",
        provenance=_provenance(),
        metadata=_metadata(metadata_cadence_seconds),
        stats=_stats(n),
        rejected=(),
        history=(_step(n),),
    )


# --------------------------------------------------------------------------
# Baseline / no gaps
# --------------------------------------------------------------------------


def test_no_gaps_returns_one_segment() -> None:
    time = tuple(float(i) for i in range(5))

    result = segment_light_curve(_filtered(time=time))

    assert result.gaps == ()
    assert len(result.segments) == 1
    assert result.stats.segment_count == 1
    assert result.stats.gap_count == 0
    assert result.stats.total_cadences == 5
    seg = result.segments[0]
    assert seg.segment_number == 1
    assert seg.start_position == 0
    assert seg.end_position == 4
    assert seg.start_source_index == 0
    assert seg.end_source_index == 4
    assert seg.time == time
    assert seg.cadence_count == 5
    assert result.cadence_count == 5


def test_nominal_cadence_is_median_of_consecutive_diffs() -> None:
    result = segment_light_curve(_filtered(time=(0.0, 1.0, 2.0, 3.0)))

    assert result.stats.measured_nominal_cadence == pytest.approx(1.0)


def test_config_defaults() -> None:
    config = GapDetectionConfig()

    assert config.gap_multiplier == 5.0
    assert config.gap_tolerance == 1e-6
    assert config.cadence_disagreement_fraction == 0.01
    assert config.missing_cadence_residual_tolerance == 0.25


# --------------------------------------------------------------------------
# Gap detection and origin classification
# --------------------------------------------------------------------------


def test_gap_with_no_skipped_source_rows_is_observation_gap() -> None:
    time = (0.0, 1.0, 2.0, 12.0, 13.0)

    result = segment_light_curve(_filtered(time=time))

    assert result.stats.gap_count == 1
    assert len(result.segments) == 2
    gap = result.gaps[0]
    assert gap.before_position == 2
    assert gap.after_position == 3
    assert gap.before_source_index == 2
    assert gap.after_source_index == 3
    assert gap.skipped_source_rows == 0
    assert gap.reasons == (GapReason.OBSERVATION_GAP,)
    assert gap.actual_interval == pytest.approx(10.0)
    assert gap.nominal_cadence == pytest.approx(1.0)
    assert gap.interval_to_cadence_ratio == pytest.approx(10.0)
    assert result.segments[0].time == (0.0, 1.0, 2.0)
    assert result.segments[1].time == (12.0, 13.0)


def test_gap_with_skipped_rows_matching_expected_interval_is_rejection_only() -> None:
    """7 days elapse across a 6-row rejection gap at a 1-day cadence:
    exactly what the skipped rows alone would explain."""
    time = (0.0, 1.0, 2.0, 3.0, 10.0, 11.0)
    source_indices = (0, 1, 2, 3, 10, 11)

    result = segment_light_curve(_filtered(time=time, source_indices=source_indices))

    gap = result.gaps[0]
    assert gap.skipped_source_rows == 6
    assert gap.reasons == (GapReason.SOURCE_ROWS_REJECTED,)
    assert gap.actual_interval == pytest.approx(7.0)


def test_gap_with_skipped_rows_and_excess_interval_carries_both_reasons() -> None:
    """A 2-row rejection gap would only explain 3 days; the actual 20-day
    interval means an additional real interruption also occurred."""
    time = (0.0, 1.0, 2.0, 3.0, 23.0, 24.0)
    source_indices = (0, 1, 2, 3, 6, 7)

    result = segment_light_curve(_filtered(time=time, source_indices=source_indices))

    gap = result.gaps[0]
    assert gap.skipped_source_rows == 2
    assert gap.reasons == (GapReason.SOURCE_ROWS_REJECTED, GapReason.OBSERVATION_GAP)
    assert gap.actual_interval == pytest.approx(20.0)


def test_before_and_after_source_indices_are_preserved_on_the_gap() -> None:
    time = (0.0, 1.0, 2.0, 3.0, 23.0, 24.0)
    source_indices = (0, 1, 2, 3, 6, 7)

    result = segment_light_curve(_filtered(time=time, source_indices=source_indices))

    gap = result.gaps[0]
    assert gap.before_source_index == 3
    assert gap.after_source_index == 6


# --------------------------------------------------------------------------
# Missing-cadence estimation
# --------------------------------------------------------------------------


def test_missing_cadences_estimated_when_interval_is_close_to_integer_multiple() -> None:
    time = (0.0, 1.0, 2.0, 3.0, 4.0, 10.0)

    result = segment_light_curve(_filtered(time=time))

    gap = result.gaps[0]
    assert gap.estimated_missing_cadences == 5
    assert result.stats.total_estimated_missing_cadences == 5


def test_missing_cadences_not_estimated_when_interval_is_not_close_to_integer_multiple() -> None:
    time = (0.0, 1.0, 2.0, 3.0, 4.0, 10.4)

    result = segment_light_curve(_filtered(time=time))

    gap = result.gaps[0]
    assert gap.estimated_missing_cadences is None
    assert result.stats.total_estimated_missing_cadences == 0


def test_single_missing_cadence_estimated() -> None:
    """A gap of exactly two cadences implies one missing cadence in
    between, distinct from the multi-cadence case above. The default
    gap_multiplier (5.0) cannot flag a 2-cadence-wide interval as a gap
    at all -- a smaller multiplier is required to isolate this case."""
    time = (0.0, 1.0, 2.0, 3.0, 4.0, 6.0)
    config = GapDetectionConfig(gap_multiplier=1.5, gap_tolerance=0.0)

    result = segment_light_curve(_filtered(time=time), config)

    gap = result.gaps[0]
    assert gap.estimated_missing_cadences == 1
    assert result.stats.total_estimated_missing_cadences == 1


# --------------------------------------------------------------------------
# Configurable multiplier / tolerance
# --------------------------------------------------------------------------


def test_smaller_gap_multiplier_detects_smaller_relative_gaps() -> None:
    time = (0.0, 1.0, 2.0, 3.0, 4.0, 6.5)

    default_result = segment_light_curve(_filtered(time=time))
    assert default_result.stats.gap_count == 0

    lenient_result = segment_light_curve(
        _filtered(time=time), GapDetectionConfig(gap_multiplier=2.0)
    )
    assert lenient_result.stats.gap_count == 1


def test_gap_tolerance_absorbs_jitter_right_at_the_threshold_boundary() -> None:
    below = _filtered(time=(0.0, 1.0, 2.0, 3.0, 4.0, 9.0000005))
    above = _filtered(time=(0.0, 1.0, 2.0, 3.0, 4.0, 9.0000015))

    assert segment_light_curve(below).stats.gap_count == 0
    assert segment_light_curve(above).stats.gap_count == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"gap_multiplier": 1.0},
        {"gap_multiplier": 0.5},
        {"gap_tolerance": -1.0},
        {"cadence_disagreement_fraction": 0.0},
        {"cadence_disagreement_fraction": 1.0},
        {"missing_cadence_residual_tolerance": 0.0},
        {"missing_cadence_residual_tolerance": 0.5},
    ],
)
def test_invalid_config_raises(kwargs: dict[str, float]) -> None:
    with pytest.raises(InvalidGapDetectionConfigError):
        GapDetectionConfig(**kwargs)


# --------------------------------------------------------------------------
# Duplicate / decreasing / nonfinite TIME
# --------------------------------------------------------------------------


def test_duplicate_consecutive_time_raises() -> None:
    with pytest.raises(NonMonotonicTimeError, match="Duplicate consecutive TIME"):
        segment_light_curve(_filtered(time=(0.0, 1.0, 1.0, 2.0)))


def test_decreasing_time_raises() -> None:
    with pytest.raises(NonMonotonicTimeError, match="TIME decreases"):
        segment_light_curve(_filtered(time=(0.0, 2.0, 1.0, 3.0)))


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_time_raises(bad: float) -> None:
    with pytest.raises(NonFiniteTimeError):
        segment_light_curve(_filtered(time=(0.0, bad, 2.0)))


def test_mismatched_column_lengths_raise() -> None:
    filtered = FilteredLightCurve(
        time=(1.0, 2.0, 3.0),
        flux=(1.0, 2.0),
        flux_err=None,
        quality=(0, 0, 0),
        source_indices=(0, 1, 2),
        flux_column="PDCSAP_FLUX",
        provenance=_provenance(),
        metadata=_metadata(86400.0),
        stats=_stats(3),
        rejected=(),
        history=(_step(3),),
    )

    with pytest.raises(InvalidLightCurveError, match="mismatched lengths"):
        segment_light_curve(filtered)


# --------------------------------------------------------------------------
# Edge cases
# --------------------------------------------------------------------------


def test_empty_filtered_light_curve_returns_empty_result_without_crashing() -> None:
    result = segment_light_curve(_filtered(time=()))

    assert result.segments == ()
    assert result.gaps == ()
    assert result.stats.total_cadences == 0
    assert result.stats.segment_count == 0
    assert result.stats.gap_count == 0
    assert result.stats.measured_nominal_cadence is None
    assert result.cadence_count == 0
    assert result.provenance.source_checksum_sha256 == CHECKSUM
    assert len(result.history) == 2


def test_single_retained_cadence_returns_one_segment_without_raising() -> None:
    result = segment_light_curve(_filtered(time=(5.0,)))

    assert len(result.segments) == 1
    assert result.segments[0].cadence_count == 1
    assert result.segments[0].time == (5.0,)
    assert result.stats.measured_nominal_cadence is None
    assert result.gaps == ()
    assert result.stats.segment_count == 1


def test_every_interval_exceeding_threshold_yields_one_segment_per_cadence() -> None:
    """A real median-derived nominal cadence can never be smaller than
    roughly half of its own input diffs, so "every interval is a gap"
    cannot arise through public measurement -- this exercises the
    boundary-building logic directly with a manually supplied nominal
    cadence, the same way ``test_fits_parser.py`` tests
    ``_assert_consistent_lengths`` directly."""
    filtered = _filtered(time=(0.0, 10.0, 20.0, 30.0))
    config = GapDetectionConfig(gap_multiplier=1.5, gap_tolerance=0.0)

    segments, gaps = _build_segments_and_gaps(filtered, nominal_cadence=1.0, config=config)

    assert len(segments) == 4
    assert len(gaps) == 3
    assert all(segment.cadence_count == 1 for segment in segments)
    assert [segment.time[0] for segment in segments] == [0.0, 10.0, 20.0, 30.0]


def test_no_cadence_is_lost_or_duplicated_across_segments() -> None:
    time = (0.0, 1.0, 2.0, 3.0, 4.0, 50.0, 51.0, 52.0)

    result = segment_light_curve(_filtered(time=time))

    all_times = tuple(t for segment in result.segments for t in segment.time)
    assert all_times == time
    assert sum(segment.cadence_count for segment in result.segments) == len(time)
    assert result.cadence_count == len(time)


def test_segment_numbers_are_sequential_and_ordered_across_multiple_gaps() -> None:
    time = (0.0, 1.0, 2.0, 20.0, 21.0, 40.0, 41.0, 42.0)

    result = segment_light_curve(_filtered(time=time))

    assert result.stats.segment_count == 3
    assert [segment.segment_number for segment in result.segments] == [1, 2, 3]
    assert [segment.time for segment in result.segments] == [
        (0.0, 1.0, 2.0),
        (20.0, 21.0),
        (40.0, 41.0, 42.0),
    ]


def test_flux_err_none_is_preserved_in_segments() -> None:
    result = segment_light_curve(_filtered(time=(0.0, 1.0, 2.0), include_flux_err=False))

    assert result.segments[0].flux_err is None


# --------------------------------------------------------------------------
# Cadence agreement (measured vs. metadata)
# --------------------------------------------------------------------------


def test_cadence_sources_agree_within_tolerance() -> None:
    result = segment_light_curve(
        _filtered(time=(0.0, 1.0, 2.0, 3.0), metadata_cadence_seconds=86400.0)
    )

    assert result.stats.metadata_cadence_native == pytest.approx(1.0)
    assert result.stats.cadence_sources_agree is True


def test_cadence_sources_disagree_when_far_apart() -> None:
    result = segment_light_curve(_filtered(time=(0.0, 1.0, 2.0, 3.0), metadata_cadence_seconds=1.0))

    assert result.stats.cadence_sources_agree is False


def test_cadence_agreement_is_none_when_metadata_missing() -> None:
    result = segment_light_curve(
        _filtered(time=(0.0, 1.0, 2.0, 3.0), metadata_cadence_seconds=None)
    )

    assert result.stats.metadata_cadence_native is None
    assert result.stats.cadence_sources_agree is None


def test_cadence_agreement_is_none_when_nominal_cadence_not_estimable() -> None:
    result = segment_light_curve(_filtered(time=(5.0,)))

    assert result.stats.cadence_sources_agree is None


def test_cadence_agreement_is_none_when_metadata_cadence_is_zero() -> None:
    """A zero metadata cadence is not a usable comparison value (it would
    make every measured cadence "disagree" trivially), so it is treated
    the same as missing metadata rather than as a genuine disagreement."""
    result = segment_light_curve(_filtered(time=(0.0, 1.0, 2.0, 3.0), metadata_cadence_seconds=0.0))

    assert result.stats.metadata_cadence_native == 0.0
    assert result.stats.cadence_sources_agree is None


def test_disagreement_does_not_change_gap_detection() -> None:
    """Measured cadence always drives thresholding, regardless of what
    the FITS metadata cadence says."""
    time = (0.0, 1.0, 2.0, 12.0, 13.0)

    agreeing = segment_light_curve(_filtered(time=time, metadata_cadence_seconds=86400.0))
    disagreeing = segment_light_curve(_filtered(time=time, metadata_cadence_seconds=1.0))

    assert agreeing.stats.gap_count == disagreeing.stats.gap_count == 1
    assert agreeing.gaps[0].threshold == disagreeing.gaps[0].threshold


# --------------------------------------------------------------------------
# Immutability, provenance, and determinism
# --------------------------------------------------------------------------


def test_filtered_light_curve_is_not_mutated() -> None:
    filtered = _filtered(time=(0.0, 1.0, 2.0, 50.0))
    before = filtered.model_dump()

    segment_light_curve(filtered)

    assert filtered.model_dump() == before


def test_segmented_light_curve_is_frozen() -> None:
    result = segment_light_curve(_filtered(time=(0.0, 1.0)))

    with pytest.raises(Exception, match="frozen"):
        result.segments = ()  # type: ignore[misc]


def test_detected_gap_is_frozen() -> None:
    result = segment_light_curve(_filtered(time=(0.0, 1.0, 2.0, 3.0, 4.0, 50.0)))

    with pytest.raises(Exception, match="frozen"):
        result.gaps[0].actual_interval = 0.0  # type: ignore[misc]


def test_provenance_and_metadata_are_preserved() -> None:
    filtered = _filtered(time=(0.0, 1.0, 2.0))

    result = segment_light_curve(filtered)

    assert result.provenance == filtered.provenance
    assert result.metadata == filtered.metadata
    assert result.flux_column == filtered.flux_column


def test_history_carries_forward_prior_steps_and_appends_gap_detection_step() -> None:
    filtered = _filtered(time=(0.0, 1.0, 2.0))

    result = segment_light_curve(filtered)

    assert len(result.history) == 2
    assert result.history[0] == filtered.history[0]
    step = result.history[1]
    assert isinstance(step, GapDetectionStep)
    assert step.step == "gap_segmentation"
    assert step.input_cadences == 3
    assert step.output_segment_count == 1
    assert step.output_gap_count == 0
    assert step.input_checksum_sha256 == CHECKSUM


def test_gap_detection_step_has_no_timestamp_field() -> None:
    step = segment_light_curve(_filtered(time=(0.0, 1.0))).history[-1]

    assert not any("time" in name or "date" in name for name in type(step).model_fields)


def test_repeated_runs_produce_identical_results() -> None:
    filtered = _filtered(time=(0.0, 1.0, 2.0, 50.0))

    first = segment_light_curve(filtered)
    second = segment_light_curve(filtered)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
