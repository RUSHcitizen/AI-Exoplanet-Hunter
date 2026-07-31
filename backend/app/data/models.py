"""Typed models for TESS target/observation discovery, download, FITS
parsing, and quality-filtering results."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.data.exceptions import (
    InvalidFilterConfigError,
    InvalidGapDetectionConfigError,
    InvalidNormalizationConfigError,
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
