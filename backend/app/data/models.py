"""Typed models for TESS target and observation discovery results."""

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
