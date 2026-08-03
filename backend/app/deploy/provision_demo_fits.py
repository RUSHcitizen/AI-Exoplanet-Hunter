"""Build-time provisioning of the fixed Pi Mensae demonstration FITS file.

The public Phase 4B deployment image needs the same cached SPOC light
curve (TIC 261136679, TESS sector 1,
``tess2018206045859-s0001-0000000261136679-0120-s_lc.fits``) that every
Phase 3A-4A real-data check in ``docs/architecture.md`` was run against.
That file is gitignored (``data/`` is local, generated cache -- see
``.gitignore``), so the deployment image fetches it once, from NASA's
Mikulski Archive for Space Telescopes (MAST), during ``docker build``.

This module is invoked by ``backend/Dockerfile`` as
``python -m app.deploy.provision_demo_fits`` -- never by the running
server process, never in response to an HTTP request, and never with a
caller-supplied URL or path: ``MAST_PRODUCT_URI`` and
``EXPECTED_SHA256`` are fixed module constants, and :func:`main` takes
no arguments.

Verification is deliberately strict: the download streams to a
temporary file in the destination directory, its SHA-256 is computed
while streaming, and the file is moved into place with
``os.replace`` (atomic on the same filesystem) only after the checksum
-- and, if provided, the size -- match exactly. Any failure removes the
temporary file and raises, which fails the ``docker build`` step rather
than shipping an unverified or partial file.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

# --- Fixed official NASA/MAST product identity ------------------------------
#
# TIC 261136679 (Pi Mensae), TESS sector 1, SPOC 2-minute-cadence light
# curve -- the exact product every Phase 3A-4A real-data sanity check in
# docs/architecture.md was run against. This is a MAST "Direct Object
# Access" URI resolved through MAST's public download endpoint; both
# constants are intentionally fixed, not configurable via environment
# variable, CLI argument, or request parameter, so this script can never
# be pointed at an arbitrary URL.
MAST_PRODUCT_URI = "mast:TESS/product/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
MAST_DOWNLOAD_URL = f"https://mast.stsci.edu/api/v0.1/Download/file?uri={MAST_PRODUCT_URI}"

# Pinned to the checksum recorded in docs/architecture.md's Phase 3A
# real-data sanity check. This value must never be silently replaced --
# changing it is a deliberate, reviewable source change, not a routine
# update.
EXPECTED_SHA256 = "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609"
EXPECTED_SIZE_BYTES: int | None = 2_039_040

DEFAULT_DEST_PATH = Path(
    "/data/raw/tess/sector_001/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
)

DEFAULT_TIMEOUT_SECONDS = 60.0
_CHUNK_SIZE = 1024 * 1024


class ProvisioningError(RuntimeError):
    """Raised when the fetched product fails checksum or size verification."""


class _UrlResponse(Protocol):
    """The subset of ``http.client.HTTPResponse`` this module depends on."""

    status: int

    def read(self, amt: int) -> bytes: ...

    def __enter__(self) -> _UrlResponse: ...

    def __exit__(self, *exc_info: object) -> None: ...


class _UrlOpener(Protocol):
    """The subset of ``urllib.request.urlopen`` this module depends on.

    Injectable so tests can supply a fake response without making a real
    network call (see ``backend/tests/test_provision_demo_fits.py``).
    """

    def __call__(self, url: str, *, timeout: float) -> _UrlResponse: ...


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def provision(
    dest_path: Path = DEFAULT_DEST_PATH,
    *,
    url: str = MAST_DOWNLOAD_URL,
    expected_sha256: str = EXPECTED_SHA256,
    expected_size_bytes: int | None = EXPECTED_SIZE_BYTES,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    opener: _UrlOpener = urlopen,
) -> Path:
    """Download, verify, and atomically install the fixed demo FITS file.

    Idempotent and safe to run against a filesystem that already has a
    file at ``dest_path``: if it already matches ``expected_sha256``, no
    network request is made at all. If it exists but does NOT match
    (e.g. from an interrupted earlier build), it is replaced -- the
    replacement is downloaded fresh and subject to the exact same
    verification as a first-time install.

    Raises:
        ProvisioningError: the HTTP status was not 200, or the
            downloaded bytes did not match ``expected_sha256`` (or
            ``expected_size_bytes``, when given). The temporary file is
            always removed before this is raised; ``dest_path`` is never
            modified.
    """
    if dest_path.is_file() and _sha256_of(dest_path) == expected_sha256:
        print(
            f"[provision_demo_fits] {dest_path} already present and verified "
            "(sha256 match); skipping download."
        )
        return dest_path

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=dest_path.parent, prefix=f".{dest_path.name}.", suffix=".part"
    )
    tmp_path = Path(tmp_name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as tmp_file:
            try:
                response = opener(url, timeout=timeout_seconds)
            except (HTTPError, URLError) as exc:
                raise ProvisioningError(f"Failed to download {url!r}: {exc}") from exc

            with response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ProvisioningError(f"Unexpected HTTP status {status} downloading {url!r}.")
                while True:
                    chunk = response.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    tmp_file.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise ProvisioningError(
                f"SHA-256 mismatch downloading {url!r}: expected {expected_sha256}, "
                f"got {actual_sha256}. Refusing to install unverified data."
            )
        if expected_size_bytes is not None and size != expected_size_bytes:
            raise ProvisioningError(
                f"Size mismatch downloading {url!r}: expected {expected_size_bytes} "
                f"bytes, got {size}."
            )

        os.replace(tmp_path, dest_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    print(
        f"[provision_demo_fits] Verified and installed {dest_path} "
        f"({size} bytes, sha256={actual_sha256})."
    )
    return dest_path


def main() -> int:
    """CLI entry point. Accepts no arguments -- the product URI,
    checksum, and destination are always the fixed module constants."""
    try:
        provision()
    except ProvisioningError as exc:
        print(f"[provision_demo_fits] FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
