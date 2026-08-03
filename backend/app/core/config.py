"""Application configuration, loaded from environment variables.

Using pydantic-settings means every setting is typed and validated at
startup instead of being read ad hoc with ``os.environ.get`` scattered
through the codebase. If a required variable is missing or malformed,
the application fails immediately with a clear error rather than
failing confusingly later during a request.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings.

    Values are loaded, in order of precedence, from: environment
    variables, then a local ``.env`` file, then the defaults below.
    Never commit a populated ``.env`` file -- see ``.env.example``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Exoplanet Hunter API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "console"

    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    database_url: str = "postgresql+psycopg://exoplanet:exoplanet@localhost:5432/exoplanet_hunter"

    data_dir: str = "../data"
    mast_cache_dir: str = "../data/raw/tess"

    pi_mensae_demo_fits_path: str = (
        "../data/raw/tess/sector_001/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits"
    )
    """Fixed local cache path for the Phase 4A Pi Mensae demonstration
    light curve (TIC 261136679, sector 1, SPOC). Never supplied by the
    frontend -- the demo API always resolves this one path."""


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    ``lru_cache`` ensures the environment is parsed once per process
    instead of on every request, while still allowing tests to call
    ``get_settings.cache_clear()`` to force a reload.
    """
    return Settings()
