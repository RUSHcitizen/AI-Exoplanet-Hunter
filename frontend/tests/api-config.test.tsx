/**
 * Confirms the API client's base URL is driven entirely by
 * `NEXT_PUBLIC_API_URL` (see `src/lib/api.ts`), not hard-coded -- and
 * that a configured production URL is what every request actually uses,
 * never a localhost fallback.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ENV_KEY = "NEXT_PUBLIC_API_URL";
const ORIGINAL_VALUE = process.env[ENV_KEY];

function restoreEnv() {
  if (ORIGINAL_VALUE === undefined) {
    delete process.env[ENV_KEY];
  } else {
    process.env[ENV_KEY] = ORIGINAL_VALUE;
  }
}

describe("API base URL configuration", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    restoreEnv();
    vi.unstubAllGlobals();
  });

  it("uses the configured production URL (the Render deployment case)", async () => {
    process.env[ENV_KEY] = "https://ai-exoplanet-hunter-api.onrender.com";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
    );
    const { fetchHealth } = await import("@/lib/api");
    await fetchHealth();
    expect(fetch).toHaveBeenCalledWith(
      "https://ai-exoplanet-hunter-api.onrender.com/api/v1/health",
      expect.anything(),
    );
  });

  it("falls back to the documented localhost default only when unset", async () => {
    delete process.env[ENV_KEY];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
    );
    const { fetchHealth } = await import("@/lib/api");
    await fetchHealth();
    expect(fetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/health", expect.anything());
  });

  it("issues same-origin relative requests for the Cloudflare deployment", async () => {
    process.env[ENV_KEY] = "same-origin";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
    );
    const { fetchDemoSummary } = await import("@/lib/api");
    await fetchDemoSummary();
    expect(fetch).toHaveBeenCalledWith("/api/v1/demo/pi-mensae", expect.anything());
  });

  it("trims a trailing slash so the path is never double-slashed", async () => {
    process.env[ENV_KEY] = "https://api.example.com/";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
    );
    const { fetchHealth } = await import("@/lib/api");
    await fetchHealth();
    expect(fetch).toHaveBeenCalledWith("https://api.example.com/api/v1/health", expect.anything());
  });

  it("treats an empty value as unset rather than as same-origin", async () => {
    process.env[ENV_KEY] = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => ({}) }) as Response),
    );
    const { fetchHealth } = await import("@/lib/api");
    await fetchHealth();
    expect(fetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/health", expect.anything());
  });

  it("never issues a request to localhost once a production URL is configured", async () => {
    process.env[ENV_KEY] = "https://ai-exoplanet-hunter-api.onrender.com";
    const fetchMock = vi.fn<typeof fetch>(
      async () => ({ ok: true, json: async () => ({}) }) as Response,
    );
    vi.stubGlobal("fetch", fetchMock);
    const { fetchDemoSummary, fetchDemoLightCurve } = await import("@/lib/api");
    await fetchDemoSummary();
    await fetchDemoLightCurve();
    for (const [url] of fetchMock.mock.calls) {
      expect(String(url)).not.toContain("localhost");
    }
  });
});
