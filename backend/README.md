# Exoplanet Hunter — Backend

FastAPI service for TESS light-curve acquisition, transit detection, ML
classification, and candidate reporting. See the [repository root
README](../README.md) for full setup instructions and the [architecture
document](../docs/architecture.md) for the system design.

## Quick start

```bash
uv venv --python 3.13 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload
```

## Testing & quality

```bash
pytest
ruff check .
ruff format .
mypy app
```
