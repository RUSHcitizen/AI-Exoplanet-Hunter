"""TESS ``QUALITY`` bit definitions and the named bitmask policies built
from them (Phase 3A).

This module holds *verified reference data only* -- no filtering logic
(see ``app.data.quality_filter`` for that). It is deliberately a separate
module so that re-auditing the bit table against a future revision of the
TESS data-products document is a single-file diff.

Authoritative sources
---------------------
1. **TESS Science Data Products Description Document**, Rev F,
   NASA/TM--20205008729, dated 11 September 2020 -- section 9 "Data
   Quality Flags", **Table 32** ("Data quality bits"), page 53 of 98.
   https://archive.stsci.edu/files/live/sites/mast/files/home/missions-and-data/active-missions/tess/_documents/EXP-TESS-ARC-ICD-TM-0014-Rev-F.pdf
   Note that older revisions (and Lightkurve's docstring) cite this as
   *Table 28*; it is Table 32 in Rev F.
2. **MAST TESS Archive, "2.0 - Data Product Overview"**, section
   "Cadence Quality Flags" -- the same bit table, plus MAST's own
   filtering recommendation and caveats.
   https://outerspace.stsci.edu/display/TESS/2.0+-+Data+Product+Overview
3. **Lightkurve** ``src/lightkurve/utils.py``, class ``TessQualityFlags``
   -- used only as a secondary *implementation* reference for how the
   named masks are composed and applied (bitwise AND). Lightkurve is
   deliberately **not** a dependency of this project; the constants below
   are defined locally and pinned by ``tests/test_quality_flags.py``.
   https://github.com/lightkurve/lightkurve/blob/main/src/lightkurve/utils.py
   (``main`` branch; latest release v2.6.0, 2026-04-16.)

All three sources were retrieved on **2026-07-24** and agreed on every
bit value and description.

A caveat carried over verbatim in intent from source (1): "Implementers
should not assume this represents a comprehensive list of flags and that
flags not defined here will be available for their use as it is very
likely there will be changes to flag values after launch. Undefined bits
will be set to zero." The table below is therefore a snapshot of Rev F,
not a permanent contract -- ``describe_bits`` reports unknown bits
explicitly rather than ignoring them.

Named policies
--------------
``default`` (17087) and ``mast`` (21183) are **not** two spellings of the
same idea, and are kept distinct on purpose:

* ``default`` is *Lightkurve-compatible*: exactly Lightkurve's
  ``TessQualityFlags.DEFAULT_BITMASK``. It does **not** include bit 13
  (Scattered Light Exclude, 4096).
* ``mast`` is *MAST-recommended*: the bit-wise AND value MAST documents
  as identifying "cadences that are likely of lesser quality" (given
  there as the binary number ``0101001010111111``). It equals ``default``
  plus bit 13.

**This project uses ``mast`` unless the caller requests another policy.**
The reasoning: the parser prefers ``PDCSAP_FLUX`` (see
``app.data.fits_parser``), and the automatic scattered-light flag marks
cadences the pipeline itself considers degraded, so rejecting it matches
the archive's own advice for this flux series. Calling 21183 "default"
would wrongly imply parity with Lightkurve's current default of 17087,
which is why both names exist.

``hardest`` rejects every cadence carrying any flag at all. It is **not
recommended** as a normal policy: MAST notes that "Not all of these
[flags] indicate that the data quality is bad. In many cases the flags
simply indicate that a correction was made" -- bit 7, for instance, means
a cosmic ray *was corrected* and MAST says such data "is likely fine".
Lightkurve's own source comment on the equivalent mask reads "Its use is
not recommended."
"""

from enum import StrEnum
from typing import Final

QUALITY_BIT_TABLE: Final[dict[int, str]] = {
    1: "Attitude Tweak",
    2: "Safe Mode",
    4: "Spacecraft is in Coarse Point",
    8: "Spacecraft is in Earth Point",
    16: "Argabrightening event",
    32: "Reaction Wheel desaturation Event",
    64: "Cosmic Ray in Optimal Aperture pixel",
    128: "Manual Exclude. The cadence was excluded because of an anomaly.",
    256: "Discontinuity corrected between this cadence and the following one.",
    512: "Impulsive outlier removed before cotrending.",
    1024: "Cosmic ray detected on collateral pixel row or column.",
    2048: "Stray light from Earth or Moon in camera FOV (predicted).",
    4096: "Scattered Light Exclude (spoc-4.0.5 and later).",
    8192: "Planet Search Exclude (spoc-4.0.5 and later).",
    16384: "Bad Calibration Exclude (spoc-4.0.14 and later).",
    32768: "Insufficient Targets for Error Correction Exclude (spoc-4.0.14 and later).",
}
"""Bit value -> meaning, transcribed from Table 32 of the TESS Science
Data Products Description Document Rev F (see the module docstring)."""

BITMASK_NONE: Final[int] = 0
"""Apply no quality filtering: retain every cadence regardless of flags."""

BITMASK_DEFAULT: Final[int] = 17087
"""Lightkurve-compatible default: bits 1, 2, 3, 4, 5, 6, 8, 10, 15
(``0x42BF``). Cadences Lightkurve describes as "definitely useless".
Does **not** include bit 13 (Scattered Light Exclude)."""

BITMASK_MAST: Final[int] = 21183
"""MAST-recommended mask: ``BITMASK_DEFAULT`` plus bit 13 (Scattered
Light Exclude, 4096), i.e. bits 1, 2, 3, 4, 5, 6, 8, 10, 13, 15
(``0x52BF``; MAST documents it as binary ``0101001010111111``). This is
the policy this project uses by default."""

BITMASK_HARD: Final[int] = 24319
"""Conservative: ``BITMASK_DEFAULT`` plus bits 7, 11, 12, 13
(``0x5EFF``). Also drops cosmic-ray-corrected cadences and predicted
stray light; Lightkurve notes this "may identify cadences which are
useful", i.e. it discards some good data."""

BITMASK_HARDEST: Final[int] = 65535
"""Every documented bit (``0xFFFF``): reject any cadence with any flag
set. Not recommended -- see the module docstring."""


class QualityPolicy(StrEnum):
    """A named TESS quality-filtering policy.

    ``CUSTOM`` carries no mask of its own; the caller supplies an integer
    via ``QualityFilterConfig.custom_quality_bitmask``.
    """

    NONE = "none"
    DEFAULT = "default"
    MAST = "mast"
    HARD = "hard"
    HARDEST = "hardest"
    CUSTOM = "custom"


POLICY_BITMASKS: Final[dict[QualityPolicy, int]] = {
    QualityPolicy.NONE: BITMASK_NONE,
    QualityPolicy.DEFAULT: BITMASK_DEFAULT,
    QualityPolicy.MAST: BITMASK_MAST,
    QualityPolicy.HARD: BITMASK_HARD,
    QualityPolicy.HARDEST: BITMASK_HARDEST,
}
"""Resolved integer mask per named policy. ``QualityPolicy.CUSTOM`` is
deliberately absent -- it has no fixed value."""

PROJECT_DEFAULT_POLICY: Final[QualityPolicy] = QualityPolicy.MAST
"""The policy applied when a caller does not request one. See the module
docstring for why this project prefers ``mast`` over ``default``."""


def describe_bits(value: int) -> tuple[str, ...]:
    """Human-readable names of the quality bits set in ``value``.

    Bits outside the documented Rev F table are reported explicitly
    (e.g. ``"bit 17 (undocumented, value 65536)"``) rather than dropped,
    because the source document warns that flag values may change and
    that this project must not silently ignore an unrecognized flag.
    """
    if value <= 0:
        return ()
    names: list[str] = []
    for bit_index in range(value.bit_length()):
        bit_value = 1 << bit_index
        if not value & bit_value:
            continue
        known = QUALITY_BIT_TABLE.get(bit_value)
        if known is not None:
            names.append(f"bit {bit_index + 1} ({bit_value}): {known}")
        else:
            names.append(f"bit {bit_index + 1} (undocumented, value {bit_value})")
    return tuple(names)
