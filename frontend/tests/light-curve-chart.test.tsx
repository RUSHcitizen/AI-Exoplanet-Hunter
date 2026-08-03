import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LightCurveChart } from "@/components/LightCurveChart";
import type { DemoGap, DemoLightCurveSegment } from "@/lib/api";

function makeSegment(segmentNumber: number, points: number, outlierAt: number | null): DemoLightCurveSegment {
  return {
    segment_number: segmentNumber,
    start_time: segmentNumber,
    end_time: segmentNumber + 0.5,
    cadence_count: points,
    analysis_status: "valid",
    points: Array.from({ length: points }, (_, i) => ({
      time: segmentNumber + i * 0.001,
      normalized_flux: 1.0,
      original_flux: 1000,
      source_index: segmentNumber * 1000 + i,
      is_high_outlier: outlierAt === i,
      robust_score: outlierAt === i ? 6.1 : 0.2,
    })),
  };
}

const SEGMENTS: DemoLightCurveSegment[] = [
  makeSegment(1, 5, 2),
  makeSegment(2, 5, null),
  makeSegment(3, 5, 1),
];

const GAPS: DemoGap[] = [
  {
    before_segment_number: 1,
    after_segment_number: 2,
    start_time: 1.005,
    end_time: 2,
    duration_days: 0.995,
    duration_seconds: 85968,
    reasons: ["source_rows_rejected"],
    estimated_missing_cadences: 3,
  },
  {
    before_segment_number: 2,
    after_segment_number: 3,
    start_time: 2.005,
    end_time: 3,
    duration_days: 0.995,
    duration_seconds: 85968,
    reasons: ["observation_gap"],
    estimated_missing_cadences: 2,
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
});

describe("LightCurveChart", () => {
  it("renders one SVG outlier marker per flagged high-outlier point, not per segment or per point", () => {
    render(<LightCurveChart segments={SEGMENTS} gaps={GAPS} />);
    const svg = document.querySelector("svg");
    expect(svg).not.toBeNull();
    const markers = svg!.querySelectorAll("polygon");
    expect(markers.length).toBe(2);
  });

  it("renders one dashed gap-boundary indicator per gap, matching segment count minus one", () => {
    render(<LightCurveChart segments={SEGMENTS} gaps={GAPS} />);
    const svg = document.querySelector("svg");
    const gapLines = svg!.querySelectorAll('line[stroke-dasharray]');
    expect(gapLines.length).toBe(GAPS.length);
    expect(SEGMENTS.length).toBe(GAPS.length + 1);
  });

  it("never draws a connecting polyline across segments (canvas-only point rendering)", () => {
    render(<LightCurveChart segments={SEGMENTS} gaps={GAPS} />);
    const svg = document.querySelector("svg");
    expect(svg!.querySelectorAll("polyline")).toHaveLength(0);
    expect(document.querySelector("canvas")).not.toBeNull();
  });

  it("includes the required outlier legend text", () => {
    render(<LightCurveChart segments={SEGMENTS} gaps={GAPS} />);
    expect(
      screen.getByText("Statistical high outlier — not a planet candidate"),
    ).toBeInTheDocument();
  });

  it("provides an accessible chart summary mentioning segments, gaps, and outliers", () => {
    render(<LightCurveChart segments={SEGMENTS} gaps={GAPS} />);
    expect(screen.getByText(/Chart summary:/)).toHaveTextContent("3 independently plotted");
    expect(screen.getByText(/Chart summary:/)).toHaveTextContent("2 gaps");
  });
});
