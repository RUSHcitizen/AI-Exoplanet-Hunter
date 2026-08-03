import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PiMensaeDemoPage from "@/app/demo/pi-mensae/page";

const SUMMARY_FIXTURE = {
  identity: {
    target_name: "Pi Mensae",
    tic_id: 261136679,
    sector: 1,
    mission: "TESS",
    source_filename: "tess2018206045859-s0001-0000000261136679-0120-s_lc.fits",
    source_checksum_sha256: "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609",
    flux_column: "PDCSAP_FLUX",
    pipeline: "SPOC",
  },
  raw: { raw_cadence_count: 20076 },
  quality_filter: {
    retained_cadence_count: 18264,
    rejected_cadence_count: 1812,
    retained_fraction: 0.9097429766885834,
    quality_policy: "mast",
    quality_bitmask_decimal: 21183,
    quality_bitmask_hex: "0x52BF",
    rejection_counts_by_reason: { nonfinite_flux: 1797, matched_quality_bits: 1812 },
    matched_quality_bit_counts: { "8": 816, "128": 963 },
  },
  segmentation: {
    segment_count: 46,
    gap_count: 45,
    measured_nominal_cadence_days: 0.0013888662138015206,
    measured_nominal_cadence_seconds: 119.99804087245138,
    metadata_cadence_days: 0.001388888888888889,
    metadata_cadence_seconds: 120,
    estimated_missing_cadence_count: 1489,
  },
  normalization: {
    normalized_segment_count: 46,
    invalid_reference_segment_count: 0,
    segment_reference_min: 1464203.25,
    segment_reference_median: 1464608.21875,
    segment_reference_max: 1465118.5,
  },
  outliers: {
    valid_segment_count: 33,
    insufficient_data_segment_count: 13,
    zero_scale_segment_count: 0,
    normalization_unavailable_segment_count: 0,
    high_outlier_count: 2,
    low_outlier_count: 0,
    lower_detection_enabled: false,
    upper_threshold: 5,
    lower_threshold: null,
    outlier_fraction: 0.00010950503723171266,
  },
  provenance: {
    processing_history: [
      {
        step: "quality_filter",
        code_version: "0.1.0",
        input_count: 20076,
        output_count: 18264,
        configuration_summary: "quality_policy=mast, bitmask=21183",
        source_checksum_sha256: "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609",
      },
      {
        step: "outlier_flagging",
        code_version: "0.1.0",
        input_count: 18264,
        output_count: 33,
        configuration_summary: "upper_threshold=5.0, lower_threshold=disabled",
        source_checksum_sha256: "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609",
      },
    ],
    source_checksum_sha256: "1eecffff3afa7e8c4ad763b6907e62447bacf339968292d86be45acd9bf1d609",
    fits_file_unchanged_statement: "The source FITS file is never modified.",
    deterministic_processing_statement: "Repeated requests return identical results.",
  },
  scientific_limitations: [
    "This dashboard does not identify or confirm planets.",
    "Statistical outliers are not planet candidates or transit signals.",
    "Downward (low-side) outlier detection is disabled by default.",
  ],
};

function makeSegment(segmentNumber: number, status: string, points: number, withOutlier = false) {
  return {
    segment_number: segmentNumber,
    start_time: segmentNumber,
    end_time: segmentNumber + 0.5,
    cadence_count: points,
    analysis_status: status,
    points: Array.from({ length: points }, (_, i) => ({
      time: segmentNumber + i * 0.001,
      normalized_flux: withOutlier && i === 0 ? 1.01 : 1.0,
      original_flux: 1000,
      source_index: segmentNumber * 1000 + i,
      is_high_outlier: withOutlier && i === 0,
      robust_score: withOutlier && i === 0 ? 6.2 : 0.1,
    })),
  };
}

const LIGHT_CURVE_FIXTURE = {
  target_name: "Pi Mensae",
  tic_id: 261136679,
  sector: 1,
  segments: [
    makeSegment(1, "valid", 10, true),
    makeSegment(2, "valid", 8, true),
    makeSegment(3, "insufficient_data", 3, false),
  ],
  gaps: [
    {
      before_segment_number: 1,
      after_segment_number: 2,
      start_time: 1.01,
      end_time: 2.0,
      duration_days: 0.99,
      duration_seconds: 85536,
      reasons: ["source_rows_rejected"],
      estimated_missing_cadences: 7,
    },
    {
      before_segment_number: 2,
      after_segment_number: 3,
      start_time: 2.008,
      end_time: 3.0,
      duration_days: 0.99,
      duration_seconds: 85536,
      reasons: ["observation_gap"],
      estimated_missing_cadences: 5,
    },
  ],
};

function mockFetchSuccess() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/light-curve")) {
        return {
          ok: true,
          json: async () => LIGHT_CURVE_FIXTURE,
        } as Response;
      }
      return {
        ok: true,
        json: async () => SUMMARY_FIXTURE,
      } as Response;
    }),
  );
}

beforeEach(() => {
  // jsdom has no ResizeObserver; the chart only needs a no-op stub.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PiMensaeDemoPage", () => {
  it("shows a loading state before data arrives", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<PiMensaeDemoPage />);
    expect(screen.getByRole("status")).toHaveTextContent(/loading/i);
  });

  it("shows a backend-error state when the backend is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    render(<PiMensaeDemoPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText(/backend unavailable/i)).toBeInTheDocument();
  });

  it("renders real summary values from the mocked API response", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);

    await waitFor(() => expect(screen.getByText("20,076")).toBeInTheDocument());
    expect(screen.getAllByText("18,264").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1,812").length).toBeGreaterThan(0);
    expect(screen.getAllByText("46").length).toBeGreaterThan(0);
    expect(screen.getAllByText("45").length).toBeGreaterThan(0);
  });

  it("shows the lower-side-detection-disabled safety message", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);
    await waitFor(() =>
      expect(screen.getByText(/lower-side \(downward\) outlier detection is disabled/i)).toBeInTheDocument(),
    );
  });

  it("shows the scientific limitations panel", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);
    await waitFor(() =>
      expect(screen.getByText("Scientific limitations")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("This dashboard does not identify or confirm planets."),
    ).toBeInTheDocument();
  });

  it("never shows a completed transit-search or machine-learning stage", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);
    await waitFor(() => expect(screen.getByText("Pipeline status")).toBeInTheDocument());

    const pipelineSection = screen.getByText("Pipeline status").closest("section");
    expect(pipelineSection).not.toBeNull();
    const completed = within(pipelineSection as HTMLElement).getAllByRole("listitem")[0];
    expect(completed).toHaveTextContent("Raw FITS parsed");

    expect(screen.getByText("Future pipeline stages (not yet implemented)")).toBeInTheDocument();
    expect(screen.getByText(/Transit search \(Box Least Squares\)/)).toBeInTheDocument();
    expect(screen.getByText(/Machine-learning classification/)).toBeInTheDocument();
  });

  it("renders the chart with an accessible label describing separate segments and outliers", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);
    await waitFor(() => expect(screen.getByRole("img")).toBeInTheDocument());
    const chart = screen.getByRole("img");
    expect(chart.getAttribute("aria-label")).toMatch(/3 independently plotted segments/);
    expect(chart.getAttribute("aria-label")).toMatch(/2 statistical high outliers/);
    expect(chart.getAttribute("aria-label")).toMatch(/not planet candidates/);
  });

  it("shows the 'not a planet candidate' outlier legend text", async () => {
    mockFetchSuccess();
    render(<PiMensaeDemoPage />);
    await waitFor(() =>
      expect(
        screen.getByText("Statistical high outlier — not a planet candidate"),
      ).toBeInTheDocument(),
    );
  });
});
