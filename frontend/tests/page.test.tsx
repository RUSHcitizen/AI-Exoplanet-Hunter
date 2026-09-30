import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OverviewPage from "@/app/page";

describe("OverviewPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("introduces the project and links to the observation", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    render(<OverviewPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(/transiting exoplanets/i);
    const links = screen.getAllByRole("link", { name: /pi mensae/i });
    expect(links.length).toBeGreaterThan(0);
    for (const link of links) expect(link).toHaveAttribute("href", "/demo/pi-mensae");
  });

  it("separates implemented stages from planned ones and never implies ML results", () => {
    vi.mocked(fetch).mockReturnValue(new Promise(() => {}));
    render(<OverviewPage />);

    expect(screen.getByRole("heading", { name: "Complete" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Planned" })).toBeInTheDocument();
    expect(screen.getByText("Machine-learning classification")).toBeInTheDocument();
    expect(screen.getByText(/No machine-learning model is part of the pipeline yet/)).toBeInTheDocument();
  });

  it("shows an offline status when the backend cannot be reached", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("network down"));

    render(<OverviewPage />);

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

    render(<OverviewPage />);

    await waitFor(() => expect(screen.getByText("Online")).toBeInTheDocument());
    expect(screen.getByText("Exoplanet Hunter API")).toBeInTheDocument();
    expect(screen.getByText("development")).toBeInTheDocument();
  });
});
