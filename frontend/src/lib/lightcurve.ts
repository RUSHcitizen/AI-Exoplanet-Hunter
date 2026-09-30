/**
 * Pure, display-side helpers for the light-curve explorer.
 *
 * Everything here is *calculated for display* from the backend's
 * already-processed Phase 3D output -- binning, a robust scatter summary,
 * and folding on a published ephemeris. None of it feeds back into the
 * pipeline, and none of it is a detection: the UI labels each derived
 * quantity as "Calculated" (or "Literature" for the ephemeris itself).
 *
 * Invariant shared by every function: segments are never merged. Bins,
 * medians, and coverage are always computed within one Phase 3B segment,
 * so nothing ever averages or connects across an observation gap.
 */

import type { DemoLightCurvePoint, DemoLightCurveSegment } from "@/lib/api";
import type { TransitEphemeris } from "@/lib/reference";

/** Median of a numeric array (copied, not mutated); NaN when empty. */
export function median(values: number[]): number {
  if (values.length === 0) return Number.NaN;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function isPlottable(point: DemoLightCurvePoint): point is DemoLightCurvePoint & {
  normalized_flux: number;
} {
  return point.normalized_flux !== null && Number.isFinite(point.normalized_flux);
}

/** A flattened, time-ordered view of every plotted cadence, for fast
 * nearest-point lookup (hover, keyboard stepping). */
export interface FlatSeries {
  time: Float64Array;
  flux: Float64Array;
  segmentIndex: Int32Array;
  pointIndex: Int32Array;
  length: number;
}

export function flattenSegments(segments: DemoLightCurveSegment[]): FlatSeries {
  let count = 0;
  for (const segment of segments) {
    for (const point of segment.points) if (isPlottable(point)) count += 1;
  }
  const time = new Float64Array(count);
  const flux = new Float64Array(count);
  const segmentIndex = new Int32Array(count);
  const pointIndex = new Int32Array(count);
  let i = 0;
  segments.forEach((segment, s) => {
    segment.points.forEach((point, p) => {
      if (!isPlottable(point)) return;
      time[i] = point.time;
      flux[i] = point.normalized_flux;
      segmentIndex[i] = s;
      pointIndex[i] = p;
      i += 1;
    });
  });
  return { time, flux, segmentIndex, pointIndex, length: count };
}

/** Index of the element of ascending `values` closest to `target`, or -1. */
export function nearestIndex(values: ArrayLike<number>, target: number): number {
  const n = values.length;
  if (n === 0) return -1;
  let lo = 0;
  let hi = n - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  if (lo > 0 && Math.abs(values[lo - 1] - target) <= Math.abs(values[lo] - target)) {
    return lo - 1;
  }
  return lo;
}

export interface Bin {
  /** Center of the bin (same unit as the input x values). */
  x: number;
  /** Median normalized flux of the cadences in the bin. */
  flux: number;
  count: number;
}

/** Median-bin one sequence of (x, flux) pairs in fixed-width bins
 * anchored at `origin`. Bins with fewer than `minCount` members are
 * dropped rather than shown as a misleadingly precise value. */
export function binSeries(
  xs: number[],
  fluxes: number[],
  width: number,
  origin: number,
  minCount = 3,
): Bin[] {
  const buckets = new Map<number, number[]>();
  for (let i = 0; i < xs.length; i += 1) {
    const key = Math.floor((xs[i] - origin) / width);
    const bucket = buckets.get(key);
    if (bucket) bucket.push(fluxes[i]);
    else buckets.set(key, [fluxes[i]]);
  }
  const bins: Bin[] = [];
  for (const [key, values] of [...buckets.entries()].sort((a, b) => a[0] - b[0])) {
    if (values.length < minCount) continue;
    bins.push({ x: origin + (key + 0.5) * width, flux: median(values), count: values.length });
  }
  return bins;
}

export interface SegmentBins {
  segmentNumber: number;
  bins: Bin[];
}

/** Per-segment time bins of the non-outlier cadences. Never crosses a gap. */
export function binSegments(segments: DemoLightCurveSegment[], widthDays: number): SegmentBins[] {
  return segments.map((segment) => {
    const xs: number[] = [];
    const fluxes: number[] = [];
    for (const point of segment.points) {
      if (!isPlottable(point) || point.is_high_outlier) continue;
      xs.push(point.time);
      fluxes.push(point.normalized_flux);
    }
    return {
      segmentNumber: segment.segment_number,
      bins: binSeries(xs, fluxes, widthDays, segment.start_time),
    };
  });
}

/**
 * Robust per-cadence scatter, in ppm: 1.4826 × MAD of normalized flux,
 * computed within each segment that Phase 3D analyzed ("valid") and
 * excluding flagged outliers, then summarized as the cadence-weighted
 * median across segments. The same robust-scale convention Phase 3D
 * uses, reported as a display statistic only.
 */
export function robustScatterPpm(segments: DemoLightCurveSegment[]): number | null {
  const perSegment: { scale: number; weight: number }[] = [];
  for (const segment of segments) {
    if (segment.analysis_status !== "valid") continue;
    const values = segment.points
      .filter((p) => isPlottable(p) && !p.is_high_outlier)
      .map((p) => p.normalized_flux as number);
    if (values.length < 5) continue;
    const center = median(values);
    const mad = median(values.map((v) => Math.abs(v - center)));
    perSegment.push({ scale: 1.4826 * mad * 1e6, weight: values.length });
  }
  if (perSegment.length === 0) return null;
  perSegment.sort((a, b) => a.scale - b.scale);
  const total = perSegment.reduce((sum, s) => sum + s.weight, 0);
  let running = 0;
  for (const entry of perSegment) {
    running += entry.weight;
    if (running >= total / 2) return entry.scale;
  }
  return perSegment[perSegment.length - 1].scale;
}

export interface PredictedTransit {
  epoch: number;
  midTime: number;
  windowStart: number;
  windowEnd: number;
  /** Retained, plotted cadences that fall inside the predicted window. */
  cadencesInWindow: number;
  /** Fraction of the window with data, relative to the nominal cadence. */
  coverage: number;
}

/**
 * Transit mid-times predicted by a published ephemeris inside
 * [start, end], with how much of each predicted window this observation
 * actually covers. A prediction, not a detection.
 */
export function predictTransits(
  ephemeris: TransitEphemeris,
  start: number,
  end: number,
  flat: FlatSeries,
  cadenceDays: number | null,
): PredictedTransit[] {
  const halfWindow = ephemeris.durationHours / 48;
  // "+ 0" normalizes -0 (from ceil of a small negative) to 0.
  const first = Math.ceil((start - halfWindow - ephemeris.epochBtjd) / ephemeris.periodDays) + 0;
  const last = Math.floor((end + halfWindow - ephemeris.epochBtjd) / ephemeris.periodDays);
  const transits: PredictedTransit[] = [];
  for (let epoch = first; epoch <= last; epoch += 1) {
    const midTime = ephemeris.epochBtjd + epoch * ephemeris.periodDays;
    const windowStart = midTime - halfWindow;
    const windowEnd = midTime + halfWindow;
    let count = 0;
    let i = lowerBound(flat.time, windowStart);
    while (i < flat.length && flat.time[i] <= windowEnd) {
      count += 1;
      i += 1;
    }
    const expected = cadenceDays && cadenceDays > 0 ? (windowEnd - windowStart) / cadenceDays : 0;
    transits.push({
      epoch,
      midTime,
      windowStart,
      windowEnd,
      cadencesInWindow: count,
      coverage: expected > 0 ? Math.min(1, count / expected) : 0,
    });
  }
  return transits;
}

export function lowerBound(values: ArrayLike<number>, target: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Hours from the nearest predicted mid-transit for time `t` (days). */
export function phaseHours(t: number, ephemeris: TransitEphemeris): number {
  const cycles = (t - ephemeris.epochBtjd) / ephemeris.periodDays;
  return (cycles - Math.round(cycles)) * ephemeris.periodDays * 24;
}

export interface FoldedSeries {
  hours: number[];
  flux: number[];
}

/** Non-outlier cadences within ±`windowHours` of a predicted mid-transit. */
export function foldSegments(
  segments: DemoLightCurveSegment[],
  ephemeris: TransitEphemeris,
  windowHours: number,
): FoldedSeries {
  const hours: number[] = [];
  const flux: number[] = [];
  for (const segment of segments) {
    for (const point of segment.points) {
      if (!isPlottable(point) || point.is_high_outlier) continue;
      const h = phaseHours(point.time, ephemeris);
      if (Math.abs(h) > windowHours) continue;
      hours.push(h);
      flux.push(point.normalized_flux);
    }
  }
  return { hours, flux };
}

/** Evenly spaced, human-friendly axis ticks covering [min, max]. */
export function niceTicks(min: number, max: number, target = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return [min];
  const rawStep = (max - min) / Math.max(target, 1);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const step = (residual >= 7 ? 10 : residual >= 3 ? 5 : residual >= 1.5 ? 2 : 1) * magnitude;
  const ticks: number[] = [];
  const start = Math.ceil(min / step) * step;
  for (let v = start; v <= max + step * 1e-9; v += step) {
    ticks.push(Number(v.toFixed(12)));
  }
  return ticks;
}

/** Decimal places needed to distinguish consecutive ticks. */
export function tickPrecision(ticks: number[]): number {
  if (ticks.length < 2) return 2;
  const step = Math.abs(ticks[1] - ticks[0]);
  return Math.max(0, Math.min(6, -Math.floor(Math.log10(step))));
}

export interface FluxExtent {
  min: number;
  max: number;
}

/** Flux range of all plotted cadences (outliers included, so a flagged
 * point is never silently clipped out of view), padded 8%. */
export function fluxExtent(flat: FlatSeries, from = 0, to = flat.length): FluxExtent {
  let min = Infinity;
  let max = -Infinity;
  for (let i = from; i < to; i += 1) {
    const f = flat.flux[i];
    if (f < min) min = f;
    if (f > max) max = f;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0.999, max: 1.001 };
  const pad = (max - min) * 0.08 || 0.0005;
  return { min: min - pad, max: max + pad };
}
