"""Optional live integration check: downloads and parses one real TESS
light-curve FITS product from MAST.

Excluded from normal ``pytest`` runs (see the ``-m "not live"`` default in
``pyproject.toml``). Requires network access and makes real requests to
MAST, so it will fail if MAST is unreachable -- that is expected and does
not indicate a code bug. Downloads to a temporary directory that is
removed afterward, so it never pollutes the normal ``data/raw/tess``
cache.

Run explicitly with:

    pytest -m live tests/test_download_live.py
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from app.data.downloader import LightCurveDownloader
from app.data.fits_parser import parse_light_curve
from app.data.mast_client import MastClient
from app.data.product_selection import select_product

pytestmark = pytest.mark.live


def test_download_and_parse_one_real_light_curve() -> None:
    client = MastClient()
    result = client.search_target("TIC 261136679")

    tmp_dir = Path(tempfile.mkdtemp(prefix="exoplanet-hunter-live-test-"))
    try:
        downloader = LightCurveDownloader(tmp_dir)
        product = select_product(
            result.observations, downloader.list_products, tic_id=result.tic_id
        )

        artifact = downloader.download(product)
        assert artifact.size_bytes > 0
        assert Path(artifact.local_path).exists()

        # Re-downloading immediately should hit the cache, not the network.
        cached_again = downloader.download(product)
        assert cached_again.was_downloaded is False
        assert cached_again.sha256 == artifact.sha256

        light_curve = parse_light_curve(Path(artifact.local_path))
        assert len(light_curve.time) > 0
        assert light_curve.provenance.tic_id == 261136679
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
