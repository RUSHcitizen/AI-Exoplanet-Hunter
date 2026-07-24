"""Tests for application configuration loading."""

from app.core.config import Settings, get_settings


def test_default_settings_are_sane() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
