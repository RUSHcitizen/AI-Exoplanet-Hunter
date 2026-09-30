"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DemoLightCurveSegment } from "@/lib/api";
import { Axes, type PlotBox } from "@/components/chart/Axes";
import { binSeries, foldSegments, median, nearestIndex, niceTicks } from "@/lib/lightcurve";
import { formatPpmOffset } from "@/lib/format";
import type { TransitEphemeris } from "@/lib/reference";
import { useElementWidth } from "@/lib/useElementWidth";

/**
 * Cadences folded on a *published* ephemeris, centered on the predicted
 * mid-transit. This is a visualization of literature parameters applied
 * to the processed light curve -- the pipeline has performed no period
 * search or fit, and a dip here is not a detection by this project.
 */

const MARGIN = { top: 28, right: 14, bottom: 42, left: 58 };
const WINDOW_HOURS = 10;
const BIN_MINUTES = 20;

export function PhaseFoldChart({
  segments,
  ephemeris,
}: {
  segments: DemoLightCurveSegment[];
  ephemeris: TransitEphemeris;
}) {
  const [containerRef, width] = useElementWidth<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const height = width < 520 ? 280 : 360;

  const folded = useMemo(
    () => foldSegments(segments, ephemeris, WINDOW_HOURS),
    [segments, ephemeris],
  );
  const bins = useMemo(
    () => binSeries(folded.hours, folded.flux, BIN_MINUTES / 60, -WINDOW_HOURS, 5),
    [folded],
  );
  const baseline = useMemo(() => {
    const outside = folded.flux.filter(
      (_, i) => Math.abs(folded.hours[i]) > ephemeris.durationHours,
    );
    return outside.length ? median(outside) : 1;
  }, [folded, ephemeris]);

  // Scale to the binned signal (with room for the expected depth), not the
  // per-cadence scatter; cadences outside the range are drawn clipped.
  const extent = useMemo(() => {
    const values = bins.map((b) => b.flux);
    const expectedLow = baseline - (ephemeris.depthPpm * 1e-6 * 1.6);
    const lo = Math.min(expectedLow, ...values);
    const hi = Math.max(baseline + (baseline - expectedLow) * 0.8, ...values);
    const pad = (hi - lo) * 0.12;
    return { min: lo - pad, max: hi + pad };
  }, [bins, baseline, ephemeris]);

  const box: PlotBox = {
    left: MARGIN.left,
    top: MARGIN.top,
    width: Math.max(width - MARGIN.left - MARGIN.right, 1),
    height: height - MARGIN.top - MARGIN.bottom,
  };
  const xFor = (h: number) => box.left + ((h + WINDOW_HOURS) / (2 * WINDOW_HOURS)) * box.width;
  const yFor = (f: number) =>
    box.top + box.height - ((f - extent.min) / (extent.max - extent.min)) * box.height;

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.beginPath();
    ctx.rect(box.left, box.top, box.width, box.height);
    ctx.clip();
    ctx.fillStyle = "rgba(57, 135, 229, 0.28)";
    for (let i = 0; i < folded.hours.length; i += 1) {
      ctx.fillRect(xFor(folded.hours[i]) - 0.8, yFor(folded.flux[i]) - 0.8, 1.6, 1.6);
    }
    ctx.restore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folded, width, height, extent]);

  const [hover, setHover] = useState<number | null>(null);
  const binXs = useMemo(() => bins.map((b) => b.x), [bins]);
  const hovered = hover !== null ? bins[hover] : null;

  const halfDuration = ephemeris.durationHours / 2;
  const pathD = bins
    .map((b, i) => `${i === 0 ? "M" : "L"}${xFor(b.x).toFixed(1)},${yFor(b.flux).toFixed(1)}`)
    .join(" ");

  return (
    <div className="flex flex-col gap-3">
      <div ref={containerRef} className="relative w-full" style={{ height }}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`Phase-folded light curve: ${folded.hours.length.toLocaleString()} cadences within ${WINDOW_HOURS} hours of a predicted ${ephemeris.planet} mid-transit, folded on the published period of ${ephemeris.periodDays} days, with ${bins.length} ${BIN_MINUTES}-minute median bins.`}
          className="absolute inset-0"
        />
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          className="absolute inset-0"
          onPointerMove={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const x = event.clientX - rect.left;
            const hours = ((x - box.left) / box.width) * 2 * WINDOW_HOURS - WINDOW_HOURS;
            const index = nearestIndex(binXs, hours);
            setHover(index >= 0 && Math.abs(xFor(binXs[index]) - x) < 20 ? index : null);
          }}
          onPointerLeave={() => setHover(null)}
        >
          <Axes
            box={box}
            xTicks={niceTicks(-WINDOW_HOURS, WINDOW_HOURS, width < 520 ? 4 : 8)}
            yTicks={niceTicks(extent.min, extent.max, 7)}
            xFor={xFor}
            yFor={yFor}
            formatX={(v) => (v > 0 ? `+${v}` : v < 0 ? `−${Math.abs(v)}` : "0")}
            formatY={(f) => {
              const ppm = Math.round((f - 1) * 1e6);
              return ppm === 0 ? "0" : `${ppm > 0 ? "+" : "−"}${Math.abs(ppm)}`;
            }}
            xTitle={`Hours from predicted mid-transit (P = ${ephemeris.periodDays} d)`}
            yTitle="Relative flux (ppm)"
          />
          <g aria-hidden="true">
            <rect
              x={xFor(-halfDuration)}
              y={box.top}
              width={xFor(halfDuration) - xFor(-halfDuration)}
              height={box.height}
              fill="#199e70"
              fillOpacity={0.1}
            />
            <line
              x1={xFor(0)}
              x2={xFor(0)}
              y1={box.top}
              y2={box.top + box.height}
              stroke="#199e70"
              strokeOpacity={0.6}
            />
            <line
              x1={box.left}
              x2={box.left + box.width}
              y1={yFor(baseline - ephemeris.depthPpm * 1e-6)}
              y2={yFor(baseline - ephemeris.depthPpm * 1e-6)}
              stroke="#199e70"
              strokeOpacity={0.55}
              strokeDasharray="4,4"
            />
            <text
              x={box.left + box.width - 4}
              y={yFor(baseline - ephemeris.depthPpm * 1e-6) - 6}
              textAnchor="end"
              fontSize={10.5}
              fill="var(--kind-reference)"
            >
              Published depth ≈ {ephemeris.depthPpm} ppm
            </text>
            <path d={pathD} fill="none" stroke="#b7d3f6" strokeWidth={2} strokeLinejoin="round" />
            {hovered && (
              <circle
                cx={xFor(hovered.x)}
                cy={yFor(hovered.flux)}
                r={4.5}
                fill="none"
                stroke="#f3f3f1"
                strokeWidth={1.5}
              />
            )}
          </g>
        </svg>
        {hovered && (
          <div
            className="pointer-events-none absolute z-10 rounded-lg border border-line-strong bg-surface-3/95 px-3 py-2 text-xs shadow-xl tabular"
            style={{ left: Math.min(xFor(hovered.x) + 12, width - 190), top: box.top + 4 }}
          >
            <p className="text-sm font-semibold text-ink-primary">
              {formatPpmOffset(hovered.flux)}
            </p>
            <p className="text-ink-muted">
              {hovered.x >= 0 ? "+" : "−"}
              {Math.abs(hovered.x).toFixed(2)} h · median of {hovered.count} cadences
            </p>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-secondary">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-2 w-2 rounded-full bg-series-observation/70" />
          Folded cadences (outliers excluded)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded bg-series-binned" />
          {BIN_MINUTES}-min median bin (calculated)
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-3 w-3 rounded-sm bg-series-reference/35" />
          Published transit duration and depth (literature)
        </span>
      </div>
    </div>
  );
}
