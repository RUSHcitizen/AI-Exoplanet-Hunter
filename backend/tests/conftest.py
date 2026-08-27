"""Shared pytest fixtures for the backend test suite."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from app.api.demo import get_demo_fits_path
from app.main import create_app
from app.services.demo_pipeline import _cache

REAL_PI_MENSAE_FITS_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "raw"
    / "tess"
    / "sector_001"
    / "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
)
"""The cached real SPOC product the Phase 3A-4A validation numbers in
``docs/architecture.md`` were recorded against. Gitignored (``data/`` is
a local cache), so it is absent on a fresh clone and in CI -- tests that
assert its exact numbers are marked ``realdata`` and are the *only*
tests allowed to require it."""

REAL_PI_MENSAE_SHA256 = "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609"


def real_fits_available() -> bool:
    """Whether the cached real Pi Mensae product is present locally."""
    return REAL_PI_MENSAE_FITS_PATH.is_file()


requires_real_fits = pytest.mark.skipif(
    not real_fits_available(),
    reason=(
        f"Cached Pi Mensae product not present at {REAL_PI_MENSAE_FITS_PATH}. "
        "Fetch it with `python -m app.cli download-target --target 'TIC 261136679' "
        "--sector 1`, then rerun with `pytest -m realdata`."
    ),
)
"""Skip marker for tests that genuinely need the real cached product.

Structural behavior of the demo API and pipeline is covered against the
synthetic fixture below instead, so an absent real file no longer means
the Phase 4A/4B code paths go untested.
"""


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient wrapping a freshly constructed FastAPI app.

    Building the app via ``create_app`` (rather than importing the
    module-level ``app`` singleton) keeps each test isolated from
    state mutated by any other test.
    """
    with TestClient(create_app()) as test_client:
        yield test_client


# --- Synthetic TESS light curve -------------------------------------------
#
# A deterministic stand-in for a real SPOC product, built to exercise
# every branch the Phase 3A-3D pipeline can take: rejected cadences (both
# quality-flagged and nonfinite), multiple observation gaps, a segment
# too short to analyse, and high outliers that are unambiguously
# instrumental rather than transit-like. It is NOT a scientific
# substitute for the real product -- tests asserting real measured values
# stay marked ``realdata``.

SYNTHETIC_CADENCE_DAYS = 120.0 / 86400.0
SYNTHETIC_TIC_ID = 261136679
SYNTHETIC_SECTOR = 1
SYNTHETIC_FLUX_LEVEL = 275_000.0

# Cadence counts of the four contiguous blocks, separated by three gaps.
# The final block is deliberately shorter than
# ``OutlierDetectionConfig.minimum_finite_cadences`` (5) so that the
# INSUFFICIENT_DATA status is exercised.
_SYNTHETIC_BLOCKS = (900, 700, 500, 3)
_SYNTHETIC_GAP_DAYS = (0.9, 0.35, 0.2)


def build_synthetic_light_curve_fits(path: Path) -> Path:
    """Write a deterministic, multi-segment TESS-format light curve.

    Seeded RNG only -- the same path always receives byte-identical
    content, so tests built on it are reproducible.
    """
    rng = np.random.default_rng(20180716)

    times: list[float] = []
    cursor = 1325.30
    for block_index, block_length in enumerate(_SYNTHETIC_BLOCKS):
        times.extend(cursor + np.arange(block_length) * SYNTHETIC_CADENCE_DAYS)
        cursor = times[-1] + SYNTHETIC_CADENCE_DAYS
        if block_index < len(_SYNTHETIC_GAP_DAYS):
            cursor += _SYNTHETIC_GAP_DAYS[block_index]

    time = np.asarray(times, dtype=np.float64)
    total = time.size

    flux = np.full(total, SYNTHETIC_FLUX_LEVEL, dtype=np.float64)
    flux += rng.normal(0.0, SYNTHETIC_FLUX_LEVEL * 2.5e-4, total)
    flux_err = np.full(total, SYNTHETIC_FLUX_LEVEL * 2.5e-4, dtype=np.float64)

    quality = np.zeros(total, dtype=np.int32)

    # Cadences rejected by the MAST policy: bit 8 (128, cosmic ray in the
    # optimal aperture) is inside the default mask, so these are dropped
    # by Phase 3A rather than surviving into the analysed arrays.
    quality[10:18] |= 128

    # Cadences rejected for nonfiniteness rather than for a quality flag,
    # so both RejectionReason branches are represented.
    flux[np.array([120, 121, 340, 655])] = np.nan

    # Unambiguously instrumental positive spikes, well above the default
    # 5.0 robust-score threshold, in the first two segments.
    flux[np.array([300, 460, 1150])] += SYNTHETIC_FLUX_LEVEL * 6.0e-3

    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "TESS"
    primary.header["TICID"] = SYNTHETIC_TIC_ID
    primary.header["SECTOR"] = SYNTHETIC_SECTOR
    primary.header["CAMERA"] = 4
    primary.header["CCD"] = 2
    primary.header["ORIGIN"] = "NASA/Ames"
    primary.header["PROCVER"] = "synthetic-test-fixture"
    primary.header["OBJECT"] = f"TIC {SYNTHETIC_TIC_ID}"

    columns = [
        fits.Column(name="TIME", format="D", array=time),
        fits.Column(name="QUALITY", format="J", array=quality),
        fits.Column(name="PDCSAP_FLUX", format="D", array=flux),
        fits.Column(name="PDCSAP_FLUX_ERR", format="D", array=flux_err),
    ]
    lc_hdu = fits.BinTableHDU.from_columns(columns, name="LIGHTCURVE")
    lc_hdu.header["TIMESYS"] = "TDB"
    lc_hdu.header["TIMEDEL"] = SYNTHETIC_CADENCE_DAYS

    fits.HDUList([primary, lc_hdu]).writeto(path, overwrite=True)
    return path


@pytest.fixture(scope="session")
def synthetic_fits_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped synthetic TESS light curve.

    Built once because it is read-only for every consumer, and parsing it
    repeatedly would dominate the suite's runtime.
    """
    directory = tmp_path_factory.mktemp("synthetic_lc")
    return build_synthetic_light_curve_fits(directory / "synthetic-tess-lc.fits")


@pytest.fixture
def synthetic_demo_client(synthetic_fits_path: Path) -> Iterator[TestClient]:
    """A TestClient whose demo endpoints resolve to the synthetic file.

    Overrides the ``get_demo_fits_path`` dependency rather than mutating
    settings, so the real cached product -- present or not -- is never
    touched by these tests.
    """
    _cache.clear()
    app = create_app()
    app.dependency_overrides[get_demo_fits_path] = lambda: synthetic_fits_path
    with TestClient(app) as test_client:
        yield test_client
    _cache.clear()
