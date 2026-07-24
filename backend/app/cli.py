"""Command-line entry points for the Exoplanet Hunter backend.

Run with ``python -m app.cli <command> ...``. This phase (2A) only
implements TESS target/observation discovery -- no downloads, no
preprocessing. See ``docs/architecture.md`` for the full roadmap.
"""

import argparse
import sys
from collections.abc import Sequence

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.data.exceptions import InvalidTargetError, MastServiceError, TargetNotFoundError
from app.data.mast_client import MastClient
from app.data.models import TargetSearchResult

logger = get_logger(__name__)

_EXIT_OK = 0
_EXIT_NOT_FOUND = 1
_EXIT_INVALID_TARGET = 2
_EXIT_SERVICE_ERROR = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Exoplanet Hunter CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser(
        "search-target",
        help="Search MAST for TESS observations of a target (discovery only, no downloads).",
    )
    search_parser.add_argument(
        "--target",
        required=True,
        help="TIC identifier (e.g. 'TIC 261136679') or a resolvable target name (e.g. 'Pi Mensae').",
    )
    return parser


def format_search_result(result: TargetSearchResult) -> str:
    """Render a ``TargetSearchResult`` as a human-readable report."""
    sectors = ", ".join(str(sector) for sector in result.sectors) or "none"
    lines = [
        f"Query:                 {result.query}",
        f"Resolved target:       {result.resolved_target}",
        f"TIC ID:                {result.tic_id if result.tic_id is not None else 'unknown'}",
        f"Matching observations: {result.observation_count}",
        f"Available sectors:     {sectors}",
        "",
        "Observations:",
    ]
    for obs in result.observations:
        sector_label = obs.sector if obs.sector is not None else "?"
        cadence = f"{obs.cadence_seconds:.1f}s" if obs.cadence_seconds is not None else "unknown"
        lines.append(
            f"  - sector={sector_label} mission={obs.mission} "
            f"product={obs.dataproduct_type} author={obs.author or 'unknown'} "
            f"cadence={cadence} obs_id={obs.obs_id}"
        )
    return "\n".join(lines)


def run_search_target(target: str, client: MastClient | None = None) -> int:
    """Run the ``search-target`` command; returns a process exit code."""
    active_client = client or MastClient()
    try:
        result = active_client.search_target(target)
    except InvalidTargetError as exc:
        print(f"Invalid target: {exc}", file=sys.stderr)
        return _EXIT_INVALID_TARGET
    except TargetNotFoundError as exc:
        print(f"Target not found: {exc}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    except MastServiceError as exc:
        print(f"MAST service error: {exc}", file=sys.stderr)
        return _EXIT_SERVICE_ERROR

    print(format_search_result(result))
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging(get_settings())
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "search-target":
        return run_search_target(args.target)

    parser.error(f"Unknown command: {args.command}")
    return _EXIT_INVALID_TARGET


if __name__ == "__main__":
    raise SystemExit(main())
