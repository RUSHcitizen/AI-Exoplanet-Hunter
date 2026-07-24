"""Tests pinning the verified TESS quality-bit reference data.

These deliberately duplicate the numbers from the authoritative sources
cited in ``app.data.quality_flags`` rather than recomputing them from the
module under test, so a typo in either the literal constants or their
composition fails the suite.
"""

import pytest

from app.data.quality_flags import (
    BITMASK_DEFAULT,
    BITMASK_HARD,
    BITMASK_HARDEST,
    BITMASK_MAST,
    BITMASK_NONE,
    POLICY_BITMASKS,
    PROJECT_DEFAULT_POLICY,
    QUALITY_BIT_TABLE,
    QualityPolicy,
    describe_bits,
)

# Table 32, TESS Science Data Products Description Document Rev F
# (NASA/TM-20205008729, 11 September 2020), p. 53; cross-checked against
# the MAST "Cadence Quality Flags" table. Retrieved 2026-07-24.
EXPECTED_BITS = {
    1: "Attitude Tweak",
    2: "Safe Mode",
    4: "Spacecraft is in Coarse Point",
    8: "Spacecraft is in Earth Point",
    16: "Argabrightening event",
    32: "Reaction Wheel desaturation Event",
    64: "Cosmic Ray in Optimal Aperture pixel",
    128: "Manual Exclude",
    256: "Discontinuity corrected",
    512: "Impulsive outlier removed before cotrending",
    1024: "Cosmic ray detected on collateral pixel",
    2048: "Stray light from Earth or Moon",
    4096: "Scattered Light Exclude",
    8192: "Planet Search Exclude",
    16384: "Bad Calibration Exclude",
    32768: "Insufficient Targets for Error Correction Exclude",
}


def test_quality_bit_table_has_all_sixteen_documented_bits() -> None:
    assert len(QUALITY_BIT_TABLE) == 16
    assert set(QUALITY_BIT_TABLE) == {1 << n for n in range(16)}


@pytest.mark.parametrize(("bit_value", "expected_fragment"), sorted(EXPECTED_BITS.items()))
def test_each_bit_maps_to_its_documented_meaning(bit_value: int, expected_fragment: str) -> None:
    assert expected_fragment in QUALITY_BIT_TABLE[bit_value]


def test_bit_descriptions_are_unique() -> None:
    descriptions = list(QUALITY_BIT_TABLE.values())
    assert len(set(descriptions)) == len(descriptions)


def test_bitmask_none_is_zero() -> None:
    assert BITMASK_NONE == 0


def test_bitmask_default_matches_lightkurve_value_and_composition() -> None:
    """default == Lightkurve TessQualityFlags.DEFAULT_BITMASK (17087)."""
    assert BITMASK_DEFAULT == 17087
    assert BITMASK_DEFAULT == 1 | 2 | 4 | 8 | 16 | 32 | 128 | 512 | 16384


def test_bitmask_default_excludes_scattered_light() -> None:
    """Bit 13 is the sole difference from the MAST-recommended mask."""
    assert not BITMASK_DEFAULT & 4096


def test_bitmask_mast_matches_documented_value_and_composition() -> None:
    """mast == MAST's recommended mask, binary 0101001010111111 == 21183."""
    assert BITMASK_MAST == 21183
    assert BITMASK_MAST == 0b0101001010111111
    assert BITMASK_MAST == 1 | 2 | 4 | 8 | 16 | 32 | 128 | 512 | 4096 | 16384


def test_bitmask_mast_is_default_plus_scattered_light() -> None:
    assert BITMASK_MAST == BITMASK_DEFAULT | 4096
    assert BITMASK_MAST & 4096


def test_bitmask_hard_matches_value_and_composition() -> None:
    assert BITMASK_HARD == 24319
    assert BITMASK_HARD == BITMASK_DEFAULT | 64 | 1024 | 2048 | 4096


def test_bitmask_hardest_covers_every_documented_bit() -> None:
    assert BITMASK_HARDEST == 65535
    assert sum(QUALITY_BIT_TABLE) == BITMASK_HARDEST


def test_masks_are_ordered_by_strictness() -> None:
    """none < default < mast < hard < hardest, each a strict superset."""
    assert BITMASK_DEFAULT & BITMASK_MAST == BITMASK_DEFAULT
    assert BITMASK_MAST & BITMASK_HARD == BITMASK_MAST
    assert BITMASK_HARD & BITMASK_HARDEST == BITMASK_HARD
    assert BITMASK_NONE < BITMASK_DEFAULT < BITMASK_MAST < BITMASK_HARD < BITMASK_HARDEST


def test_policy_bitmasks_cover_every_named_policy_except_custom() -> None:
    assert set(POLICY_BITMASKS) == set(QualityPolicy) - {QualityPolicy.CUSTOM}
    assert POLICY_BITMASKS[QualityPolicy.NONE] == BITMASK_NONE
    assert POLICY_BITMASKS[QualityPolicy.DEFAULT] == BITMASK_DEFAULT
    assert POLICY_BITMASKS[QualityPolicy.MAST] == BITMASK_MAST
    assert POLICY_BITMASKS[QualityPolicy.HARD] == BITMASK_HARD
    assert POLICY_BITMASKS[QualityPolicy.HARDEST] == BITMASK_HARDEST


def test_project_default_policy_is_mast() -> None:
    assert PROJECT_DEFAULT_POLICY is QualityPolicy.MAST
    assert POLICY_BITMASKS[PROJECT_DEFAULT_POLICY] == 21183


def test_policy_values_are_the_documented_names() -> None:
    assert [policy.value for policy in QualityPolicy] == [
        "none",
        "default",
        "mast",
        "hard",
        "hardest",
        "custom",
    ]


def test_describe_bits_names_known_bits() -> None:
    described = describe_bits(1 | 16384)

    assert len(described) == 2
    assert "Attitude Tweak" in described[0]
    assert "bit 1 (1)" in described[0]
    assert "Bad Calibration Exclude" in described[1]
    assert "bit 15 (16384)" in described[1]


def test_describe_bits_reports_undocumented_bits_rather_than_ignoring_them() -> None:
    described = describe_bits(1 << 16)

    assert described == ("bit 17 (undocumented, value 65536)",)


@pytest.mark.parametrize("value", [0, -1])
def test_describe_bits_returns_empty_for_no_flags(value: int) -> None:
    assert describe_bits(value) == ()
