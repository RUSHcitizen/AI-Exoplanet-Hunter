"""Typed models for TESS target/observation discovery, download, FITS
parsing, and quality-filtering results."""

from enum import StrEnum
from math import isfinite
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.data.exceptions import (
    InvalidFilterConfigError,
    InvalidGapDetectionConfigError,
    InvalidNormalizationConfigError,
    InvalidOutlierDetectionConfigError,
)
from app.data.quality_flags import (
    POLICY_BITMASKS,
    PROJECT_DEFAULT_POLICY,
    QualityPolicy,
)


class TessObservation(BaseModel):
    """One matching MAST observation for a TESS target.

    Field names mirror astroquery's MAST column semantics (see
    ``app.data.mast_client``) so a result can be traced back to the
    source columns it came from.
    """

    model_config = ConfigDict(frozen=True)

    obs_id: str
    target_name: str
    mission: str
    dataproduct_type: str
    sector: int | None = None
    author: str | None = None
    cadence_seconds: float | None = None
    calib_level: int | None = None


class TargetSearchResult(BaseModel):
    """The result of a TESS target/observation discovery search."""

    model_config = ConfigDict(frozen=True)

    query: str
    resolved_target: str
    tic_id: int | None
    observations: tuple[TessObservation, ...]

    @property
    def observation_count(self) -> int:
        return len(self.observations)

    @property
    def sectors(self) -> list[int]:
        return sorted({obs.sector for obs in self.observations if obs.sector is not None})


class DownloadRequest(BaseModel):
    """A validated request to download one light-curve product."""

    model_config = ConfigDict(frozen=True)

    target: str
    sector: int | None = None
    author: str | None = None
    cadence_seconds: float | None = None
    output_dir: str
    force: bool = False


class SelectedProduct(BaseModel):
    """One light-curve product chosen from an observation's product list
    by the deterministic selection rules in ``app.data.product_selection``."""

    model_config = ConfigDict(frozen=True)

    obs_id: str
    tic_id: int | None
    sector: int | None
    author: str | None
    cadence_seconds: float | None
    filename: str
    data_uri: str
    size_bytes: int | None = None
    description: str | None = None


class CachedArtifact(BaseModel):
    """A product that has been downloaded to (or reused from) the local
    on-disk cache."""

    model_config = ConfigDict(frozen=True)

    product: SelectedProduct
    local_path: str
    size_bytes: int
    sha256: str
    was_downloaded: bool
    """``True`` if this call performed a network download; ``False`` if a
    valid cached copy was reused instead."""


class FileProvenance(BaseModel):
    """Where a parsed light curve's bytes came from, for traceability from
    a candidate score back to the exact source file (see
    ``docs/architecture.md``'s provenance section)."""

    model_config = ConfigDict(frozen=True)

    source_filename: str
    source_checksum_sha256: str
    tic_id: int | None
    sector: int | None
    camera: int | None
    ccd: int | None
    author: str | None
    mission: str | None
    telescope: str | None


class FitsMetadata(BaseModel):
    """Metadata describing a parsed light-curve FITS file, extracted from
    its header and structure (not from the scientific arrays)."""

    model_config = ConfigDict(frozen=True)

    object_name: str | None
    time_system: str | None
    cadence_seconds: float | None
    header: dict[str, str]
    """A flattened, string-valued subset of the PRIMARY and LIGHTCURVE
    header cards, for reference/debugging. Not exhaustive."""


class RawLightCurve(BaseModel):
    """The unmodified scientific arrays read from a supported TESS
    light-curve FITS file, plus their provenance and metadata.

    Values are preserved exactly as represented in the source file
    (aside from safe conversion into typed Python structures) -- no
    NaN removal, quality filtering, normalization, or detrending has
    been applied. See ``docs/architecture.md`` for what remains
    unimplemented.
    """

    model_config = ConfigDict(frozen=True)

    time: tuple[float, ...]
    flux: tuple[float, ...]
    flux_err: tuple[float, ...] | None
    quality: tuple[int, ...]
    flux_column: str
    """Which flux column was extracted (``PDCSAP_FLUX`` or ``SAP_FLUX``);
    see ``app.data.fits_parser`` for the selection rule."""
    provenance: FileProvenance
    metadata: FitsMetadata


class RejectionReason(StrEnum):
    """Why one cadence was rejected by quality filtering.

    Kept as four distinct reasons so a missing measurement is never
    conflated with a measurement the pipeline flagged as suspect: a
    nonfinite value means *no usable number was recorded*, while a
    matched quality bit means *a number was recorded but the SPOC
    pipeline flagged the cadence*.
    """

    NONFINITE_TIME = "nonfinite_time"
    NONFINITE_FLUX = "nonfinite_flux"
    NONFINITE_FLUX_ERR = "nonfinite_flux_err"
    MATCHED_QUALITY_BITS = "matched_quality_bits"


class QualityFilterConfig(BaseModel):
    """Configuration for one quality/finite-value filtering run.

    The quality policy defaults to ``QualityPolicy.MAST`` (21183, the
    MAST-recommended mask) rather than ``QualityPolicy.DEFAULT`` (17087,
    Lightkurve-compatible) -- see ``app.data.quality_flags`` for the
    reasoning and the citations behind both values.
    """

    model_config = ConfigDict(frozen=True)

    quality_policy: QualityPolicy = PROJECT_DEFAULT_POLICY
    custom_quality_bitmask: int | None = None
    """Required when (and only when) ``quality_policy`` is
    ``QualityPolicy.CUSTOM``."""
    require_finite_time: bool = True
    require_finite_flux: bool = True
    require_finite_flux_err: bool = True

    @model_validator(mode="after")
    def _check_bitmask(self) -> Self:
        """Reject configurations whose mask would be ambiguous or
        silently ignored."""
        if self.quality_policy is QualityPolicy.CUSTOM:
            if self.custom_quality_bitmask is None:
                raise InvalidFilterConfigError(
                    "quality_policy='custom' requires custom_quality_bitmask to be set."
                )
            if self.custom_quality_bitmask < 0:
                raise InvalidFilterConfigError(
                    f"custom_quality_bitmask must be >= 0, got {self.custom_quality_bitmask}."
                )
        elif self.custom_quality_bitmask is not None:
            raise InvalidFilterConfigError(
                f"custom_quality_bitmask is only valid with quality_policy='custom', "
                f"but quality_policy={self.quality_policy.value!r} was given. "
                "A supplied mask is never silently ignored."
            )
        return self

    @property
    def active_bitmask(self) -> int:
        """The integer actually applied, via ``quality & active_bitmask``."""
        if self.quality_policy is QualityPolicy.CUSTOM:
            mask = self.custom_quality_bitmask
            if mask is None:  # pragma: no cover - prevented by the validator above
                raise InvalidFilterConfigError(
                    "quality_policy='custom' requires custom_quality_bitmask to be set."
                )
            return mask
        return POLICY_BITMASKS[self.quality_policy]


def config_from_policy_name(
    name: str,
    *,
    custom_quality_bitmask: int | None = None,
    require_finite_time: bool = True,
    require_finite_flux: bool = True,
    require_finite_flux_err: bool = True,
) -> QualityFilterConfig:
    """Build a ``QualityFilterConfig`` from a caller-supplied policy
    string (e.g. from the CLI), raising ``InvalidFilterConfigError``
    naming the valid options rather than a Pydantic ``ValidationError``.
    """
    try:
        policy = QualityPolicy(name)
    except ValueError as exc:
        valid = ", ".join(repr(option.value) for option in QualityPolicy)
        raise InvalidFilterConfigError(
            f"quality_policy={name!r} is not supported, expected one of {valid}."
        ) from exc
    return QualityFilterConfig(
        quality_policy=policy,
        custom_quality_bitmask=custom_quality_bitmask,
        require_finite_time=require_finite_time,
        require_finite_flux=require_finite_flux,
        require_finite_flux_err=require_finite_flux_err,
    )


class RejectedCadence(BaseModel):
    """One cadence that quality filtering removed, and exactly why.

    Every rejected cadence gets one of these records, so no observation
    is ever discarded silently or without an attributable rule.
    """

    model_config = ConfigDict(frozen=True)

    index: int
    """Row index in the source FITS table, preserving correspondence with
    the original file."""
    time: float
    """The original TIME value, preserved exactly (may be NaN or +/-inf,
    which is itself the rejection reason)."""
    quality: int
    """The cadence's original ``QUALITY`` integer, unmodified."""
    matched_quality_bits: int
    """``quality & config.active_bitmask`` -- the bits that actually
    triggered rejection. Zero when the cadence was rejected only for
    nonfinite values."""
    reasons: tuple[RejectionReason, ...]
    """Non-empty, in a fixed order (time, flux, flux error, quality) so
    results are deterministic. A cadence may carry several reasons."""


class QualityFilterStats(BaseModel):
    """Summary counts for one filtering run."""

    model_config = ConfigDict(frozen=True)

    total_cadences: int
    retained_cadences: int
    rejected_cadences: int
    rejected_by_reason: dict[RejectionReason, int]
    """Per-reason counts. **Not a partition**: one cadence can carry
    several reasons, so these sum to >= ``rejected_cadences``."""
    rejected_by_quality_bit: dict[int, int]
    """Per-bit counts of matched quality bits. Also not a partition, for
    the same reason."""

    @property
    def retained_fraction(self) -> float:
        """Fraction of input cadences retained; 0.0 for empty input."""
        if self.total_cadences == 0:
            return 0.0
        return self.retained_cadences / self.total_cadences


class ProcessingStep(BaseModel):
    """One recorded transformation, for end-to-end provenance.

    Deliberately carries no wall-clock timestamp: the result stays a pure
    function of its inputs, so a rerun on the same file with the same
    config is reproducible byte-for-byte. Run times belong in logs.
    """

    model_config = ConfigDict(frozen=True)

    step: str
    code_version: str
    quality_policy: QualityPolicy
    active_quality_bitmask: int
    """The resolved integer mask, recorded so provenance never has to be
    re-derived from the policy name."""
    config: QualityFilterConfig
    input_cadences: int
    output_cadences: int
    input_checksum_sha256: str
    """SHA-256 of the source FITS file, tying this step back to the exact
    bytes it consumed."""


class FilteredLightCurve(BaseModel):
    """Cadences of a ``RawLightCurve`` that survived quality filtering.

    Retained values are copies of the originals -- no arithmetic of any
    kind is applied, and the source ``RawLightCurve`` is never mutated.
    Provenance and metadata are carried over unchanged, so a filtered
    curve still points at the exact FITS file it came from.
    """

    model_config = ConfigDict(frozen=True)

    time: tuple[float, ...]
    flux: tuple[float, ...]
    flux_err: tuple[float, ...] | None
    quality: tuple[int, ...]
    source_indices: tuple[int, ...]
    """For each retained cadence, its row index in the original file."""
    flux_column: str
    provenance: FileProvenance
    metadata: FitsMetadata
    stats: QualityFilterStats
    rejected: tuple[RejectedCadence, ...]
    history: tuple[ProcessingStep, ...]

    @property
    def cadence_count(self) -> int:
        return len(self.time)


class GapDetectionConfig(BaseModel):
    """Configuration for one gap-detection and segmentation run (Phase 3B).

    Units: every duration here (``gap_tolerance`` and all values derived
    from it) is in the same unit as ``FilteredLightCurve.time`` -- TESS
    BJD **days**, per ``app.data.fits_parser``: the FITS ``TIMEDEL``
    keyword is read in days and only ``FitsMetadata.cadence_seconds`` is
    ever converted to seconds, for display. ``gap_segmentation`` converts
    that seconds value back to days internally to compare it with the
    measured (day-native) cadence; nothing here is expressed in seconds.
    """

    model_config = ConfigDict(frozen=True)

    gap_multiplier: float = 5.0
    """A cadence-to-cadence interval strictly greater than
    ``nominal_cadence * gap_multiplier + gap_tolerance`` is classified as
    a gap. Must exceed 1.0, or every ordinary cadence step would qualify."""
    gap_tolerance: float = 1e-6
    """Small absolute floating-point tolerance (in days) added to the gap
    threshold so ordinary cadence jitter is never misclassified as a gap.
    Also used, unscaled, as the tolerance for judging whether a gap's
    excess interval implies an additional observation interruption beyond
    what skipped source rows alone would explain (see
    ``GapReason.OBSERVATION_GAP``)."""
    cadence_disagreement_fraction: float = 0.01
    """Fractional difference above which the measured nominal cadence and
    the FITS metadata cadence are flagged as disagreeing in
    ``SegmentationStats.cadence_sources_agree``. Purely informational --
    metadata never overrides or suppresses a measured disagreement (see
    module docstring)."""
    missing_cadence_residual_tolerance: float = 0.25
    """How close ``actual_interval / nominal_cadence`` must be to a whole
    number (as a fraction of one cadence) before ``DetectedGap`` reports
    an ``estimated_missing_cadences`` count at all. Keeps the estimate
    from claiming false precision on an interval that is not close to an
    integer multiple of the nominal cadence. Must be in ``(0, 0.5)``."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.gap_multiplier <= 1.0:
            raise InvalidGapDetectionConfigError(
                f"gap_multiplier must be > 1.0, got {self.gap_multiplier}."
            )
        if self.gap_tolerance < 0:
            raise InvalidGapDetectionConfigError(
                f"gap_tolerance must be >= 0, got {self.gap_tolerance}."
            )
        if not 0 < self.cadence_disagreement_fraction < 1:
            raise InvalidGapDetectionConfigError(
                "cadence_disagreement_fraction must be in (0, 1), got "
                f"{self.cadence_disagreement_fraction}."
            )
        if not 0 < self.missing_cadence_residual_tolerance < 0.5:
            raise InvalidGapDetectionConfigError(
                "missing_cadence_residual_tolerance must be in (0, 0.5), got "
                f"{self.missing_cadence_residual_tolerance}."
            )
        return self


class GapReason(StrEnum):
    """Why a detected gap is believed to have occurred, derived only from
    ``FilteredLightCurve.source_indices`` and the retained TIME values --
    never inferred beyond what those two arrays can prove.

    A gap may carry both reasons at once (see
    ``app.data.gap_segmentation`` for exactly when).
    """

    OBSERVATION_GAP = "observation_gap"
    """The interval is not (fully) explained by rows an earlier step
    removed: either no source rows were skipped at all (the two retained
    cadences are adjacent in the original FITS table, so the time jump
    was already present between neighbouring source rows -- a genuine
    interruption in the observation itself, e.g. a downlink or safe-mode
    event), or rows were skipped but the interval still exceeds what
    those skipped rows alone would account for at the nominal cadence."""
    SOURCE_ROWS_REJECTED = "source_rows_rejected"
    """One or more original FITS rows between these two retained cadences
    were removed by an earlier processing step (their ``source_indices``
    are not adjacent), so at least part of the interval is attributable
    to filtering rather than to the telescope itself."""


class DetectedGap(BaseModel):
    """One interval between consecutive retained cadences that exceeded
    the configured gap threshold."""

    model_config = ConfigDict(frozen=True)

    before_position: int
    """Index into the input ``FilteredLightCurve``'s retained arrays of
    the cadence immediately before the gap."""
    after_position: int
    """Index into the input ``FilteredLightCurve``'s retained arrays of
    the cadence immediately after the gap. Always ``before_position + 1``."""
    before_source_index: int
    """Original FITS row index of the cadence immediately before the gap."""
    after_source_index: int
    """Original FITS row index of the cadence immediately after the gap."""
    time_before: float
    time_after: float
    actual_interval: float
    """``time_after - time_before``, in days."""
    nominal_cadence: float
    """The measured nominal cadence used to evaluate this gap, in days."""
    threshold: float
    """``nominal_cadence * gap_multiplier + gap_tolerance`` -- the exact
    value ``actual_interval`` was compared against."""
    interval_to_cadence_ratio: float
    """``actual_interval / nominal_cadence``."""
    reasons: tuple[GapReason, ...]
    """Non-empty, in a fixed order (``SOURCE_ROWS_REJECTED`` before
    ``OBSERVATION_GAP`` when both apply)."""
    skipped_source_rows: int
    """``after_source_index - before_source_index - 1``: FITS rows an
    earlier step removed between these two retained cadences. Zero when
    the two cadences were adjacent in the source file."""
    estimated_missing_cadences: int | None
    """``round(actual_interval / nominal_cadence) - 1``, floored at zero,
    reported only when that ratio is within
    ``GapDetectionConfig.missing_cadence_residual_tolerance`` of a whole
    number; ``None`` when the interval is not close enough to an integer
    multiple of the nominal cadence to avoid false precision."""


class LightCurveSegment(BaseModel):
    """One maximal run of consecutive retained cadences with no detected
    gap between any of them. Values are copies of the input
    ``FilteredLightCurve``'s retained arrays -- no arithmetic of any kind
    is applied."""

    model_config = ConfigDict(frozen=True)

    segment_number: int
    """1-indexed position of this segment among its ``SegmentedLightCurve``."""
    start_position: int
    """Index into the input ``FilteredLightCurve``'s retained arrays of
    this segment's first cadence."""
    end_position: int
    """Index into the input ``FilteredLightCurve``'s retained arrays of
    this segment's last cadence (inclusive)."""
    start_source_index: int
    """Original FITS row index of this segment's first cadence."""
    end_source_index: int
    """Original FITS row index of this segment's last cadence."""
    time: tuple[float, ...]
    flux: tuple[float, ...]
    flux_err: tuple[float, ...] | None
    quality: tuple[int, ...]
    source_indices: tuple[int, ...]

    @property
    def start_time(self) -> float:
        return self.time[0]

    @property
    def end_time(self) -> float:
        return self.time[-1]

    @property
    def cadence_count(self) -> int:
        return len(self.time)


class SegmentationStats(BaseModel):
    """Summary counts and cadence-estimation results for one segmentation
    run."""

    model_config = ConfigDict(frozen=True)

    total_cadences: int
    segment_count: int
    gap_count: int
    measured_nominal_cadence: float | None
    """Median of strictly positive, finite consecutive TIME differences,
    in days. ``None`` when fewer than two retained cadences exist to
    compute a difference from -- not an error (see
    ``app.data.gap_segmentation``'s edge-case handling)."""
    metadata_cadence_seconds: float | None
    """``FitsMetadata.cadence_seconds`` as parsed from the FITS
    ``TIMEDEL`` keyword, carried through unchanged for reference."""
    metadata_cadence_native: float | None
    """``metadata_cadence_seconds`` converted into TIME's native unit
    (days), so it is directly comparable with ``measured_nominal_cadence``."""
    cadence_sources_agree: bool | None
    """Whether ``measured_nominal_cadence`` and ``metadata_cadence_native``
    agree within ``GapDetectionConfig.cadence_disagreement_fraction``.
    ``None`` when either cadence is unavailable. This is purely
    informational: gap detection always uses the measured cadence, never
    the metadata value, so a disagreement is recorded but never silently
    changes behaviour."""
    total_estimated_missing_cadences: int
    """Sum of every gap's ``estimated_missing_cadences`` that could be
    defensibly estimated; gaps with no defensible estimate contribute
    zero rather than being guessed at."""


class GapDetectionStep(BaseModel):
    """One recorded Phase 3B transformation, for end-to-end provenance --
    the ``ProcessingStep`` equivalent for gap detection and segmentation.

    Deliberately carries no wall-clock timestamp: the result stays a pure
    function of its inputs, so a rerun on the same filtered light curve
    with the same config is reproducible byte-for-byte."""

    model_config = ConfigDict(frozen=True)

    step: str
    code_version: str
    config: GapDetectionConfig
    input_cadences: int
    output_segment_count: int
    output_gap_count: int
    input_checksum_sha256: str
    """SHA-256 of the original source FITS file, carried through from the
    input ``FilteredLightCurve``'s provenance."""


class SegmentedLightCurve(BaseModel):
    """A ``FilteredLightCurve`` divided into contiguous segments at every
    detected gap.

    Every retained value is a copy of the input ``FilteredLightCurve``'s
    values -- no arithmetic of any kind is applied, and the input is
    never mutated. ``history`` carries forward every prior processing
    step (e.g. Phase 3A's quality-filter step) plus this phase's own
    ``GapDetectionStep``, so full provenance survives segmentation."""

    model_config = ConfigDict(frozen=True)

    segments: tuple[LightCurveSegment, ...]
    gaps: tuple[DetectedGap, ...]
    stats: SegmentationStats
    flux_column: str
    provenance: FileProvenance
    metadata: FitsMetadata
    history: tuple[ProcessingStep | GapDetectionStep, ...]

    @property
    def cadence_count(self) -> int:
        return sum(segment.cadence_count for segment in self.segments)


class NormalizationConfig(BaseModel):
    """Configuration for one per-segment flux-normalization run (Phase 3C).

    Deliberately minimal: median-ratio normalization
    (``flux / segment_reference``) is the only supported algorithm, so
    there is no method selector here -- see ``app.data.normalization``'s
    module docstring for why.
    """

    model_config = ConfigDict(frozen=True)

    zero_reference_tolerance: float = 0.0
    """A segment's median reference is treated as ``ZERO_REFERENCE``
    when ``abs(reference) <= zero_reference_tolerance`` -- exact zero is
    always included regardless of this value. Must be >= 0."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if self.zero_reference_tolerance < 0:
            raise InvalidNormalizationConfigError(
                f"zero_reference_tolerance must be >= 0, got {self.zero_reference_tolerance}."
            )
        return self


class ReferenceIssue(StrEnum):
    """Why a segment's median flux reference could not be used to
    normalize it.

    Checked in this fixed order, so a value can only carry the first
    condition that applies to it:

    1. ``NO_FINITE_FLUX`` -- no cadence in the segment has a finite flux
       value, so no median can be computed at all.
    2. ``NONFINITE_REFERENCE`` -- a median *was* computed from finite
       values but is itself not finite. Only reachable through
       floating-point overflow when averaging the two central values of
       an even-length segment at extreme magnitude; see
       ``app.data.normalization`` for a worked example.
    3. ``ZERO_REFERENCE`` -- ``abs(reference) <= zero_reference_tolerance``
       (exact zero is always included, regardless of the configured
       tolerance).
    4. ``NEGATIVE_REFERENCE`` -- ``reference < 0`` and outside the zero
       tolerance. Dividing by a negative reference would reverse the
       direction of every flux variation in the segment (a downward
       change in raw flux would become an upward normalized feature),
       which is unsafe for any later transit analysis, so this is never
       treated as a successful normalization.
    """

    NO_FINITE_FLUX = "no_finite_flux"
    NONFINITE_REFERENCE = "nonfinite_reference"
    ZERO_REFERENCE = "zero_reference"
    NEGATIVE_REFERENCE = "negative_reference"


class SegmentNormalizationStats(BaseModel):
    """Per-segment diagnostic record for one normalization attempt."""

    model_config = ConfigDict(frozen=True)

    reference: float | None
    """The computed median reference, in the segment's native flux
    units. ``None`` only for ``NO_FINITE_FLUX`` (there is nothing to
    report a value for); otherwise always recorded -- even when
    invalid -- so a zero, negative, or nonfinite value is visible rather
    than hidden."""
    finite_flux_count: int
    """How many of the segment's cadences had a finite flux value and
    contributed to the median."""
    reference_valid: bool
    reference_issue: ReferenceIssue | None
    """``None`` exactly when ``reference_valid`` is ``True``."""


class NormalizedSegment(BaseModel):
    """One ``LightCurveSegment``'s normalization result.

    The original segment is embedded, not copied field-by-field, so
    TIME, original flux, original flux error, QUALITY, source indices,
    and segment/source-row boundaries are preserved by construction --
    there is exactly one copy of each, and nothing here can silently
    diverge from it.
    """

    model_config = ConfigDict(frozen=True)

    segment: LightCurveSegment
    normalized_flux: tuple[float, ...] | None
    """``flux / stats.reference`` for every cadence in ``segment.flux``,
    same order, same length. A cadence whose original flux was itself
    nonfinite (NaN or +/-inf) yields a nonfinite normalized value the
    same way -- it is never silently dropped or replaced. ``None``
    exactly when ``stats.reference_valid`` is ``False``; never partially
    populated."""
    normalized_flux_err: tuple[float, ...] | None
    """``flux_err / abs(stats.reference)`` for every cadence, or
    ``None`` when the input had no ``flux_err`` column at all, or when
    ``normalized_flux`` is ``None``."""
    stats: SegmentNormalizationStats


class NormalizationStats(BaseModel):
    """Summary counts for one normalization run."""

    model_config = ConfigDict(frozen=True)

    total_cadences: int
    segment_count: int
    normalized_segment_count: int
    invalid_segment_count: int
    invalid_by_issue: dict[ReferenceIssue, int]
    """Per-issue counts of segments that could not be normalized. Unlike
    ``QualityFilterStats.rejected_by_reason``, each segment carries at
    most one ``ReferenceIssue``, so this **is** a partition: its values
    sum to exactly ``invalid_segment_count``."""


class NormalizationStep(BaseModel):
    """One recorded Phase 3C transformation, for end-to-end provenance --
    the ``ProcessingStep``/``GapDetectionStep`` equivalent for
    normalization.

    Deliberately carries no wall-clock timestamp: the result stays a
    pure function of its inputs, so a rerun on the same segmented light
    curve with the same config is reproducible byte-for-byte."""

    model_config = ConfigDict(frozen=True)

    step: str
    code_version: str
    config: NormalizationConfig
    input_cadences: int
    input_segment_count: int
    normalized_segment_count: int
    input_checksum_sha256: str
    """SHA-256 of the original source FITS file, carried through from the
    input ``SegmentedLightCurve``'s provenance."""


class NormalizedLightCurve(BaseModel):
    """A ``SegmentedLightCurve`` with each segment independently
    normalized to a median-ratio flux scale.

    Every cadence from the input is present in exactly one
    ``NormalizedSegment``; no value is removed, reordered, or duplicated,
    and the input is never mutated. ``gaps`` is carried through
    unchanged. ``history`` carries forward every prior processing step
    (Phase 3A's ``ProcessingStep``, Phase 3B's ``GapDetectionStep``) plus
    this phase's own ``NormalizationStep``, so full provenance survives
    normalization."""

    model_config = ConfigDict(frozen=True)

    segments: tuple[NormalizedSegment, ...]
    gaps: tuple[DetectedGap, ...]
    stats: NormalizationStats
    flux_column: str
    provenance: FileProvenance
    metadata: FitsMetadata
    history: tuple[ProcessingStep | GapDetectionStep | NormalizationStep, ...]

    @property
    def cadence_count(self) -> int:
        return sum(segment.segment.cadence_count for segment in self.segments)


class OutlierDirection(StrEnum):
    """Which side of a segment's robust center a flagged cadence fell on."""

    HIGH = "high"
    """``normalized_flux`` is unusually far *above* the segment's robust
    center -- a positive spike (cosmic ray, momentum-dump artifact, etc.).
    Flagged by default."""
    LOW = "low"
    """``normalized_flux`` is unusually far *below* the segment's robust
    center. A real planetary transit is a downward brightness change, so
    low-side detection is disabled by default -- see
    ``OutlierDetectionConfig.lower_threshold``."""


class OutlierAnalysisStatus(StrEnum):
    """The outcome of attempting robust per-cadence statistical analysis
    on one segment. Every status other than ``VALID`` still preserves the
    segment and produces an all-``False`` statistical-outlier mask --
    analysis is simply not attempted, never approximated or guessed at.
    """

    VALID = "valid"
    """Enough finite normalized-flux values existed and the robust scale
    was usable; every finite value received a ``robust_score``."""
    INSUFFICIENT_DATA = "insufficient_data"
    """Fewer finite normalized-flux values than
    ``OutlierDetectionConfig.minimum_finite_cadences`` -- e.g. a
    one-cadence segment. A median/MAD computed from too few points is not
    trustworthy enough to score anything against."""
    ZERO_SCALE = "zero_scale"
    """The segment's robust scale (``1.4826 * MAD``) is not finite, or is
    at or below ``OutlierDetectionConfig.minimum_robust_scale`` -- e.g. a
    constant or near-constant segment. Dividing by it would either raise
    or invent meaningless scores, so none are computed."""
    NORMALIZATION_UNAVAILABLE = "normalization_unavailable"
    """The embedded ``NormalizedSegment.normalized_flux`` is ``None``
    (Phase 3C could not normalize this segment -- see ``ReferenceIssue``).
    There is nothing to analyze; the Phase 3C reference issue is still
    visible on the embedded segment."""


class OutlierReason(StrEnum):
    """Why one cadence received a ``FlaggedCadence`` record. Kept
    disjoint from ``OutlierDirection``/``OutlierAnalysisStatus`` so a
    missing measurement is never conflated with a statistically unusual
    one: a nonfinite value means *no usable robust score could be
    computed*, while a high/low reason means *a score was computed and it
    exceeded a configured threshold*."""

    HIGH_STATISTICAL_OUTLIER = "high_statistical_outlier"
    LOW_STATISTICAL_OUTLIER = "low_statistical_outlier"
    NONFINITE_NORMALIZED_FLUX = "nonfinite_normalized_flux"
    """``normalized_flux`` at this position is NaN or +/-inf. Never
    classified as a high or low statistical outlier -- there is no finite
    value to score. Phase 3A's default configuration
    (``require_finite_flux=True``) normally prevents this from ever
    reaching Phase 3D, but defensive handling remains necessary for
    light curves quality-filtered with ``require_finite_flux=False`` or
    ``NormalizedSegment``/``NormalizedLightCurve`` objects constructed
    directly."""


class OutlierDetectionConfig(BaseModel):
    """Configuration for one per-segment robust outlier-flagging run
    (Phase 3D).

    This stage never removes, replaces, or reorders a cadence -- it only
    attaches transparent flags that later stages may choose whether to
    use. Downward (``LOW``) detection is disabled by default
    (``lower_threshold=None``) because a real planetary transit is itself
    a downward brightness change: a generic two-sided clipping rule could
    erase the exact signal this project searches for. A caller may
    explicitly enable it, but doing so can flag possible transits along
    with genuine instrumental artifacts.
    """

    model_config = ConfigDict(frozen=True)

    upper_threshold: float = 5.0
    """A finite normalized value is a high outlier when
    ``robust_score > upper_threshold``. Must be finite and strictly
    positive. High-side (positive-spike) detection is always active --
    there is no way to disable it, since it can never mask a transit
    signal."""
    lower_threshold: float | None = None
    """When not ``None``, a finite normalized value is a low outlier when
    ``robust_score < -lower_threshold``. Must be finite and strictly
    positive when enabled. **Disabled by default** -- enabling this can
    flag possible transit signals, since a transit is itself a downward
    brightness change. Only enable it with a clear understanding that any
    resulting low-outlier flags may include real astrophysical signal,
    not just artifacts."""
    minimum_finite_cadences: int = 5
    """A segment needs at least this many finite normalized-flux values
    before its median/MAD are trusted enough to score anything against.
    Must be a positive integer. Segments with fewer are recorded as
    ``OutlierAnalysisStatus.INSUFFICIENT_DATA``, not analyzed."""
    minimum_robust_scale: float = 0.0
    """A segment's robust scale (``1.4826 * MAD``) must be finite and
    strictly greater than this value to be trusted for scoring -- the
    same "invalid unless proven otherwise" convention as
    ``NormalizationConfig.zero_reference_tolerance``. The default (0.0)
    only rejects an exactly-zero (perfectly constant) scale; raising it
    also rejects a near-zero scale from an almost-constant segment. Must
    be finite and >= 0."""
    flag_nonfinite_normalized_flux: bool = True
    """Whether a nonfinite ``normalized_flux`` position gets its own
    ``FlaggedCadence`` record (reason
    ``OutlierReason.NONFINITE_NORMALIZED_FLUX``) for traceability. Such
    positions are never counted as high/low statistical outliers and
    never set ``high_outlier_mask``/``low_outlier_mask`` either way; this
    only controls whether they additionally appear in
    ``flagged_cadences``."""

    @model_validator(mode="after")
    def _validate(self) -> Self:
        if not isfinite(self.upper_threshold) or self.upper_threshold <= 0:
            raise InvalidOutlierDetectionConfigError(
                f"upper_threshold must be finite and > 0, got {self.upper_threshold}."
            )
        if self.lower_threshold is not None and (
            not isfinite(self.lower_threshold) or self.lower_threshold <= 0
        ):
            raise InvalidOutlierDetectionConfigError(
                f"lower_threshold must be None or finite and > 0, got {self.lower_threshold}."
            )
        if self.minimum_finite_cadences < 1:
            raise InvalidOutlierDetectionConfigError(
                "minimum_finite_cadences must be a positive integer, got "
                f"{self.minimum_finite_cadences}."
            )
        if not isfinite(self.minimum_robust_scale) or self.minimum_robust_scale < 0:
            raise InvalidOutlierDetectionConfigError(
                f"minimum_robust_scale must be finite and >= 0, got {self.minimum_robust_scale}."
            )
        return self


class FlaggedCadence(BaseModel):
    """One cadence that outlier detection flagged, and exactly why.

    Traceable back through every earlier stage: ``segment_number`` and
    ``position_in_segment`` locate it within its ``LightCurveSegment``;
    ``filtered_position`` locates it within Phase 3B's retained-cadence
    arrays; ``source_index`` locates it in the original FITS table.
    """

    model_config = ConfigDict(frozen=True)

    segment_number: int
    position_in_segment: int
    """0-indexed position within the segment's own arrays."""
    filtered_position: int
    """``segment.start_position + position_in_segment`` -- index into the
    Phase 3B ``FilteredLightCurve``'s retained arrays."""
    source_index: int
    """Original FITS row index (``segment.source_indices[position_in_segment]``)."""
    time: float
    normalized_flux: float
    """The Phase 3C normalized flux value at this position, preserved
    exactly (may itself be NaN or +/-inf when ``reason`` is
    ``NONFINITE_NORMALIZED_FLUX``)."""
    robust_score: float | None
    """``(normalized_flux - center) / robust_scale``. ``None`` exactly
    when ``reason`` is ``NONFINITE_NORMALIZED_FLUX`` -- no meaningful
    score exists for a nonfinite input."""
    direction: OutlierDirection | None
    """``None`` exactly when ``reason`` is ``NONFINITE_NORMALIZED_FLUX``."""
    threshold: float | None
    """The configured threshold this cadence's ``robust_score`` exceeded
    (``upper_threshold`` or ``lower_threshold``, always positive; compare
    against ``-threshold`` for a low outlier). ``None`` exactly when
    ``reason`` is ``NONFINITE_NORMALIZED_FLUX``."""
    reason: OutlierReason


class SegmentOutlierStats(BaseModel):
    """Per-segment diagnostic record for one outlier-detection attempt."""

    model_config = ConfigDict(frozen=True)

    status: OutlierAnalysisStatus
    finite_values_analyzed: int
    """How many of the segment's ``normalized_flux`` values were finite
    and contributed to ``center``/``raw_mad``. Zero when
    ``status is NORMALIZATION_UNAVAILABLE``."""
    center: float | None
    """``median(finite normalized flux values)``. Recorded whenever at
    least one finite value exists -- even for ``INSUFFICIENT_DATA`` or
    ``ZERO_SCALE`` -- so nothing is hidden; ``None`` only when there is no
    finite value to compute it from at all."""
    raw_mad: float | None
    """``median(abs(value - center))``, unscaled. ``None`` under the same
    condition as ``center``."""
    robust_scale: float | None
    """``1.4826 * raw_mad`` -- the Gaussian-consistency scaling
    convention for MAD (an unbiased estimator of the standard deviation
    *if* the underlying distribution were exactly Gaussian; TESS
    photometric noise is not claimed to be). ``None`` under the same
    condition as ``center``."""
    high_outlier_count: int
    low_outlier_count: int
    """Always 0 when low-side detection is disabled
    (``OutlierDetectionConfig.lower_threshold is None``)."""
    nonfinite_flagged_count: int
    """How many positions received a ``NONFINITE_NORMALIZED_FLUX``
    record. Always 0 when
    ``OutlierDetectionConfig.flag_nonfinite_normalized_flux`` is
    ``False``, regardless of how many nonfinite values are actually
    present."""


class OutlierFlaggedSegment(BaseModel):
    """One ``NormalizedSegment``'s outlier-flagging result.

    The Phase 3C ``NormalizedSegment`` is embedded, not copied
    field-by-field, so TIME, original flux, normalized flux, QUALITY,
    source indices, and every earlier stage's output are preserved by
    construction. No cadence is ever removed, replaced, or reordered by
    this model or the module that builds it -- every mask has exactly one
    entry per cadence in ``normalized.segment``.
    """

    model_config = ConfigDict(frozen=True)

    normalized: NormalizedSegment
    outlier_mask: tuple[bool, ...]
    """``True`` at every position classified as a high **or** low
    statistical outlier (``high_outlier_mask[i] or (low_outlier_mask or
    ...)[i]``). Never ``True`` at a nonfinite-flagged position -- that is
    a distinct, disjoint reason (see ``OutlierReason``). All-``False``
    when ``stats.status is not VALID``."""
    high_outlier_mask: tuple[bool, ...]
    """``True`` exactly where ``robust_score > upper_threshold``.
    All-``False`` when ``stats.status is not VALID``."""
    low_outlier_mask: tuple[bool, ...] | None
    """``True`` exactly where ``robust_score < -lower_threshold``.
    ``None`` -- not an all-``False`` tuple -- when
    ``OutlierDetectionConfig.lower_threshold is None``, so "low-side
    detection was never run" is never confused with "low-side detection
    ran and found nothing"."""
    flagged_cadences: tuple[FlaggedCadence, ...]
    """One record per ``True`` position in ``high_outlier_mask`` or (when
    enabled) ``low_outlier_mask``, plus one per nonfinite-flagged position
    (when enabled), in ascending ``position_in_segment`` order."""
    stats: SegmentOutlierStats


class OutlierDetectionStats(BaseModel):
    """Summary counts for one outlier-detection run."""

    model_config = ConfigDict(frozen=True)

    total_cadences: int
    segment_count: int
    analyzed_segment_count: int
    """Segments with ``stats.status is VALID``."""
    unanalyzed_by_status: dict[OutlierAnalysisStatus, int]
    """Per-status counts of segments that were *not* ``VALID`` (so
    ``OutlierAnalysisStatus.VALID`` never appears as a key). Each segment
    carries exactly one status, so this is a partition: its values sum to
    exactly ``segment_count - analyzed_segment_count``."""
    total_high_outliers: int
    total_low_outliers: int
    """Always 0 when low-side detection is disabled."""
    total_nonfinite_flagged: int


class OutlierDetectionStep(BaseModel):
    """One recorded Phase 3D transformation, for end-to-end provenance --
    the ``ProcessingStep``/``GapDetectionStep``/``NormalizationStep``
    equivalent for outlier flagging.

    Deliberately carries no wall-clock timestamp: the result stays a pure
    function of its inputs, so a rerun on the same normalized light curve
    with the same config is reproducible byte-for-byte."""

    model_config = ConfigDict(frozen=True)

    step: str
    code_version: str
    config: OutlierDetectionConfig
    input_cadences: int
    input_segment_count: int
    analyzed_segment_count: int
    flagged_cadence_count: int
    """Total ``FlaggedCadence`` records across every segment (high + low +
    nonfinite, when each is applicable/enabled)."""
    input_checksum_sha256: str
    """SHA-256 of the original source FITS file, carried through from the
    input ``NormalizedLightCurve``'s provenance."""


class OutlierFlaggedLightCurve(BaseModel):
    """A ``NormalizedLightCurve`` with each segment independently
    analyzed for statistically unusual normalized flux values.

    This is a flagging stage, not a removal stage: every cadence from the
    input is present in exactly one ``OutlierFlaggedSegment``, in the
    same order, with the same TIME/flux/normalized-flux/QUALITY/source
    index values -- nothing is deleted, replaced, interpolated, or
    reordered. ``gaps`` is carried through unchanged. ``history`` carries
    forward every prior processing step (Phase 3A's ``ProcessingStep``,
    Phase 3B's ``GapDetectionStep``, Phase 3C's ``NormalizationStep``)
    plus this phase's own ``OutlierDetectionStep``, so full provenance
    survives outlier flagging."""

    model_config = ConfigDict(frozen=True)

    segments: tuple[OutlierFlaggedSegment, ...]
    gaps: tuple[DetectedGap, ...]
    stats: OutlierDetectionStats
    flux_column: str
    provenance: FileProvenance
    metadata: FitsMetadata
    history: tuple[
        ProcessingStep | GapDetectionStep | NormalizationStep | OutlierDetectionStep, ...
    ]

    @property
    def cadence_count(self) -> int:
        return sum(segment.normalized.segment.cadence_count for segment in self.segments)
