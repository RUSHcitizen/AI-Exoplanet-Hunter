# Exoplanet Hunter — Backend

FastAPI service for TESS light-curve acquisition, transit detection, ML
classification, and candidate reporting. See the [repository root
README](../README.md) for full setup instructions and the [architecture
document](../docs/architecture.md) for the system design.

## Quick start

```bash
uv venv --python 3.13 .venv
source .venv/bin/activate
uv pip install -e ".[dev,mast]"
uvicorn app.main:app --reload
```

## TESS target search (Phase 2A)

```bash
python -m app.cli search-target --target "TIC 261136679"
python -m app.cli search-target --target "Pi Mensae"
```

See [`docs/architecture.md`](../docs/architecture.md#current-status-phase-2a-tess-target--observation-discovery)
for what this does and does not implement.

## Testing & quality

```bash
pytest
ruff check .
ruff format .
mypy app
```
