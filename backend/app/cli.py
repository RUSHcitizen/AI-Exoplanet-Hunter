"""Command-line entry points for the Exoplanet Hunter backend.

Run with ``python -m app.cli <command> ...``. Phase 2A implements TESS
target/observation discovery; Phase 2B adds downloading and parsing one
selected light-curve product. No preprocessing, transit search, or ML
happens here yet. See ``docs/architecture.md`` for the full roadmap.
"""

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.data.downloader import LightCurveDownloader
from app.data.exceptions import (
    DownloadError,
    FitsError,
    InvalidTargetError,
    MastServiceError,
    TargetNotFoundError,
)
from app.data.fits_parser import parse_light_curve
from app.data.mast_client import MastClient
from app.data.models import CachedArtifact, RawLightCurve, TargetSearchResult
from app.data.product_selection import select_product

logger = get_logger(__name__)

_EXIT_OK = 0
_EXIT_NOT_FOUND = 1
_EXIT_INVALID_TARGET = 2
_EXIT_SERVICE_ERROR = 3
_EXIT_DOWNLOAD_ERROR = 4
_EXIT_FITS_ERROR = 5


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

    download_parser = subparsers.add_parser(
        "download-target",
        help=(
            "Download one TESS light-curve FITS product for a target "
            "(deterministic selection, cached locally; discovery only, no parsing)."
        ),
    )
    download_parser.add_argument(
        "--target",
        required=True,
        help="TIC identifier (e.g. 'TIC 261136679') or a resolvable target name (e.g. 'Pi Mensae').",
    )
    download_parser.add_argument(
        "--sector", type=int, default=None, help="Restrict selection to this TESS sector."
    )
    download_parser.add_argument(
        "--author",
        default=None,
        help="Restrict selection to this pipeline/author (e.g. SPOC, TESS-SPOC, QLP).",
    )
    download_parser.add_argument(
        "--cadence",
        type=float,
        default=None,
        help="Restrict selection to this cadence, in seconds.",
    )
    download_parser.add_argument(
        "--output-dir",
        default=None,
        help="Local cache directory root (default: the mast_cache_dir setting).",
    )
    download_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if a valid cached copy already exists.",
    )

    inspect_parser = subparsers.add_parser(
        "inspect-fits",
        help="Summarize a downloaded TESS light-curve FITS file (descriptive only).",
    )
    inspect_parser.add_argument("fits_path", help="Path to a cached TESS light-curve FITS file.")

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


def format_download_result(artifact: CachedArtifact, resolved_target: str) -> str:
    """Render a ``CachedArtifact`` as a human-readable download report."""
    product = artifact.product
    cadence = (
        f"{product.cadence_seconds:.1f}s" if product.cadence_seconds is not None else "unknown"
    )
    source = "downloaded" if artifact.was_downloaded else "reused from cache"
    return "\n".join(
        [
            f"Resolved target:  {resolved_target}",
            f"Selected product: {product.filename}",
            f"TESS sector:      {product.sector if product.sector is not None else 'unknown'}",
            f"Pipeline/author:  {product.author or 'unknown'}",
            f"Cadence:          {cadence}",
            f"Local path:       {artifact.local_path}",
            f"File size:        {artifact.size_bytes} bytes",
            f"SHA-256:          {artifact.sha256}",
            f"Source:           {source}",
        ]
    )


def run_download_target(
    target: str,
    *,
    sector: int | None = None,
    author: str | None = None,
    cadence: float | None = None,
    output_dir: str | None = None,
    force: bool = False,
    client: MastClient | None = None,
    downloader: LightCurveDownloader | None = None,
) -> int:
    """Run the ``download-target`` command; returns a process exit code."""
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

    cache_root = Path(output_dir) if output_dir is not None else Path(get_settings().mast_cache_dir)
    active_downloader = downloader or LightCurveDownloader(cache_root)

    try:
        product = select_product(
            result.observations,
            active_downloader.list_products,
            tic_id=result.tic_id,
            sector=sector,
            author=author,
            cadence_seconds=cadence,
        )
    except TargetNotFoundError as exc:
        print(f"Target not found: {exc}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    except MastServiceError as exc:
        print(f"MAST service error: {exc}", file=sys.stderr)
        return _EXIT_SERVICE_ERROR

    try:
        artifact = active_downloader.download(product, force=force)
    except DownloadError as exc:
        print(f"Download error: {exc}", file=sys.stderr)
        return _EXIT_DOWNLOAD_ERROR

    print(format_download_result(artifact, result.resolved_target))
    return _EXIT_OK


def format_inspect_result(light_curve: RawLightCurve, file_size: int) -> str:
    """Render a ``RawLightCurve`` as a human-readable inspection report."""
    meta = light_curve.metadata
    prov = light_curve.provenance
    time_min = min(light_curve.time)
    time_max = max(light_curve.time)
    missing_flux = sum(1 for value in light_curve.flux if math.isnan(value))
    nonzero_quality = sum(1 for flag in light_curve.quality if flag != 0)
    cadence = f"{meta.cadence_seconds:.1f}s" if meta.cadence_seconds is not None else "unknown"
    return "\n".join(
        [
            f"Target (TIC):        {prov.tic_id if prov.tic_id is not None else 'unknown'}",
            f"Sector:              {prov.sector if prov.sector is not None else 'unknown'}",
            f"Camera / CCD:        {prov.camera if prov.camera is not None else '?'} / "
            f"{prov.ccd if prov.ccd is not None else '?'}",
            f"Pipeline:            {prov.author or 'unknown'}",
            f"Cadences:            {len(light_curve.time)}",
            f"Time range:          {time_min:.6f} - {time_max:.6f} "
            f"({meta.time_system or 'unknown time system'})",
            f"Flux column:         {light_curve.flux_column}",
            f"Missing flux values: {missing_flux}",
            f"Nonzero quality:     {nonzero_quality}",
            f"Cadence:             {cadence}",
            f"File size:           {file_size} bytes",
            f"SHA-256:             {prov.source_checksum_sha256}",
        ]
    )


def run_inspect_fits(fits_path: str) -> int:
    """Run the ``inspect-fits`` command; returns a process exit code."""
    path = Path(fits_path)
    if not path.is_file():
        print(f"FITS file not found: {fits_path}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        light_curve = parse_light_curve(path)
    except FitsError as exc:
        print(f"Invalid FITS file: {exc}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    print(format_inspect_result(light_curve, path.stat().st_size))
    return _EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging(get_settings())
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "search-target":
        return run_search_target(args.target)
    if args.command == "download-target":
        return run_download_target(
            args.target,
            sector=args.sector,
            author=args.author,
            cadence=args.cadence,
            output_dir=args.output_dir,
            force=args.force,
        )
    if args.command == "inspect-fits":
        return run_inspect_fits(args.fits_path)

    parser.error(f"Unknown command: {args.command}")
    return _EXIT_INVALID_TARGET


if __name__ == "__main__":
    raise SystemExit(main())
