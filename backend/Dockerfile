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

# Only the core web-service dependencies are installed for now. The
# `science` and `ml` extras (astropy, lightkurve, torch, ...) are heavy
# and get added to this image starting Phase 2, when the code actually
# uses them -- no point paying for a multi-gigabyte build today.
RUN uv pip install --system --no-cache .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
