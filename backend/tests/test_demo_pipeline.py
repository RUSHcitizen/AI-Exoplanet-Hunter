"""Tests for the Phase 4A demo-pipeline orchestration helper directly
(independent of the HTTP layer), including its process-local
memoization cache and invalidation behavior.

Cache and orchestration behavior is input-independent, so it is exercised
against the synthetic fixture and runs everywhere. Only the assertions on
the real product's measured values are marked ``realdata``.
"""

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.data.exceptions import InvalidFitsError
from app.services.demo_pipeline import (
    DemoFitsNotFoundError,
    _cache,
    run_demo_pipeline,
)

from .conftest import REAL_PI_MENSAE_FITS_PATH, requires_real_fits


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    _cache.clear()
    yield
    _cache.clear()


def test_run_demo_pipeline_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DemoFitsNotFoundError):
        run_demo_pipeline(tmp_path / "nope.fits")


def test_run_demo_pipeline_returns_every_stage(synthetic_fits_path: Path) -> None:
    result = run_demo_pipeline(synthetic_fits_path)

    assert result.filtered.stats.total_cadences > 0
    assert result.segmented.stats.segment_count == len(result.segmented.gaps) + 1
    assert result.normalized.stats.segment_count == result.segmented.stats.segment_count
    assert result.flagged.stats.segment_count == result.segmented.stats.segment_count


def test_no_cadence_is_lost_between_stages(synthetic_fits_path: Path) -> None:
    """Phases 3B-3D select and group but never drop -- every retained
    cadence must still be present at the end of the pipeline."""
    result = run_demo_pipeline(synthetic_fits_path)
    retained = result.filtered.stats.retained_cadences

    assert sum(segment.cadence_count for segment in result.segmented.segments) == retained
    assert result.normalized.stats.total_cadences == retained
    assert result.flagged.stats.total_cadences == retained


def test_every_cadence_keeps_an_aligned_mask_entry(synthetic_fits_path: Path) -> None:
    result = run_demo_pipeline(synthetic_fits_path)
    for segment in result.flagged.segments:
        cadence_count = segment.normalized.segment.cadence_count
        assert len(segment.outlier_mask) == cadence_count
        assert len(segment.high_outlier_mask) == cadence_count


def test_low_side_detection_stays_disabled(synthetic_fits_path: Path) -> None:
    result = run_demo_pipeline(synthetic_fits_path)
    assert result.flagged.stats.total_low_outliers == 0
    for segment in result.flagged.segments:
        assert segment.low_outlier_mask is None


def test_repeated_calls_use_the_cache(tmp_path: Path, synthetic_fits_path: Path) -> None:
    working_copy = tmp_path / "demo.fits"
    shutil.copyfile(synthetic_fits_path, working_copy)

    first = run_demo_pipeline(working_copy)
    second = run_demo_pipeline(working_copy)

    assert first is second


def test_changed_file_invalidates_the_cache(tmp_path: Path, synthetic_fits_path: Path) -> None:
    """A cache keyed only on the path (not size/mtime) would incorrectly
    reuse a stale, now-invalid pipeline result. This proves the cache
    notices the file changed underneath the same path."""
    working_copy = tmp_path / "demo.fits"
    shutil.copyfile(synthetic_fits_path, working_copy)

    first = run_demo_pipeline(working_copy)
    assert first.filtered.stats.total_cadences > 0

    time.sleep(0.01)
    working_copy.write_bytes(b"not a fits file any more")

    with pytest.raises(InvalidFitsError):
        run_demo_pipeline(working_copy)


def test_pipeline_is_reproducible(tmp_path: Path, synthetic_fits_path: Path) -> None:
    """Identical bytes yield identical science, wherever the file sits.

    Distinct copies at distinct paths bypass the cache, so these are two
    genuinely independent runs. ``source_filename`` is excluded because
    provenance is *supposed* to differ -- it records which file was read.
    Its sibling ``source_checksum_sha256`` is what pins the content, and
    that must match.
    """
    first_copy = tmp_path / "first.fits"
    second_copy = tmp_path / "second.fits"
    shutil.copyfile(synthetic_fits_path, first_copy)
    shutil.copyfile(synthetic_fits_path, second_copy)

    first = run_demo_pipeline(first_copy)
    second = run_demo_pipeline(second_copy)

    assert first is not second
    assert (
        first.flagged.provenance.source_checksum_sha256
        == second.flagged.provenance.source_checksum_sha256
    )
    assert first.flagged.provenance.source_filename != second.flagged.provenance.source_filename

    exclude: dict[str, set[str]] = {"provenance": {"source_filename"}}
    assert first.flagged.model_dump_json(exclude=exclude) == second.flagged.model_dump_json(
        exclude=exclude
    )


@requires_real_fits
@pytest.mark.realdata
def test_run_demo_pipeline_on_real_fixture_matches_known_values() -> None:
    result = run_demo_pipeline(REAL_PI_MENSAE_FITS_PATH)
    assert result.filtered.stats.total_cadences == 20076
    assert result.filtered.stats.retained_cadences == 18264
    assert result.segmented.stats.segment_count == 46
    assert result.normalized.stats.normalized_segment_count == 46
    assert result.flagged.stats.total_high_outliers == 2
    assert result.flagged.stats.total_low_outliers == 0
