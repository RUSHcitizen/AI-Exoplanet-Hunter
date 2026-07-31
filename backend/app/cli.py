"""Command-line entry points for the Exoplanet Hunter backend.

Run with ``python -m app.cli <command> ...``. Phase 2A implements TESS
target/observation discovery; Phase 2B adds downloading and parsing one
selected light-curve product; Phase 3A adds quality and finite-value
filtering; Phase 3B adds gap detection and contiguous segmentation;
Phase 3C adds per-segment median-ratio flux normalization. No sigma
clipping, detrending, transit search, or ML happens here yet. See
``docs/architecture.md`` for the full roadmap.
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
    ProcessingError,
    TargetNotFoundError,
)
from app.data.fits_parser import parse_light_curve
from app.data.gap_segmentation import segment_light_curve
from app.data.mast_client import MastClient
from app.data.models import (
    CachedArtifact,
    FilteredLightCurve,
    GapDetectionConfig,
    NormalizationConfig,
    NormalizedLightCurve,
    RawLightCurve,
    SegmentedLightCurve,
    TargetSearchResult,
    config_from_policy_name,
)
from app.data.normalization import normalize_light_curve
from app.data.product_selection import select_product
from app.data.quality_filter import filter_quality
from app.data.quality_flags import QUALITY_BIT_TABLE, QualityPolicy

_SECONDS_PER_DAY = 86400.0

logger = get_logger(__name__)

_EXIT_OK = 0
_EXIT_NOT_FOUND = 1
_EXIT_INVALID_TARGET = 2
_EXIT_SERVICE_ERROR = 3
_EXIT_DOWNLOAD_ERROR = 4
_EXIT_FITS_ERROR = 5
_EXIT_PROCESSING_ERROR = 6


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

    filter_parser = subparsers.add_parser(
        "filter-quality",
        help=(
            "Filter a downloaded TESS light curve by quality flags and finite values "
            "(selects cadences; never modifies the FITS file or its values)."
        ),
    )
    filter_parser.add_argument("fits_path", help="Path to a cached TESS light-curve FITS file.")
    filter_parser.add_argument(
        "--quality-policy",
        default=QualityPolicy.MAST.value,
        choices=[policy.value for policy in QualityPolicy],
        help=(
            "Named quality-bitmask policy (default: mast, the MAST-recommended mask 21183). "
            "'default' is the Lightkurve-compatible mask 17087; 'hardest' rejects every "
            "flagged cadence and is not recommended."
        ),
    )
    filter_parser.add_argument(
        "--quality-bitmask",
        type=int,
        default=None,
        help="Custom integer bitmask; requires --quality-policy custom.",
    )
    filter_parser.add_argument(
        "--allow-nonfinite-time",
        action="store_true",
        help="Do not reject cadences whose TIME is NaN or infinite.",
    )
    filter_parser.add_argument(
        "--allow-nonfinite-flux",
        action="store_true",
        help="Do not reject cadences whose flux is NaN or infinite.",
    )
    filter_parser.add_argument(
        "--allow-nonfinite-flux-err",
        action="store_true",
        help="Do not reject cadences whose flux error is NaN or infinite.",
    )

    segment_parser = subparsers.add_parser(
        "segment-light-curve",
        help=(
            "Filter a TESS light curve by quality flags, then detect TIME gaps and divide it "
            "into contiguous segments (selects and groups cadences; never modifies values)."
        ),
    )
    segment_parser.add_argument("fits_path", help="Path to a cached TESS light-curve FITS file.")
    segment_parser.add_argument(
        "--quality-policy",
        default=QualityPolicy.MAST.value,
        choices=[policy.value for policy in QualityPolicy],
        help="Named quality-bitmask policy applied before segmentation (default: mast).",
    )
    segment_parser.add_argument(
        "--quality-bitmask",
        type=int,
        default=None,
        help="Custom integer bitmask; requires --quality-policy custom.",
    )
    segment_parser.add_argument(
        "--allow-nonfinite-time",
        action="store_true",
        help="Do not reject cadences whose TIME is NaN or infinite.",
    )
    segment_parser.add_argument(
        "--allow-nonfinite-flux",
        action="store_true",
        help="Do not reject cadences whose flux is NaN or infinite.",
    )
    segment_parser.add_argument(
        "--allow-nonfinite-flux-err",
        action="store_true",
        help="Do not reject cadences whose flux error is NaN or infinite.",
    )
    segment_parser.add_argument(
        "--gap-multiplier",
        type=float,
        default=GapDetectionConfig().gap_multiplier,
        help="An interval exceeding nominal_cadence * multiplier is a gap (default: 5.0).",
    )
    segment_parser.add_argument(
        "--gap-tolerance",
        type=float,
        default=GapDetectionConfig().gap_tolerance,
        help="Absolute floating-point tolerance added to the gap threshold, in days.",
    )
    segment_parser.add_argument(
        "--cadence-disagreement-fraction",
        type=float,
        default=GapDetectionConfig().cadence_disagreement_fraction,
        help="Fractional difference above which measured/metadata cadence are flagged disagreeing.",
    )
    segment_parser.add_argument(
        "--missing-cadence-residual-tolerance",
        type=float,
        default=GapDetectionConfig().missing_cadence_residual_tolerance,
        help="How close a gap's interval must be to an integer cadence multiple to be estimated.",
    )

    normalize_parser = subparsers.add_parser(
        "normalize-light-curve",
        help=(
            "Filter, segment, then normalize a TESS light curve by dividing each segment's "
            "flux by its own median (never modifies TIME, QUALITY, source indices, or gaps)."
        ),
    )
    normalize_parser.add_argument("fits_path", help="Path to a cached TESS light-curve FITS file.")
    normalize_parser.add_argument(
        "--quality-policy",
        default=QualityPolicy.MAST.value,
        choices=[policy.value for policy in QualityPolicy],
        help="Named quality-bitmask policy applied before segmentation (default: mast).",
    )
    normalize_parser.add_argument(
        "--quality-bitmask",
        type=int,
        default=None,
        help="Custom integer bitmask; requires --quality-policy custom.",
    )
    normalize_parser.add_argument(
        "--allow-nonfinite-time",
        action="store_true",
        help="Do not reject cadences whose TIME is NaN or infinite.",
    )
    normalize_parser.add_argument(
        "--allow-nonfinite-flux",
        action="store_true",
        help="Do not reject cadences whose flux is NaN or infinite.",
    )
    normalize_parser.add_argument(
        "--allow-nonfinite-flux-err",
        action="store_true",
        help="Do not reject cadences whose flux error is NaN or infinite.",
    )
    normalize_parser.add_argument(
        "--gap-multiplier",
        type=float,
        default=GapDetectionConfig().gap_multiplier,
        help="An interval exceeding nominal_cadence * multiplier is a gap (default: 5.0).",
    )
    normalize_parser.add_argument(
        "--gap-tolerance",
        type=float,
        default=GapDetectionConfig().gap_tolerance,
        help="Absolute floating-point tolerance added to the gap threshold, in days.",
    )
    normalize_parser.add_argument(
        "--cadence-disagreement-fraction",
        type=float,
        default=GapDetectionConfig().cadence_disagreement_fraction,
        help="Fractional difference above which measured/metadata cadence are flagged disagreeing.",
    )
    normalize_parser.add_argument(
        "--missing-cadence-residual-tolerance",
        type=float,
        default=GapDetectionConfig().missing_cadence_residual_tolerance,
        help="How close a gap's interval must be to an integer cadence multiple to be estimated.",
    )
    normalize_parser.add_argument(
        "--zero-reference-tolerance",
        type=float,
        default=NormalizationConfig().zero_reference_tolerance,
        help=(
            "A segment's median reference at or below this magnitude is treated as "
            "zero_reference and left un-normalized (default: 0.0, exact zero only)."
        ),
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


def format_filter_result(filtered: FilteredLightCurve) -> str:
    """Render a ``FilteredLightCurve`` as a human-readable report."""
    stats = filtered.stats
    step = filtered.history[0]
    prov = filtered.provenance
    lines = [
        f"Source file:         {prov.source_filename}",
        f"Target (TIC):        {prov.tic_id if prov.tic_id is not None else 'unknown'}",
        f"Sector:              {prov.sector if prov.sector is not None else 'unknown'}",
        f"Flux column:         {filtered.flux_column}",
        f"Quality policy:      {step.quality_policy.value}",
        f"Resolved bitmask:    {step.active_quality_bitmask} (0x{step.active_quality_bitmask:04X})",
        f"Total cadences:      {stats.total_cadences}",
        f"Retained cadences:   {stats.retained_cadences} ({stats.retained_fraction * 100:.1f}%)",
        f"Rejected cadences:   {stats.rejected_cadences}",
    ]

    if stats.rejected_by_reason:
        lines.append("")
        lines.append("Rejections by reason (a cadence may have several):")
        for reason, count in sorted(stats.rejected_by_reason.items()):
            lines.append(f"  - {reason.value}: {count}")

    if stats.rejected_by_quality_bit:
        lines.append("")
        lines.append("Matched quality bits:")
        for bit_value, count in sorted(stats.rejected_by_quality_bit.items()):
            meaning = QUALITY_BIT_TABLE.get(bit_value, "undocumented bit")
            lines.append(f"  - {bit_value} ({meaning}): {count}")

    if stats.retained_cadences == 0:
        lines.append("")
        lines.append(
            "WARNING: every cadence was rejected. Nothing remains to analyse; "
            "consider a less aggressive --quality-policy."
        )

    lines.extend(
        [
            "",
            f"Code version:        {step.code_version}",
            f"Source SHA-256:      {step.input_checksum_sha256}",
            "The source FITS file was not modified.",
        ]
    )
    return "\n".join(lines)


def run_filter_quality(
    fits_path: str,
    *,
    quality_policy: str = QualityPolicy.MAST.value,
    quality_bitmask: int | None = None,
    allow_nonfinite_time: bool = False,
    allow_nonfinite_flux: bool = False,
    allow_nonfinite_flux_err: bool = False,
) -> int:
    """Run the ``filter-quality`` command; returns a process exit code."""
    path = Path(fits_path)
    if not path.is_file():
        print(f"FITS file not found: {fits_path}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        config = config_from_policy_name(
            quality_policy,
            custom_quality_bitmask=quality_bitmask,
            require_finite_time=not allow_nonfinite_time,
            require_finite_flux=not allow_nonfinite_flux,
            require_finite_flux_err=not allow_nonfinite_flux_err,
        )
    except ProcessingError as exc:
        print(f"Invalid filter configuration: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    try:
        light_curve = parse_light_curve(path)
    except FitsError as exc:
        print(f"Invalid FITS file: {exc}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        filtered = filter_quality(light_curve, config)
    except ProcessingError as exc:
        print(f"Filtering error: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    print(format_filter_result(filtered))
    return _EXIT_OK


def _format_days(value: float) -> str:
    """Render a day-native duration alongside its second-equivalent, since
    TIME (and every duration derived from it) is in TESS BJD days, but
    TESS cadences are more familiar to a reader in seconds."""
    return f"{value:.8f} d (~{value * _SECONDS_PER_DAY:.2f} s)"


def format_segment_result(segmented: SegmentedLightCurve) -> str:
    """Render a ``SegmentedLightCurve`` as a human-readable report."""
    stats = segmented.stats
    step = segmented.history[-1]
    prov = segmented.provenance
    lines = [
        f"Source file:              {prov.source_filename}",
        f"Target (TIC):             {prov.tic_id if prov.tic_id is not None else 'unknown'}",
        f"Sector:                   {prov.sector if prov.sector is not None else 'unknown'}",
        f"Flux column:              {segmented.flux_column}",
        f"Total retained cadences:  {stats.total_cadences}",
        f"Segments:                 {stats.segment_count}",
        f"Gaps detected:            {stats.gap_count}",
    ]

    if stats.measured_nominal_cadence is not None:
        lines.append(f"Measured nominal cadence: {_format_days(stats.measured_nominal_cadence)}")
    else:
        lines.append("Measured nominal cadence: not estimable (fewer than two retained cadences)")

    if stats.metadata_cadence_native is not None:
        lines.append(f"Metadata cadence:         {_format_days(stats.metadata_cadence_native)}")
        agreement = (
            "unknown"
            if stats.cadence_sources_agree is None
            else ("yes" if stats.cadence_sources_agree else "NO -- measured cadence still used")
        )
        lines.append(f"Cadence sources agree:    {agreement}")
    else:
        lines.append("Metadata cadence:         unknown")

    if stats.gap_count:
        lines.append(f"Total estimated missing cadences: {stats.total_estimated_missing_cadences}")
        lines.append("")
        lines.append("Segments:")
        for segment in segmented.segments:
            lines.append(
                f"  #{segment.segment_number}: positions {segment.start_position}-"
                f"{segment.end_position} (source rows {segment.start_source_index}-"
                f"{segment.end_source_index}), {segment.cadence_count} cadences, "
                f"time {segment.start_time:.6f} - {segment.end_time:.6f}"
            )
        lines.append("")
        lines.append("Gaps:")
        for index, gap in enumerate(segmented.gaps, start=1):
            reasons = ", ".join(reason.value for reason in gap.reasons)
            missing = (
                "unknown"
                if gap.estimated_missing_cadences is None
                else gap.estimated_missing_cadences
            )
            lines.append(
                f"  #{index}: positions {gap.before_position}/{gap.after_position} "
                f"(source rows {gap.before_source_index}/{gap.after_source_index}), "
                f"interval={_format_days(gap.actual_interval)}, "
                f"threshold={_format_days(gap.threshold)}, ratio={gap.interval_to_cadence_ratio:.2f}"
            )
            lines.append(
                f"       reasons: {reasons}; skipped source rows: {gap.skipped_source_rows}; "
                f"estimated missing cadences: {missing}"
            )
    else:
        lines.append("")
        lines.append("No gaps detected -- the entire retained light curve is one segment.")

    lines.extend(
        [
            "",
            f"Code version:        {step.code_version}",
            f"Source SHA-256:      {prov.source_checksum_sha256}",
            "The source FITS file was not modified.",
        ]
    )
    return "\n".join(lines)


def run_segment_light_curve(
    fits_path: str,
    *,
    quality_policy: str = QualityPolicy.MAST.value,
    quality_bitmask: int | None = None,
    allow_nonfinite_time: bool = False,
    allow_nonfinite_flux: bool = False,
    allow_nonfinite_flux_err: bool = False,
    gap_multiplier: float = GapDetectionConfig().gap_multiplier,
    gap_tolerance: float = GapDetectionConfig().gap_tolerance,
    cadence_disagreement_fraction: float = GapDetectionConfig().cadence_disagreement_fraction,
    missing_cadence_residual_tolerance: float = (
        GapDetectionConfig().missing_cadence_residual_tolerance
    ),
) -> int:
    """Run the ``segment-light-curve`` command; returns a process exit code."""
    path = Path(fits_path)
    if not path.is_file():
        print(f"FITS file not found: {fits_path}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        quality_config = config_from_policy_name(
            quality_policy,
            custom_quality_bitmask=quality_bitmask,
            require_finite_time=not allow_nonfinite_time,
            require_finite_flux=not allow_nonfinite_flux,
            require_finite_flux_err=not allow_nonfinite_flux_err,
        )
        gap_config = GapDetectionConfig(
            gap_multiplier=gap_multiplier,
            gap_tolerance=gap_tolerance,
            cadence_disagreement_fraction=cadence_disagreement_fraction,
            missing_cadence_residual_tolerance=missing_cadence_residual_tolerance,
        )
    except ProcessingError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    try:
        light_curve = parse_light_curve(path)
    except FitsError as exc:
        print(f"Invalid FITS file: {exc}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        filtered = filter_quality(light_curve, quality_config)
        segmented = segment_light_curve(filtered, gap_config)
    except ProcessingError as exc:
        print(f"Processing error: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    print(format_segment_result(segmented))
    return _EXIT_OK


def format_normalize_result(normalized: NormalizedLightCurve) -> str:
    """Render a ``NormalizedLightCurve`` as a human-readable report."""
    stats = normalized.stats
    step = normalized.history[-1]
    prov = normalized.provenance
    lines = [
        f"Source file:              {prov.source_filename}",
        f"Target (TIC):             {prov.tic_id if prov.tic_id is not None else 'unknown'}",
        f"Sector:                   {prov.sector if prov.sector is not None else 'unknown'}",
        f"Flux column:              {normalized.flux_column}",
        f"Total cadences:           {stats.total_cadences}",
        f"Segments:                 {stats.segment_count}",
        f"Normalized segments:      {stats.normalized_segment_count}",
        f"Un-normalized segments:   {stats.invalid_segment_count}",
    ]

    if stats.invalid_by_issue:
        lines.append("")
        lines.append("Un-normalized segments by issue:")
        for issue, count in sorted(stats.invalid_by_issue.items(), key=lambda item: item[0].value):
            lines.append(f"  - {issue.value}: {count}")

    lines.append("")
    lines.append("Segments:")
    for entry in normalized.segments:
        segment = entry.segment
        reference = "n/a" if entry.stats.reference is None else f"{entry.stats.reference:.6f}"
        status = "normalized" if entry.stats.reference_valid else entry.stats.reference_issue.value  # type: ignore[union-attr]
        lines.append(
            f"  #{segment.segment_number}: positions {segment.start_position}-"
            f"{segment.end_position} (source rows {segment.start_source_index}-"
            f"{segment.end_source_index}), {segment.cadence_count} cadences, "
            f"reference={reference}, status={status}"
        )

    lines.extend(
        [
            "",
            f"Gaps carried through unchanged: {len(normalized.gaps)}",
            f"Code version:        {step.code_version}",
            f"Source SHA-256:      {prov.source_checksum_sha256}",
            "The source FITS file was not modified.",
            "No sigma clipping, outlier rejection, detrending, smoothing, or interpolation "
            "was applied.",
        ]
    )
    return "\n".join(lines)


def run_normalize_light_curve(
    fits_path: str,
    *,
    quality_policy: str = QualityPolicy.MAST.value,
    quality_bitmask: int | None = None,
    allow_nonfinite_time: bool = False,
    allow_nonfinite_flux: bool = False,
    allow_nonfinite_flux_err: bool = False,
    gap_multiplier: float = GapDetectionConfig().gap_multiplier,
    gap_tolerance: float = GapDetectionConfig().gap_tolerance,
    cadence_disagreement_fraction: float = GapDetectionConfig().cadence_disagreement_fraction,
    missing_cadence_residual_tolerance: float = (
        GapDetectionConfig().missing_cadence_residual_tolerance
    ),
    zero_reference_tolerance: float = NormalizationConfig().zero_reference_tolerance,
) -> int:
    """Run the ``normalize-light-curve`` command; returns a process exit code."""
    path = Path(fits_path)
    if not path.is_file():
        print(f"FITS file not found: {fits_path}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        quality_config = config_from_policy_name(
            quality_policy,
            custom_quality_bitmask=quality_bitmask,
            require_finite_time=not allow_nonfinite_time,
            require_finite_flux=not allow_nonfinite_flux,
            require_finite_flux_err=not allow_nonfinite_flux_err,
        )
        gap_config = GapDetectionConfig(
            gap_multiplier=gap_multiplier,
            gap_tolerance=gap_tolerance,
            cadence_disagreement_fraction=cadence_disagreement_fraction,
            missing_cadence_residual_tolerance=missing_cadence_residual_tolerance,
        )
        normalization_config = NormalizationConfig(
            zero_reference_tolerance=zero_reference_tolerance
        )
    except ProcessingError as exc:
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    try:
        light_curve = parse_light_curve(path)
    except FitsError as exc:
        print(f"Invalid FITS file: {exc}", file=sys.stderr)
        return _EXIT_FITS_ERROR

    try:
        filtered = filter_quality(light_curve, quality_config)
        segmented = segment_light_curve(filtered, gap_config)
        normalized = normalize_light_curve(segmented, normalization_config)
    except ProcessingError as exc:
        print(f"Processing error: {exc}", file=sys.stderr)
        return _EXIT_PROCESSING_ERROR

    print(format_normalize_result(normalized))
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
    if args.command == "filter-quality":
        return run_filter_quality(
            args.fits_path,
            quality_policy=args.quality_policy,
            quality_bitmask=args.quality_bitmask,
            allow_nonfinite_time=args.allow_nonfinite_time,
            allow_nonfinite_flux=args.allow_nonfinite_flux,
            allow_nonfinite_flux_err=args.allow_nonfinite_flux_err,
        )
    if args.command == "segment-light-curve":
        return run_segment_light_curve(
            args.fits_path,
            quality_policy=args.quality_policy,
            quality_bitmask=args.quality_bitmask,
            allow_nonfinite_time=args.allow_nonfinite_time,
            allow_nonfinite_flux=args.allow_nonfinite_flux,
            allow_nonfinite_flux_err=args.allow_nonfinite_flux_err,
            gap_multiplier=args.gap_multiplier,
            gap_tolerance=args.gap_tolerance,
            cadence_disagreement_fraction=args.cadence_disagreement_fraction,
            missing_cadence_residual_tolerance=args.missing_cadence_residual_tolerance,
        )
    if args.command == "normalize-light-curve":
        return run_normalize_light_curve(
            args.fits_path,
            quality_policy=args.quality_policy,
            quality_bitmask=args.quality_bitmask,
            allow_nonfinite_time=args.allow_nonfinite_time,
            allow_nonfinite_flux=args.allow_nonfinite_flux,
            allow_nonfinite_flux_err=args.allow_nonfinite_flux_err,
            gap_multiplier=args.gap_multiplier,
            gap_tolerance=args.gap_tolerance,
            cadence_disagreement_fraction=args.cadence_disagreement_fraction,
            missing_cadence_residual_tolerance=args.missing_cadence_residual_tolerance,
            zero_reference_tolerance=args.zero_reference_tolerance,
        )

    parser.error(f"Unknown command: {args.command}")
    return _EXIT_INVALID_TARGET


if __name__ == "__main__":
    raise SystemExit(main())
