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
Gap detection and contiguous segmentation (TIME discontinuities)
        |
Per-segment flux normalization (median-ratio)
        |
Sigma clipping (per-segment outlier rejection)
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

## Current status: Phase 2B (TESS FITS download and raw parsing)

Implemented:
- `app/data/product_selection.py` -- deterministic selection of exactly
  one downloadable light-curve product from a target's discovered
  observations (Phase 2A) and MAST's per-observation product list. Rules
  (documented in the module docstring): only `timeseries` observations
  are considered; any `--sector`/`--author`/`--cadence` filters are
  applied; remaining observations are tried in pipeline-priority order
  (SPOC, then TESS-SPOC, then QLP, then alphabetically); products are
  filtered to light-curve rows (`productSubGroupDescription == "LC"`, or
  a `_lc.fits`/`_llc.fits` filename for pipelines that don't set that
  field); ties are broken by filename. Never picks arbitrarily among
  ambiguous matches -- if nothing matches, it raises a clear error
  instead.
- `app/data/downloader.py` -- `LightCurveDownloader`, a typed, testable
  layer that downloads one selected product and caches it locally.
  Network access (listing an observation's products, fetching one) is
  isolated behind a `MastProductGateway` protocol, the same pattern
  Phase 2A uses for `MastGateway`. Downloads go to a temporary file
  first and are only moved into place after validating size (and, if
  MAST reported one, comparing it against the manifest); a SHA-256
  checksum is computed and stored in a `.sha256` sidecar next to the
  cached file so a later run can detect local corruption without
  re-contacting MAST. Transient MAST failures are retried up to 3 times
  with exponential backoff (1s, 2s, ...); non-network errors (invalid
  target, no matching product) are never retried.
- `app/data/fits_parser.py` -- `parse_light_curve`, which reads a
  supported SPOC/TESS-SPOC light-curve FITS file (Astropy) into a typed
  `RawLightCurve`: time, flux (preferring `PDCSAP_FLUX` over `SAP_FLUX`
  when both are present), flux uncertainty, quality flags, cadence,
  sector/camera/CCD, TIC ID, object name, pipeline, telescope/mission,
  a flattened subset of the FITS header, and the source file's name and
  SHA-256 checksum. No preprocessing happens: values are copied out
  exactly as stored, aside from safe conversion to typed Python
  structures -- no NaN removal, quality filtering, normalization,
  detrending, or sector stitching.
- `app/cli.py` -- two new commands:
  - `download-target` (`--target`, `--sector`, `--author`, `--cadence`,
    `--output-dir`, `--force`) resolves a target, selects one product,
    downloads or reuses it from cache, and reports the resolved target,
    selected product, sector, pipeline, cadence, local path, file size,
    SHA-256 checksum, and whether it was downloaded or served from
    cache.
  - `inspect-fits <path>` parses a cached FITS file and prints a
    descriptive summary (target, sector, camera/CCD, pipeline, cadence
    count, time range, flux column used, missing-flux count, nonzero-
    quality-flag count, cadence, file size, checksum) without modifying
    the data.
- New exceptions (`app/data/exceptions.py`): `DownloadError`,
  `RetryExhaustedError`, `ChecksumMismatchError`, `CorruptedCacheError`
  (download/cache), and `FitsError`, `InvalidFitsError`,
  `UnsupportedProductError`, `MissingExtensionError`,
  `MissingColumnError` (FITS parsing).
- New typed models (`app/data/models.py`): `DownloadRequest`,
  `SelectedProduct`, `CachedArtifact`, `FileProvenance`, `FitsMetadata`,
  `RawLightCurve`.
- `astropy` added as an explicit direct dependency of the `mast` extra
  (previously only pulled in transitively via astroquery), since this
  phase imports `astropy.io.fits` directly.
- One additional `@pytest.mark.live` test
  (`tests/test_download_live.py`) that downloads and parses one real
  light-curve product to a temporary directory (cleaned up afterward);
  excluded from normal runs like Phase 2A's live search test.

Explicitly not implemented in this milestone: quality-flag filtering,
NaN handling, normalization, detrending, sector stitching, transit
search, feature extraction, machine learning, database persistence, or
any dashboard/API integration. Those remain later phases.

### Cache design

Downloaded FITS files are cached under `data/raw/tess/` (configurable
via `--output-dir` or the `mast_cache_dir` setting), laid out as:

```text
data/raw/tess/sector_<NNN>/<original MAST filename>
data/raw/tess/sector_<NNN>/<original MAST filename>.sha256
```

The sector subdirectory keeps the cache path deterministic given only a
product's identity (sector, filename). Re-running `download-target`
against an existing valid cache entry reuses it without contacting MAST;
`--force` is required to replace an existing entry (valid or not). If a
cached file's contents no longer match its `.sha256` sidecar (e.g. from
manual editing or disk corruption), the command reports a clear
`CorruptedCacheError` and refuses to silently reuse it. To clear a
cached file safely, delete both the FITS file and its `.sha256` sidecar
(or delete the whole `data/raw/tess/` directory) and re-run
`download-target`.

### Known limitation discovered while implementing this phase

MAST's `Observations.get_product_list` requires the *numeric* internal
observation ID (`obsid`), not the human-readable `obs_id` string
(e.g. `tess2018206045859-s0001-0000000261136679-0120-s`) that Phase 2A
surfaces in its search-target report; using the string form fails with
a server-side type-conversion error. `MastClient._row_to_observation`
now prefers the numeric `obsid` column when present (real MAST rows
always have both), falling back to `obs_id` only for the synthetic rows
used in Phase 2A's mocked unit tests. Similarly, a light-curve FITS
file's `TIMESYS`/`TIMEDEL` keywords live in the `LIGHTCURVE` extension
header, not the primary header, and the primary header's `ORIGIN`
keyword names the *institution* that produced the file ("NASA/Ames"),
not the pipeline -- the pipeline name is derived from the `PROCVER`
keyword instead (e.g. `"spoc-5.0.10-20200904"` -> `"SPOC"`). All three
were caught by the manually-invoked live integration test against a
real MAST product, not by the mocked unit tests, which is exactly the
gap that test exists to cover.

## Current status: Phase 3A (Quality and finite-value filtering)

This is the `Quality filtering (TESS quality flags)` stage of the data
flow above -- the first slice of roadmap phase 3 (light-curve
preprocessing). It *selects* cadences and never alters a value; nothing
is normalized, detrended, sigma-clipped, smoothed, or stitched.

Implemented:
- `app/data/quality_flags.py` -- the verified TESS `QUALITY` bit table
  and the named bitmask policies built from it, with full source
  citations and a retrieval date. Reference data only, no logic; kept in
  its own module so re-auditing it against a future revision of the TESS
  data-products document is a single-file diff.
- `app/data/quality_filter.py` -- `filter_quality(raw, config)`, a pure
  function from a `RawLightCurve` plus a `QualityFilterConfig` to a new
  `FilteredLightCurve`. Four independent rejection rules are evaluated
  for *every* cadence with no short-circuiting, so a cadence with
  several problems records all of them and the result does not depend on
  rule ordering: nonfinite `TIME`, nonfinite flux, nonfinite flux error
  (each individually switchable), and `quality & active_bitmask != 0`.
- New typed models (`app/data/models.py`): `RejectionReason`,
  `QualityFilterConfig`, `RejectedCadence`, `QualityFilterStats`,
  `ProcessingStep`, `FilteredLightCurve`, plus
  `config_from_policy_name` for CLI-supplied policy strings.
- New exceptions (`app/data/exceptions.py`): `ProcessingError`,
  `InvalidLightCurveError`, `InvalidFilterConfigError`.
- `app/cli.py` -- a `filter-quality` command:

```bash
python -m app.cli filter-quality <path>.fits                       # mast policy (default)
python -m app.cli filter-quality <path>.fits --quality-policy hard
python -m app.cli filter-quality <path>.fits --quality-policy custom --quality-bitmask 128
```

  It reports the policy name *and* the resolved integer mask, retained
  and rejected counts, a per-reason breakdown, a per-bit breakdown
  naming each matched flag, the code version, and the source checksum.

Explicitly not implemented: normalization, detrending, sigma clipping,
smoothing, brightness-based outlier rejection, gap detection, sector
stitching, transit search, feature extraction, machine learning,
database persistence, or dashboard/API integration.

### Why this lives in `app/data/`

The milestone is named Phase 3A because the roadmap places quality
filtering under phase 3 (light-curve preprocessing), but the module sits
in `app/data/` beside `fits_parser.py` rather than in `app/services/`.
That is deliberate: this step performs no value transformation -- it
consumes a `RawLightCurve` and selects rows from it. The first stage that
actually changes numbers (normalization) is what belongs in
`app/services/`.

### Quality-bitmask policies

Bit meanings are transcribed from **Table 32** ("Data quality bits") of
the *TESS Science Data Products Description Document*, Rev F
(NASA/TM--20205008729, 11 September 2020), section 9, page 53, and
cross-checked against MAST's "Cadence Quality Flags" table in
[2.0 - Data Product Overview](https://outerspace.stsci.edu/display/TESS/2.0+-+Data+Product+Overview).
Lightkurve's `TessQualityFlags` was used only as a secondary
*implementation* reference for how the named masks are composed and
applied. All three sources were retrieved on **2026-07-24** and agreed on
every value. Note older revisions (and Lightkurve's own docstring) cite
this as Table 28; it is Table 32 in Rev F.

| Policy | Mask | Meaning |
|---|---|---|
| `none` | 0 | No quality filtering; every cadence retained regardless of flags. |
| `default` | 17087 (`0x42BF`) | **Lightkurve-compatible**: exactly `TessQualityFlags.DEFAULT_BITMASK`. Bits 1, 2, 3, 4, 5, 6, 8, 10, 15. Does *not* include bit 13. |
| `mast` | 21183 (`0x52BF`) | **MAST-recommended**: `default` plus bit 13 (Scattered Light Exclude). MAST documents it as binary `0101001010111111`. **This project's default.** |
| `hard` | 24319 (`0x5EFF`) | `default` plus bits 7, 11, 12, 13. Conservative; Lightkurve notes it "may identify cadences which are useful", i.e. it discards some good data. |
| `hardest` | 65535 (`0xFFFF`) | Every documented bit. **Not recommended** -- see below. |
| custom | any `int >= 0` | Caller-supplied, applied identically via bitwise AND. |

`default` and `mast` are kept as distinct names on purpose. This project
uses **`mast`** unless the caller requests otherwise, because the parser
prefers `PDCSAP_FLUX` and the automatic scattered-light flag marks
cadences the pipeline itself considers degraded, so rejecting it follows
the archive's own advice for that flux series. Calling 21183 "default"
would wrongly imply parity with Lightkurve's current default of 17087.

`hardest` rejects every cadence carrying any flag at all and should not
be a normal choice: MAST states that "Not all of these [flags] indicate
that the data quality is bad. In many cases the flags simply indicate
that a correction was made" -- bit 7, for instance, means a cosmic ray
*was corrected*, and MAST says such data "is likely fine". Lightkurve's
source comment on the equivalent mask reads "Its use is not recommended."

Source (1) also warns that the bit list is not comprehensive and that
"it is very likely there will be changes to flag values after launch".
The table is therefore a snapshot of Rev F, and `describe_bits` reports
unrecognized bits explicitly rather than ignoring them.

### Scientific guarantees

- The input `RawLightCurve` is never mutated. It is frozen with tuple
  fields, so this is enforced by the type rather than by convention, and
  provenance/metadata are carried onto the result by reference.
- `retained + rejected == total`, always. No cadence is discarded
  without a `RejectedCadence` record naming the documented rule(s) that
  removed it.
- Each rejected cadence records both its **original `QUALITY` integer**
  and the **actually matched bits** (`quality & active_bitmask`), so a
  flag that exists but was not part of the active policy is never
  mistaken for the cause of rejection.
- Nonfinite values and quality flags are distinguished as separate
  rejection reasons: a NaN means *no measurement was recorded*, while a
  matched quality bit means *a measurement exists but the pipeline
  flagged it*.
- Every retained cadence keeps its original FITS row index in
  `source_indices`, so correspondence with the source file survives
  filtering.
- Results are a pure function of `(raw, config)` -- `ProcessingStep`
  carries the code version, policy, resolved mask, config, in/out
  counts, and the source SHA-256, but deliberately **no timestamp**, so
  reruns are reproducible byte-for-byte.
- A flux error of exactly `0.0` is *not* treated as invalid; it is an
  unusual but reported measurement. Negative or large flux values are
  likewise retained -- brightness-based outlier rejection is out of
  scope.
- When every cadence is rejected the result is returned normally with
  empty arrays and complete statistics rather than raising: an unusable
  sector is a meaningful scientific outcome, and raising would discard
  the counts explaining why. The CLI prints a prominent warning and
  still exits 0.

### Real-data sanity check

Run against a real cached SPOC product (TIC 261136679 / Pi Mensae,
sector 1, `tess2018206045859-s0001-0000000261136679-0120-s_lc.fits`,
20,076 cadences) under the default `mast` policy: 18,264 cadences
retained (91.0%), 1,812 rejected -- 1,797 nonfinite flux, 1,797 nonfinite
flux error, 815 nonfinite `TIME`, and 1,812 with matched quality bits
(mostly Earth Point 8 and Manual Exclude 128). The file's SHA-256 and
mtime were identical before and after.

That sector contains **zero** cadences with bit 4096 set, so `default`
and `mast` retain identically on this particular file; the behavioural
difference between them is pinned directly by unit tests instead.

## Current status: Phase 3B (Gap detection and contiguous light-curve segmentation)

This is the `Gap detection and contiguous segmentation` stage of the
data flow above -- the second slice of roadmap phase 3. It takes an
already quality-filtered `FilteredLightCurve` and *selects and groups*
its retained cadences at every TIME discontinuity large enough to be a
meaningful gap; no value is ever changed, invented, or interpolated.
Normalization, detrending, sigma clipping, smoothing, gap filling, and
sector stitching all remain out of scope for later phases.

Implemented:
- `app/data/gap_segmentation.py` -- `segment_light_curve(filtered, config)`,
  a pure function from a `FilteredLightCurve` plus a `GapDetectionConfig`
  to a new `SegmentedLightCurve`.
- New typed models (`app/data/models.py`): `GapDetectionConfig`,
  `GapReason`, `DetectedGap`, `LightCurveSegment`, `SegmentationStats`,
  `GapDetectionStep`, `SegmentedLightCurve`.
- New exceptions (`app/data/exceptions.py`): `GapSegmentationError`,
  `InvalidGapDetectionConfigError`, `NonFiniteTimeError`,
  `NonMonotonicTimeError`.
- `app/cli.py` -- a `segment-light-curve` command that filters by quality
  and then segments in one step:

```bash
python -m app.cli segment-light-curve <path>.fits                                  # mast policy, default gap config
python -m app.cli segment-light-curve <path>.fits --gap-multiplier 3.0 --gap-tolerance 0.001
python -m app.cli segment-light-curve <path>.fits --quality-policy hard --missing-cadence-residual-tolerance 0.1
```

  It reports total retained cadences, segment and gap counts, measured
  vs. metadata cadence agreement, per-segment position/source-index/time
  ranges, per-gap boundaries/reasons/estimates, the code version, and the
  source checksum.

Explicitly not implemented: normalization, detrending, sigma clipping,
smoothing, brightness-based outlier rejection, sector stitching, transit
search, feature extraction, machine learning, database persistence, or
dashboard/API integration.

### Nominal cadence estimation

The nominal cadence is the **median** of every consecutive, strictly
positive TIME difference -- a robust statistic, resistant to the handful
of outlying intervals a real gap produces (a mean would be skewed
upward by every gap it is supposed to detect). It is estimable whenever
at least two retained cadences exist (duplicate and decreasing TIME
values are rejected before this step runs, guaranteeing every
difference computed is strictly positive), and is `None` -- not an
error -- when fewer than two cadences remain.

The FITS metadata cadence (`TIMEDEL`, when present) is recorded
alongside the measured cadence, and whether the two agree within
`GapDetectionConfig.cadence_disagreement_fraction` (default `0.01`,
i.e. 1%) is reported in `SegmentationStats.cadence_sources_agree`.
**Metadata never drives gap detection and never overrides a measured
disagreement**: thresholding always uses the measured cadence, because
it reflects this file's own actual TIME sampling, while the metadata
value is a single per-file header constant. A zero or missing metadata
cadence is treated as unavailable (`cadence_sources_agree=None`), not
as a disagreement.

### The gap rule

An interval between two consecutive retained cadences is a gap when::

```
actual_interval > nominal_cadence * gap_multiplier + gap_tolerance
```

Defaults (`GapDetectionConfig`): `gap_multiplier=5.0`,
`gap_tolerance=1e-6` (days), `cadence_disagreement_fraction=0.01`,
`missing_cadence_residual_tolerance=0.25`. `gap_multiplier` must exceed
`1.0` (otherwise every ordinary cadence step would qualify as a gap);
`gap_tolerance` exists specifically so ordinary floating-point cadence
jitter is never misclassified as a gap. Both -- along with the
disagreement fraction and missing-cadence residual tolerance -- are
configurable via the CLI or `GapDetectionConfig` directly.

### Gap-origin classification

Classification uses only `source_indices` (each retained cadence's row
index in the original FITS table) and the retained TIME values --
nothing is inferred beyond what those two arrays can prove:

- **`skipped_source_rows == 0`** (the two retained cadences were
  adjacent in the original FITS table): the time jump was already
  present between neighbouring source rows, so the gap is a genuine
  interruption in the observation itself (a downlink or safe-mode
  event, for example). Reason: `observation_gap`.
- **`skipped_source_rows > 0`**: an earlier step (typically Phase 3A's
  quality filter) removed one or more rows in between. Reason:
  `source_rows_rejected`. If the actual interval still exceeds what
  those skipped rows alone would account for at the nominal cadence
  (beyond `gap_tolerance`), the gap *also* carries `observation_gap`:
  the skipped rows explain part of the interval, but not all of it.

A gap can therefore carry one or both reasons; it never carries neither.

### Missing-cadence estimation

`DetectedGap.estimated_missing_cadences` is
`round(actual_interval / nominal_cadence) - 1` (floored at zero),
reported only when that ratio is within
`GapDetectionConfig.missing_cadence_residual_tolerance` of a whole
number. An interval that doesn't land close to an integer multiple of
the nominal cadence gets `None` instead of a falsely precise guess.

### Duplicate, decreasing, and nonfinite TIME

Gap detection never silently repairs measurements. A duplicate or
decreasing consecutive TIME value raises `NonMonotonicTimeError`; a
nonfinite (NaN or +/-inf) retained TIME value raises
`NonFiniteTimeError` (Phase 3A's default configuration already removes
these, so this only fires if quality filtering was run with
`require_finite_time=False`, or a `FilteredLightCurve` was constructed
directly). Neither condition is sorted, deduplicated, or discarded
automatically.

### Edge cases

- **No gaps**: one segment containing every retained cadence.
- **Zero retained cadences**: zero segments, zero gaps,
  `measured_nominal_cadence=None`. Not an error.
- **One retained cadence**: one one-cadence segment,
  `measured_nominal_cadence=None` (nothing to estimate cadence from).
- **Every interval exceeding the threshold**: one single-cadence
  segment per retained cadence, with a gap between every consecutive
  pair.

### Scientific guarantees

- The input `FilteredLightCurve` is never mutated. It is frozen with
  tuple fields, so this is enforced by the type rather than by
  convention.
- Every retained cadence appears in exactly one segment; none are lost
  or duplicated, and segment order matches input (TIME) order.
- Results are a pure function of `(filtered, config)` --
  `GapDetectionStep` carries the code version, config, in/out counts,
  and the source SHA-256, but deliberately **no timestamp**, so reruns
  are reproducible byte-for-byte (verified with `model_dump_json()`
  equality in both the unit tests and the real-data check below).
- `history` carries forward every prior processing step (e.g. Phase
  3A's `ProcessingStep`) plus this phase's own `GapDetectionStep`, so
  full provenance survives segmentation.

### Real-data sanity check

Run `segment-light-curve` (default `mast` quality policy, default gap
config) against the same cached SPOC product as the Phase 3A check (TIC
261136679 / Pi Mensae, sector 1, 18,264 quality-retained cadences): the
measured nominal cadence (0.00138887 d, ~120.00 s) agreed with the FITS
metadata cadence (~120.00 s) to within the default 1% tolerance. The
light curve split into **46 segments** and **45 gaps**, every one
classified `source_rows_rejected` -- including the widest gap, a
~1.13-day interval fully attributable to 816 rows Phase 3A had already
removed there, with no additional `observation_gap` interruption on top
(its excess over the skipped-rows-only expectation was within
`gap_tolerance`). A total of 1,489 missing cadences were estimated
across the gaps where the interval was defensibly close to an integer
cadence multiple. The file's SHA-256, size, and mtime were identical
before and after. Repeated runs on the same input produced
byte-identical `model_dump_json()` output, every retained
TIME/source-index round-tripped through the segments in order with no
omission or duplication, and the `FilteredLightCurve` input was
confirmed unchanged by `model_dump()` equality.

## Current status: Phase 3C (Per-segment flux normalization)

This is the `Per-segment flux normalization` stage of the data flow
above -- the third slice of roadmap phase 3. It takes a
`SegmentedLightCurve` and divides each `LightCurveSegment`'s flux by a
reference computed **only from that segment's own values**, so a
segment's normalization never depends on -- and never crosses -- a
Phase 3B gap boundary. No cadence is ever removed, reordered, or
duplicated; TIME, QUALITY, source indices, gap records, and every prior
processing step are carried through unchanged.

Implemented:
- `app/data/normalization.py` -- `normalize_light_curve(segmented, config)`,
  a pure function from a `SegmentedLightCurve` plus a
  `NormalizationConfig` to a new `NormalizedLightCurve`.
- New typed models (`app/data/models.py`): `NormalizationConfig`,
  `ReferenceIssue`, `SegmentNormalizationStats`, `NormalizedSegment`,
  `NormalizationStats`, `NormalizationStep`, `NormalizedLightCurve`.
- New exceptions (`app/data/exceptions.py`): `NormalizationError`,
  `InvalidNormalizationConfigError`.
- `app/cli.py` -- a `normalize-light-curve` command that filters,
  segments, and normalizes in one step:

```bash
python -m app.cli normalize-light-curve <path>.fits                              # mast policy, default config
python -m app.cli normalize-light-curve <path>.fits --zero-reference-tolerance 1e-6
python -m app.cli normalize-light-curve <path>.fits --gap-multiplier 3.0 --quality-policy hard
```

  It reports total cadences, segment/normalized/un-normalized counts, a
  per-issue breakdown of why any segment was left un-normalized, a
  per-segment reference and status line, the code version, and the
  source checksum.

Explicitly not implemented: sigma clipping, outlier rejection,
detrending, smoothing, spline fitting, Gaussian processes,
interpolation, gap filling, sector stitching, transit search, feature
extraction, machine learning, database persistence, or dashboard/API
integration. **Sigma clipping remains a separate, later milestone
(tentatively Phase 3D)** and must not be confused with normalization:
normalization only rescales each segment by one constant; it never
examines individual cadences for outliers and never excludes a cadence
from the output.

### Median-ratio normalization

The only supported algorithm is::

```
normalized_flux = flux / segment_reference
```

where `segment_reference` is the **median** of the segment's finite
flux values -- median, not mean, for the same robustness reason Phase
3B measures cadence with a median: a brief transit or a handful of
outlying flux values would bias a mean, but cannot move a median by
more than its own magnitude allows. The expected baseline for a
successfully normalized segment is `normalized_flux ~= 1.0`.

There is no method-selector field or `NormalizationMethod` enum: with
exactly one documented algorithm, pinned by `code_version`, a
single-member enum would be an abstraction with nothing to abstract
over -- the same reason `GapDetectionStep` has no "gap rule" field.
`relative_flux = normalized_flux - 1` is also intentionally **not**
stored anywhere: it is a lossless, one-line derivation of
`normalized_flux`, so persisting it would duplicate scientific data for
no new information.

### Independent per-segment calculation, and why normalization never crosses a gap

Every segment's reference is computed from that segment's `flux` tuple
alone. `LightCurveSegment.flux` is already gap-isolated by Phase 3B's
own construction (sliced from the parent `FilteredLightCurve` at
segment boundaries), and `app.data.normalization` never reads two
segments' arrays together -- there is no code path by which one
segment's flux can influence another segment's reference or normalized
values. This is verified directly: changing one segment's flux leaves
every other segment's `normalized_flux` and `stats.reference`
byte-identical.

### Why negative and nonpositive references are not normalized

Dividing by a negative reference reverses the direction of every flux
variation in the segment: a downward change in raw flux would become an
upward normalized feature, which would be unsafe for later transit
analysis (a real transit dip could appear as a normalized brightening).
A reference of zero, or within `NormalizationConfig.zero_reference_tolerance`
of zero, makes the ratio undefined or numerically meaningless. Neither
condition is ever silently normalized:

| `ReferenceIssue` | Condition | Checked |
|---|---|---|
| `NO_FINITE_FLUX` | No cadence in the segment has a finite flux value | first |
| `NONFINITE_REFERENCE` | The median itself is not finite (reachable only via floating-point overflow averaging two extreme-magnitude central values -- see `tests/test_normalization.py`'s worked example) | second |
| `ZERO_REFERENCE` | `abs(reference) <= zero_reference_tolerance` (exact zero always included) | third |
| `NEGATIVE_REFERENCE` | `reference < 0`, outside the zero tolerance | fourth |

A segment with any of these issues is left un-normalized
(`normalized_flux`/`normalized_flux_err` are `None`), but its original
`LightCurveSegment` -- every TIME, flux, flux error, QUALITY, and
source index -- is fully preserved in the output, and every other
segment is still normalized. One bad segment never blocks the rest of
the file.

### Mixed finite/nonfinite flux within a segment

Phase 3A's default configuration (`require_finite_flux=True`) already
removes nonfinite flux before a light curve ever reaches this stage, so
this case does not arise under standard configuration. It remains
explicitly handled for light curves quality-filtered with
`require_finite_flux=False`, or objects constructed directly: **the
reference is calculated from the segment's finite flux values only,
and every cadence -- finite or not -- is still normalized.** A cadence
whose original flux is NaN or +/-inf divides through to a nonfinite
`normalized_flux` value at that position via ordinary floating-point
division (`nan / reference` is `nan`; `inf / reference` is `inf` for a
positive reference) -- no special-casing is needed, and no cadence is
silently dropped or its count silently changed.

### Flux-error propagation

For a successfully normalized segment::

```
normalized_flux_err = flux_err / abs(segment_reference)
```

This treats the computed reference as an **exact** scaling constant.
**The median estimator's own sampling uncertainty is not propagated**
into `normalized_flux_err` -- a deliberate simplification (also made
by, e.g., Lightkurve's own `.normalize()`), not an oversight. When the
input has no `flux_err` column at all, `normalized_flux_err` remains
`None` for every segment, and it is also `None` whenever
`normalized_flux` is `None` for that segment.

### Edge cases

- **Empty `SegmentedLightCurve`** (zero segments): zero segments out.
  Not an error.
- **One-cadence segments**: the median of one value is that value, so
  `normalized_flux == (1.0,)` whenever that value is itself finite,
  positive, and outside the zero tolerance. No special-cased code path
  exists for this -- it falls out of the general algorithm.
- **A segment with no finite flux at all**: `ReferenceIssue.NO_FINITE_FLUX`;
  `normalized_flux`/`normalized_flux_err` are `None`.

### Scientific guarantees

- No cadence is ever removed, reordered, or duplicated by this module,
  including cadences in a segment whose reference is invalid.
- The input `SegmentedLightCurve` is never mutated (frozen models,
  tuple fields).
- `gaps` and every prior `history` entry (Phase 3A's `ProcessingStep`,
  Phase 3B's `GapDetectionStep`) are carried through unchanged; this
  phase's own `NormalizationStep` (no timestamp) is appended.
- The result is a pure function of `(segmented, config)` -- reruns are
  reproducible byte-for-byte, verified with `model_dump_json()`
  equality in both the unit tests and the real-data check below.
- This is not detrending (no time-varying baseline is fit or removed)
  and not outlier rejection (no cadence is ever excluded from the
  output because of its flux value).

### Real-data sanity check

Run `normalize-light-curve` (default `mast` quality policy, default gap
and normalization config) against the same cached SPOC product as the
Phase 3A/3B checks (TIC 261136679 / Pi Mensae, sector 1): all **46**
Phase 3B segments (18,264 total cadences) received a valid, positive
median reference and normalized successfully -- **zero** segments hit
any `ReferenceIssue`. Segment references ranged from a minimum of
1,464,203.25 to a maximum of 1,465,118.5 electrons/s (median across
segments 1,464,608.22), consistent with PDCSAP flux for a bright,
stable star with no large intra-segment excursions. Every successfully
normalized segment's own `normalized_flux` has a median within
`1e-9` of exactly `1.0`, as expected by construction. The file's
SHA-256, size, and mtime were identical before and after; cadence and
segment counts matched Phase 3A/3B exactly; every retained TIME and
source index round-tripped through the normalized segments in order
with no omission or duplication; `gaps` was identical to Phase 3B's own
output; and two runs on the same input produced byte-identical
`model_dump_json()` output.

## Current status: Phase 3D (Robust per-segment outlier flagging)

This is the `Sigma clipping (per-segment outlier rejection)` stage of the
data flow above -- the fourth slice of roadmap phase 3, and the
non-destructive half of it: it takes a `NormalizedLightCurve` and
independently analyzes each `NormalizedSegment`'s own finite
`normalized_flux` values for statistically unusual measurements, then
attaches transparent, traceable flags. It never deletes, replaces,
interpolates, or reorders a cadence -- every cadence that enters this
stage leaves it, in the same order, with the same values. Later stages
remain free to decide whether or how to use the flags; nothing here
commits to excluding a cadence from anything.

Implemented:
- `app/data/outlier_detection.py` -- `flag_outliers(normalized, config)`,
  a pure function from a `NormalizedLightCurve` plus an
  `OutlierDetectionConfig` to a new `OutlierFlaggedLightCurve`.
- New typed models (`app/data/models.py`): `OutlierDirection`,
  `OutlierAnalysisStatus`, `OutlierReason`, `OutlierDetectionConfig`,
  `FlaggedCadence`, `SegmentOutlierStats`, `OutlierFlaggedSegment`,
  `OutlierDetectionStats`, `OutlierDetectionStep`,
  `OutlierFlaggedLightCurve`.
- New exceptions (`app/data/exceptions.py`): `OutlierDetectionError`,
  `InvalidOutlierDetectionConfigError`.
- `app/cli.py` -- a `flag-outliers` command that filters, segments,
  normalizes, and flags in one step:

```bash
python -m app.cli flag-outliers <path>.fits                          # mast policy, default config
python -m app.cli flag-outliers <path>.fits --upper-threshold 4.0
python -m app.cli flag-outliers <path>.fits --lower-threshold 5.0     # diagnostic only -- see below
python -m app.cli flag-outliers <path>.fits --no-flag-nonfinite-normalized-flux
```

  It reports total cadences, segment/analyzed counts, a per-status
  breakdown of any segment not analyzed, high/low/nonfinite-flagged
  totals, a per-segment status and count line, the code version, and
  the source checksum.

Explicitly not implemented: automatic cadence removal, two-sided
clipping by default, detrending, smoothing, spline fitting, Gaussian
processes, interpolation, gap filling, sector stitching, transit search,
Box Least Squares, feature extraction, machine learning, database
persistence, or dashboard/API integration.

### Statistical method

For each `NormalizedSegment`, independently, using only that segment's
own finite `normalized_flux` values:

```
center       = median(finite normalized flux values)
MAD          = median(abs(value - center))
robust_scale = 1.4826 * MAD
robust_score = (value - center) / robust_scale
```

`1.4826` is the conventional Gaussian-consistency scaling factor for
MAD: it makes `robust_scale` an unbiased estimator of the standard
deviation *if* the underlying distribution were exactly Gaussian. TESS
photometric noise is not claimed to be Gaussian -- the factor is used
only as a documented, deterministic convention, the same way Lightkurve
and other pipelines use it. Median and MAD are used instead of mean and
standard deviation for the same robustness reason Phase 3B and 3C use a
median: a handful of outlying values (including a real transit) cannot
move either statistic by more than its own breakdown point allows.

This module never crosses a gap or mixes segments: each segment's
`center`/`MAD`/`robust_scale` are computed only from that segment's own
`normalized_flux` tuple, the same guarantee `app.data.normalization`
makes for the segment reference.

### Default policy

- `upper_threshold = 5.0` -- a finite normalized value is a **high
  outlier** when `robust_score > upper_threshold`. High-side (positive
  spike) detection is always active and cannot be disabled, since a
  positive spike (cosmic ray, momentum-dump artifact, etc.) can never be
  mistaken for a transit.
- `lower_threshold = None` -- **downward detection is disabled by
  default.** A finite normalized value is a **low outlier** only when
  `lower_threshold` is explicitly set (to a finite, strictly positive
  value) and `robust_score < -lower_threshold`.
- Threshold comparison is strict in both directions: a `robust_score`
  exactly equal to `upper_threshold` or exactly equal to
  `-lower_threshold` is never flagged, verified directly by
  `test_score_at_or_just_below_upper_threshold_is_not_an_outlier` and
  `test_score_just_above_upper_threshold_is_an_outlier` in
  `tests/test_outlier_detection.py`.
- This module never iterates: scores are computed once, from the whole
  segment, with no repeated clipping/re-fitting loop.

### Scientific safety decision

A possible exoplanet transit appears as a *downward* brightness change.
A generic two-sided sigma-clipping rule would erase exactly the signal
this project searches for. Consequently:

- Downward (`OutlierDirection.LOW`) detection is **disabled by default**
  (`OutlierDetectionConfig.lower_threshold=None`).
- Upward (`OutlierDirection.HIGH`) detection is flagged by default and
  cannot be disabled, since a positive spike can never be mistaken for a
  transit.
- **No cadence is ever removed automatically, regardless of
  configuration** -- this stage only flags; it never clips, replaces, or
  excludes.
- A caller may explicitly pass `--lower-threshold` for diagnostic
  purposes, but the CLI's report clearly marks it `ENABLED -- may flag
  transits`, since enabling it can flag possible transits along with
  genuine artifacts. This is never the project default.

### Segment analysis statuses

A segment's cadences are always preserved and its masks are always
present and aligned with one entry per cadence, but `robust_score` is
only computed -- and `high_outlier_mask`/`low_outlier_mask` can only be
`True` -- when `SegmentOutlierStats.status is OutlierAnalysisStatus.VALID`:

| Status | Condition |
|---|---|
| `VALID` | Enough finite normalized-flux values and a usable robust scale; every finite value received a `robust_score`. |
| `INSUFFICIENT_DATA` | Fewer finite normalized-flux values than `OutlierDetectionConfig.minimum_finite_cadences` (default 5) -- e.g. a one-cadence segment. A median/MAD from too few points is not trustworthy enough to score anything against. |
| `ZERO_SCALE` | `robust_scale` is not finite, or is at or below `OutlierDetectionConfig.minimum_robust_scale` (default 0.0) -- e.g. a constant or near-constant segment. No division by zero, no invented scores. |
| `NORMALIZATION_UNAVAILABLE` | The embedded `NormalizedSegment.normalized_flux` is `None` (Phase 3C could not normalize it; see `ReferenceIssue`). There is nothing to analyze. |

A segment with any non-`VALID` status is left with an all-`False`
statistical-outlier mask, but its embedded `NormalizedSegment` -- every
TIME, flux, normalized flux, QUALITY, and source index -- is fully
preserved, and every other segment is still analyzed. One unanalyzable
segment never blocks the rest of the file.

### Defensive nonfinite normalized-flux handling

Phase 3A's default configuration (`require_finite_flux=True`) already
removes nonfinite flux before a light curve ever reaches Phase 3D, so a
nonfinite `normalized_flux` value does not arise under standard
configuration. It remains explicitly handled for light curves
quality-filtered with `require_finite_flux=False`, or
`NormalizedSegment`/`NormalizedLightCurve` objects constructed directly:
such a position is excluded from `center`/`MAD`, is never classified as
a high or low statistical outlier, never sets
`high_outlier_mask`/`low_outlier_mask`, and -- when
`OutlierDetectionConfig.flag_nonfinite_normalized_flux` is `True` (the
default) -- gets its own `FlaggedCadence` record with reason
`NONFINITE_NORMALIZED_FLUX`, distinct from both statistical-outlier
reasons. Every mask position still exists; nothing is silently omitted
from the aligned output.

### Edge cases

- **Empty `NormalizedLightCurve`** (zero segments): zero segments out.
  Not an error.
- **One-cadence segments**: classified `INSUFFICIENT_DATA` under the
  default `minimum_finite_cadences=5`, not an error.
- **A perfectly constant segment**: classified `ZERO_SCALE` (MAD is
  exactly 0), not an error and not a division by zero.

### Scientific guarantees

- No cadence is ever removed, reordered, or duplicated by this module.
- The input `NormalizedLightCurve` is never mutated (frozen models,
  tuple fields).
- `gaps` and every prior `history` entry (Phase 3A's `ProcessingStep`,
  Phase 3B's `GapDetectionStep`, Phase 3C's `NormalizationStep`) are
  carried through unchanged; this phase's own `OutlierDetectionStep` (no
  timestamp) is appended.
- The result is a pure function of `(normalized, config)` -- no
  timestamps, no randomness, no iterative reweighting -- so reruns are
  reproducible byte-for-byte, verified with `model_dump_json()` equality
  in both the unit tests and the real-data check below.
- This module is not detrending, not smoothing, not sector stitching,
  and not transit detection: it computes one robust score per finite
  cadence, once, and compares it to a fixed threshold.

### Real-data sanity check

Run `flag-outliers` (default `mast` quality policy, default gap,
normalization, and outlier-detection config) against the same cached
SPOC product as the Phase 3A/3B/3C checks (TIC 261136679 / Pi Mensae,
sector 1, 20,076 raw cadences, 18,264 retained by Phase 3A, 46 Phase
3B/3C segments, zero invalid-reference segments): of the 46 segments,
**33** reached `VALID` status and **13** were `INSUFFICIENT_DATA`
(short segments below `minimum_finite_cadences=5`); no segment hit
`ZERO_SCALE` or `NORMALIZATION_UNAVAILABLE`. Every `VALID` segment's
robust center was exactly `1.0` (as expected -- Phase 3C normalizes each
segment to a median of 1.0), and nonzero robust scales ranged from
~3.7e-6 to ~7.7e-4 (median ~1.4e-4), reflecting how photometrically
quiet this bright, stable target is. Using the default configuration
(`upper_threshold=5.0`, `lower_threshold=None`), exactly **2** cadences
were flagged as high (positive-spike) outliers, spread across two
different segments, and -- as guaranteed by the default configuration
-- **zero** low (downward) outliers were flagged. The most extreme high
flag had `robust_score ~= 5.49` (source row 3268, TIME ~= 1329.83). The
single most negative `robust_score` in the whole file was `~= -12.77`
(source row 17139, TIME ~= 1349.10) -- a clear downward excursion that
was, as required, **not flagged** under the default configuration,
since low-side detection is disabled by default. A diagnostic run with
`lower_threshold=5.0` (same numerical value as the default
`upper_threshold`, matching this document's own convention above)
additionally flagged **4** low-side cadences with no change to the
2 high flags -- reported here only as a diagnostic; the disabled-by-default
policy remains the project default, and any of those 4 low flags could
in principle include real transit-like signal rather than pure
instrumental artifacts. The file's SHA-256, size, and mtime were
identical before and after; cadence and segment counts matched Phase
3A/3B/3C exactly; every retained TIME and source index round-tripped
through the flagged segments in order with no omission or duplication;
`gaps` and earlier `history` were identical to Phase 3C's own output;
and two runs on the same input produced byte-identical
`model_dump_json()` output.

## Current status: Phase 4A (Local Pi Mensae science website preview)

This is the first slice of roadmap phase 4 (Mission Control website): a
local, read-only dashboard that runs the completed Phase 3A-3D pipeline
against one fixed cached observation (TIC 261136679 / Pi Mensae,
sector 1) and displays the real result. It adds no new scientific
processing -- no detrending, transit search, Box Least Squares,
candidate scoring, or machine learning.

Implemented:
- `backend/app/services/demo_pipeline.py` -- `run_demo_pipeline(fits_path)`,
  a small orchestration function that sequences the existing Phase
  3A-3D pure functions (`filter_quality`, `segment_light_curve`,
  `normalize_light_curve`, `flag_outliers`) with each stage's
  project-default configuration and returns every stage's result. A
  process-local, in-memory cache keyed by the file's resolved path,
  size, and modification time avoids repeating the ~20k-cadence run on
  every request; it holds nothing on disk and is invalidated
  automatically if the file underneath the path changes.
- `backend/app/api/demo.py` -- a read-only router
  (`GET /api/v1/demo/pi-mensae`, `GET /api/v1/demo/pi-mensae/light-curve`)
  with API-specific typed response models, kept separate from the core
  scientific models in `app/data/models.py`. The FITS path is resolved
  from a typed settings value (`Settings.pi_mensae_demo_fits_path`) via
  a FastAPI dependency (`get_demo_fits_path`) -- never from a request
  parameter -- so tests override it cleanly with
  `app.dependency_overrides` and the frontend cannot request an
  arbitrary path. A missing file returns a structured `404`; invalid or
  corrupted FITS data returns a structured `422`.
- `frontend/src/app/demo/pi-mensae/page.tsx` -- the dashboard page:
  pipeline status, summary statistic tiles, a gap-aware light-curve
  chart, per-phase detail panels (quality filtering, segmentation,
  normalization, outlier flagging), processing history, and a visible
  scientific-limitations panel. Loading, backend-unavailable,
  missing-file, and generic-API-error states are distinct and never
  substitute fabricated zero values for real data.
- `frontend/src/components/LightCurveChart.tsx` -- draws each Phase 3B
  segment from its own points only (never one flat connected series),
  so no code path can draw a line across a gap. The ~18,264 points are
  drawn once onto a `<canvas>` for performance; the handful of
  high-outlier markers and gap-boundary indicators are a separate SVG
  overlay with real accessible markup (title text, an
  `aria-label`ed chart summary, and a legend that pairs color with
  shape). The horizontal axis is literal TIME, so a real gap shows up
  honestly as blank space rather than an interpolated bridge.
- `frontend/src/lib/api.ts` -- extended with typed request/response
  contracts (`DemoSummaryResponse`, `DemoLightCurveResponse`, ...) and
  `fetchDemoSummary`/`fetchDemoLightCurve`, plus a `DemoApiError` that
  carries the backend's structured error code and HTTP status so the
  page can distinguish "file missing" from "backend unreachable."
- Backend tests: `backend/tests/test_demo_api.py` (HTTP-level, asserting
  the same real-data numbers recorded below) and
  `backend/tests/test_demo_pipeline.py` (the orchestration helper
  directly, including cache-hit and cache-invalidation behavior).
- Frontend tests: `frontend/tests/demo-page.test.tsx` and
  `frontend/tests/light-curve-chart.test.tsx`, using the project's
  existing Vitest + React Testing Library setup. Fixing a latent gap in
  `frontend/tests/setup.ts` (Testing Library's automatic per-test
  `cleanup()` was never actually registered, since Vitest only exposes
  a global `afterEach` when `test.globals: true` is set, which this
  project does not set) was necessary for multi-test files to pass
  reliably; it now registers `cleanup()` explicitly.

Explicitly not implemented: file uploads, arbitrary target selection,
user accounts, authentication, database persistence, background jobs,
browser-triggered downloads or reprocessing, editing scientific
results, deployment, detrending, Box Least Squares, transit detection,
candidate scoring, or machine learning.

### Why a service module, not logic in the route functions

`app/services/demo_pipeline.py` exists so `app/api/demo.py`'s route
handlers only translate an already-completed pipeline result into
response models -- the same separation of concerns the rest of the
backend follows (`app/data/*` never imports FastAPI). This is also
where the project's `services/` package (reserved since Phase 1 for
"preprocessing, transit search, ranking, ...") gets its first real
content: orchestration of already-implemented stages, not new
scientific logic.

### Read-only guarantees

- The demo endpoints perform no writes, no database operations, and
  never mutate the FITS file, the parsed pipeline objects, or the
  request path.
- The FITS path is fixed by typed settings, never accepted from the
  browser; a `?path=...` query parameter is silently ignored (FastAPI
  simply does not bind it to anything).
- Verified directly: `test_source_fits_file_unchanged_by_repeated_requests`
  reads the cached file's SHA-256, size, and mtime before and after
  several summary and chart requests and asserts all three are
  identical, matching the checksum recorded in the Phase 3A real-data
  sanity check above.

### Chart response shape

`DemoLightCurveResponse` groups points by Phase 3B segment
(`DemoLightCurveSegment.points`) and lists `DemoGap` entries separately,
each naming the segment numbers on either side. This mirrors why
Phase 3B segments a light curve in the first place: a flat, ungrouped
point array would let a naive chart draw a connecting line straight
through a real observation gap. `before_segment_number`/
`after_segment_number` are derived from the same ordered construction
`app/data/gap_segmentation.py` uses to build segments and gaps in one
pass, not recomputed by searching -- gap `i` is always between segments
`i` and `i+1` (0-indexed) by construction.

### Real-data sanity check

`GET /api/v1/demo/pi-mensae` and `GET /api/v1/demo/pi-mensae/light-curve`,
run against the same cached SPOC product as every Phase 3 real-data
check above (TIC 261136679 / Pi Mensae, sector 1,
`tess2018206045859-s0001-0000000261136679-0120-s_lc.fits`), reproduce
every one of those checks' numbers exactly, because the demo pipeline
runs the identical Phase 3A-3D functions with identical default
configuration: 20,076 raw cadences; 18,264 retained / 1,812 rejected
under the `mast` policy (mask 21183 / `0x52BF`); 46 Phase 3B segments
and 45 gaps; 46/46 Phase 3C segments normalized with zero
`ReferenceIssue`s (reference range 1,464,203.25-1,465,118.5); Phase 3D
status 33 `VALID` / 13 `INSUFFICIENT_DATA`, 0 `ZERO_SCALE`, 0
`NORMALIZATION_UNAVAILABLE`; exactly 2 high statistical outliers and 0
low outliers under the default (lower-side-disabled) configuration. The
chart response's 46 segments' point counts sum to exactly 18,264, no
segment is connected across any of the 45 gaps, and exactly 2 chart
points carry `is_high_outlier=true`. Repeated requests produce
byte-identical JSON, and the source file's SHA-256
(`1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609`),
size, and modification time were confirmed unchanged before and after,
both via the automated test and via manual `curl`/browser requests
against a locally running server.

#### Known limitations of Phase 4A

- The demo is fixed to exactly one target, sector, and cached file --
  there is no target search, sector picker, or upload path, by design.
- The in-memory pipeline-result cache is process-local and unbounded
  (holds at most one entry per distinct file identity actually
  requested, which in practice is one); it is not shared across
  worker processes and is lost on restart, which is fine for a local
  single-process demo but would need a different design for multi-worker
  deployment.
- The light-curve chart renders every displayed point rather than
  applying any display-only decimation; this is fine at ~18k cadences
  for one sector but would need a downsampling strategy (preserving
  segment boundaries and every flagged outlier) for a much longer
  baseline.
- `robust_score` in the chart response is recomputed per point from
  each segment's already-computed `center`/`robust_scale` (the same
  formula `app/data/outlier_detection.py` uses), rather than read from
  a stored per-cadence field -- Phase 3D only persists `robust_score` on
  `FlaggedCadence` records for already-flagged cadences, not for every
  cadence, so the chart response derives it for display without
  altering any stored scientific value.
- No visual regression testing is set up; frontend verification relies
  on Vitest/React Testing Library assertions, `tsc --noEmit`, ESLint,
  a production `next build`, and manual browser verification.

## Current status: Phase 4B (Public read-only deployment)

This is the second slice of roadmap phase 4: taking the completed
Phase 4A local dashboard public, without adding any new scientific
processing, any database, any accounts, or any path that accepts an
upload or an arbitrary target. It adds infrastructure only.

```text
Public browser
        | HTTPS
Vercel (Next.js frontend, frontend/ as project root)
        | HTTPS API calls
Render (FastAPI backend, backend/ as root directory, Docker runtime)
        | read-only
Verified Pi Mensae FITS file baked into the backend image at build time
```

### Why Vercel and Render

- **Vercel** builds and hosts the Next.js frontend directly from this
  GitHub repository's `master` branch, with `frontend` as the project
  root; it needs no configuration beyond `NEXT_PUBLIC_API_URL` and
  matches the project's existing `output: "standalone"` Next.js build.
- **Render** was chosen for the backend specifically because the
  project already ships `backend/Dockerfile`: Render's Docker runtime
  runs that image directly, so the exact reproducible scientific
  environment (Python 3.12, `uv`-pinned dependencies) that already
  exists for local development and CI is what serves the public API,
  with no separate deployment-specific dependency file to keep in
  sync.
- Neither host requires a database, a persistent disk, or background
  workers for this milestone, which matches the actual requirement:
  one fixed, read-only demonstration with no runtime state.

### Build-time FITS provisioning

`data/` is gitignored (see `.gitignore`) -- the Pi Mensae FITS file
used throughout every Phase 3A-4A real-data check is a local cache,
not a source file, so it is never committed to git. The deployed image
instead fetches it once, during `docker build`, via
`backend/app/deploy/provision_demo_fits.py` (invoked by
`backend/Dockerfile` as `python -m app.deploy.provision_demo_fits`):

1. Downloads from a **fixed** NASA/MAST "Direct Object Access" URL
   (`https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:TESS/product/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits`)
   -- there is no environment variable, CLI argument, or request
   parameter that can point it anywhere else.
2. Streams the response to a temporary file in the destination
   directory (never assumes the file is small), computing its SHA-256
   while streaming.
3. Verifies the checksum against the exact value recorded in this
   document's Phase 3A real-data sanity check --
   `1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609`
   -- and, when given, the known size (2,039,040 bytes).
4. Only on a full match does it atomically install the file
   (`os.replace`) at its final path; any failure removes the temporary
   file and raises, which fails the `docker build` step rather than
   shipping unverified or partial data.
5. Is idempotent: an existing file at the destination that already
   matches the expected checksum is reused without a network request;
   one that doesn't match is replaced under the exact same
   verification.

This never runs from a running server process or an HTTP request --
only from `docker build` -- so there is no code path by which a public
request could trigger a NASA download. The deployed service also
performs no runtime filesystem writes and relies on no persistent
disk: the embedded file is part of the image itself, and a fresh
container from the same image always starts with the identical,
already-verified file.

`Settings.pi_mensae_demo_fits_path`'s existing default
(`../data/raw/tess/sector_001/<filename>`, resolved from the
container's `/app` working directory to `/data/raw/tess/sector_001/<filename>`)
already matches the provisioning script's destination and Docker
Compose's existing `./data:/data` bind mount, so no path override is
needed between local development and the deployed image.

Tests (`backend/tests/test_provision_demo_fits.py`) inject a fake
downloader and never make a real network call; a correct payload,
an incorrect checksum, an incorrect size, a non-200 status, an
already-valid cached file, and an already-invalid cached file are all
covered. No test in the default suite contacts NASA/MAST.

### CORS decision

CORS is a **browser-enforced** policy, not an authentication boundary
-- this API has no cookies, no sessions, and no credentialed requests,
so `allow_credentials=False` (changed from Phase 1-4A's
`allow_credentials=True`, which was never actually needed). Allowed
origins come from `Settings.cors_origins` (default: `http://localhost:3000`
and `http://127.0.0.1:3000`), overridable via the `CORS_ORIGINS`
environment variable (a JSON array); an optional
`Settings.cors_origin_regex` / `CORS_ORIGIN_REGEX` exists only for the
case where Vercel preview-deployment URLs (which vary per branch/PR)
must also reach the backend, and is unset by default. `allow_origins=["*"]`
is never combined with credentials. See `backend/tests/test_cors.py`
for the exact allow/deny behavior and confirmation that CORS
configuration never changes a response body.

### Render configuration

`render.yaml` (repository root) is a Render Blueprint for one web
service, `ai-exoplanet-hunter-api`:

- `runtime: docker`, `branch: master`, `rootDir: backend` (so
  `backend/Dockerfile` is built with `backend/` as the Docker context
  -- everything the provisioning script needs already lives there, so
  no repository-root Docker context was needed).
- `plan: free`, `healthCheckPath: /api/v1/health`, `autoDeploy: true`.
- `envVars`: `ENVIRONMENT=production`, `LOG_FORMAT=json`, and
  `CORS_ORIGINS` (starts as the local-dev origins; updated to the
  exact Vercel production URL once known -- see "Final production
  CORS" below).
- No database, no persistent disk, no background worker.

`backend/Dockerfile`'s `CMD` was changed to shell form
(`uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`) so it
binds Render's injected `PORT` at runtime while still defaulting to
`8000` locally (matching the existing `EXPOSE 8000` and Docker
Compose's `8000:8000` mapping, so local development is unaffected).

### Frontend configuration

The Vercel project's root directory is `frontend`, production branch
`master`. `NEXT_PUBLIC_API_URL` is a Vercel environment variable set to
the final Render HTTPS URL -- **never** hard-coded into source, since
Next.js inlines `NEXT_PUBLIC_*` variables into the browser bundle at
build time (the same reason `frontend/Dockerfile` already takes it as
a build `ARG`). Changing this variable in Vercel requires a new
deployment (redeploy from the Vercel dashboard, or push a new commit)
before it takes effect -- Vercel does not hot-reload environment
variables into an already-built bundle.

### Cold-start behavior

Render's free instance type sleeps when idle and can take up to
roughly a minute to wake on the next request. The demo page
(`frontend/src/app/demo/pi-mensae/page.tsx`) treats a network error or
a `5xx` response as "possibly waking" (`isRetryableApiError` in
`src/lib/api.ts`) and automatically retries every 5 seconds for up to
60 seconds (`RETRY_INTERVAL_MS` / `MAX_AUTO_RETRY_MS`), showing
`BackendWakingNotice` ("Waking the science backend. This can take up
to about one minute on the free demonstration service.") rather than a
blank page or a fabricated zero value. After the bounded window, or
immediately for a permanent `4xx` scientific/configuration error (a
missing FITS file, invalid data), the page shows the existing
`DemoErrorState` with a manual "Retry" button -- a scientific error is
never auto-retried indefinitely, since retrying it can't change the
answer.

### Security headers

`frontend/next.config.ts` adds `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, and
`X-Frame-Options: DENY` to every route. A Content-Security-Policy was
deliberately not added: the canvas-based light-curve chart and
Next.js's own runtime bootstrap script would need a carefully tuned
CSP that hasn't been written or tested, and shipping an untested CSP
risks silently breaking the chart -- worse than shipping none.

### What Phase 4B does not add

No detrending, transit search, Box Least Squares, candidate ranking,
or machine learning (unchanged from Phase 4A); no PostgreSQL, Redis,
object storage, Celery, background workers, or queues; no user
accounts, authentication, file uploads, arbitrary-path or
arbitrary-target processing; no write endpoint of any kind. The public
API surface is exactly the same two read-only Phase 4A endpoints plus
the existing health check.

### Public URLs

- Public dashboard: see the root `README.md`'s Phase 4B entry for the
  current live Vercel URL (filled in once deployed; this document does
  not duplicate a URL that can change on redeploy).
- Public backend health check: `<Render URL>/api/v1/health`.

### Rollback procedure

- **Render**: open the service's "Deploys" tab and roll back to the
  preceding successful deploy, or push a revert commit to `master`
  (auto-deploy will build it). Automatic deploys can be paused from
  the service's Settings without deleting the service.
- **Vercel**: open the project's "Deployments" tab and promote a
  previous deployment to Production, or revert the commit on `master`.
- **Disabling the public demo**: pause auto-deploy (or suspend/delete
  the Render service) and remove or unpublish the Vercel project;
  removing `NEXT_PUBLIC_API_URL` alone is not sufficient, since the
  frontend would fall back to a localhost URL the public browser can't
  reach, which is a broken state, not a disabled one.
- **Revoking GitHub integration**: remove repository access from the
  Render and Vercel GitHub App installations in each platform's
  account settings; this stops both future auto-deploys immediately.
- **Verifying removal**: after suspending or deleting a service,
  confirm its URL returns a host-level error (DNS failure or platform
  "not found" page) rather than a stale successful response.

### Known limitations of Phase 4B

- The free Render instance type sleeps when idle; the first public
  request after a period of inactivity can take up to roughly a
  minute, mitigated but not eliminated by the frontend's bounded retry.
- The Render free plan has no SLA and may be reclaimed or rate-limited
  by the platform; this deployment is a demonstration, not a
  production service.
- CORS is a browser convenience, not an authentication boundary: the
  API itself is, and is intended to be, fully public and read-only --
  anyone can call it directly (e.g. with `curl`) regardless of CORS
  configuration.
- No Content-Security-Policy is set (see "Security headers" above);
  only low-risk, framework-agnostic headers are applied.
- The provisioning script's build-time NASA/MAST fetch means every
  fresh image build requires network access at build time; a fully
  air-gapped build is out of scope for this milestone.
- Vercel preview-deployment URLs are not permitted through CORS by
  default (`Settings.cors_origin_regex` is unset); enabling them for a
  given branch/PR is a deliberate, documented opt-in, not automatic.

## Known limitations of this milestone

- The backend Docker image installs core web-service dependencies plus
  the small `fits` extra (astropy only), which `app/data/fits_parser.py`
  needs to parse the Pi Mensae FITS file for the public Phase 4B demo
  endpoints. The heavier `mast` (astroquery), `science` (Lightkurve,
  ...), and `ml` (PyTorch, scikit-learn) extras are deliberately
  deferred to the phases that use them at runtime, to avoid
  multi-gigabyte builds with no corresponding functionality.
- Postgres is provisioned but nothing reads from or writes to it yet --
  database models for search results arrive in a later phase.
- The dashboard's mission-overview numbers are static placeholders; they
  become live once the pipeline starts writing to the database.
- Name-based search relies on MAST's cone search around a resolved
  coordinate (Sesame/Simbad name resolution via astropy), then filters
  to the TESS mission; it can occasionally surface a full-frame-image
  row before a target's own timeseries row, though `MastClient` prefers
  rows with a numeric TIC ID when picking the resolved identity.
- No rate-limiting wraps the MAST calls; each CLI invocation makes a
  fresh request with a fixed 30s timeout, with up to 3 retries and
  exponential backoff for downloads specifically (search/discovery
  calls are not retried).
- The quality-bit table is a snapshot of Rev F of the TESS data-products
  document (retrieved 2026-07-24). That document explicitly warns flag
  values may change, so the table needs re-verification against future
  revisions; it is isolated in `app/data/quality_flags.py` and pinned by
  `tests/test_quality_flags.py` to make that a small, reviewable change.
- `filter_quality` holds the whole light curve and every rejection
  record in memory (bounded by the cadence count, ~20k for a 2-minute
  sector). Fine at single-sector scale; batch processing of many sectors
  may want a streaming variant later.
- Gap-origin classification (`observation_gap` vs. `source_rows_rejected`)
  is derived only from `source_indices` and TIME; it cannot distinguish
  *which* Phase 3A rejection rule(s) caused skipped rows, or whether a
  claimed `observation_gap` was a downlink, safe mode, momentum-dump, or
  some other real interruption -- it only proves the interval was not
  (fully) explained by rows an earlier step removed.
- `estimated_missing_cadences` is a count derived from timing alone, not
  a claim about *which* cadences are missing or why; it is withheld
  (`None`) whenever the interval isn't close enough to an integer
  cadence multiple to avoid false precision, and no attempt is made to
  reconstruct or interpolate the missing values themselves.
- The gap threshold uses one single measured nominal cadence for the
  entire file. A light curve whose true cadence changes partway through
  (e.g. a mid-sector pipeline reprocessing) is not currently detected as
  such -- it would show up only indirectly, as apparent gaps or unusual
  `interval_to_cadence_ratio` values.
- A segment's median reference has no protection against a transit (or
  other astrophysical dip) that occupies a large fraction of that
  segment: the median's ~50% breakdown point makes it robust to a
  brief transit, but a segment mostly *within* a long transit or an
  eclipsing binary would still bias its own reference. This is an
  inherent limitation of any reference-based normalization at this
  stage, not a bug.
- Very short segments (one or two cadences) have essentially no
  robustness in their median reference -- it is just one of the raw
  values. This is not corrected by merging or filtering short segments,
  since doing so would mean rejecting or moving cadences, which this
  phase never does.
- `normalized_flux_err` treats the segment's median reference as an
  exact constant; the reference's own sampling uncertainty is not
  propagated into the reported error.
- `parse_light_curve` only supports the standard SPOC/TESS-SPOC
  light-curve FITS schema (a `LIGHTCURVE` extension with `TIME`,
  `QUALITY`, and `PDCSAP_FLUX`/`SAP_FLUX` columns). QLP light curves use
  a different column schema and are rejected with a clear
  `MissingExtensionError` rather than parsed incorrectly.
- The download size/checksum check compares against MAST's reported
  product size when available; MAST does not publish a per-product
  checksum, so integrity beyond size comparison relies on the locally
  computed SHA-256 sidecar detecting *later* corruption, not validating
  the transfer against an independent source checksum.
- `1.4826 * MAD` is a Gaussian-consistency convention, not a claim that
  TESS photometric noise is Gaussian; `robust_score` should be read as a
  robust, comparable-across-segments unit, not a calibrated probability.
- A segment's `center`/`MAD` have no protection against a transit (or
  other astrophysical dip) that occupies a large fraction of that
  segment, the same inherent limitation Phase 3C's median reference has;
  the median's ~50% breakdown point makes it robust to a brief transit,
  not to one spanning most of a short segment.
- This phase only flags; it never removes, replaces, or invents a value
  for an outlier. A caller who wants to actually exclude, down-weight,
  or otherwise act on flagged cadences must do so in a later stage --
  this phase never decides that for them.
- Enabling `--lower-threshold` is a diagnostic tool, not a substitute for
  transit detection: it flags any large downward deviation from a
  segment's own robust center, including a real transit, an eclipsing
  binary, or an instrumental dip alike -- it cannot and does not
  distinguish between them.
- `minimum_finite_cadences` and `minimum_robust_scale` are fixed,
  global-default thresholds applied identically to every segment
  regardless of that segment's own length or noise characteristics; a
  very long, very quiet segment and a short, noisy one use the same
  cutoffs unless the caller overrides them per run (not per segment).
