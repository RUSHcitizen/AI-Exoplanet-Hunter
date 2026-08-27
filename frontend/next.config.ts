import type { NextConfig } from "next";

/**
 * `output` is chosen by the deployment target:
 *
 * - `export` (default here) emits a fully static site, which is what the
 *   Cloudflare deployment serves. Every route in this app is a client
 *   component that fetches its data in the browser, so nothing needs a
 *   Node server at request time.
 * - `standalone` produces the self-contained server bundle the Docker
 *   image ships. Set `NEXT_OUTPUT=standalone` to build that instead.
 *
 * Security headers are deliberately not configured here: `headers()` has
 * no effect under `output: "export"`, because a static export has no
 * server to apply them. They live in `public/_headers` (served by
 * Cloudflare for static assets) and in the Worker (for API responses)
 * instead, so both paths are covered by exactly one mechanism each.
 * Deliberately not a Content-Security-Policy -- this app's canvas-based
 * light-curve chart and Next.js's own runtime bootstrap script would
 * need a carefully tuned CSP that hasn't been written or tested yet
 * (see docs/architecture.md's Phase 4B section).
 */
const output = process.env.NEXT_OUTPUT === "standalone" ? "standalone" : "export";

const nextConfig: NextConfig = {
  output,

  // A static export cannot run the on-demand image optimizer, which has
  // no server to run on. This app ships no <Image> usage today; the flag
  // keeps a future one from failing the export build.
  images: { unoptimized: true },
};

export default nextConfig;
