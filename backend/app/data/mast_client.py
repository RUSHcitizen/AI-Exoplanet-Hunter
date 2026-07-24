"""TESS/MAST target and observation discovery (Phase 2A).

This module resolves a target -- a TIC identifier or a resolvable target
name -- to the set of TESS observations MAST knows about for it: which
sectors were observed, which pipeline produced each product, and at what
cadence. It performs discovery only: no FITS files are downloaded and no
light curves are parsed. That is a later phase (see
``docs/architecture.md``).

Network access is isolated behind ``MastGateway`` (a ``Protocol``), so
``MastClient`` -- the typed business-logic layer -- can be unit-tested
with a fake gateway that never touches the network.
``AstroqueryMastGateway`` is the real implementation, built on
astroquery's MAST interface (https://astroquery.readthedocs.io/en/latest/mast/mast.html).

Column semantics reused from astroquery's ``Observations.query_criteria``
/ ``query_object`` as our typed field names:

- ``sequence_number``  -> TESS sector number
- ``provenance_name``  -> pipeline/author that produced the product
                          (e.g. SPOC, TESS-SPOC, QLP)
- ``t_exptime``         -> cadence, in seconds
- ``obs_collection``    -> mission (e.g. "TESS")
- ``dataproduct_type``  -> product type (e.g. "timeseries", "image")
"""

import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.logging import get_logger
from app.data.exceptions import InvalidTargetError, MastServiceError, TargetNotFoundError
from app.data.models import TargetSearchResult, TessObservation

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
TESS_COLLECTION = "TESS"
_NAME_SEARCH_RADIUS = "0.02 deg"

_TIC_PATTERN = re.compile(r"^(?:tic\s*-?\s*)?(\d+)$", re.IGNORECASE)
_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .+-]{0,99}$")


class MastGateway(Protocol):
    """The subset of astroquery's MAST API this module depends on."""

    def query_by_tic(self, tic_id: int) -> list[dict[str, Any]]: ...

    def query_by_name(self, name: str) -> list[dict[str, Any]]: ...


class AstroqueryMastGateway:
    """Real MAST access via astroquery.

    astroquery/astropy are imported lazily (inside ``_run``) so building
    a ``MastClient`` with an injected fake gateway never requires the
    optional ``mast`` dependency group to be installed.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def query_by_tic(self, tic_id: int) -> list[dict[str, Any]]:
        return self._run(
            f"TIC {tic_id}",
            lambda obs: obs.query_criteria(obs_collection=TESS_COLLECTION, target_name=str(tic_id)),
        )

    def query_by_name(self, name: str) -> list[dict[str, Any]]:
        def _query(obs: Any) -> Any:
            table = obs.query_object(name, radius=_NAME_SEARCH_RADIUS)
            return table[table["obs_collection"] == TESS_COLLECTION]

        return self._run(name, _query)

    def _run(self, target_label: str, query: Callable[[Any], Any]) -> list[dict[str, Any]]:
        from astropy.coordinates.name_resolve import NameResolveError
        from astroquery.exceptions import NoResultsWarning
        from astroquery.mast import Conf, Observations

        try:
            Conf.timeout = self._timeout_seconds
        except AttributeError:
            logger.debug("mast_timeout_config_unavailable")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", NoResultsWarning)
                table = query(Observations)
        except NameResolveError as exc:
            raise TargetNotFoundError(
                f"Could not resolve target name {target_label!r}: {exc}"
            ) from exc
        except Exception as exc:
            # astroquery/requests raise many exception types for network
            # failures (timeouts, connection errors, unexpected responses);
            # callers only need to know the service call failed.
            raise MastServiceError(f"MAST query failed for {target_label!r}: {exc}") from exc

        return _rows_from_table(table)


def _rows_from_table(table: Any) -> list[dict[str, Any]]:
    return [
        {col: (None if _is_masked(record[col]) else record[col]) for col in table.colnames}
        for record in table
    ]


def _is_masked(value: Any) -> bool:
    return bool(getattr(value, "mask", False))


@dataclass(frozen=True)
class _TicQuery:
    tic_id: int


@dataclass(frozen=True)
class _NameQuery:
    name: str


def _parse_target(raw: str) -> _TicQuery | _NameQuery:
    target = raw.strip()
    if not target:
        raise InvalidTargetError("Target must not be empty.")

    tic_match = _TIC_PATTERN.match(target)
    if tic_match:
        tic_id = int(tic_match.group(1))
        if tic_id <= 0:
            raise InvalidTargetError(f"Invalid TIC identifier: {raw!r}.")
        return _TicQuery(tic_id=tic_id)

    if not _NAME_PATTERN.match(target):
        raise InvalidTargetError(
            f"Unsupported target format: {raw!r}. Use a TIC identifier "
            "(e.g. 'TIC 261136679') or a resolvable target name (e.g. 'Pi Mensae')."
        )
    return _NameQuery(name=target)


class MastClient:
    """Typed, testable interface for TESS target/observation discovery."""

    def __init__(
        self,
        gateway: MastGateway | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._gateway: MastGateway = gateway or AstroqueryMastGateway(
            timeout_seconds=timeout_seconds
        )

    def search_target(self, target: str) -> TargetSearchResult:
        parsed = _parse_target(target)

        resolved_target: str
        tic_id: int | None
        if isinstance(parsed, _TicQuery):
            logger.info("mast_search_started", query=target, kind="tic", tic_id=parsed.tic_id)
            rows = self._gateway.query_by_tic(parsed.tic_id)
            resolved_target = f"TIC {parsed.tic_id}"
            tic_id = parsed.tic_id
        else:
            logger.info("mast_search_started", query=target, kind="name")
            rows = self._gateway.query_by_name(parsed.name)
            resolved_target, tic_id = _resolve_name_search(rows, fallback=parsed.name)

        if not rows:
            logger.warning("mast_search_no_results", query=target)
            raise TargetNotFoundError(f"No TESS observations found for target {target!r}.")

        observations = tuple(_row_to_observation(row) for row in rows)
        result = TargetSearchResult(
            query=target,
            resolved_target=resolved_target,
            tic_id=tic_id,
            observations=observations,
        )
        logger.info(
            "mast_search_completed",
            query=target,
            observation_count=result.observation_count,
            sectors=result.sectors,
        )
        return result


def _row_to_observation(row: dict[str, Any]) -> TessObservation:
    return TessObservation(
        obs_id=str(row.get("obsid", row.get("obs_id", ""))),
        target_name=str(row.get("target_name", "")),
        mission=str(row.get("obs_collection", "")),
        dataproduct_type=str(row.get("dataproduct_type", "")),
        sector=_clean_int(row.get("sequence_number")),
        author=_clean_str(row.get("provenance_name")),
        cadence_seconds=_clean_float(row.get("t_exptime")),
        calib_level=_clean_int(row.get("calib_level")),
    )


def _extract_tic_id(target_name: str) -> int | None:
    match = _TIC_PATTERN.match(target_name.strip())
    return int(match.group(1)) if match else None


def _resolve_name_search(rows: list[dict[str, Any]], fallback: str) -> tuple[str, int | None]:
    """Pick a resolved target label and TIC ID from a name-based search.

    A cone search returns every product near the resolved coordinates,
    including full-frame-image rows whose ``target_name`` is a generic
    label like "TESS FFI" rather than the star's TIC ID. Prefer the
    first row that actually carries a numeric TIC ID so the reported
    identity is meaningful.
    """
    for row in rows:
        target_name = str(row.get("target_name", "")).strip()
        tic_id = _extract_tic_id(target_name)
        if tic_id is not None:
            return target_name, tic_id

    if rows:
        return str(rows[0].get("target_name", "")).strip() or fallback, None
    return fallback, None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
