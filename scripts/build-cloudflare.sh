#!/usr/bin/env bash
#
# Assemble the Cloudflare deployment bundle.
#
# Cloudflare Workers cannot run the FastAPI backend (astropy/numpy FITS
# parsing is outside the Workers runtime), but the demo API is a pure
# function of one fixed, checksum-pinned observation -- so this script
# runs the real Phase 3A-3D pipeline once at build time and ships its
# output as static JSON alongside the static site.
#
#   1. provision the pinned Pi Mensae FITS from NASA/MAST (checksum-verified)
#   2. run the pipeline and export both API payloads as JSON
#   3. build the Next.js static export
#   4. assemble everything into cloudflare/dist
#
# Usage:  scripts/build-cloudflare.sh
# Deploy: cd cloudflare && npx wrangler deploy
#
# Requires: python3 with the backend's `fits` extra installed, and node/npm.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"
FRONTEND_DIR="$REPO_ROOT/frontend"
DIST_DIR="$REPO_ROOT/cloudflare/dist"

# Where the pinned FITS lands. Override to reuse an already-downloaded
# copy (the local cache from `python -m app.cli download-target`, say)
# and skip the network entirely.
DEMO_FITS_PATH="${DEMO_FITS_PATH:-$REPO_ROOT/data/raw/tess/sector_001/tess2018206045859-s0001-0000000261136679-0120-s_lc.fits}"

# The venv `make install` creates, if present; otherwise whatever python3
# is on PATH (the case in CI and in Cloudflare's build image).
PYTHON="$BACKEND_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON="python3"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "1/4  Provisioning the pinned Pi Mensae FITS"
# provision() verifies SHA-256 and size before moving the file into
# place, and is idempotent: an existing file that already matches the
# pinned checksum makes no network request at all.
#
# It is called directly rather than through `python -m` because the
# module's main() deliberately accepts no arguments -- the product URI
# and checksum are fixed constants, and that guarantee is worth keeping.
# Only the destination varies here, and it stays a build-script concern.
( cd "$BACKEND_DIR" && "$PYTHON" -c "
from pathlib import Path
from app.deploy.provision_demo_fits import provision
provision(Path('$DEMO_FITS_PATH'))
" )

step "2/4  Exporting the pipeline output as static JSON"
( cd "$BACKEND_DIR" && "$PYTHON" -m app.deploy.export_static \
    --fits "$DEMO_FITS_PATH" \
    --output "$DIST_DIR/_data" )

step "3/4  Building the Next.js static export"
# same-origin: the Worker serves /api/v1/* from the same host as the site,
# so the browser makes relative requests and no CORS is involved.
( cd "$FRONTEND_DIR" && NEXT_PUBLIC_API_URL=same-origin npm run build )

step "4/4  Assembling cloudflare/dist"
# Copy the export in without clobbering _data, which step 2 just wrote.
cp -R "$FRONTEND_DIR/out/." "$DIST_DIR/"

printf '\n\033[1mBundle ready:\033[0m %s\n' "$DIST_DIR"
du -sh "$DIST_DIR" 2>/dev/null || true
printf '\nPreview locally:  cd cloudflare && npx wrangler dev\n'
printf 'Deploy:           cd cloudflare && npx wrangler deploy\n'
