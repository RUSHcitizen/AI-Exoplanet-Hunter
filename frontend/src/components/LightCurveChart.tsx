"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DemoGap, DemoLightCurvePoint, DemoLightCurveSegment } from "@/lib/api";
import { Axes, type PlotBox } from "@/components/chart/Axes";
import {
  binSegments,
  flattenSegments,
  fluxExtent,
  lowerBound,
  nearestIndex,
  niceTicks,
  tickPrecision,
  type PredictedTransit,
} from "@/lib/lightcurve";
import { formatFixed, formatPpmOffset } from "@/lib/format";
import { BTJD_OFFSET } from "@/lib/reference";
import { useElementWidth } from "@/lib/useElementWidth";

/**
 * Gap-aware normalized light-curve chart.
 *
 * Rendering: the ~20k cadences are painted onto one <canvas> (cheap),
 * never as individual DOM nodes. Axes, gap boundaries, predicted transit
 * windows, outlier markers, the zoom brush and the hover crosshair live
 * in a light SVG overlay on top. The canvas repaints only when the data,
 * zoom, size, or display options change -- never on hover.
 *
 * Every segment is drawn from its own points only: there is no code path
 * that connects one segment's last point (or bin) to the next segment's
 * first, so a Phase 3B gap can never be drawn as a connecting line. The
 * horizontal axis is literal TIME, so a real observation gap shows up
 * honestly as blank space.
 */

export type TimeDomain = [number, number];

const ANALYZED_POINT_COLOR = "rgba(57, 135, 229, ALPHA)";
const UNANALYZED_POINT_COLOR = "rgba(141, 140, 134, ALPHA)";
const BINNED_COLOR = "#b7d3f6";
const OUTLIER_COLOR = "#d95926";
const REFERENCE_COLOR = "#199e70";
const GAP_LINE_COLOR = "rgba(255, 255, 255, 0.22)";

const MARGIN = { top: 28, right: 14, bottom: 42, left: 58 };
const MIN_ZOOM_SPAN_DAYS = 0.02;

interface OutlierMarker {
  time: number;
  flux: number;
  segmentNumber: number;
  sourceIndex: number;
  robustScore: number | null;
}

function collectOutliers(segments: DemoLightCurveSegment[]): OutlierMarker[] {
  const outliers: OutlierMarker[] = [];
  for (const segment of segments) {
    for (const point of segment.points) {
      if (point.is_high_outlier && point.normalized_flux !== null) {
        outliers.push({
          time: point.time,
          flux: point.normalized_flux,
          segmentNumber: segment.segment_number,
          sourceIndex: point.source_index,
          robustScore: point.robust_score,
        });
      }
    }
  }
  return outliers;
}

function formatPpmTick(flux: number): string {
  const ppm = Math.round((flux - 1) * 1e6);
  if (ppm === 0) return "0";
  return `${ppm > 0 ? "+" : "−"}${Math.abs(ppm).toLocaleString("en-US")}`;
}

function describeStatus(status: string): string {
  if (status === "valid") return "analyzed for outliers";
  if (status === "insufficient_data") return "too short for outlier analysis";
  return status.replaceAll("_", " ");
}

export function LightCurveChart({
  segments,
  gaps,
  domain = null,
  onDomainChange,
  showBinned = true,
  binMinutes = 30,
  showOutliers = true,
  transits = [],
  transitLabel = "Predicted transit window",
}: {
  segments: DemoLightCurveSegment[];
  gaps: DemoGap[];
  domain?: TimeDomain | null;
  onDomainChange?: (domain: TimeDomain | null) => void;
  showBinned?: boolean;
  binMinutes?: number;
  showOutliers?: boolean;
  transits?: PredictedTransit[];
  transitLabel?: string;
}) {
  const [containerRef, width] = useElementWidth<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const height = width < 520 ? 280 : 360;

  const flat = useMemo(() => flattenSegments(segments), [segments]);
  const outliers = useMemo(() => collectOutliers(segments), [segments]);
  const bins = useMemo(
    () => (showBinned ? binSegments(segments, binMinutes / 1440) : []),
    [segments, showBinned, binMinutes],
  );
  const totalPoints = useMemo(
    () => segments.reduce((sum, segment) => sum + segment.points.length, 0),
    [segments],
  );

  const fullDomain = useMemo<TimeDomain>(() => {
    if (flat.length === 0) return [0, 1];
    const first = flat.time[0];
    const last = flat.time[flat.length - 1];
    return last > first ? [first, last] : [first - 0.5, last + 0.5];
  }, [flat]);
  const [d0, d1] = domain ?? fullDomain;
  const isZoomed = domain !== null;

  const i0 = lowerBound(flat.time, d0);
  const i1 = lowerBound(flat.time, d1 + 1e-9);
  const extent = useMemo(() => fluxExtent(flat, i0, Math.max(i1, i0)), [flat, i0, i1]);

  const box: PlotBox = {
    left: MARGIN.left,
    top: MARGIN.top,
    width: Math.max(width - MARGIN.left - MARGIN.right, 1),
    height: height - MARGIN.top - MARGIN.bottom,
  };
  const span = d1 - d0 || 1;
  const fluxSpan = extent.max - extent.min || 1;
  const xFor = (t: number) => box.left + ((t - d0) / span) * box.width;
  const yFor = (f: number) => box.top + box.height - ((f - extent.min) / fluxSpan) * box.height;
  const timeAt = (x: number) => d0 + ((x - box.left) / box.width) * span;

  const xTicks = niceTicks(d0, d1, Math.max(3, Math.floor(box.width / 90)));
  const xPrecision = tickPrecision(xTicks);
  const yTicks = niceTicks(extent.min, extent.max, height < 320 ? 5 : 7);

  // --- Canvas: points and per-segment bins ----------------------------------
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
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

    // Dense views get small, faint points; zoomed-in views get larger ones.
    const density = (i1 - i0) / box.width;
    const size = density > 6 ? 1.3 : density > 1.5 ? 1.8 : 2.6;
    const alpha = showBinned ? (density > 6 ? 0.35 : 0.5) : density > 6 ? 0.55 : 0.8;
    const analyzed = ANALYZED_POINT_COLOR.replace("ALPHA", String(alpha));
    const unanalyzed = UNANALYZED_POINT_COLOR.replace("ALPHA", String(alpha));

    for (let i = i0; i < i1; i += 1) {
      const segment = segments[flat.segmentIndex[i]];
      if (showOutliers && segment.points[flat.pointIndex[i]].is_high_outlier) continue;
      ctx.fillStyle = segment.analysis_status === "valid" ? analyzed : unanalyzed;
      ctx.fillRect(xFor(flat.time[i]) - size / 2, yFor(flat.flux[i]) - size / 2, size, size);
    }

    if (showBinned) {
      ctx.strokeStyle = BINNED_COLOR;
      ctx.fillStyle = BINNED_COLOR;
      ctx.lineWidth = 1.4;
      ctx.globalAlpha = 0.9;
      ctx.lineJoin = "round";
      for (const segment of bins) {
        const visible = segment.bins.filter((b) => b.x >= d0 - 0.1 && b.x <= d1 + 0.1);
        if (visible.length === 0) continue;
        ctx.beginPath();
        visible.forEach((bin, index) => {
          const x = xFor(bin.x);
          const y = yFor(bin.flux);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        if (visible.length === 1 || box.width / visible.length > 14) {
          for (const bin of visible) {
            ctx.beginPath();
            ctx.arc(xFor(bin.x), yFor(bin.flux), 2.2, 0, Math.PI * 2);
            ctx.fill();
          }
        }
      }
    }
    ctx.restore();
    // xFor/yFor are pure functions of the values listed below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments, flat, bins, width, height, d0, d1, i0, i1, extent, showBinned, showOutliers]);

  // --- Interaction: hover crosshair, drag-to-zoom, keyboard stepping -------
  const [cursor, setCursor] = useState<number | null>(null);
  const [brush, setBrush] = useState<{ from: number; to: number } | null>(null);
  const dragStart = useRef<number | null>(null);

  const cursorValid = cursor !== null && cursor >= 0 && cursor < flat.length;
  const active = cursorValid ? cursor : null;
  const activePoint: DemoLightCurvePoint | null =
    active !== null ? segments[flat.segmentIndex[active]].points[flat.pointIndex[active]] : null;
  const activeSegment = active !== null ? segments[flat.segmentIndex[active]] : null;

  function localX(event: React.PointerEvent<SVGSVGElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    return event.clientX - rect.left;
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    const x = localX(event);
    if (dragStart.current !== null) {
      setBrush({ from: dragStart.current, to: Math.min(Math.max(x, box.left), box.left + box.width) });
    }
    if (x < box.left || x > box.left + box.width || i1 <= i0) {
      setCursor(null);
      return;
    }
    const index = nearestIndex(flat.time.subarray(i0, i1), timeAt(x));
    const candidate = index + i0;
    // Inside a gap the nearest cadence may be far away: show nothing
    // rather than implying data exists where it doesn't.
    setCursor(Math.abs(xFor(flat.time[candidate]) - x) <= 24 ? candidate : null);
  }

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    // A tap on touch screens has no preceding hover, so inspect on press too.
    handlePointerMove(event);
    if (!onDomainChange || event.button !== 0) return;
    const x = localX(event);
    if (x < box.left || x > box.left + box.width) return;
    dragStart.current = x;
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function handlePointerUp() {
    const start = dragStart.current;
    dragStart.current = null;
    if (start === null || !brush || !onDomainChange) {
      setBrush(null);
      return;
    }
    const a = timeAt(Math.min(brush.from, brush.to));
    const b = timeAt(Math.max(brush.from, brush.to));
    setBrush(null);
    if (Math.abs(brush.to - brush.from) > 8 && b - a >= MIN_ZOOM_SPAN_DAYS) {
      onDomainChange([a, b]);
    }
  }

  function zoomAround(center: number, factor: number) {
    if (!onDomainChange) return;
    const half = Math.max(((d1 - d0) * factor) / 2, MIN_ZOOM_SPAN_DAYS / 2);
    const lo = Math.max(fullDomain[0], center - half);
    const hi = Math.min(fullDomain[1], center + half);
    if (hi - lo >= fullDomain[1] - fullDomain[0] - 1e-9) onDomainChange(null);
    else onDomainChange([lo, hi]);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (flat.length === 0) return;
    const step = event.shiftKey ? 30 : 1;
    const current = active ?? (i1 > i0 ? i0 : 0);
    let next: number | null = null;
    switch (event.key) {
      case "ArrowRight":
        next = Math.min(current + (active === null ? 0 : step), flat.length - 1);
        break;
      case "ArrowLeft":
        next = Math.max(current - (active === null ? 0 : step), 0);
        break;
      case "Home":
        next = i0;
        break;
      case "End":
        next = Math.max(i1 - 1, i0);
        break;
      case "+":
      case "=":
        zoomAround(active !== null ? flat.time[active] : (d0 + d1) / 2, 0.5);
        break;
      case "-":
      case "_":
        zoomAround(active !== null ? flat.time[active] : (d0 + d1) / 2, 2);
        break;
      case "0":
      case "Escape":
        onDomainChange?.(null);
        setCursor(null);
        break;
      default:
        return;
    }
    event.preventDefault();
    if (next !== null) {
      setCursor(next);
      const t = flat.time[next];
      if (onDomainChange && (t < d0 || t > d1)) {
        const half = (d1 - d0) / 2;
        onDomainChange([t - half, t + half]);
      }
    }
  }

  const activeTransit =
    activePoint !== null
      ? transits.find((t) => activePoint.time >= t.windowStart && activePoint.time <= t.windowEnd)
      : undefined;

  const tooltipLeft =
    active !== null ? Math.min(Math.max(xFor(flat.time[active]) + 14, 8), width - 236) : 0;
  const flipTooltip = active !== null && xFor(flat.time[active]) > width - 250;

  const summary =
    `Normalized light curve: ${segments.length} independently plotted segments, ` +
    `${totalPoints.toLocaleString()} cadences, ${outliers.length} statistical high outliers ` +
    `marked (not planet candidates), zero low outliers (lower-side detection disabled).`;

  return (
    <div className="flex flex-col gap-3">
      <div
        ref={containerRef}
        role="application"
        tabIndex={0}
        aria-roledescription="interactive chart"
        aria-label="Light curve explorer. Arrow keys step between cadences (Shift for 30), plus and minus zoom, 0 or Escape resets the zoom."
        onKeyDown={handleKeyDown}
        onBlur={() => setCursor(null)}
        className="relative w-full touch-pan-y select-none rounded-lg"
        style={{ height }}
      >
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={summary}
          className="absolute inset-0"
        />
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="absolute inset-0 cursor-crosshair"
          width={width}
          height={height}
          onPointerMove={handlePointerMove}
          onPointerDown={handlePointerDown}
          onPointerUp={handlePointerUp}
          onPointerLeave={() => {
            if (dragStart.current === null) setCursor(null);
          }}
          onDoubleClick={() => onDomainChange?.(null)}
        >
          <Axes
            box={box}
            xTicks={xTicks}
            yTicks={yTicks}
            xFor={xFor}
            yFor={yFor}
            formatX={(v) => v.toFixed(xPrecision)}
            formatY={formatPpmTick}
            xTitle="Time (BTJD = BJD − 2457000)"
            yTitle="Relative flux (ppm)"
          />

          <defs>
            <clipPath id="lc-plot-clip">
              <rect x={box.left} y={box.top - 8} width={box.width} height={box.height + 8} />
            </clipPath>
          </defs>

          <g clipPath="url(#lc-plot-clip)">
            {/* Predicted transit windows from a published ephemeris (literature, not a detection). */}
            {transits.map((transit) => {
              if (transit.windowEnd < d0 || transit.windowStart > d1) return null;
              const x = xFor(transit.windowStart);
              const w = Math.max(xFor(transit.windowEnd) - x, 2);
              return (
                <g key={`transit-${transit.epoch}`} data-kind="predicted-transit" aria-hidden="true">
                  <rect
                    x={x}
                    y={box.top}
                    width={w}
                    height={box.height}
                    fill={REFERENCE_COLOR}
                    fillOpacity={0.12}
                  />
                  <rect x={x} y={box.top - 3} width={w} height={3} fill={REFERENCE_COLOR} />
                </g>
              );
            })}

            {/* Gap boundary indicators -- a subtle dashed tick, never a connecting line */}
            {gaps.map((gap) => {
              const midpoint = xFor((gap.start_time + gap.end_time) / 2);
              if (midpoint < box.left || midpoint > box.left + box.width) return null;
              return (
                <line
                  key={`${gap.before_segment_number}-${gap.after_segment_number}`}
                  x1={midpoint}
                  y1={box.top}
                  x2={midpoint}
                  y2={box.top + box.height}
                  stroke={GAP_LINE_COLOR}
                  strokeDasharray="2,3"
                  aria-hidden="true"
                />
              );
            })}

            {/* High-outlier markers: a distinct shape (triangle), not color alone */}
            {showOutliers &&
              outliers.map((outlier) => {
                if (outlier.time < d0 || outlier.time > d1) return null;
                const x = xFor(outlier.time);
                const y = yFor(outlier.flux);
                return (
                  <g key={`${outlier.segmentNumber}-${outlier.sourceIndex}`}>
                    <title>
                      {`Statistical high outlier — not a planet candidate. Segment ${outlier.segmentNumber}, `}
                      {`time ${outlier.time.toFixed(4)} BTJD, robust score ${outlier.robustScore?.toFixed(2) ?? "n/a"}.`}
                    </title>
                    <polygon
                      points={`${x},${y - 6} ${x - 5.5},${y + 4.5} ${x + 5.5},${y + 4.5}`}
                      fill={OUTLIER_COLOR}
                      stroke="var(--surface-1)"
                      strokeWidth={1.5}
                    />
                  </g>
                );
              })}
          </g>

          {brush && (
            <rect
              x={Math.min(brush.from, brush.to)}
              y={box.top}
              width={Math.abs(brush.to - brush.from)}
              height={box.height}
              fill="rgba(85,152,231,0.12)"
              stroke="rgba(85,152,231,0.6)"
              aria-hidden="true"
            />
          )}

          {active !== null && activePoint?.normalized_flux != null && (
            <g aria-hidden="true" pointerEvents="none">
              <line
                x1={xFor(flat.time[active])}
                x2={xFor(flat.time[active])}
                y1={box.top}
                y2={box.top + box.height}
                stroke="rgba(255,255,255,0.35)"
              />
              <circle
                cx={xFor(flat.time[active])}
                cy={yFor(activePoint.normalized_flux)}
                r={4.5}
                fill="none"
                stroke="#f3f3f1"
                strokeWidth={1.5}
              />
            </g>
          )}
        </svg>

        {activePoint && activeSegment && active !== null && (
          <div
            className="pointer-events-none absolute z-10 w-[222px] rounded-lg border border-line-strong bg-surface-3/95 p-3 text-xs shadow-xl backdrop-blur"
            style={{
              left: flipTooltip ? Math.max(xFor(flat.time[active]) - 236, 8) : tooltipLeft,
              top: box.top + 4,
            }}
          >
            <p className="text-sm font-semibold text-ink-primary tabular">
              {formatFixed(activePoint.normalized_flux, 6)}
              <span className="ml-1.5 text-xs font-normal text-ink-secondary">
                {activePoint.normalized_flux !== null
                  ? formatPpmOffset(activePoint.normalized_flux)
                  : ""}
              </span>
            </p>
            <p className="text-ink-muted">Normalized flux</p>
            <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 tabular">
              <dt className="text-ink-muted">Time</dt>
              <dd className="text-right text-ink-primary">{activePoint.time.toFixed(5)} BTJD</dd>
              <dt className="text-ink-muted">BJD</dt>
              <dd className="text-right text-ink-secondary">
                {(activePoint.time + BTJD_OFFSET).toFixed(5)}
              </dd>
              <dt className="text-ink-muted">Segment</dt>
              <dd className="text-right text-ink-primary">{activeSegment.segment_number}</dd>
              <dt className="text-ink-muted">FITS row</dt>
              <dd className="text-right text-ink-primary">{activePoint.source_index}</dd>
              <dt className="text-ink-muted">Robust score</dt>
              <dd className="text-right text-ink-primary">
                {activePoint.robust_score !== null ? activePoint.robust_score.toFixed(2) : "n/a"}
              </dd>
            </dl>
            <p className="mt-2 text-ink-muted">Segment {describeStatus(activeSegment.analysis_status)}.</p>
            {activePoint.is_high_outlier && (
              <p className="mt-1.5 font-medium text-series-outlier">
                ▲ Statistical high outlier — not a planet candidate.
              </p>
            )}
            {activeTransit && (
              <p className="mt-1.5 text-kind-reference">
                ■ Inside the {transitLabel.replace(/^Predicted /, "predicted ")} (literature ephemeris).
              </p>
            )}
          </div>
        )}

        <p className="sr-only" aria-live="polite">
          {activePoint
            ? `Time ${activePoint.time.toFixed(4)} BTJD, normalized flux ${formatFixed(activePoint.normalized_flux, 6)}, segment ${activeSegment?.segment_number}${activePoint.is_high_outlier ? ", statistical high outlier" : ""}${activeTransit ? ", inside predicted transit window" : ""}.`
            : ""}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-secondary">
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: "rgba(57, 135, 229, 0.8)" }}
          />
          Normalized observation
        </span>
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: "rgba(141, 140, 134, 0.8)" }}
          />
          Segment too short for outlier analysis
        </span>
        {showBinned && (
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded" style={{ background: BINNED_COLOR }} />
            {binMinutes}-min median bin (calculated for display)
          </span>
        )}
        {showOutliers && (
          <span className="flex items-center gap-2">
            <svg width="10" height="10" aria-hidden="true">
              <polygon points="5,0 0,10 10,10" fill={OUTLIER_COLOR} />
            </svg>
            Statistical high outlier — not a planet candidate
          </span>
        )}
        {transits.length > 0 && (
          <span className="flex items-center gap-2">
            <span
              aria-hidden="true"
              className="inline-block h-3 w-3 rounded-sm"
              style={{ background: "rgba(25, 158, 112, 0.35)", borderTop: `2px solid ${REFERENCE_COLOR}` }}
            />
            {transitLabel} (literature ephemeris, not a detection)
          </span>
        )}
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-3 w-px border-l border-dashed border-white/40" />
          Phase 3B gap boundary (not interpolated)
        </span>
      </div>

      <p className="text-xs leading-relaxed text-ink-muted">
        Chart summary: {segments.length} independently plotted Phase 3B segments spanning{" "}
        {totalPoints.toLocaleString()} cadences, separated by {gaps.length} gaps shown as blank
        intervals with a dashed boundary marker. {outliers.length} point
        {outliers.length === 1 ? " is" : "s are"} marked as statistical high outliers (triangle
        markers) — these are unusual measurements, not planet candidates. Zero low (downward)
        outliers are marked, since lower-side detection is disabled by default to avoid flagging a
        real transit-like dip. Every cadence is drawn; binned values are an added display layer,
        not a replacement.
        {isZoomed ? ` Currently zoomed to ${d0.toFixed(3)}–${d1.toFixed(3)} BTJD.` : ""}
      </p>
    </div>
  );
}
