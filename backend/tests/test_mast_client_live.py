"""Optional live integration check against the real MAST service.

Excluded from normal ``pytest`` runs (see the ``-m "not live"`` default
in ``pyproject.toml``). Requires network access and makes one real
request to MAST for a well-known target, so it will fail if MAST is
unreachable -- that is expected and does not indicate a code bug.

Run explicitly with:

    pytest -m live tests/test_mast_client_live.py
"""

import pytest

from app.data.mast_client import MastClient

pytestmark = pytest.mark.live


def test_search_target_against_real_mast() -> None:
    client = MastClient()

    result = client.search_target("TIC 261136679")

    assert result.observation_count > 0
    assert result.tic_id == 261136679
    assert result.sectors
