"""Tests for the build-time Pi Mensae FITS provisioning script
(``app.deploy.provision_demo_fits``).

Every test injects a fake ``opener`` callable -- none makes a real
network request, matching the same dependency-injection pattern
``app/data/downloader.py``'s tests use for ``MastProductGateway``. A
separately marked live test may exercise the real MAST endpoint later,
but is intentionally not part of this file or the default suite.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.deploy.provision_demo_fits import (
    EXPECTED_SHA256,
    EXPECTED_SIZE_BYTES,
    MAST_DOWNLOAD_URL,
    MAST_PRODUCT_URI,
    ProvisioningError,
    provision,
)

_PAYLOAD = b"pretend-fits-bytes" * 100
_PAYLOAD_SHA256 = hashlib.sha256(_PAYLOAD).hexdigest()


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._remaining: bytes | None = payload
        self.status = status

    def read(self, size: int) -> bytes:
        if self._remaining is None:
            return b""
        chunk, self._remaining = self._remaining, None
        return chunk

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None


def _opener_returning(payload: bytes, status: int = 200):  # type: ignore[no-untyped-def]
    def _opener(url: str, *, timeout: float) -> _FakeResponse:
        return _FakeResponse(payload, status=status)

    return _opener


def test_module_constants_are_fixed_and_not_user_controllable() -> None:
    """provision()'s defaults are the only URL/checksum this script ever
    uses -- there is no environment variable, CLI flag, or request
    parameter that can override them."""
    assert MAST_PRODUCT_URI.startswith("mast:TESS/product/")
    assert MAST_DOWNLOAD_URL.startswith("https://mast.stsci.edu/")
    assert EXPECTED_SHA256 == "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609"
    assert EXPECTED_SIZE_BYTES == 2_039_040


def test_accepts_mocked_correct_payload(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    result = provision(
        dest,
        url="https://example.invalid/fixed",
        expected_sha256=_PAYLOAD_SHA256,
        expected_size_bytes=len(_PAYLOAD),
        opener=_opener_returning(_PAYLOAD),
    )
    assert result == dest
    assert dest.is_file()
    assert dest.read_bytes() == _PAYLOAD


def test_rejects_incorrect_sha256(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    with pytest.raises(ProvisioningError, match="SHA-256 mismatch"):
        provision(
            dest,
            url="https://example.invalid/fixed",
            expected_sha256="0" * 64,
            expected_size_bytes=None,
            opener=_opener_returning(_PAYLOAD),
        )
    assert not dest.exists()


def test_rejects_incorrect_size(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    with pytest.raises(ProvisioningError, match="Size mismatch"):
        provision(
            dest,
            url="https://example.invalid/fixed",
            expected_sha256=_PAYLOAD_SHA256,
            expected_size_bytes=len(_PAYLOAD) + 1,
            opener=_opener_returning(_PAYLOAD),
        )
    assert not dest.exists()


def test_temporary_file_removed_on_failure(tmp_path: Path) -> None:
    dest_dir = tmp_path / "sector_001"
    dest = dest_dir / "pi_mensae.fits"
    with pytest.raises(ProvisioningError):
        provision(
            dest,
            url="https://example.invalid/fixed",
            expected_sha256="0" * 64,
            expected_size_bytes=None,
            opener=_opener_returning(_PAYLOAD),
        )
    assert list(dest_dir.iterdir()) == []


def test_rejects_non_200_status(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    with pytest.raises(ProvisioningError, match="HTTP status"):
        provision(
            dest,
            url="https://example.invalid/fixed",
            expected_sha256=_PAYLOAD_SHA256,
            opener=_opener_returning(_PAYLOAD, status=503),
        )
    assert not dest.exists()


def test_existing_correct_file_is_reused_without_network_call(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(_PAYLOAD)

    calls: list[str] = []

    def _opener(url: str, *, timeout: float) -> _FakeResponse:
        calls.append(url)
        return _FakeResponse(_PAYLOAD)

    provision(
        dest,
        url="https://example.invalid/fixed",
        expected_sha256=_PAYLOAD_SHA256,
        expected_size_bytes=len(_PAYLOAD),
        opener=_opener,
    )
    assert calls == []


def test_existing_incorrect_file_is_replaced(tmp_path: Path) -> None:
    dest = tmp_path / "sector_001" / "pi_mensae.fits"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"stale-wrong-content")

    provision(
        dest,
        url="https://example.invalid/fixed",
        expected_sha256=_PAYLOAD_SHA256,
        expected_size_bytes=len(_PAYLOAD),
        opener=_opener_returning(_PAYLOAD),
    )
    assert dest.read_bytes() == _PAYLOAD


def test_atomic_move_only_happens_after_successful_verification(tmp_path: Path) -> None:
    """dest_path must never exist mid-download or after a failed
    verification -- only ``os.replace`` after every check passes."""
    dest_dir = tmp_path / "sector_001"
    dest = dest_dir / "pi_mensae.fits"

    with pytest.raises(ProvisioningError):
        provision(
            dest,
            url="https://example.invalid/fixed",
            expected_sha256="0" * 64,
            expected_size_bytes=None,
            opener=_opener_returning(_PAYLOAD),
        )
    assert not dest.exists()

    provision(
        dest,
        url="https://example.invalid/fixed",
        expected_sha256=_PAYLOAD_SHA256,
        expected_size_bytes=len(_PAYLOAD),
        opener=_opener_returning(_PAYLOAD),
    )
    assert dest.is_file()
