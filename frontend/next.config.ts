import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output produces a minimal, self-contained server bundle
  // (node_modules pruned to only what's needed) so the Docker image
  // doesn't have to ship the full monorepo node_modules tree.
  output: "standalone",

  // Phase 4B: low-risk, framework-agnostic headers for the public
  // deployment. Deliberately not a Content-Security-Policy -- this app's
  // canvas-based light-curve chart and Next.js's own runtime bootstrap
  // script would need a carefully tuned CSP that hasn't been written or
  // tested yet (see docs/architecture.md's Phase 4B section).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
    ];
  },
};

export default nextConfig;
