"""Tests for TESS light-curve download/caching.

All network access is mocked via ``FakeProductGateway``, which implements
the same ``MastProductGateway`` protocol as ``AstroqueryProductGateway``
but never touches astroquery or the network.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.data.downloader import LightCurveDownloader
from app.data.exceptions import (
    ChecksumMismatchError,
    CorruptedCacheError,
    MastServiceError,
    RetryExhaustedError,
)
from app.data.models import SelectedProduct


class FakeProductGateway:
    def __init__(
        self,
        products: list[dict[str, Any]] | None = None,
        file_content: bytes = b"fits-bytes",
        fail_times: int = 0,
        partial_content_on_failure: bytes | None = None,
    ) -> None:
        self.products = products or []
        self.file_content = file_content
        self.fail_times = fail_times
        self.partial_content_on_failure = partial_content_on_failure
        self.fetch_calls = 0
        self.list_calls: list[str] = []

    def list_products(self, obs_id: str) -> list[dict[str, Any]]:
        self.list_calls.append(obs_id)
        return self.products

    def fetch_product(self, data_uri: str, dest_path: Path) -> None:
        self.fetch_calls += 1
        if self.fetch_calls <= self.fail_times:
            if self.partial_content_on_failure is not None:
                dest_path.write_bytes(self.partial_content_on_failure)
            raise MastServiceError("simulated transient network failure")
        dest_path.write_bytes(self.file_content)


def _product(
    filename: str = "tess-s0001-lc.fits", sector: int | None = 1, size_bytes: int | None = None
) -> SelectedProduct:
    return SelectedProduct(
        obs_id="obs-1",
        tic_id=261136679,
        sector=sector,
        author="SPOC",
        cadence_seconds=120.0,
        filename=filename,
        data_uri=f"mast:TESS/product/{filename}",
        size_bytes=size_bytes,
        description="Light curves",
    )


def _downloader(tmp_path: Path, gateway: FakeProductGateway, **kwargs: Any) -> LightCurveDownloader:
    return LightCurveDownloader(tmp_path, gateway=gateway, sleep=lambda _seconds: None, **kwargs)


def test_cache_path_is_deterministic_given_sector_and_filename(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path, FakeProductGateway())

    path = downloader.cache_path(_product(sector=37, filename="tess-s0037-lc.fits"))

    assert path == tmp_path / "sector_037" / "tess-s0037-lc.fits"


def test_cache_path_handles_unknown_sector(tmp_path: Path) -> None:
    downloader = _downloader(tmp_path, FakeProductGateway())

    path = downloader.cache_path(_product(sector=None))

    assert path == tmp_path / "sector_unknown" / "tess-s0001-lc.fits"


def test_download_writes_file_and_checksum_sidecar(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"hello-fits")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=len(b"hello-fits"))

    artifact = downloader.download(product)

    assert artifact.was_downloaded is True
    assert Path(artifact.local_path).read_bytes() == b"hello-fits"
    assert artifact.size_bytes == len(b"hello-fits")
    sidecar = Path(artifact.local_path + ".sha256")
    assert sidecar.exists()
    assert sidecar.read_text().strip() == hashlib.sha256(b"hello-fits").hexdigest()
    assert artifact.sha256 == hashlib.sha256(b"hello-fits").hexdigest()


def test_valid_cached_file_is_reused_without_network_call(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"cached-content")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=len(b"cached-content"))
    downloader.download(product)
    assert gateway.fetch_calls == 1

    artifact = downloader.download(product)

    assert artifact.was_downloaded is False
    assert gateway.fetch_calls == 1  # no second network call


def test_force_redownloads_even_with_valid_cache(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"first")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=None)
    downloader.download(product)

    gateway.file_content = b"second-version"
    artifact = downloader.download(product, force=True)

    assert artifact.was_downloaded is True
    assert Path(artifact.local_path).read_bytes() == b"second-version"


def test_corrupted_cache_without_force_raises(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"original")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=len(b"original"))
    downloader.download(product)

    # Simulate local corruption: overwrite the cached file after the fact.
    Path(downloader.cache_path(product)).write_bytes(b"corrupted!!")

    with pytest.raises(CorruptedCacheError):
        downloader.download(product)


def test_corrupted_cache_is_replaced_with_force(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"original")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=len(b"original"))
    downloader.download(product)
    Path(downloader.cache_path(product)).write_bytes(b"corrupted!!")

    artifact = downloader.download(product, force=True)

    assert artifact.was_downloaded is True
    assert Path(artifact.local_path).read_bytes() == b"original"


def test_interrupted_download_leaves_no_partial_or_temp_files(tmp_path: Path) -> None:
    gateway = FakeProductGateway(
        fail_times=10, partial_content_on_failure=b"partial-bytes", file_content=b"never-reached"
    )
    downloader = _downloader(tmp_path, gateway, max_attempts=2)
    product = _product()

    with pytest.raises(RetryExhaustedError):
        downloader.download(product)

    remaining = list((tmp_path / "sector_001").glob("*"))
    assert remaining == []


def test_checksum_mismatch_when_size_does_not_match_manifest(tmp_path: Path) -> None:
    gateway = FakeProductGateway(file_content=b"short")
    downloader = _downloader(tmp_path, gateway)
    product = _product(size_bytes=999)

    with pytest.raises(ChecksumMismatchError):
        downloader.download(product)

    assert list((tmp_path / "sector_001").glob("*")) == []


def test_retries_transient_failures_then_succeeds(tmp_path: Path) -> None:
    gateway = FakeProductGateway(fail_times=2, file_content=b"eventually-ok")
    downloader = _downloader(tmp_path, gateway, max_attempts=3)
    product = _product(size_bytes=len(b"eventually-ok"))

    artifact = downloader.download(product)

    assert gateway.fetch_calls == 3
    assert artifact.was_downloaded is True


def test_retry_exhausted_after_max_attempts(tmp_path: Path) -> None:
    gateway = FakeProductGateway(fail_times=10)
    downloader = _downloader(tmp_path, gateway, max_attempts=3)
    product = _product()

    with pytest.raises(RetryExhaustedError):
        downloader.download(product)

    assert gateway.fetch_calls == 3


def test_non_transient_errors_are_not_retried(tmp_path: Path) -> None:
    class RaisesValueError(FakeProductGateway):
        def fetch_product(self, data_uri: str, dest_path: Path) -> None:
            self.fetch_calls += 1
            raise ValueError("not a MastServiceError, must not be retried")

    gateway = RaisesValueError()
    downloader = _downloader(tmp_path, gateway, max_attempts=3)
    product = _product()

    with pytest.raises(ValueError, match="must not be retried"):
        downloader.download(product)

    assert gateway.fetch_calls == 1


def test_list_products_retries_transient_failures() -> None:
    class RetryingListGateway(FakeProductGateway):
        def __init__(self) -> None:
            super().__init__()
            self.list_attempts = 0

        def list_products(self, obs_id: str) -> list[dict[str, Any]]:
            self.list_attempts += 1
            if self.list_attempts < 2:
                raise MastServiceError("transient")
            return [{"productFilename": "x.fits"}]

    gateway = RetryingListGateway()
    downloader = LightCurveDownloader(
        Path("unused"), gateway=gateway, sleep=lambda _seconds: None, max_attempts=3
    )

    rows = downloader.list_products("obs-1")

    assert rows == [{"productFilename": "x.fits"}]
    assert gateway.list_attempts == 2
