# Architecture

## Mission

AI Exoplanet Hunter is a research-grade pipeline that downloads real NASA TESS
telescope observations, searches them for planetary transit signals, ranks
candidates with machine learning, cross-checks them against known-exoplanet
catalogs, and presents everything in an interactive Mission Control dashboard.

It is designed to grow over many months of development without becoming
unmaintainable: each phase adds one coherent capability, with tests,
documentation, and provenance tracking added alongside the code.

## System data flow

```text
TESS telescope data (MAST)
        |
Target selection (TIC ID / target name)
        |
Data downloader (astroquery / Lightkurve, cached, checksummed)
        |
FITS-file parser (Astropy)
        |
Quality filtering (TESS quality flags)
        |
Light-curve preprocessing (normalization, sigma clipping, gap detection)
        |
Detrending (median / Savitzky-Golay / spline / custom)
        |
Transit-search engine (Box Least Squares, pluggable interface)
        |
Candidate feature extraction (period, depth, duration, SNR, odd/even, ...)
        |
Physical property estimation (planet radius, equilibrium temperature, ...)
        |
Machine-learning classification (classical baseline -> CNN -> ensemble)
        |
Known-planet cross-check (NASA Exoplanet Archive)
        |
Candidate-ranking engine (transparent, explainable scoring)
        |
PostgreSQL (full provenance: file -> config -> features -> model -> score)
        |
FastAPI service (versioned REST API)
        |
Mission Control dashboard (Next.js) + scientific report generator
```

Every stage records what it did and why -- input file checksum, processing
configuration, code/model version -- so any candidate's score can be traced
back to the raw observation that produced it.

## Monorepo layout

```text
exoplanet-hunter/
|-- backend/            FastAPI service, Python 3.12+, managed with uv
|   |-- app/
|   |   |-- api/         HTTP routers (versioned under /api/v1)
|   |   |-- core/        Settings, structured logging
|   |   |-- data/        TESS/MAST acquisition, FITS parsing        (Phase 2)
|   |   |-- database/    SQLAlchemy models, Alembic migrations       (Phase 2+)
|   |   |-- ml/          Classical/CNN/ensemble models                (Phase 8)
|   |   |-- models/      Pydantic request/response schemas
|   |   |-- reports/     Scientific candidate report generation      (Phase 14)
|   |   |-- services/    Preprocessing, transit search, ranking, ...  (Phase 3-10)
|   |   |-- simulations/ Synthetic light-curve generation             (Phase 6)
|   |   |-- workers/     Background job workers                       (Phase 15)
|   |-- tests/
|-- frontend/           Next.js 16 (App Router) + TypeScript Mission Control UI
|   |-- src/app/         Pages
|   |-- src/components/  Shared UI components
|   |-- src/lib/         Typed API client
|   |-- tests/           Vitest + React Testing Library
|-- data/               raw/ processed/ synthetic/ models/ (gitignored contents)
|-- docs/               This document and future guides
|-- notebooks/          Exploratory analysis (not part of the shipped pipeline)
|-- reports/            Generated candidate reports (gitignored contents)
|-- scripts/            One-off operational scripts
|-- docker-compose.yml  Postgres + backend + frontend, orchestrated together
```

## Why these technology choices

- **FastAPI + Pydantic**: request/response validation is declarative and
  generates OpenAPI docs for free, which matters once the API surface grows
  past a handful of endpoints (Phase 12 alone lists 15+).
- **SQLAlchemy + Alembic**: the database schema (Phase 11) needs to evolve
  over many months without losing data -- migrations make schema changes
  reviewable and reversible, unlike hand-run `ALTER TABLE` statements.
- **structlog**: scientific pipelines make many small decisions (which
  quality flag dropped a point, which detrending method ran, which model
  version scored a candidate). Structured key/value logs make those decisions
  greppable later, which matters most once batch jobs are processing
  hundreds of targets unattended (Phase 15).
- **uv** for Python environment management: fast, reproducible, and pins an
  exact Python version per-project regardless of what's on the host machine.
- **Next.js (App Router) + TypeScript**: server components let the dashboard
  fetch data close to the backend when useful, while TypeScript catches an
  entire class of "the API changed shape and the frontend didn't notice" bugs
  before they reach a browser.
- **Docker Compose**: Postgres, backend, and frontend need to run together
  consistently across machines; Compose is the smallest tool that does that
  without inventing a bespoke process-management script.

## Provenance and scientific integrity

Every processing run, from raw file download through final candidate score,
is expected to record enough metadata to be reproduced later: file
checksums, processing configuration, code version, model version, and
random seeds where applicable. This is a mandatory design constraint, not an
optional nice-to-have -- see the root README's "Scientific Integrity Rules"
section. No component in this system is permitted to label an unmatched
signal a "confirmed exoplanet."

## Current status: Phase 1 (Foundation)

Implemented:
- FastAPI app with a versioned `/api/v1/health` endpoint (plus an
  unversioned `/health` alias for infrastructure probes).
- Typed settings loaded from environment variables (`app/core/config.py`).
- Structured logging configured at startup (`app/core/logging.py`).
- Next.js Mission Control shell with a live backend-connection status panel
  and placeholder mission-overview stat tiles.
- Ruff, mypy, pytest, ESLint, TypeScript, and Vitest all configured and
  passing.
- Docker Compose stack (Postgres + backend + frontend).
- GitHub Actions CI running lint/typecheck/test for both backend and
  frontend on every push and pull request.

Not yet implemented (by design -- these are later phases): any real TESS
data access, database models, transit search, machine learning, or
reporting. The stub packages under `backend/app/{data,database,ml,...}`
exist so the tree is navigable, but contain no logic yet.

## Current status: Phase 2A (TESS target & observation discovery)

Implemented:
- `app/data/mast_client.py` -- a typed data-acquisition module that
  resolves a target (TIC identifier or a resolvable target name) to the
  TESS observations MAST knows about, via astroquery's MAST interface.
  Network access is isolated behind a `MastGateway` protocol
  (`AstroqueryMastGateway` is the real implementation), so the business
  logic in `MastClient` can be unit-tested with a fake gateway.
- `app/data/models.py` -- typed Pydantic result models (`TessObservation`,
  `TargetSearchResult`).
- `app/data/exceptions.py` -- `InvalidTargetError`, `TargetNotFoundError`,
  `MastServiceError`.
- `app/cli.py` -- a `search-target` command
  (`python -m app.cli search-target --target "TIC 261136679"`) that
  prints resolved target identity, available sectors, mission/product
  type, cadence, pipeline/author, and observation count.
- A new `mast` optional dependency group (`astroquery`, pulling in
  `astropy` transitively) -- deliberately smaller than the full `science`
  group, since FITS parsing and preprocessing aren't in scope yet.
- One `@pytest.mark.live` integration test
  (`tests/test_mast_client_live.py`) that makes a real MAST request; it
  is excluded from normal `pytest` runs (`-m "not live"` in
  `pyproject.toml`) and must be run explicitly with `pytest -m live`.

Explicitly not implemented in this milestone: downloading or caching
FITS files, parsing light curves, quality filtering, preprocessing,
transit search, database persistence of search results, or any
dashboard/API integration of target search. Those remain later phases
(see the root README's roadmap).

### Data-source attribution

Target and observation discovery queries NASA's Mikulski Archive for
Space Telescopes (MAST) via [astroquery](https://astroquery.readthedocs.io/en/latest/mast/mast.html).
TESS data products are produced by pipelines including SPOC, TESS-SPOC,
and QLP; MAST reports which pipeline produced each product (the
`provenance_name` column, surfaced here as "author"). No data is
downloaded or redistributed by this milestone -- only observation
metadata is retrieved.

## Known limitations of this milestone

- The backend Docker image installs only core web-service dependencies.
  The `mast` (astroquery), `science` (Astropy, Lightkurve, ...), and `ml`
  (PyTorch, scikit-learn) extras are deliberately deferred to the phases
  that use them, to avoid multi-gigabyte builds with no corresponding
  functionality.
- Postgres is provisioned but nothing reads from or writes to it yet --
  database models for search results arrive in a later phase.
- The dashboard's mission-overview numbers are static placeholders; they
  become live once the pipeline starts writing to the database.
- Name-based search relies on MAST's cone search around a resolved
  coordinate (Sesame/Simbad name resolution via astropy), then filters
  to the TESS mission; it can occasionally surface a full-frame-image
  row before a target's own timeseries row, though `MastClient` prefers
  rows with a numeric TIC ID when picking the resolved identity.
- No caching, rate-limiting, or retry logic wraps the MAST calls yet;
  each CLI invocation makes a fresh request with a fixed 30s timeout.
