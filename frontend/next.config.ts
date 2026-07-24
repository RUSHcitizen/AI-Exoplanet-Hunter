import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Standalone output produces a minimal, self-contained server bundle
  // (node_modules pruned to only what's needed) so the Docker image
  // doesn't have to ship the full monorepo node_modules tree.
  output: "standalone",
};

export default nextConfig;
