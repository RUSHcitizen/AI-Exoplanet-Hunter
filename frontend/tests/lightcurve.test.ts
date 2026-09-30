import { describe, expect, it } from "vitest";
import type { DemoLightCurveSegment } from "@/lib/api";
import {
  binSegments,
  binSeries,
  flattenSegments,
  fluxExtent,
  foldSegments,
  median,
  nearestIndex,
  niceTicks,
  phaseHours,
  predictTransits,
  robustScatterPpm,
} from "@/lib/lightcurve";
import type { TransitEphemeris } from "@/lib/reference";

function segment(
  number: number,
  times: number[],
  fluxes: (number | null)[],
  options: { status?: string; outlierAt?: number } = {},
): DemoLightCurveSegment {
  return {
    segment_number: number,
    start_time: times[0],
    end_time: times[times.length - 1],
    cadence_count: times.length,
    analysis_status: options.status ?? "valid",
    points: times.map((time, i) => ({
      time,
      normalized_flux: fluxes[i],
      original_flux: 1000,
      source_index: number * 1000 + i,
      is_high_outlier: options.outlierAt === i,
      robust_score: 0,
    })),
  };
}

const EPHEMERIS: TransitEphemeris = {
  planet: "test b",
  periodDays: 2,
  epochBtjd: 10,
  durationHours: 2.4,
  depthPpm: 500,
  source: { label: "test", href: "https://example.org" },
};

describe("median", () => {
  it("handles odd, even, and empty inputs without mutating", () => {
    const values = [3, 1, 2];
    expect(median(values)).toBe(2);
    expect(values).toEqual([3, 1, 2]);
    expect(median([4, 1, 3, 2])).toBe(2.5);
    expect(median([])).toBeNaN();
  });
});

describe("flattenSegments / nearestIndex", () => {
  it("skips null flux and keeps time order across segments", () => {
    const flat = flattenSegments([
      segment(1, [0, 1, 2], [1, null, 1]),
      segment(2, [10, 11], [1, 1]),
    ]);
    expect(flat.length).toBe(4);
    expect(Array.from(flat.time)).toEqual([0, 2, 10, 11]);
    expect(Array.from(flat.segmentIndex)).toEqual([0, 0, 1, 1]);
    expect(Array.from(flat.pointIndex)).toEqual([0, 2, 0, 1]);
  });

  it("finds the closest element, preferring the earlier one on ties", () => {
    const values = [0, 2, 10, 11];
    expect(nearestIndex(values, -5)).toBe(0);
    expect(nearestIndex(values, 1)).toBe(0);
    expect(nearestIndex(values, 5.9)).toBe(1);
    expect(nearestIndex(values, 7)).toBe(2);
    expect(nearestIndex(values, 99)).toBe(3);
    expect(nearestIndex([], 1)).toBe(-1);
  });
});

describe("binning", () => {
  it("takes the median within each bin and drops sparse bins", () => {
    const bins = binSeries([0, 0.1, 0.2, 0.3, 1.1], [1, 2, 9, 3, 5], 1, 0, 3);
    expect(bins).toEqual([{ x: 0.5, flux: 2.5, count: 4 }]);
  });

  it("never mixes cadences from different segments into one bin", () => {
    // Two segments whose points would share a bin if binned globally.
    const bins = binSegments(
      [
        segment(1, [0, 0.001, 0.002], [1, 1, 1]),
        segment(2, [0.003, 0.004, 0.005], [2, 2, 2]),
      ],
      1,
    );
    expect(bins).toHaveLength(2);
    expect(bins[0].bins[0].flux).toBe(1);
    expect(bins[1].bins[0].flux).toBe(2);
  });

  it("excludes flagged high outliers from bins", () => {
    const bins = binSegments([segment(1, [0, 0.1, 0.2, 0.3], [1, 1, 1, 50], { outlierAt: 3 })], 1);
    expect(bins[0].bins[0]).toMatchObject({ flux: 1, count: 3 });
  });
});

describe("robustScatterPpm", () => {
  it("uses 1.4826 × MAD of analyzed segments, ignoring outliers and unanalyzed segments", () => {
    const flux = [1 - 1e-4, 1, 1 + 1e-4, 1 - 1e-4, 1, 1 + 1e-4, 5];
    const result = robustScatterPpm([
      segment(1, flux.map((_, i) => i), flux, { outlierAt: 6 }),
      segment(2, [100, 101, 102], [9, 9, 9], { status: "insufficient_data" }),
    ]);
    // MAD of [-1,0,1,-1,0,1]e-4 around 0 is 1e-4 → 148.26 ppm.
    expect(result).toBeCloseTo(148.26, 1);
  });

  it("returns null when no segment was analyzed", () => {
    expect(robustScatterPpm([segment(1, [0, 1], [1, 1], { status: "insufficient_data" })])).toBeNull();
  });
});

describe("ephemeris helpers", () => {
  it("measures signed hours from the nearest predicted mid-transit", () => {
    expect(phaseHours(10, EPHEMERIS)).toBeCloseTo(0);
    expect(phaseHours(12.25, EPHEMERIS)).toBeCloseTo(6);
    expect(phaseHours(11.75, EPHEMERIS)).toBeCloseTo(-6);
  });

  it("predicts every transit inside the span and reports data coverage", () => {
    const cadence = 0.01;
    const times: number[] = [];
    for (let t = 9.5; t < 12.5; t += cadence) times.push(Number(t.toFixed(4)));
    const flat = flattenSegments([segment(1, times, times.map(() => 1))]);
    const transits = predictTransits(EPHEMERIS, 9.5, 14.9, flat, cadence);
    expect(transits.map((t) => t.epoch)).toEqual([0, 1, 2]);
    expect(transits[0].coverage).toBeGreaterThan(0.95);
    expect(transits[1].coverage).toBeGreaterThan(0.95);
    // Epoch 2 (t = 14) has no data at all.
    expect(transits[2].cadencesInWindow).toBe(0);
    expect(transits[2].coverage).toBe(0);
  });

  it("folds only non-outlier cadences within the window", () => {
    const folded = foldSegments(
      [segment(1, [10, 10.1, 11, 12.02], [0.9, 1, 1, 7], { outlierAt: 3 })],
      EPHEMERIS,
      3,
    );
    expect(folded.hours.map((h) => Number(h.toFixed(2)))).toEqual([0, 2.4]);
    expect(folded.flux).toEqual([0.9, 1]);
  });
});

describe("axis helpers", () => {
  it("produces round, evenly spaced ticks inside the range", () => {
    expect(niceTicks(1325.3, 1353.2, 5)).toEqual([1330, 1335, 1340, 1345, 1350]);
    expect(niceTicks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
  });

  it("pads the flux extent and never returns an empty range", () => {
    const flat = flattenSegments([segment(1, [0, 1], [1, 1])]);
    const extent = fluxExtent(flat);
    expect(extent.max).toBeGreaterThan(extent.min);
    expect(fluxExtent(flattenSegments([]))).toEqual({ min: 0.999, max: 1.001 });
  });
});
