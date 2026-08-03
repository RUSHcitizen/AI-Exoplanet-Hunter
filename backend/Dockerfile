# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Build tools are needed to compile a couple of the scientific-stack
# dependencies (e.g. psycopg's C extension) on some platforms.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app

# Core web-service dependencies, plus the small `fits` extra (astropy
# only) that app/data/fits_parser.py needs to parse the Pi Mensae FITS
# file for the public demo endpoints (app/api/demo.py). The heavier
# `mast`/`science`/`ml` extras (astroquery, lightkurve, torch, ...) stay
# out of this image -- nothing at runtime performs a live MAST query or
# ML inference, so there's no point paying for that build weight here.
RUN uv pip install --system --no-cache ".[fits]"

# --- Phase 4B: build-time Pi Mensae demo FITS provisioning -------------------
#
# Fetches the fixed, checksum-verified TIC 261136679 / TESS sector 1 SPOC
# light curve from NASA/MAST (app/deploy/provision_demo_fits.py) so the
# deployed image can serve the read-only demo endpoints without bundling
# the FITS file in git or downloading it at request time. Uses only the
# standard library -- no extra dependency install needed. Fails the build
# (not the running server) if the download or its SHA-256 don't match.
RUN python -m app.deploy.provision_demo_fits

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/api/v1/health')" || exit 1

# Render (and other PaaS hosts) inject PORT at runtime; local Docker
# Compose leaves it unset, so this defaults to 8000 to match the existing
# EXPOSE/compose port mapping. Shell form is required for ${PORT} expansion.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
