"""Typed models for TESS target/observation discovery, download, FITS
parsing, and quality-filtering results."""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.data.exceptions import InvalidFilterConfigError
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
