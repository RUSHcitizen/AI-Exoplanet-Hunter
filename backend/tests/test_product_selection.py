"""Tests for deterministic light-curve product selection.

``list_products`` is a plain injected callable here (no network/gateway
involved), so these tests never touch astroquery or MAST.
"""

from typing import Any

import pytest

from app.data.exceptions import TargetNotFoundError
from app.data.models import TessObservation
from app.data.product_selection import select_product


def _obs(
    obs_id: str = "obs-1",
    sector: int | None = 1,
    author: str | None = "SPOC",
    cadence_seconds: float | None = 120.0,
    dataproduct_type: str = "timeseries",
) -> TessObservation:
    return TessObservation(
        obs_id=obs_id,
        target_name="261136679",
        mission="TESS",
        dataproduct_type=dataproduct_type,
        sector=sector,
        author=author,
        cadence_seconds=cadence_seconds,
        calib_level=3,
    )


def _lc_row(filename: str = "tess-s0001-lc.fits", subgroup: str | None = "LC") -> dict[str, Any]:
    return {
        "productFilename": filename,
        "productSubGroupDescription": subgroup,
        "dataURI": f"mast:TESS/product/{filename}",
        "size": 12345,
        "description": "Light curves",
    }


def test_selects_the_only_light_curve_product() -> None:
    obs = _obs()
    products_by_obs = {"obs-1": [_lc_row()]}

    selected = select_product([obs], lambda obs_id: products_by_obs[obs_id], tic_id=261136679)

    assert selected.obs_id == "obs-1"
    assert selected.tic_id == 261136679
    assert selected.filename == "tess-s0001-lc.fits"
    assert selected.data_uri == "mast:TESS/product/tess-s0001-lc.fits"
    assert selected.size_bytes == 12345


def test_ignores_non_timeseries_observations() -> None:
    observations = [_obs(obs_id="ffi-1", dataproduct_type="image"), _obs(obs_id="obs-1")]
    products_by_obs = {"obs-1": [_lc_row()], "ffi-1": [_lc_row(filename="should-not-pick.fits")]}

    selected = select_product(
        observations, lambda obs_id: products_by_obs[obs_id], tic_id=261136679
    )

    assert selected.obs_id == "obs-1"


def test_filters_out_non_light_curve_products() -> None:
    obs = _obs()
    products = [
        {
            "productFilename": "tess-s0001-tp.fits",
            "productSubGroupDescription": "TP",
            "dataURI": "mast:TESS/product/tp.fits",
            "size": 999,
            "description": "Target pixel file",
        },
        _lc_row(),
    ]

    selected = select_product([obs], lambda _obs_id: products, tic_id=261136679)

    assert selected.filename == "tess-s0001-lc.fits"


def test_accepts_qlp_light_curve_by_filename_suffix_without_subgroup() -> None:
    obs = _obs(author="QLP", cadence_seconds=1800.0)
    products = [
        {
            "productFilename": "hlsp_qlp_tess_s0001_llc.fits",
            "productSubGroupDescription": None,
            "dataURI": "mast:TESS/product/hlsp_qlp_tess_s0001_llc.fits",
            "size": 500,
            "description": None,
        }
    ]

    selected = select_product([obs], lambda _obs_id: products, tic_id=261136679)

    assert selected.filename == "hlsp_qlp_tess_s0001_llc.fits"
    assert selected.description is None


def test_sector_filter_excludes_non_matching_observations() -> None:
    observations = [_obs(obs_id="obs-1", sector=1), _obs(obs_id="obs-2", sector=37)]
    products_by_obs = {
        "obs-1": [_lc_row(filename="sector1.fits")],
        "obs-2": [_lc_row(filename="sector37.fits")],
    }

    selected = select_product(
        observations, lambda obs_id: products_by_obs[obs_id], tic_id=1, sector=37
    )

    assert selected.filename == "sector37.fits"


def test_author_filter_is_case_insensitive() -> None:
    obs = _obs(author="SPOC")
    products = [_lc_row()]

    selected = select_product([obs], lambda _obs_id: products, tic_id=1, author="spoc")

    assert selected.filename == "tess-s0001-lc.fits"


def test_cadence_filter_excludes_non_matching_observations() -> None:
    observations = [
        _obs(obs_id="obs-1", cadence_seconds=120.0),
        _obs(obs_id="obs-2", cadence_seconds=1800.0),
    ]
    products_by_obs = {
        "obs-1": [_lc_row(filename="fast.fits")],
        "obs-2": [_lc_row(filename="slow.fits")],
    }

    selected = select_product(
        observations, lambda obs_id: products_by_obs[obs_id], tic_id=1, cadence_seconds=1800.0
    )

    assert selected.filename == "slow.fits"


def test_pipeline_priority_prefers_spoc_over_qlp_when_both_match_filters() -> None:
    observations = [
        _obs(obs_id="obs-qlp", author="QLP", cadence_seconds=1800.0),
        _obs(obs_id="obs-spoc", author="SPOC", cadence_seconds=120.0),
    ]
    products_by_obs = {
        "obs-qlp": [_lc_row(filename="qlp-llc.fits")],
        "obs-spoc": [_lc_row(filename="spoc-lc.fits")],
    }

    selected = select_product(observations, lambda obs_id: products_by_obs[obs_id], tic_id=1)

    assert selected.filename == "spoc-lc.fits"


def test_falls_through_to_next_observation_when_first_has_no_lc_product() -> None:
    observations = [_obs(obs_id="obs-spoc", author="SPOC"), _obs(obs_id="obs-qlp", author="QLP")]
    products_by_obs: dict[str, list[dict[str, Any]]] = {
        "obs-spoc": [
            {
                "productFilename": "spoc-tp.fits",
                "productSubGroupDescription": "TP",
                "dataURI": "mast:TESS/product/tp.fits",
                "size": 1,
                "description": None,
            }
        ],
        "obs-qlp": [_lc_row(filename="hlsp_qlp_tess_s0001_llc.fits", subgroup=None)],
    }

    selected = select_product(observations, lambda obs_id: products_by_obs[obs_id], tic_id=1)

    assert selected.filename == "hlsp_qlp_tess_s0001_llc.fits"


def test_raises_target_not_found_when_no_observation_has_a_light_curve_product() -> None:
    obs = _obs()
    products = [
        {
            "productFilename": "tess-s0001-tp.fits",
            "productSubGroupDescription": "TP",
            "dataURI": "mast:TESS/product/tp.fits",
            "size": 1,
            "description": None,
        }
    ]

    with pytest.raises(TargetNotFoundError):
        select_product([obs], lambda _obs_id: products, tic_id=1)


def test_raises_target_not_found_when_sector_filter_matches_nothing() -> None:
    obs = _obs(sector=1)

    with pytest.raises(TargetNotFoundError, match="sector=99"):
        select_product([obs], lambda _obs_id: [_lc_row()], tic_id=1, sector=99)
