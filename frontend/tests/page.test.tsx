import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MissionControlPage from "@/app/page";

describe("MissionControlPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("renders the Mission Control heading and stat tiles", () => {
    render(<MissionControlPage />);

    expect(screen.getByRole("heading", { name: "Mission Control" })).toBeInTheDocument();
    expect(screen.getByText("Targets processed")).toBeInTheDocument();
    expect(screen.getByText("Candidates detected")).toBeInTheDocument();
  });

  it("shows an offline status when the backend cannot be reached", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("network down"));

    render(<MissionControlPage />);

    await waitFor(() => expect(screen.getByText("Offline")).toBeInTheDocument());
    expect(screen.getByText(/Could not reach the backend API/)).toBeInTheDocument();
  });

  it("shows an online status with service info when the backend responds", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "ok",
        app_name: "Exoplanet Hunter API",
        environment: "development",
        timestamp: "2026-01-01T00:00:00Z",
      }),
    } as Response);

    render(<MissionControlPage />);

    await waitFor(() => expect(screen.getByText("Online")).toBeInTheDocument());
    expect(screen.getByText("Exoplanet Hunter API")).toBeInTheDocument();
    expect(screen.getByText("development")).toBeInTheDocument();
  });
});
