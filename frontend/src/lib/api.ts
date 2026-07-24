/**
 * Typed client for the Exoplanet Hunter backend API.
 *
 * `NEXT_PUBLIC_API_URL` is read at build time and baked into the browser
 * bundle (any `NEXT_PUBLIC_*` var is), so it must point somewhere the
 * *browser* can reach -- e.g. `http://localhost:8000` in local dev, even
 * though inside Docker Compose the backend's hostname is `backend`.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  app_name: string;
  environment: string;
  timestamp: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/health`, { cache: "no-store" });
  } catch (cause) {
    throw new ApiError("Could not reach the backend API.", cause);
  }

  if (!response.ok) {
    throw new ApiError(`Backend returned HTTP ${response.status}.`);
  }

  return (await response.json()) as HealthResponse;
}
