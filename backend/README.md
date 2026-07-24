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

## TESS FITS download and inspection (Phase 2B)

Download one light-curve product for a target (deterministic product
selection -- see `app/data/product_selection.py` for the rules; cached
under `data/raw/tess/`, gitignored):

```bash
python -m app.cli download-target --target "TIC 261136679" --sector 1
python -m app.cli download-target --target "TIC 261136679" --sector 1 --author SPOC
python -m app.cli download-target --target "TIC 261136679" --sector 1 --force
python -m app.cli download-target --target "TIC 261136679" --sector 1 --output-dir /tmp/tess-cache
```

Inspect a downloaded FITS file (descriptive only -- does not modify data):

```bash
python -m app.cli inspect-fits data/raw/tess/sector_001/<filename>.fits
```

To clear a cached file safely, delete both it and its `.sha256` sidecar
(or remove the whole `data/raw/tess/` directory) and re-run
`download-target`.

See [`docs/architecture.md`](../docs/architecture.md#current-status-phase-2b-tess-fits-download-and-raw-parsing)
for what this does and does not implement, the cache layout, and
known limitations.

## Testing & quality

```bash
pytest
ruff check .
ruff format .
mypy app
```
