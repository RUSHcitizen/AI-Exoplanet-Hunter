"""Tests for the Phase 4A demo-pipeline orchestration helper directly
(independent of the HTTP layer), including its process-local
memoization cache and invalidation behavior."""

import shutil
import time
from pathlib import Path

import pytest

from app.data.exceptions import InvalidFitsError
from app.services.demo_pipeline import (
    DemoFitsNotFoundError,
    _cache,
    run_demo_pipeline,
)

_REAL_FITS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "raw"
    / "tess"
    / "sector_001"
    / "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
)


def _require_real_fixture() -> None:
    if not _REAL_FITS_PATH.is_file():
        pytest.skip(f"Cached Pi Mensae fixture not present at {_REAL_FITS_PATH}")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _cache.clear()
    yield
    _cache.clear()


def test_run_demo_pipeline_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DemoFitsNotFoundError):
        run_demo_pipeline(tmp_path / "nope.fits")


def test_run_demo_pipeline_on_real_fixture_matches_known_values() -> None:
    _require_real_fixture()
    result = run_demo_pipeline(_REAL_FITS_PATH)
    assert result.filtered.stats.total_cadences == 20076
    assert result.filtered.stats.retained_cadences == 18264
    assert result.segmented.stats.segment_count == 46
    assert result.normalized.stats.normalized_segment_count == 46
    assert result.flagged.stats.total_high_outliers == 2
    assert result.flagged.stats.total_low_outliers == 0


def test_repeated_calls_use_the_cache(tmp_path: Path) -> None:
    _require_real_fixture()
    working_copy = tmp_path / "pi_mensae.fits"
    shutil.copyfile(_REAL_FITS_PATH, working_copy)

    first = run_demo_pipeline(working_copy)
    second = run_demo_pipeline(working_copy)

    assert first is second


def test_changed_file_invalidates_the_cache(tmp_path: Path) -> None:
    """A cache keyed only on the path (not size/mtime) would incorrectly
    reuse a stale, now-invalid pipeline result. This proves the cache
    notices the file changed underneath the same path."""
    _require_real_fixture()
    working_copy = tmp_path / "pi_mensae.fits"
    shutil.copyfile(_REAL_FITS_PATH, working_copy)

    first = run_demo_pipeline(working_copy)
    assert first.filtered.stats.total_cadences == 20076

    time.sleep(0.01)
    working_copy.write_bytes(b"not a fits file any more")

    with pytest.raises(InvalidFitsError):
        run_demo_pipeline(working_copy)
