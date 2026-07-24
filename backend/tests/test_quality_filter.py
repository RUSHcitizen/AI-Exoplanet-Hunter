"""Tests for quality-flag and finite-value filtering (Phase 3A).

Light curves are built directly as ``RawLightCurve`` objects rather than
via FITS files: it keeps the suite fast, and it is the only way to reach
the structurally-invalid states (mismatched column lengths, zero
cadences) that ``parse_light_curve`` already rejects but that
``RawLightCurve`` itself does not cross-validate.
"""

import math

import pytest

from app.data.exceptions import InvalidFilterConfigError, InvalidLightCurveError
from app.data.models import (
    FileProvenance,
    FitsMetadata,
    QualityFilterConfig,
    RawLightCurve,
    RejectionReason,
    config_from_policy_name,
)
from app.data.quality_filter import filter_quality
from app.data.quality_flags import (
    BITMASK_DEFAULT,
    BITMASK_HARD,
    BITMASK_HARDEST,
    BITMASK_MAST,
    QUALITY_BIT_TABLE,
    QualityPolicy,
)

CHECKSUM = "a" * 64


def _raw(
    *,
    time: tuple[float, ...] | None = None,
    flux: tuple[float, ...] | None = None,
    flux_err: tuple[float, ...] | None = None,
    quality: tuple[int, ...] | None = None,
    include_flux_err: bool = True,
    n_rows: int = 3,
) -> RawLightCurve:
    """A minimal, all-clean RawLightCurve unless fields are overridden."""
    time = time if time is not None else tuple(float(i) for i in range(n_rows))
    flux = flux if flux is not None else tuple(100.0 for _ in range(n_rows))
    quality = quality if quality is not None else tuple(0 for _ in range(n_rows))
    if flux_err is None and include_flux_err:
        flux_err = tuple(1.0 for _ in range(n_rows))
    if not include_flux_err:
        flux_err = None

    return RawLightCurve(
        time=time,
        flux=flux,
        flux_err=flux_err,
        quality=quality,
        flux_column="PDCSAP_FLUX",
        provenance=FileProvenance(
            source_filename="test-lc.fits",
            source_checksum_sha256=CHECKSUM,
            tic_id=261136679,
            sector=1,
            camera=2,
            ccd=3,
            author="SPOC",
            mission="TESS",
            telescope="TESS",
        ),
        metadata=FitsMetadata(
            object_name="TIC 261136679",
            time_system="TDB",
            cadence_seconds=120.0,
            header={},
        ),
    )


def _custom(bitmask: int) -> QualityFilterConfig:
    return QualityFilterConfig(quality_policy=QualityPolicy.CUSTOM, custom_quality_bitmask=bitmask)


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_clean_light_curve_rejects_nothing() -> None:
    result = filter_quality(_raw())

    assert result.stats.total_cadences == 3
    assert result.stats.retained_cadences == 3
    assert result.stats.rejected_cadences == 0
    assert result.rejected == ()
    assert result.stats.rejected_by_reason == {}
    assert result.stats.rejected_by_quality_bit == {}
    assert result.time == (0.0, 1.0, 2.0)
    assert result.flux == (100.0,) * 3
    assert result.flux_err == (1.0,) * 3
    assert result.source_indices == (0, 1, 2)
    assert result.stats.retained_fraction == 1.0


def test_omitted_config_uses_project_default_of_mast() -> None:
    result = filter_quality(_raw())
    step = result.history[0]

    assert step.quality_policy is QualityPolicy.MAST
    assert step.active_quality_bitmask == 21183


def test_omitted_policy_in_config_resolves_to_mast() -> None:
    config = QualityFilterConfig()

    assert config.quality_policy is QualityPolicy.MAST
    assert config.active_bitmask == BITMASK_MAST == 21183


# --------------------------------------------------------------------------
# Named policies
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (QualityPolicy.NONE, 0),
        (QualityPolicy.DEFAULT, BITMASK_DEFAULT),
        (QualityPolicy.MAST, BITMASK_MAST),
        (QualityPolicy.HARD, BITMASK_HARD),
        (QualityPolicy.HARDEST, BITMASK_HARDEST),
    ],
)
def test_each_named_policy_resolves_to_its_mask(policy: QualityPolicy, expected: int) -> None:
    config = QualityFilterConfig(quality_policy=policy)

    assert config.active_bitmask == expected
    assert filter_quality(_raw(), config).history[0].active_quality_bitmask == expected


def test_none_policy_retains_flagged_cadences() -> None:
    raw = _raw(quality=(0, 2048, 128))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.NONE))

    assert result.stats.retained_cadences == 3
    assert result.stats.rejected_cadences == 0
    assert result.quality == (0, 2048, 128)


@pytest.mark.parametrize("bit_value", sorted(QUALITY_BIT_TABLE))
def test_hardest_policy_rejects_every_documented_bit(bit_value: int) -> None:
    raw = _raw(quality=(0, bit_value, 0))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.HARDEST))

    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].index == 1
    assert result.rejected[0].matched_quality_bits == bit_value


def test_hardest_policy_rejects_mixed_flag_values() -> None:
    raw = _raw(quality=(0, 64 | 256, 8192))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.HARDEST))

    assert result.stats.retained_cadences == 1
    assert result.stats.rejected_cadences == 2


def test_default_policy_keeps_scattered_light_bit_4096() -> None:
    """Bit 13 is absent from the Lightkurve-compatible default mask."""
    raw = _raw(quality=(0, 4096, 0))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.DEFAULT))

    assert result.stats.retained_cadences == 3
    assert result.stats.rejected_cadences == 0
    assert result.quality == (0, 4096, 0)


def test_mast_policy_rejects_scattered_light_bit_4096() -> None:
    """Bit 13 is the sole difference between 'default' and 'mast'."""
    raw = _raw(quality=(0, 4096, 0))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.MAST))

    assert result.stats.retained_cadences == 2
    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].index == 1
    assert result.rejected[0].matched_quality_bits == 4096
    assert result.rejected[0].reasons == (RejectionReason.MATCHED_QUALITY_BITS,)
    assert result.source_indices == (0, 2)


@pytest.mark.parametrize("bit_value", [1, 2, 4, 8, 16, 32, 128, 512, 16384])
@pytest.mark.parametrize("policy", [QualityPolicy.DEFAULT, QualityPolicy.MAST])
def test_default_and_mast_both_reject_every_bit_they_share(
    policy: QualityPolicy, bit_value: int
) -> None:
    """Every bit in mask 17087 is rejected by both policies."""
    raw = _raw(quality=(0, bit_value, 0))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=policy))

    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].matched_quality_bits == bit_value


@pytest.mark.parametrize(
    ("quality_value", "expect_rejected"),
    [
        (0, False),
        (128, True),  # bit 8, Manual Exclude
        (64, False),  # bit 7, cosmic ray corrected -- MAST: data is likely fine
        (16384, True),  # bit 15, Bad Calibration Exclude
        (256, False),  # bit 9, discontinuity corrected -- in no mask but hardest
        (128 | 64, True),  # one masked bit is enough
        (4096, True),  # bit 13, rejected by mast but not by default
    ],
)
def test_mast_policy_against_representative_quality_values(
    quality_value: int, expect_rejected: bool
) -> None:
    raw = _raw(quality=(quality_value,), n_rows=1)

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.MAST))

    assert (result.stats.rejected_cadences == 1) is expect_rejected


def test_bits_outside_the_active_mask_remain_accepted() -> None:
    """Bit 9 (256) is in no named mask except hardest."""
    raw = _raw(quality=(256, 256, 256))

    for policy in (QualityPolicy.DEFAULT, QualityPolicy.MAST, QualityPolicy.HARD):
        result = filter_quality(raw, QualityFilterConfig(quality_policy=policy))
        assert result.stats.retained_cadences == 3, policy

    hardest = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.HARDEST))
    assert hardest.stats.retained_cadences == 0


def test_hard_policy_rejects_cosmic_ray_bit_that_mast_keeps() -> None:
    raw = _raw(quality=(64,), n_rows=1)

    assert (
        filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.MAST)).cadence_count
        == 1
    )
    assert (
        filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.HARD)).cadence_count
        == 0
    )


# --------------------------------------------------------------------------
# Custom masks and configuration errors
# --------------------------------------------------------------------------


def test_custom_mask_is_applied_exactly() -> None:
    raw = _raw(quality=(64, 64 | 1, 128))

    result = filter_quality(raw, _custom(64))

    assert result.stats.rejected_cadences == 2
    assert [record.index for record in result.rejected] == [0, 1]
    assert result.quality == (128,)


def test_custom_mask_of_zero_behaves_like_none() -> None:
    raw = _raw(quality=(2048, 128, 16384))

    result = filter_quality(raw, _custom(0))

    assert result.stats.retained_cadences == 3
    assert result.history[0].active_quality_bitmask == 0


def test_custom_mask_may_exceed_documented_bits() -> None:
    raw = _raw(quality=(1 << 16, 0, 0))

    result = filter_quality(raw, _custom(1 << 16))

    assert result.stats.rejected_cadences == 1
    assert result.stats.rejected_by_quality_bit == {1 << 16: 1}


def test_invalid_policy_name_raises_listing_valid_options() -> None:
    with pytest.raises(InvalidFilterConfigError) as exc_info:
        config_from_policy_name("aggressive")

    message = str(exc_info.value)
    assert "'aggressive' is not supported" in message
    for option in ("none", "default", "mast", "hard", "hardest", "custom"):
        assert repr(option) in message


def test_valid_policy_names_are_accepted() -> None:
    for policy in QualityPolicy:
        mask = 64 if policy is QualityPolicy.CUSTOM else None
        config = config_from_policy_name(policy.value, custom_quality_bitmask=mask)
        assert config.quality_policy is policy


def test_negative_custom_mask_raises() -> None:
    with pytest.raises(InvalidFilterConfigError, match="must be >= 0"):
        _custom(-1)


def test_custom_policy_without_mask_raises() -> None:
    with pytest.raises(InvalidFilterConfigError, match="requires custom_quality_bitmask"):
        QualityFilterConfig(quality_policy=QualityPolicy.CUSTOM)


def test_named_policy_with_custom_mask_raises_rather_than_ignoring_it() -> None:
    with pytest.raises(InvalidFilterConfigError, match="only valid with quality_policy='custom'"):
        QualityFilterConfig(quality_policy=QualityPolicy.MAST, custom_quality_bitmask=64)


# --------------------------------------------------------------------------
# Nonfinite values
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_time_is_rejected(bad: float) -> None:
    raw = _raw(time=(0.0, bad, 2.0))

    result = filter_quality(raw)

    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].reasons == (RejectionReason.NONFINITE_TIME,)
    assert result.rejected[0].index == 1
    assert result.source_indices == (0, 2)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_flux_is_rejected(bad: float) -> None:
    raw = _raw(flux=(100.0, bad, 100.0))

    result = filter_quality(raw)

    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].reasons == (RejectionReason.NONFINITE_FLUX,)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_nonfinite_flux_err_is_rejected(bad: float) -> None:
    raw = _raw(flux_err=(1.0, bad, 1.0))

    result = filter_quality(raw)

    assert result.stats.rejected_cadences == 1
    assert result.rejected[0].reasons == (RejectionReason.NONFINITE_FLUX_ERR,)


def test_zero_flux_error_is_retained() -> None:
    """A zero uncertainty is unusual but is a reported measurement."""
    raw = _raw(flux_err=(0.0, 1.0, 0.0))

    result = filter_quality(raw)

    assert result.stats.retained_cadences == 3
    assert result.flux_err == (0.0, 1.0, 0.0)


def test_negative_flux_is_retained() -> None:
    """Brightness-based outlier rejection is out of scope for this step."""
    raw = _raw(flux=(-50.0, 100.0, 1e12))

    result = filter_quality(raw)

    assert result.stats.retained_cadences == 3


def test_missing_flux_err_column_yields_no_flux_err_rejections() -> None:
    raw = _raw(flux=(100.0, 100.0, 100.0), include_flux_err=False)

    result = filter_quality(raw)

    assert result.flux_err is None
    assert result.stats.retained_cadences == 3


@pytest.mark.parametrize(
    ("field", "toggle", "reason"),
    [
        ("time", "require_finite_time", RejectionReason.NONFINITE_TIME),
        ("flux", "require_finite_flux", RejectionReason.NONFINITE_FLUX),
        ("flux_err", "require_finite_flux_err", RejectionReason.NONFINITE_FLUX_ERR),
    ],
)
def test_each_finiteness_check_can_be_disabled(
    field: str, toggle: str, reason: RejectionReason
) -> None:
    values = (1.0, math.nan, 3.0)
    raw = _raw(**{field: values})  # type: ignore[arg-type]

    enabled = filter_quality(raw, QualityFilterConfig())
    assert reason in enabled.stats.rejected_by_reason

    disabled = filter_quality(raw, QualityFilterConfig(**{toggle: False}))
    assert disabled.stats.retained_cadences == 3


# --------------------------------------------------------------------------
# Multiple reasons and matched-bit recording
# --------------------------------------------------------------------------


def test_multiple_simultaneous_reasons_are_all_recorded() -> None:
    raw = _raw(time=(0.0, math.nan, 2.0), flux=(100.0, math.nan, 100.0), quality=(0, 128, 0))

    result = filter_quality(raw)

    assert result.stats.rejected_cadences == 1
    record = result.rejected[0]
    assert record.reasons == (
        RejectionReason.NONFINITE_TIME,
        RejectionReason.NONFINITE_FLUX,
        RejectionReason.MATCHED_QUALITY_BITS,
    )
    assert result.stats.rejected_by_reason == {
        RejectionReason.NONFINITE_TIME: 1,
        RejectionReason.NONFINITE_FLUX: 1,
        RejectionReason.MATCHED_QUALITY_BITS: 1,
    }
    assert sum(result.stats.rejected_by_reason.values()) > result.stats.rejected_cadences


def test_matched_quality_bits_records_only_bits_in_the_active_mask() -> None:
    """quality = bits 1|7|15; under 'default' only bits 1 and 15 match."""
    raw = _raw(quality=(1 | 64 | 16384,), n_rows=1)

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.DEFAULT))

    record = result.rejected[0]
    assert record.quality == 16449
    assert record.matched_quality_bits == 16385
    assert not record.matched_quality_bits & 64


def test_matched_quality_bits_is_zero_for_nonfinite_only_rejections() -> None:
    raw = _raw(flux=(math.nan,), quality=(0,), n_rows=1)

    result = filter_quality(raw)

    assert result.rejected[0].matched_quality_bits == 0
    assert result.stats.rejected_by_quality_bit == {}


def test_rejected_by_quality_bit_counts_each_bit_separately() -> None:
    raw = _raw(quality=(1, 1 | 128, 128))

    result = filter_quality(raw)

    assert result.stats.rejected_by_quality_bit == {1: 2, 128: 2}
    assert result.stats.rejected_cadences == 3


def test_original_quality_integer_is_preserved_on_the_record() -> None:
    raw = _raw(quality=(2048 | 128,), n_rows=1)

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.MAST))

    assert result.rejected[0].quality == 2176
    assert result.rejected[0].matched_quality_bits == 128


# --------------------------------------------------------------------------
# Structural validation and edge cases
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"time": (1.0, 2.0)},
        {"flux": (1.0, 2.0)},
        {"quality": (0, 0)},
        {"flux_err": (1.0, 2.0)},
    ],
)
def test_mismatched_column_lengths_raise(kwargs: dict[str, tuple[float, ...]]) -> None:
    raw = _raw(**kwargs)  # type: ignore[arg-type]

    with pytest.raises(InvalidLightCurveError, match="mismatched lengths"):
        filter_quality(raw)


def test_empty_light_curve_raises() -> None:
    raw = _raw(time=(), flux=(), flux_err=(), quality=())

    with pytest.raises(InvalidLightCurveError, match="no cadences"):
        filter_quality(raw)


def test_every_cadence_rejected_returns_normally_with_full_statistics() -> None:
    raw = _raw(quality=(128, 16384, 2))

    result = filter_quality(raw)

    assert result.time == ()
    assert result.flux == ()
    assert result.flux_err == ()
    assert result.quality == ()
    assert result.source_indices == ()
    assert result.cadence_count == 0
    assert result.stats.total_cadences == 3
    assert result.stats.retained_cadences == 0
    assert result.stats.rejected_cadences == 3
    assert result.stats.retained_fraction == 0.0
    assert len(result.rejected) == 3
    assert result.history[0].output_cadences == 0


def test_retained_plus_rejected_always_equals_total() -> None:
    raw = _raw(
        time=(0.0, math.nan, 2.0, 3.0, 4.0),
        flux=(100.0, 100.0, math.inf, 100.0, 100.0),
        flux_err=(1.0, 1.0, 1.0, math.nan, 1.0),
        quality=(0, 0, 0, 128, 16384),
    )

    result = filter_quality(raw)

    assert result.stats.retained_cadences + result.stats.rejected_cadences == 5
    assert result.stats.total_cadences == 5
    assert result.stats.retained_cadences == 1


def test_source_indices_map_back_to_the_original_arrays() -> None:
    raw = _raw(
        time=(0.0, 1.0, 2.0, 3.0, 4.0),
        flux=(10.0, math.nan, 30.0, 40.0, 50.0),
        flux_err=(1.0, 1.0, 1.0, 1.0, 1.0),
        quality=(0, 0, 128, 0, 0),
    )

    result = filter_quality(raw)

    assert result.source_indices == (0, 3, 4)
    assert all(index < len(raw.time) for index in result.source_indices)
    assert list(result.source_indices) == sorted(result.source_indices)
    for position, index in enumerate(result.source_indices):
        assert result.time[position] == raw.time[index]
        assert result.flux[position] == raw.flux[index]
        assert result.quality[position] == raw.quality[index]

    rejected_indices = [record.index for record in result.rejected]
    assert rejected_indices == [1, 2]
    assert set(rejected_indices) & set(result.source_indices) == set()


# --------------------------------------------------------------------------
# Immutability and provenance
# --------------------------------------------------------------------------


def test_raw_light_curve_is_not_modified() -> None:
    raw = _raw(
        time=(0.0, math.nan, 2.0),
        flux=(100.0, 200.0, math.inf),
        flux_err=(1.0, 2.0, 3.0),
        quality=(0, 128, 4096),
    )
    before = raw.model_dump()

    result = filter_quality(raw)

    assert raw.model_dump() == before
    assert raw.time == (0.0, raw.time[1], 2.0)
    assert math.isnan(raw.time[1])
    assert len(raw.time) == 3
    assert result.provenance is raw.provenance
    assert result.metadata is raw.metadata
    assert result.flux_column == raw.flux_column


def test_raw_light_curve_rejects_attribute_assignment() -> None:
    raw = _raw()

    with pytest.raises(Exception, match="frozen"):
        raw.time = (9.0,)  # type: ignore[misc]


def test_filtered_light_curve_is_frozen() -> None:
    result = filter_quality(_raw())

    with pytest.raises(Exception, match="frozen"):
        result.time = (9.0,)  # type: ignore[misc]


def test_processing_history_records_deterministic_provenance() -> None:
    raw = _raw(quality=(0, 128, 0))

    result = filter_quality(raw, QualityFilterConfig(quality_policy=QualityPolicy.MAST))
    step = result.history[0]

    assert len(result.history) == 1
    assert step.step == "quality_filter"
    assert step.code_version
    assert step.quality_policy is QualityPolicy.MAST
    assert step.active_quality_bitmask == BITMASK_MAST
    assert step.config.quality_policy is QualityPolicy.MAST
    assert step.input_cadences == 3
    assert step.output_cadences == 2
    assert step.input_checksum_sha256 == CHECKSUM


def test_processing_step_has_no_timestamp_field() -> None:
    """Results stay a pure function of their inputs, so reruns match."""
    step = filter_quality(_raw()).history[0]

    assert not any("time" in name or "date" in name for name in type(step).model_fields)


def test_repeated_runs_produce_identical_results() -> None:
    raw = _raw(
        time=(0.0, math.inf, 2.0),
        flux=(100.0, 100.0, 100.0),
        flux_err=(1.0, 1.0, 1.0),
        quality=(0, 0, 128),
    )

    first = filter_quality(raw)
    second = filter_quality(raw)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_filtering_preserves_flux_column_choice_from_the_parser() -> None:
    """The flux series is decided by the parser (PDCSAP with SAP fallback)
    and is never re-selected here."""
    raw = _raw()

    assert filter_quality(raw).flux_column == "PDCSAP_FLUX"
