"""Typed models for TESS target/observation discovery, download, and FITS
parsing results."""

from pydantic import BaseModel, ConfigDict


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
