"""Tests for the CLI presentation layer.

The CLI is exercised directly via ``run_search_target``/``main`` with an
injected fake ``MastClient`` (or a monkeypatched ``run_search_target``),
so no network access or real astroquery calls happen here.
"""

import pytest

from app import cli
from app.data.exceptions import InvalidTargetError, MastServiceError, TargetNotFoundError
from app.data.models import TargetSearchResult, TessObservation


class FakeClient:
    def __init__(
        self, result: TargetSearchResult | None = None, error: Exception | None = None
    ) -> None:
        self._result = result
        self._error = error

    def search_target(self, target: str) -> TargetSearchResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _sample_result() -> TargetSearchResult:
    return TargetSearchResult(
        query="TIC 261136679",
        resolved_target="TIC 261136679",
        tic_id=261136679,
        observations=(
            TessObservation(
                obs_id="obs-1",
                target_name="261136679",
                mission="TESS",
                dataproduct_type="timeseries",
                sector=37,
                author="SPOC",
                cadence_seconds=120.0,
                calib_level=3,
            ),
        ),
    )


def test_run_search_target_success_prints_report(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = cli.run_search_target("TIC 261136679", client=FakeClient(result=_sample_result()))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Resolved target:       TIC 261136679" in out
    assert "Matching observations: 1" in out
    assert "sector=37" in out
    assert "author=SPOC" in out


def test_run_search_target_invalid_target_returns_exit_code_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "???", client=FakeClient(error=InvalidTargetError("bad target"))
    )

    assert exit_code == 2
    assert "Invalid target: bad target" in capsys.readouterr().err


def test_run_search_target_not_found_returns_exit_code_1(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "TIC 1", client=FakeClient(error=TargetNotFoundError("no observations"))
    )

    assert exit_code == 1
    assert "Target not found: no observations" in capsys.readouterr().err


def test_run_search_target_service_error_returns_exit_code_3(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.run_search_target(
        "TIC 1", client=FakeClient(error=MastServiceError("timed out"))
    )

    assert exit_code == 3
    assert "MAST service error: timed out" in capsys.readouterr().err


def test_main_dispatches_search_target_with_parsed_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def fake_run_search_target(target: str, client: object = None) -> int:
        captured["target"] = target
        return 0

    monkeypatch.setattr(cli, "run_search_target", fake_run_search_target)

    exit_code = cli.main(["search-target", "--target", "TIC 261136679"])

    assert exit_code == 0
    assert captured["target"] == "TIC 261136679"


def test_main_requires_target_argument() -> None:
    with pytest.raises(SystemExit):
        cli.main(["search-target"])
