"""Deterministic selection of one downloadable light-curve product.

Phase 2A's ``MastClient.search_target`` resolves a target to a list of
*observations* (one row per sector/pipeline combination). Each observation
can have several *products* on MAST (the light curve itself, a target-pixel
file, a data-validation report, preview images, ...); this module narrows
that down to exactly one downloadable light-curve product, using rules
that are documented here rather than picking arbitrarily when several
products match.

Selection rules, applied in order:

1. Only observations with ``dataproduct_type == "timeseries"`` are
   considered -- full-frame images and other non-timeseries products are
   never downloadable light curves.
2. Any ``--sector``, ``--author``, or ``--cadence`` filters the caller
   supplied are applied; observations that don't match are dropped.
3. Remaining observations are tried in a fixed priority order: pipeline
   SPOC, then TESS-SPOC, then QLP, then anything else alphabetically;
   within the same pipeline, ascending sector, then ``obs_id``.
4. For each observation (in that order), its MAST product list is
   filtered to science light-curve rows: ``productSubGroupDescription
   == "LC"`` (SPOC / TESS-SPOC), or -- for pipelines that don't set that
   field, e.g. QLP -- a filename ending in ``_lc.fits`` or ``_llc.fits``.
5. The first observation with at least one matching product wins; among
   its matching products, the one with the alphabetically-first filename
   is selected (SPOC/TESS-SPOC observations normally have exactly one).
6. If no observation yields a matching product, ``TargetNotFoundError``
   is raised, naming the filters that were applied.
"""

from collections.abc import Callable, Sequence
from typing import Any

from app.data.exceptions import TargetNotFoundError
from app.data.models import SelectedProduct, TessObservation

_PIPELINE_PRIORITY = {"SPOC": 0, "TESS-SPOC": 1, "QLP": 2}


def select_product(
    observations: Sequence[TessObservation],
    list_products: Callable[[str], list[dict[str, Any]]],
    *,
    tic_id: int | None,
    sector: int | None = None,
    author: str | None = None,
    cadence_seconds: float | None = None,
) -> SelectedProduct:
    """Pick one downloadable light-curve product for ``observations``.

    ``list_products`` is called with an observation's ``obs_id`` and must
    return MAST's raw product rows for it (as from
    ``Observations.get_product_list``); it is injected so this function
    never touches the network directly and can be unit-tested with a
    fake.
    """
    candidates = [obs for obs in observations if obs.dataproduct_type == "timeseries"]
    if sector is not None:
        candidates = [obs for obs in candidates if obs.sector == sector]
    if author is not None:
        candidates = [obs for obs in candidates if (obs.author or "").upper() == author.upper()]
    if cadence_seconds is not None:
        candidates = [
            obs
            for obs in candidates
            if obs.cadence_seconds is not None and abs(obs.cadence_seconds - cadence_seconds) < 1e-6
        ]

    ordered = sorted(
        candidates,
        key=lambda obs: (
            *_pipeline_rank(obs.author),
            obs.sector if obs.sector is not None else -1,
            obs.obs_id,
        ),
    )

    for obs in ordered:
        rows = [row for row in list_products(obs.obs_id) if _is_light_curve_row(row)]
        if not rows:
            continue
        rows.sort(key=lambda row: str(row.get("productFilename") or ""))
        return _row_to_selected_product(rows[0], obs, tic_id=tic_id)

    raise TargetNotFoundError(
        f"No downloadable light-curve product found{_describe_filters(sector, author, cadence_seconds)}."
    )


def _pipeline_rank(author: str | None) -> tuple[int, str]:
    name = (author or "").upper()
    return (_PIPELINE_PRIORITY.get(name, len(_PIPELINE_PRIORITY)), name)


def _is_light_curve_row(row: dict[str, Any]) -> bool:
    subgroup = str(row.get("productSubGroupDescription") or "").strip().upper()
    if subgroup == "LC":
        return True
    filename = str(row.get("productFilename") or "").strip().lower()
    return filename.endswith("_lc.fits") or filename.endswith("_llc.fits")


def _row_to_selected_product(
    row: dict[str, Any], obs: TessObservation, *, tic_id: int | None
) -> SelectedProduct:
    size = row.get("size")
    description = row.get("description")
    return SelectedProduct(
        obs_id=obs.obs_id,
        tic_id=tic_id,
        sector=obs.sector,
        author=obs.author,
        cadence_seconds=obs.cadence_seconds,
        filename=str(row.get("productFilename") or ""),
        data_uri=str(row.get("dataURI") or row.get("dataUri") or ""),
        size_bytes=int(size) if isinstance(size, int | float) else None,
        description=str(description).strip() or None if description is not None else None,
    )


def _describe_filters(sector: int | None, author: str | None, cadence_seconds: float | None) -> str:
    parts = []
    if sector is not None:
        parts.append(f"sector={sector}")
    if author is not None:
        parts.append(f"author={author}")
    if cadence_seconds is not None:
        parts.append(f"cadence={cadence_seconds}")
    return f" matching {', '.join(parts)}" if parts else ""
