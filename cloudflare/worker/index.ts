/**
 * Cloudflare Worker serving the Pi Mensae demo API.
 *
 * Why a Worker rather than the FastAPI service: the Python backend
 * depends on astropy and numpy to parse a 2 MB FITS file, which is
 * outside what the Workers runtime can run. It does not need to run
 * here, though -- the demo API is a pure function of one fixed,
 * checksum-pinned observation, so `app.deploy.export_static` computes
 * both responses at build time and this Worker serves those exact bytes
 * from the asset store. `backend/tests/test_export_static.py` pins the
 * exported payloads byte-for-byte against the live FastAPI responses, so
 * what ships here is what the backend would have returned.
 *
 * The Python backend remains the source of truth and stays runnable via
 * `make dev`, the CLI, and its Docker image. This is a delivery
 * mechanism, not a reimplementation: no scientific logic lives in this
 * file, and none should ever be added to it.
 */

interface Env {
  ASSETS: Fetcher;
}

/** Request path -> asset path holding that route's precomputed payload. */
const ROUTES: Record<string, string> = {
  "/api/v1/demo/pi-mensae": "/_data/summary.json",
  "/api/v1/demo/pi-mensae/light-curve": "/_data/light-curve.json",
};

const HEALTH_ROUTES = new Set(["/api/v1/health", "/health"]);

/**
 * The payloads are immutable for a given deployment -- a new build
 * produces a new set of assets -- so they can be cached hard. Combined
 * with the ETag below, a returning visitor revalidates with a 304
 * instead of re-downloading ~3 MB of JSON.
 */
const PAYLOAD_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400";

function jsonResponse(body: unknown, status = 200, extraHeaders: HeadersInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

/**
 * Mirrors the headers the Next.js config previously set for the Vercel
 * deployment. A static export cannot emit headers itself, so the site's
 * assets get these from `dist/_headers` and API responses get them here.
 */
function securityHeaders(): Record<string, string> {
  return {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
  };
}

async function servePayload(assetPath: string, request: Request, env: Env): Promise<Response> {
  const assetUrl = new URL(assetPath, request.url);
  const asset = await env.ASSETS.fetch(new Request(assetUrl, { method: "GET" }));

  if (!asset.ok) {
    // The asset store did not have the payload, which means the build
    // did not run app.deploy.export_static. Report it as a backend
    // failure rather than a 404 the page would read as "no such route".
    return jsonResponse(
      {
        detail: {
          error: "demo_payload_missing",
          message:
            "This deployment was built without its precomputed pipeline output. " +
            "Run scripts/build-cloudflare.sh to regenerate it.",
        },
      },
      503,
    );
  }

  const etag = asset.headers.get("etag");
  if (etag && request.headers.get("if-none-match") === etag) {
    return new Response(null, {
      status: 304,
      headers: { etag, "cache-control": PAYLOAD_CACHE_CONTROL, ...securityHeaders() },
    });
  }

  const headers = new Headers(asset.headers);
  headers.set("content-type", "application/json; charset=utf-8");
  headers.set("cache-control", PAYLOAD_CACHE_CONTROL);
  for (const [key, value] of Object.entries(securityHeaders())) {
    headers.set(key, value);
  }
  return new Response(asset.body, { status: 200, headers });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (!path.startsWith("/api/") && !HEALTH_ROUTES.has(path)) {
      return env.ASSETS.fetch(request);
    }

    // The API is read-only. Anything else is rejected here rather than
    // reaching the asset store.
    if (request.method !== "GET" && request.method !== "HEAD") {
      return jsonResponse(
        { detail: { error: "method_not_allowed", message: "This API is read-only." } },
        405,
        { allow: "GET, HEAD" },
      );
    }

    if (HEALTH_ROUTES.has(path)) {
      return jsonResponse({
        status: "ok",
        app_name: "Exoplanet Hunter API",
        environment: "production",
        timestamp: new Date().toISOString(),
      });
    }

    const assetPath = ROUTES[path];
    if (assetPath) {
      return servePayload(assetPath, request, env);
    }

    return jsonResponse(
      {
        detail: {
          error: "not_found",
          message: `No such endpoint: ${path}`,
        },
      },
      404,
    );
  },
} satisfies ExportedHandler<Env>;
