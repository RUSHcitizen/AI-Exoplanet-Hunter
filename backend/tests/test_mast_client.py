"""Tests for TESS/MAST target discovery business logic.

All network access is mocked: ``FakeGateway`` implements the same
``MastGateway`` protocol as ``AstroqueryMastGateway`` but never touches
astroquery or the network, so these tests never depend on live MAST
availability.
"""

from typing import Any

import pytest

from app.data.exceptions import InvalidTargetError, MastServiceError, TargetNotFoundError
from app.data.mast_client import MastClient


class FakeGateway:
    def __init__(
        self,
        tic_rows: list[dict[str, Any]] | None = None,
        name_rows: list[dict[str, Any]] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self.tic_rows = tic_rows or []
        self.name_rows = name_rows or []
        self.raise_error = raise_error
        self.tic_calls: list[int] = []
        self.name_calls: list[str] = []

    def query_by_tic(self, tic_id: int) -> list[dict[str, Any]]:
        self.tic_calls.append(tic_id)
        if self.raise_error is not None:
            raise self.raise_error
        return self.tic_rows

    def query_by_name(self, name: str) -> list[dict[str, Any]]:
        self.name_calls.append(name)
        if self.raise_error is not None:
            raise self.raise_error
        return self.name_rows


def _row(
    obs_id: str = "obs-1",
    target_name: str = "261136679",
    obs_collection: str = "TESS",
    dataproduct_type: str = "timeseries",
    sequence_number: int | None = 42,
    provenance_name: str | None = "SPOC",
    t_exptime: float | None = 120.0,
    calib_level: int | None = 3,
) -> dict[str, Any]:
    return {
        "obs_id": obs_id,
        "target_name": target_name,
        "obs_collection": obs_collection,
        "dataproduct_type": dataproduct_type,
        "sequence_number": sequence_number,
        "provenance_name": provenance_name,
        "t_exptime": t_exptime,
        "calib_level": calib_level,
    }


def test_search_by_tic_id_returns_typed_result() -> None:
    gateway = FakeGateway(
        tic_rows=[
            _row(obs_id="obs-1", sequence_number=10, provenance_name="SPOC", t_exptime=120.0),
            _row(obs_id="obs-2", sequence_number=37, provenance_name="QLP", t_exptime=1800.0),
        ]
    )
    client = MastClient(gateway=gateway)

    result = client.search_target("TIC 261136679")

    assert gateway.tic_calls == [261136679]
    assert result.resolved_target == "TIC 261136679"
    assert result.tic_id == 261136679
    assert result.observation_count == 2
    assert result.sectors == [10, 37]
    assert result.observations[0].author == "SPOC"
    assert result.observations[1].cadence_seconds == 1800.0


def test_tic_id_accepts_bare_digits_and_lowercase_prefix() -> None:
    gateway = FakeGateway(tic_rows=[_row()])
    client = MastClient(gateway=gateway)

    client.search_target("261136679")
    client.search_target("tic261136679")

    assert gateway.tic_calls == [261136679, 261136679]


def test_search_by_name_resolves_tic_id_from_target_name() -> None:
    gateway = FakeGateway(name_rows=[_row(target_name="261136679")])
    client = MastClient(gateway=gateway)

    result = client.search_target("Pi Mensae")

    assert gateway.name_calls == ["Pi Mensae"]
    assert result.resolved_target == "261136679"
    assert result.tic_id == 261136679


def test_search_by_name_without_numeric_target_name_leaves_tic_id_none() -> None:
    gateway = FakeGateway(name_rows=[_row(target_name="Some Non-Numeric Target")])
    client = MastClient(gateway=gateway)

    result = client.search_target("Pi Mensae")

    assert result.tic_id is None
    assert result.resolved_target == "Some Non-Numeric Target"


def test_search_by_name_skips_generic_ffi_rows_to_find_tic_id() -> None:
    # A cone search can return full-frame-image rows with a generic
    # target_name ("TESS FFI") ahead of the star's own timeseries row.
    gateway = FakeGateway(
        name_rows=[
            _row(target_name="TESS FFI", dataproduct_type="image", obs_id="ffi-1"),
            _row(target_name="261136679", dataproduct_type="timeseries", obs_id="ts-1"),
        ]
    )
    client = MastClient(gateway=gateway)

    result = client.search_target("Pi Mensae")

    assert result.resolved_target == "261136679"
    assert result.tic_id == 261136679


def test_search_raises_target_not_found_when_no_rows() -> None:
    client = MastClient(gateway=FakeGateway(tic_rows=[]))

    with pytest.raises(TargetNotFoundError):
        client.search_target("TIC 999999999")


def test_search_raises_invalid_target_for_empty_string() -> None:
    gateway = FakeGateway()
    client = MastClient(gateway=gateway)

    with pytest.raises(InvalidTargetError):
        client.search_target("   ")

    assert gateway.tic_calls == []
    assert gateway.name_calls == []


def test_search_raises_invalid_target_for_unsupported_characters() -> None:
    gateway = FakeGateway()
    client = MastClient(gateway=gateway)

    with pytest.raises(InvalidTargetError):
        client.search_target("???")

    assert gateway.tic_calls == []
    assert gateway.name_calls == []


def test_search_raises_invalid_target_for_zero_tic_id() -> None:
    client = MastClient(gateway=FakeGateway())

    with pytest.raises(InvalidTargetError):
        client.search_target("TIC 0")


def test_gateway_service_error_propagates() -> None:
    client = MastClient(gateway=FakeGateway(raise_error=MastServiceError("timeout")))

    with pytest.raises(MastServiceError):
        client.search_target("TIC 261136679")


def test_masked_optional_fields_become_none() -> None:
    gateway = FakeGateway(
        tic_rows=[
            _row(sequence_number=None, provenance_name=None, t_exptime=None, calib_level=None)
        ]
    )
    client = MastClient(gateway=gateway)

    result = client.search_target("TIC 261136679")

    obs = result.observations[0]
    assert obs.sector is None
    assert obs.author is None
    assert obs.cadence_seconds is None
    assert obs.calib_level is None
