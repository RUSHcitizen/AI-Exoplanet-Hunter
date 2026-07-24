"""Shared pytest fixtures for the backend test suite."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A TestClient wrapping a freshly constructed FastAPI app.

    Building the app via ``create_app`` (rather than importing the
    module-level ``app`` singleton) keeps each test isolated from
    state mutated by any other test.
    """
    with TestClient(create_app()) as test_client:
        yield test_client
