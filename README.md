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

**Phase 3A: Quality and finite-value filtering** -- complete. Select the
cadences worth analysing, by TESS quality flags and by finiteness, while
leaving the raw file and its values untouched:

```bash
cd backend
python -m app.cli filter-quality data/raw/tess/sector_001/<filename>.fits
python -m app.cli filter-quality <path>.fits --quality-policy default
python -m app.cli filter-quality <path>.fits --quality-policy custom --quality-bitmask 128
```

Quality policies (bit meanings verified against the TESS Science Data
Products Description Document Rev F, Table 32, and MAST's Cadence
Quality Flags table):

| Policy | Mask | Meaning |
|---|---|---|
| `none` | 0 | Retain every cadence regardless of flags. |
| `default` | 17087 | Lightkurve-compatible default mask. |
| `mast` | 21183 | MAST-recommended mask (`default` plus the automatic scattered-light flag). **Used unless you request another policy.** |
| `hard` | 24319 | Conservative; also drops cosmic-ray-corrected and stray-light cadences. |
| `hardest` | 65535 | Any flag at all. Not recommended -- many flags mean a correction was *applied*, not that the data is bad. |
| custom | any integer | Your own bitmask. |

Every rejected cadence is recorded with its original `QUALITY` value,
the bits that actually matched, and its reason(s); nothing is discarded
silently. See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-3a-quality-and-finite-value-filtering)
for the full bit table, citations, and scientific guarantees.

**Phase 3B: Gap detection and contiguous segmentation** -- complete.
Filter by quality, then detect TIME discontinuities large enough to be
real observation gaps (not ordinary cadence jitter) and divide the
result into contiguous segments -- selecting and grouping cadences only,
never modifying a value:

```bash
cd backend
python -m app.cli segment-light-curve data/raw/tess/sector_001/<filename>.fits
python -m app.cli segment-light-curve <path>.fits --gap-multiplier 3.0 --gap-tolerance 0.001
```

An interval between two consecutive retained cadences is a gap when it
exceeds `nominal_cadence * gap_multiplier + gap_tolerance`, where
`nominal_cadence` is the **median** of consecutive TIME differences
(default multiplier `5.0`, default tolerance `1e-6` days). Each detected
gap records exact retained-array positions and original FITS row
indices on both sides, whether it stems from Phase 3A rejecting rows in
between, a genuine interruption in observation, or both, and -- when
defensible -- how many cadences are estimated missing. See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-3b-gap-detection-and-contiguous-segmentation)
for the full gap rule, edge cases, and known limitations.

**Phase 3C: Per-segment flux normalization** -- complete. Filter,
segment, then divide each segment's flux by its own median -- entirely
independently of every other segment, so nothing is ever averaged or
scaled across a gap:

```bash
cd backend
python -m app.cli normalize-light-curve data/raw/tess/sector_001/<filename>.fits
python -m app.cli normalize-light-curve <path>.fits --zero-reference-tolerance 1e-6
```

`normalized_flux = flux / segment_reference`, where `segment_reference`
is the **median** of the segment's finite flux values (baseline
~1.0 for a successfully normalized segment). A segment whose reference
is zero, near-zero (within `--zero-reference-tolerance`), or **negative**
is left un-normalized rather than silently normalized -- dividing by a
negative reference would flip the direction of every flux variation in
that segment, which would be unsafe for later transit analysis. Every
cadence is still reported either way; nothing is ever removed. See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-3c-per-segment-flux-normalization)
for the full rule, error propagation, and known limitations.

**Phase 3D: Robust per-segment outlier flagging** -- complete. Filter,
segment, normalize, then independently score each segment's normalized
flux for statistically unusual values -- this is a flagging stage, not a
removal stage: no cadence is ever deleted, replaced, interpolated, or
reordered:

```bash
cd backend
python -m app.cli flag-outliers data/raw/tess/sector_001/<filename>.fits
python -m app.cli flag-outliers <path>.fits --upper-threshold 4.0
python -m app.cli flag-outliers <path>.fits --lower-threshold 5.0
```

For each segment, independently, using only that segment's own finite
`normalized_flux` values:

```text
center       = median(finite normalized flux values)
MAD          = median(abs(value - center))
robust_scale = 1.4826 * MAD
robust_score = (value - center) / robust_scale
```

`1.4826` is the conventional Gaussian-consistency scaling factor for MAD
(it makes `robust_scale` an unbiased estimator of the standard deviation
*if* the underlying distribution were exactly Gaussian). TESS photometric
noise is not assumed to be Gaussian -- the factor is used only as a
documented, deterministic convention, the same way Lightkurve and other
pipelines use it.

A value is a **high outlier** when `robust_score > upper_threshold`
(default `5.0`, always active). A value is a **low outlier** only when
`--lower-threshold` is explicitly set and `robust_score < -lower_threshold`.
Threshold equality is never flagged (strict comparison only).

**Downward (low-side) detection is disabled by default.** A real
planetary transit is itself a downward brightness change, so a generic
two-sided clipping rule would erase exactly the signal this project
searches for. Enabling `--lower-threshold` is possible for diagnostic
use, but the CLI prints an explicit warning that any resulting low-side
flags may include real transit-like signal, not just instrumental
artifacts -- it is not the project default.

Every segment is classified with an explicit status: `VALID` (enough
finite values and a usable robust scale -- flagging was performed),
`INSUFFICIENT_DATA` (fewer finite values than
`--minimum-finite-cadences`), `ZERO_SCALE` (a constant or near-constant
segment whose robust scale is unusable), or `NORMALIZATION_UNAVAILABLE`
(Phase 3C could not normalize this segment). A nonfinite normalized-flux
value is never scored or flagged as a statistical outlier; it instead
gets its own traceable record by default. Every cadence keeps an
aligned mask entry regardless of status, and every flag is traceable
back to its original TIME and FITS source-row index. See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-3d-robust-per-segment-outlier-flagging)
for the full method, status semantics, and known limitations.

**Explicitly not implemented by Phase 3D:** cadence removal, clipping,
flux replacement, interpolation, smoothing, detrending, transit
detection, Box Least Squares, machine learning, or website/database
integration.

**Phase 4A: Local Pi Mensae science website preview** -- complete. A
read-only Mission Control dashboard that runs the completed Phase
3A-3D pipeline against the cached Pi Mensae sector 1 FITS file and
displays the real result:

```bash
make dev
# then open http://localhost:3000/demo/pi-mensae
```

Backend endpoints (`backend/app/api/demo.py`, registered under
`/api/v1`):

- `GET /api/v1/demo/pi-mensae` -- pipeline summary: identity, raw/Phase
  3A/3B/3C/3D statistics, processing history, and scientific
  limitations.
- `GET /api/v1/demo/pi-mensae/light-curve` -- the normalized light
  curve, grouped by Phase 3B segment with Phase 3B gaps listed
  separately, so a chart can never draw a line across a gap.

Both endpoints are fixed to one local file (`backend/app/services/demo_pipeline.py`
resolves it from typed settings, never from a request parameter),
read-only, and deterministic -- repeated requests return identical
results and never modify the source FITS file. There is no database
persistence, no upload, and no browser-triggered reprocessing of an
arbitrary file.

The frontend route (`frontend/src/app/demo/pi-mensae/page.tsx`) renders
the pipeline status, summary statistics, a gap-aware canvas/SVG light
curve chart, per-phase detail panels, processing history, and a visible
scientific-limitations panel. High statistical outliers are marked with
a distinct triangle marker and the legend "Statistical high outlier --
not a planet candidate"; the dashboard never implies a candidate or
confirmed planet. If the backend is unreachable or the cached FITS file
is missing, the page shows a clear error state rather than fabricated
zero values.

**Explicitly not implemented by Phase 4A:** detrending, transit search,
Box Least Squares, candidate scoring, machine learning, deployment,
arbitrary target selection, file uploads, authentication, or database
persistence.

**Phase 4B: Public read-only deployment** -- complete. The Phase 4A
dashboard is publicly reachable, read-only, with no database and no
runtime FITS download:

- Frontend: [Vercel](https://vercel.com) (Next.js, `frontend/` as the
  project root, production branch `master`).
- Backend: [Render](https://render.com) (`render.yaml` Blueprint; Docker
  web service, `backend/` as the root directory, free instance type).
- The exact TIC 261136679 / TESS sector 1 SPOC FITS file is fetched once
  from NASA/MAST during `docker build`
  (`backend/app/deploy/provision_demo_fits.py`), verified against its
  known SHA-256
  (`1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609`)
  and size (2,039,040 bytes), and baked into the image -- never
  downloaded at request time, never bundled in git.
- CORS is configured for the exact production frontend origin plus the
  local dev origins; see `Settings.cors_origins` /
  `Settings.cors_origin_regex`.
- The free Render instance can take up to about a minute to wake from
  idle; the frontend shows a clear "waking" message and retries
  automatically for a bounded period before offering a manual retry.

**Public dashboard:** _filled in once deployed -- see the live URL
recorded after Step B of the Phase 4B deployment order in
[`docs/architecture.md`](docs/architecture.md#current-status-phase-4b-public-read-only-deployment)._

**Explicitly not added by Phase 4B:** a database, a persistent disk,
background workers, user accounts, authentication, file uploads, or
arbitrary-target processing -- the public API surface is exactly the
same two read-only Phase 4A endpoints plus the existing health check.
See
[`docs/architecture.md`](docs/architecture.md#current-status-phase-4b-public-read-only-deployment)
for the full deployment architecture, CORS decision, cold-start
behavior, and rollback procedure.

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
   - **2B: FITS download, caching, and parsing** -- done.
3. Light-curve preprocessing pipeline.
   - **3A: quality and finite-value filtering** -- done.
   - **3B: gap detection and contiguous segmentation** -- done.
   - **3C: per-segment flux normalization** -- done.
   - **3D: robust per-segment outlier flagging** -- done.
4. Mission Control website.
   - **4A: local Pi Mensae science website preview** -- done.
   - **4B: public read-only deployment** -- done (this milestone).
5. Transit-search engine (Box Least Squares + pluggable interface).
6. Physical property estimation.
7. Synthetic planetary system generator.
8. Candidate feature engineering.
9. Machine-learning classifier (classical baseline).
10. Known-planet cross-matching.
11. Candidate-ranking engine.
12. Full database schema + migrations.
13. Full FastAPI endpoint surface.
14. Full Mission Control dashboard (target explorer, transit-search view,
    candidate detail, model laboratory, system operations).
15. Scientific candidate reports.
16. Autonomous research agent for batch analysis.

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
