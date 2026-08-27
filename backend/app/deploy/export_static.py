"""Build-time export of the demo API's responses as static JSON.

The Phase 4A/4B demo API is a pure function of one fixed, checksum-pinned
FITS file: ``app.services.demo_pipeline`` runs the same deterministic
Phase 3A-3D stages on every request and the endpoints never accept a
caller-supplied parameter. Two consequences follow, and this module
exists because of the second:

1. Nothing about the response can change between requests, so there is
   no reason to recompute it per request.
2. Nothing about the response requires a Python process at request time
   at all -- it can be computed once, at build time, and served as a
   static file from a CDN.

That is what makes a Cloudflare deployment possible. Cloudflare Workers
cannot run this backend directly (astropy, numpy, and FITS parsing are
outside what the Workers Python runtime supports), but they can serve
what this module writes. See ``docs/deployment-cloudflare.md``.

Byte-parity with the live API is structural, not asserted: this module
calls the exact same ``build_summary_response`` /
``build_light_curve_response`` functions that ``app.api.demo``'s route
handlers call, and serializes them with the same Pydantic models. It
adds no display logic of its own. ``backend/tests/test_export_static.py``
pins that equivalence against the FastAPI app's real responses.

This module never downloads anything. Provisioning the FITS file is
``app.deploy.provision_demo_fits``'s job, and remains a separate,
independently verified step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.api.demo import build_light_curve_response, build_summary_response
from app.services.demo_pipeline import DemoFitsNotFoundError, run_demo_pipeline

SUMMARY_FILENAME = "summary.json"
LIGHT_CURVE_FILENAME = "light-curve.json"
MANIFEST_FILENAME = "manifest.json"

# Mirrors the versioned routes in app/api/demo.py. The Worker maps these
# request paths onto the filenames above; keeping the mapping recorded in
# the manifest means the two sides cannot silently drift.
SUMMARY_ROUTE = "/api/v1/demo/pi-mensae"
LIGHT_CURVE_ROUTE = "/api/v1/demo/pi-mensae/light-curve"


class ExportError(RuntimeError):
    """The pipeline could not be run, or its output could not be written."""


@dataclass(frozen=True)
class ExportedFile:
    """One written artifact, with the digest a caller can verify."""

    path: Path
    route: str
    byte_count: int
    sha256: str


def export_static_payloads(fits_path: Path, output_dir: Path) -> tuple[ExportedFile, ...]:
    """Run the pipeline once and write both API payloads under ``output_dir``.

    Returns one :class:`ExportedFile` per payload, plus the manifest.

    Raises:
        ExportError: the FITS file is missing. Invalid-FITS and
            processing failures propagate unchanged from the pipeline --
            a corrupt input should fail the build loudly, not produce a
            plausible-looking JSON file.
    """
    try:
        result = run_demo_pipeline(fits_path)
    except DemoFitsNotFoundError as exc:
        raise ExportError(str(exc)) from exc

    output_dir.mkdir(parents=True, exist_ok=True)

    summary = build_summary_response(result)
    light_curve = build_light_curve_response(result)

    written = [
        _write_json(output_dir / SUMMARY_FILENAME, summary.model_dump_json(), SUMMARY_ROUTE),
        _write_json(
            output_dir / LIGHT_CURVE_FILENAME,
            light_curve.model_dump_json(),
            LIGHT_CURVE_ROUTE,
        ),
    ]

    manifest = {
        "source_filename": summary.identity.source_filename,
        "source_checksum_sha256": summary.identity.source_checksum_sha256,
        "routes": {entry.route: entry.path.name for entry in written},
        "payloads": {
            entry.path.name: {"bytes": entry.byte_count, "sha256": entry.sha256}
            for entry in written
        },
    }
    written.append(
        _write_json(
            output_dir / MANIFEST_FILENAME,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            route="",
        )
    )
    return tuple(written)


def _write_json(path: Path, payload: str, route: str) -> ExportedFile:
    encoded = payload.encode("utf-8")
    path.write_bytes(encoded)
    return ExportedFile(
        path=path,
        route=route,
        byte_count=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.deploy.export_static",
        description="Export the Pi Mensae demo API responses as static JSON for CDN hosting.",
    )
    parser.add_argument(
        "--fits",
        type=Path,
        required=True,
        help="Path to the cached Pi Mensae SPOC light curve.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Directory to write summary.json, light-curve.json, and manifest.json into.",
    )
    args = parser.parse_args(argv)

    try:
        written = export_static_payloads(args.fits, args.output)
    except ExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for entry in written:
        print(f"wrote {entry.path}  {entry.byte_count:,} bytes  sha256={entry.sha256[:16]}...")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
