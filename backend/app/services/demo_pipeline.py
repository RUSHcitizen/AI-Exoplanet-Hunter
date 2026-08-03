"""Orchestrates the completed Phase 3A-3D pipeline for the fixed local
Pi Mensae demonstration light curve (Phase 4A).

This module runs exactly the pipeline stages already implemented and
scientifically validated in ``app.data``: FITS parsing, quality
filtering, gap segmentation, per-segment normalization, and robust
outlier flagging -- each with its project-default configuration. It
performs no new scientific processing of its own; it only sequences
existing pure functions and returns their results for
``app.api.demo`` to translate into HTTP response models.

A small process-local, in-memory cache avoids repeating the ~20k-cadence
pipeline run on every request. It is keyed by the resolved file's
identity (path, size, and modification time), not by the checksum alone,
so it is cheap to check without re-reading the whole file; a changed
mtime/size (e.g. a test fixture swapped out between requests) always
invalidates it. Nothing is written to disk.
"""

from dataclasses import dataclass
from pathlib import Path

from app.data.fits_parser import parse_light_curve
from app.data.gap_segmentation import segment_light_curve
from app.data.models import (
    FilteredLightCurve,
    NormalizedLightCurve,
    OutlierFlaggedLightCurve,
    SegmentedLightCurve,
)
from app.data.normalization import normalize_light_curve
from app.data.outlier_detection import flag_outliers
from app.data.quality_filter import filter_quality

PI_MENSAE_TARGET_NAME = "Pi Mensae"
"""Display name for the one fixed Phase 4A demonstration target. The
FITS file's own ``OBJECT`` header only records the TIC identifier, not
this common name."""


class DemoFitsNotFoundError(Exception):
    """The fixed Pi Mensae demonstration FITS file is not present on disk."""


@dataclass(frozen=True)
class DemoPipelineResult:
    """Every stage's output for one pipeline run, so API response
    builders can read whichever phase's statistics they need without
    re-running anything."""

    filtered: FilteredLightCurve
    segmented: SegmentedLightCurve
    normalized: NormalizedLightCurve
    flagged: OutlierFlaggedLightCurve


_CacheKey = tuple[str, int, int]
_cache: dict[_CacheKey, DemoPipelineResult] = {}


def run_demo_pipeline(fits_path: Path) -> DemoPipelineResult:
    """Run the completed Phase 3A-3D pipeline against ``fits_path``
    using each stage's project-default configuration.

    Raises:
        DemoFitsNotFoundError: ``fits_path`` does not exist.
        FitsError: the file is not a valid, supported FITS light curve.
        ProcessingError: a later stage's configuration or input was
            invalid (not expected under default configuration).
    """
    if not fits_path.is_file():
        raise DemoFitsNotFoundError(f"Demo FITS file not found: {fits_path}")

    cache_key = _cache_key(fits_path)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    raw = parse_light_curve(fits_path)
    filtered = filter_quality(raw)
    segmented = segment_light_curve(filtered)
    normalized = normalize_light_curve(segmented)
    flagged = flag_outliers(normalized)

    result = DemoPipelineResult(
        filtered=filtered, segmented=segmented, normalized=normalized, flagged=flagged
    )
    _cache[cache_key] = result
    return result


def _cache_key(fits_path: Path) -> _CacheKey:
    stat = fits_path.stat()
    return (str(fits_path.resolve()), stat.st_mtime_ns, stat.st_size)


__all__ = [
    "PI_MENSAE_TARGET_NAME",
    "DemoFitsNotFoundError",
    "DemoPipelineResult",
    "run_demo_pipeline",
]
