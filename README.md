# AI Exoplanet Hunter

A research-grade pipeline that downloads real NASA TESS telescope
observations, searches them for planetary transit signals, ranks candidates
with machine learning, cross-checks them against known-exoplanet catalogs,
and presents everything in an interactive Mission Control dashboard.

See [`docs/architecture.md`](docs/architecture.md) for the full system
design, data flow, and rationale behind each technology choice.

> **Scientific integrity notice**: this system never labels an unmatched
> signal a confirmed exoplanet. Candidates are reported with scientifically
> careful language such as *"Unmatched candidate signal -- not a confirmed
> exoplanet."* See the integrity rules at the bottom of this file.

## Project status

**Phase 1: Foundation and local development environment** -- complete. See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-1-foundation)
for exactly what that includes.

**Phase 2A: TESS target and observation discovery** -- complete. Search
MAST for a target's available TESS sectors, pipeline/author, and cadence
without downloading any FITS files:

```bash
cd backend
python -m app.cli search-target --target "TIC 261136679"
python -m app.cli search-target --target "Pi Mensae"
```

See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-2a-tess-target--observation-discovery)
for exactly what is and isn't implemented yet.

**Phase 2B: TESS FITS download and raw parsing** -- complete. Download
one selected light-curve product, cache it locally with a checksum, and
parse it into typed raw arrays (no preprocessing):

```bash
cd backend
python -m app.cli download-target --target "TIC 261136679" --sector 1
python -m app.cli inspect-fits data/raw/tess/sector_001/<filename>.fits
```

See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-2b-tess-fits-download-and-raw-parsing)
for the cache design, FITS fields extracted, and known limitations.

## Prerequisites

- Python 3.12+ (this project uses [`uv`](https://docs.astral.sh/uv/) to
  manage an isolated 3.13 environment, so your system Python doesn't need to
  match)
- Node.js 22+
- Docker and Docker Compose (for the full-stack option)

## Quick start

### Option A: run backend and frontend directly (fastest iteration)

```bash
# One-time setup
cp .env.example .env
make install

# Run both dev servers (Ctrl+C stops both)
make dev
```

- Backend: http://localhost:8000 (docs at `/docs`, health check at
  `/api/v1/health`)
- Frontend: http://localhost:3000

### Option B: run the full stack with Docker Compose

```bash
cp .env.example .env
make docker-up
```

This starts PostgreSQL, the backend, and the frontend together. Use
`make docker-down` to stop everything.

## Common commands

```bash
make install     # Install backend (uv) and frontend (npm) dependencies
make dev         # Run backend + frontend dev servers
make test        # Run backend (pytest) and frontend (vitest) test suites
make lint        # Ruff (backend) + ESLint (frontend)
make format      # Auto-format backend (ruff format) and frontend
make typecheck   # mypy (backend) + tsc --noEmit (frontend)
make docker-up   # Build and start the full Docker Compose stack
make docker-down # Stop the Docker Compose stack
```

Each of these also has a `-backend` / `-frontend` suffixed variant (e.g.
`make test-backend`) if you only want to run one side.

## Repository structure

```text
exoplanet-hunter/
|-- backend/     FastAPI service (Python)
|-- frontend/    Next.js Mission Control dashboard (TypeScript)
|-- data/        raw/processed/synthetic/models -- local data, gitignored
|-- docs/        Architecture and future guides
|-- notebooks/   Exploratory analysis
|-- reports/     Generated scientific candidate reports (gitignored)
|-- scripts/     One-off operational scripts
```

## Pre-commit hooks

This repo ships a `.pre-commit-config.yaml` that runs Ruff, mypy, and
ESLint using the exact tool versions installed by `make install` (so hooks
never drift out of sync with CI). To enable it locally:

```bash
pip install --user pre-commit   # or: pipx install pre-commit
pre-commit install
```

## Continuous integration

Every push and pull request runs `.github/workflows/ci.yml`, which lints,
type-checks, tests, and (for the frontend) builds both the backend and
frontend independently.

## Development roadmap

1. **Foundation & dev environment** -- done.
2. Real TESS Data Explorer -- CLI-driven download and FITS parsing.
   - **2A: target and observation discovery** -- done.
   - **2B: FITS download, caching, and parsing** -- done (this milestone).
3. Light-curve preprocessing pipeline.
4. Transit-search engine (Box Least Squares + pluggable interface).
5. Physical property estimation.
6. Synthetic planetary system generator.
7. Candidate feature engineering.
8. Machine-learning classifier (classical baseline).
9. Known-planet cross-matching.
10. Candidate-ranking engine.
11. Full database schema + migrations.
12. Full FastAPI endpoint surface.
13. Full Mission Control dashboard (target explorer, transit-search view,
    candidate detail, model laboratory, system operations).
14. Scientific candidate reports.
15. Autonomous research agent for batch analysis.

Further "extremely difficult" extensions (explainable AI, distributed
processing, citizen-science review, follow-up planning, pixel-level
contamination analysis, multi-planet search, an original detection
algorithm, Bayesian validation, realistic orbital modeling, and full
reproducibility tooling) are planned after the core pipeline (phases 1-15)
is functional.

## Glossary

- **Light curve** -- a star's measured brightness over time.
- **Transit** -- a temporary dip in brightness as a planet passes in front
  of its host star, from our line of sight.
- **Transit depth** -- how much the brightness drops during a transit,
  roughly `(planet radius / star radius)^2`.
- **Orbital period** -- the time for a planet to complete one orbit.
- **Phase folding** -- stacking multiple orbits on top of each other (using
  the orbital period) so repeated transits overlap into one clearer signal.
- **Signal-to-noise ratio (SNR)** -- how strong a transit signal is relative
  to the light curve's background noise.
- **Eclipsing binary (EB)** -- two stars orbiting each other that produce
  transit-like dips; a common false-positive source for planet searches.
- **Limb darkening** -- stars appear dimmer near their visible edge, which
  changes the shape of a transit.
- **Centroid shift** -- if the source of a brightness dip is offset from a
  target star's actual position, it may belong to a different, nearby star.
- **Ephemeris** -- a predicted schedule of future transit times, from a
  known period and reference epoch.
- **False positive** -- a detected signal that mimics a transit but isn't
  caused by a planet (e.g. an eclipsing binary or instrument artifact).
- **TESS sector** -- roughly one month of continuous observation of one
  region of sky by the TESS telescope.
- **FITS file** -- Flexible Image Transport System; the standard file
  format for astronomical data.

## Scientific integrity rules

These rules are mandatory throughout the project:

1. Never call a candidate a confirmed planet without authoritative
   confirmation.
2. Show uncertainties and limitations.
3. Preserve original observations.
4. Record every preprocessing step.
5. Distinguish simulated and real data.
6. Do not hide failed tests.
7. Do not select only favorable examples.
8. Report false positives and false negatives.
9. Explain model limitations.
10. Keep human review in the final decision process.
11. Make every result reproducible.
12. Cite the source of astronomical data in generated reports.

## License

[MIT](LICENSE)
