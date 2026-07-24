"""Downloading and locally caching TESS light-curve FITS products (Phase 2B).

Network access (listing a MAST observation's products, and fetching one)
is isolated behind ``MastProductGateway`` (a ``Protocol``), the same
pattern Phase 2A uses in ``app.data.mast_client``. ``LightCurveDownloader``
is the typed, testable business-logic layer: it computes deterministic
cache paths, reuses a valid cached file unless ``force`` is set, downloads
to a temporary file first and only moves it into place after validating
its size, and retries transient MAST failures with exponential backoff.

Cache layout
------------
Downloads are stored under a cache root (default ``../data/raw/tess``,
see ``app.core.config.Settings.mast_cache_dir``) as::

    <cache_root>/sector_<NNN>/<original MAST filename>
    <cache_root>/sector_<NNN>/<original MAST filename>.sha256

The sector subdirectory keeps the path deterministic given only a
product's identity (sector, filename); the ``.sha256`` sidecar records
the checksum computed right after a successful download, so a later run
can detect local corruption of the cached file without re-contacting
MAST.
"""

import hashlib
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.core.logging import get_logger
from app.data.exceptions import (
    ChecksumMismatchError,
    CorruptedCacheError,
    DownloadError,
    MastServiceError,
    RetryExhaustedError,
)
from app.data.models import CachedArtifact, SelectedProduct

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY_SECONDS = 1.0
_SHA256_SUFFIX = ".sha256"
_CHUNK_SIZE = 1024 * 1024


class MastProductGateway(Protocol):
    """The subset of astroquery's MAST product API this module depends on."""

    def list_products(self, obs_id: str) -> list[dict[str, Any]]: ...

    def fetch_product(self, data_uri: str, dest_path: Path) -> None: ...


class AstroqueryProductGateway:
    """Real MAST product listing/download via astroquery.

    astroquery is imported lazily (inside each method) so building a
    ``LightCurveDownloader`` with an injected fake gateway never requires
    the optional ``mast`` dependency group to be installed.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._timeout_seconds = timeout_seconds

    def list_products(self, obs_id: str) -> list[dict[str, Any]]:
        from astroquery.mast import Conf, Observations

        self._configure_timeout(Conf)
        try:
            table = Observations.get_product_list(obs_id)
        except Exception as exc:
            raise MastServiceError(f"Failed to list products for obs_id {obs_id!r}: {exc}") from exc
        return [{col: record[col] for col in table.colnames} for record in table]

    def fetch_product(self, data_uri: str, dest_path: Path) -> None:
        from astroquery.mast import Conf, Observations

        self._configure_timeout(Conf)
        try:
            # astroquery's return shape for download_file has changed across
            # versions (tuple vs. bare status string), so success is verified
            # by checking the destination file directly rather than parsing
            # the return value.
            Observations.download_file(data_uri, local_path=str(dest_path), cache=False)
        except Exception as exc:
            raise MastServiceError(f"Failed to download product {data_uri!r}: {exc}") from exc
        if not dest_path.exists() or dest_path.stat().st_size == 0:
            raise MastServiceError(f"MAST download of {data_uri!r} produced no data.")

    def _configure_timeout(self, conf: Any) -> None:
        try:
            conf.timeout = self._timeout_seconds
        except AttributeError:
            logger.debug("mast_timeout_config_unavailable")


class LightCurveDownloader:
    """Typed, testable interface for downloading and caching one light-curve
    product at a time."""

    def __init__(
        self,
        cache_root: Path,
        gateway: MastProductGateway | None = None,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        base_delay_seconds: float = DEFAULT_BASE_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._cache_root = cache_root
        self._gateway: MastProductGateway = gateway or AstroqueryProductGateway()
        self._max_attempts = max_attempts
        self._base_delay_seconds = base_delay_seconds
        self._sleep = sleep

    def list_products(self, obs_id: str) -> list[dict[str, Any]]:
        """List an observation's products, retrying transient MAST failures.

        Passed as the ``list_products`` callable to
        ``app.data.product_selection.select_product`` so its deterministic
        filtering logic never has to deal with retries itself.
        """
        result: list[dict[str, Any]] = []

        def _call() -> None:
            nonlocal result
            result = self._gateway.list_products(obs_id)

        self._with_retry(_call)
        return result

    def cache_path(self, product: SelectedProduct) -> Path:
        sector_label = (
            f"sector_{product.sector:03d}" if product.sector is not None else "sector_unknown"
        )
        return self._cache_root / sector_label / product.filename

    def download(self, product: SelectedProduct, *, force: bool = False) -> CachedArtifact:
        dest_path = self.cache_path(product)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if dest_path.exists() and not force:
            sha256 = self._verify_cached_file(dest_path)
            logger.info("download_cache_hit", path=str(dest_path))
            return CachedArtifact(
                product=product,
                local_path=str(dest_path),
                size_bytes=dest_path.stat().st_size,
                sha256=sha256,
                was_downloaded=False,
            )

        return self._download_fresh(product, dest_path)

    def _verify_cached_file(self, dest_path: Path) -> str:
        sidecar_path = _sidecar_path(dest_path)
        if not sidecar_path.exists():
            raise CorruptedCacheError(
                f"Cached file {dest_path} has no checksum sidecar; "
                "re-run with --force to replace it."
            )
        expected = sidecar_path.read_text().strip()
        actual = _sha256_of(dest_path)
        if actual != expected:
            raise CorruptedCacheError(
                f"Cached file {dest_path} does not match its stored checksum; "
                "re-run with --force to replace it."
            )
        return actual

    def _download_fresh(self, product: SelectedProduct, dest_path: Path) -> CachedArtifact:
        fd, tmp_name = tempfile.mkstemp(
            dir=dest_path.parent, prefix=f".{dest_path.name}.", suffix=".part"
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.unlink()  # let the gateway create it fresh; avoids "already exists" ambiguity

        try:

            def _call() -> None:
                self._gateway.fetch_product(product.data_uri, tmp_path)

            self._with_retry(_call)

            size = tmp_path.stat().st_size
            if size == 0:
                raise DownloadError(f"Downloaded file for {product.filename!r} is empty.")
            if product.size_bytes is not None and size != product.size_bytes:
                raise ChecksumMismatchError(
                    f"Downloaded size {size} for {product.filename!r} does not match "
                    f"MAST-reported size {product.size_bytes}."
                )

            sha256 = _sha256_of(tmp_path)
            os.replace(tmp_path, dest_path)
            _sidecar_path(dest_path).write_text(sha256 + "\n")
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.info("download_completed", path=str(dest_path), sha256=sha256, size=size)
        return CachedArtifact(
            product=product,
            local_path=str(dest_path),
            size_bytes=size,
            sha256=sha256,
            was_downloaded=True,
        )

    def _with_retry(self, func: Callable[[], None]) -> None:
        last_error: MastServiceError | None = None
        for attempt in range(self._max_attempts):
            try:
                func()
                return
            except MastServiceError as exc:
                last_error = exc
                logger.warning(
                    "download_attempt_failed",
                    attempt=attempt + 1,
                    max_attempts=self._max_attempts,
                    error=str(exc),
                )
                if attempt < self._max_attempts - 1:
                    self._sleep(self._base_delay_seconds * (2**attempt))
        assert last_error is not None
        raise RetryExhaustedError(
            f"Download failed after {self._max_attempts} attempts: {last_error}"
        ) from last_error


def _sidecar_path(dest_path: Path) -> Path:
    return dest_path.with_name(dest_path.name + _SHA256_SUFFIX)


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
