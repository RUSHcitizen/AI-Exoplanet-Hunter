# Deploying to Cloudflare

The public Pi Mensae dashboard runs on Cloudflare as a single Worker with
static assets: one origin serving both the site and the API, with no
container, no cold start, and no database.

## Why the Python backend is not what runs here

Cloudflare Workers cannot run this backend. Parsing a 2 MB FITS file
needs `astropy` and `numpy`, which are outside the Workers Python
runtime, and the Phase 3A-3D pipeline is not something to reimplement in
TypeScript — a second implementation of the science would be a second
thing to keep correct, and the project's integrity rules exist precisely
to stop that kind of drift.

It does not need to run at request time. The demo API is a *pure function
of one fixed, checksum-pinned observation*:

- `app/api/demo.py` never accepts a caller-supplied parameter; the path
  comes from typed settings.
- `app/services/demo_pipeline.py` runs the same deterministic stages on
  every request.
- `backend/tests/test_demo_pipeline.py::test_pipeline_is_reproducible`
  pins that identical bytes in produce identical results out.

So the pipeline runs **once, at build time**, and Cloudflare serves the
result. `app/deploy/export_static.py` calls the exact same
`build_summary_response` / `build_light_curve_response` functions the
route handlers call, and
`backend/tests/test_export_static.py` asserts the exported files are
byte-identical to the live FastAPI responses. What the CDN serves is
what the backend would have returned.

The FastAPI service remains the source of truth and stays fully runnable
— `make dev`, the CLI, and its Docker image are unchanged. Cloudflare is
a delivery mechanism, not a reimplementation.

## What gets deployed

```
cloudflare/dist/
├── index.html, demo/, _next/…   Next.js static export
├── _headers                     security + cache headers for assets
└── _data/
    ├── summary.json             GET /api/v1/demo/pi-mensae
    ├── light-curve.json         GET /api/v1/demo/pi-mensae/light-curve
    └── manifest.json            route → file map, source checksum, digests
```

`cloudflare/worker/index.ts` routes `/api/v1/*` and serves everything
else from the asset store. `run_worker_first` in `wrangler.jsonc` means
the Worker is only invoked for API paths — page and bundle requests are
served by Cloudflare's edge without running any code.

## Build and deploy

```bash
# One command: provision FITS → run pipeline → export JSON → build site
scripts/build-cloudflare.sh

cd cloudflare
npx wrangler dev      # preview at http://localhost:8787
npx wrangler deploy   # publish
```

The build fetches the pinned SPOC product from NASA/MAST and verifies its
SHA-256 before use, so a corrupted or substituted file fails the build
rather than reaching the site. Set `DEMO_FITS_PATH` to reuse a local copy
and skip the download.

### Cloudflare dashboard settings

| Setting | Value |
|---|---|
| Build command | `scripts/build-cloudflare.sh` |
| Deploy command | `npx wrangler deploy` |
| Root directory | repository root |
| Build output | `cloudflare/dist` |

The build image needs Python 3.12+ with the backend's `fits` extra
(`pip install -e "backend[fits]"`) and Node 22+.

## What this fixes

Serving from the edge resolves two findings from the project review:

- **Cold start.** The Render free tier took up to a minute to wake, and
  the frontend carried a bounded retry loop for it. Static assets have
  no cold start.
- **Payload size.** The light-curve response is 3.3 MB of JSON.
  Cloudflare negotiates compression automatically (measured: **3.3 MB →
  660 KB gzip**, 5.0×), and the Worker sets `Cache-Control` plus an
  `ETag`, so a returning visitor revalidates with a **304 and zero
  bytes**.

CORS disappears too: the API is same-origin with the page, so
`NEXT_PUBLIC_API_URL=same-origin` makes the browser issue relative
requests and no preflight is involved.

## Keeping the other deployment

Nothing here removes the Vercel + Render path. `NEXT_OUTPUT=standalone`
still builds the server bundle the Docker image ships, and setting
`NEXT_PUBLIC_API_URL` to an absolute URL points the frontend at a
separately hosted FastAPI backend. `render.yaml` is untouched.

## Verifying a deployment

```bash
BASE=https://your-worker.workers.dev

curl -s "$BASE/api/v1/health"
curl -s "$BASE/api/v1/demo/pi-mensae" | jq '.identity'

# Compression and revalidation
curl -sH 'Accept-Encoding: gzip' -o /dev/null -w '%{size_download} bytes\n' \
  "$BASE/api/v1/demo/pi-mensae/light-curve"
ETAG=$(curl -sI "$BASE/api/v1/demo/pi-mensae/light-curve" | grep -i ^etag | cut -d' ' -f2- | tr -d '\r')
curl -s -o /dev/null -w '%{http_code}\n' -H "If-None-Match: $ETAG" \
  "$BASE/api/v1/demo/pi-mensae/light-curve"   # expect 304
```

Confirm the served `identity.source_checksum_sha256` is
`1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609` — the
pinned Pi Mensae product. A different value means the build used a
different observation, and the page's scientific claims no longer refer
to what the documentation describes.

## Scientific integrity note

Precomputing does not weaken any of the project's guarantees. The
exported payloads carry the same provenance the live API returns: the
full processing history, per-stage configuration, and the source FITS
SHA-256. The dashboard still states its limitations, still marks
statistical outliers as *not* planet candidates, and still never claims a
detection. The only thing that changed is *when* the pipeline ran.
