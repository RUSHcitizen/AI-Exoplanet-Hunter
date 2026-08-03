"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { DemoGap, DemoLightCurveSegment } from "@/lib/api";

/**
 * Gap-aware normalized light-curve chart for the Pi Mensae demo.
 *
 * Performance: ~18,264 points are drawn once per resize onto a single
 * <canvas> (cheap -- a few thousand 1px fills), not as individual DOM
 * nodes. The handful of high-outlier markers and gap indicators are a
 * separate, tiny SVG overlay so they can carry real accessible markup
 * (title, aria-label) without the point cloud paying that cost too.
 *
 * Every segment is drawn from its own points only -- there is no code
 * path that connects one segment's last point to the next segment's
 * first point, so a Phase 3B gap can never be drawn as a connecting
 * line. The horizontal axis is literal TIME, so a real observation gap
 * shows up honestly as blank space, not as an interpolated bridge.
 */

const CHART_HEIGHT = 320;
const MARGIN = { top: 16, right: 16, bottom: 28, left: 56 };

const ANALYZED_POINT_COLOR = "rgba(57, 135, 229, 0.55)";
const UNANALYZED_POINT_COLOR = "rgba(137, 135, 129, 0.45)";
const OUTLIER_COLOR = "#ec835a";
const GAP_LINE_COLOR = "rgba(255, 255, 255, 0.14)";

interface Bounds {
  minTime: number;
  maxTime: number;
  minFlux: number;
  maxFlux: number;
}

interface OutlierMarker {
  time: number;
  flux: number;
  segmentNumber: number;
  sourceIndex: number;
  robustScore: number | null;
}

function computeBounds(segments: DemoLightCurveSegment[]): Bounds {
  let minTime = Infinity;
  let maxTime = -Infinity;
  let minFlux = Infinity;
  let maxFlux = -Infinity;

  for (const segment of segments) {
    for (const point of segment.points) {
      if (point.time < minTime) minTime = point.time;
      if (point.time > maxTime) maxTime = point.time;
      if (point.normalized_flux !== null) {
        if (point.normalized_flux < minFlux) minFlux = point.normalized_flux;
        if (point.normalized_flux > maxFlux) maxFlux = point.normalized_flux;
      }
    }
  }

  if (!Number.isFinite(minTime) || !Number.isFinite(maxTime)) {
    minTime = 0;
    maxTime = 1;
  }
  if (!Number.isFinite(minFlux) || !Number.isFinite(maxFlux)) {
    minFlux = 0.99;
    maxFlux = 1.01;
  }
  const padding = (maxFlux - minFlux) * 0.1 || 0.0005;
  return { minTime, maxTime, minFlux: minFlux - padding, maxFlux: maxFlux + padding };
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

export function LightCurveChart({
  segments,
  gaps,
}: {
  segments: DemoLightCurveSegment[];
  gaps: DemoGap[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(800);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) setWidth(Math.max(entry.contentRect.width, 240));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const bounds = useMemo(() => computeBounds(segments), [segments]);
  const outliers = useMemo(() => collectOutliers(segments), [segments]);
  const totalPoints = useMemo(
    () => segments.reduce((sum, segment) => sum + segment.points.length, 0),
    [segments],
  );

  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 1);
  const plotHeight = CHART_HEIGHT - MARGIN.top - MARGIN.bottom;
  const timeSpan = bounds.maxTime - bounds.minTime || 1;
  const fluxSpan = bounds.maxFlux - bounds.minFlux || 1;

  const xFor = (time: number) => MARGIN.left + ((time - bounds.minTime) / timeSpan) * plotWidth;
  const yFor = (flux: number) =>
    MARGIN.top + plotHeight - ((flux - bounds.minFlux) / fluxSpan) * plotHeight;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = typeof window === "undefined" ? 1 : window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = CHART_HEIGHT * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${CHART_HEIGHT}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, CHART_HEIGHT);

    for (const segment of segments) {
      ctx.fillStyle =
        segment.analysis_status === "valid" ? ANALYZED_POINT_COLOR : UNANALYZED_POINT_COLOR;
      for (const point of segment.points) {
        if (point.normalized_flux === null || point.is_high_outlier) continue;
        const x = xFor(point.time);
        const y = yFor(point.normalized_flux);
        ctx.fillRect(x - 0.6, y - 0.6, 1.3, 1.3);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments, width, bounds]);

  return (
    <div className="flex flex-col gap-3">
      <div ref={containerRef} className="relative w-full" style={{ height: CHART_HEIGHT }}>
        <canvas
          ref={canvasRef}
          role="img"
          aria-label={`Normalized light curve: ${segments.length} independently plotted segments, ${totalPoints.toLocaleString()} cadences, ${outliers.length} statistical high outliers marked (not planet candidates), zero low outliers (lower-side detection disabled).`}
          className="absolute inset-0"
        />
        <svg
          viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
          className="absolute inset-0"
          aria-hidden="true"
          width={width}
          height={CHART_HEIGHT}
        >
          {/* Axis frame */}
          <line
            x1={MARGIN.left}
            y1={MARGIN.top}
            x2={MARGIN.left}
            y2={CHART_HEIGHT - MARGIN.bottom}
            stroke="var(--border-hairline)"
          />
          <line
            x1={MARGIN.left}
            y1={CHART_HEIGHT - MARGIN.bottom}
            x2={width - MARGIN.right}
            y2={CHART_HEIGHT - MARGIN.bottom}
            stroke="var(--border-hairline)"
          />

          {/* Gap boundary indicators -- a subtle dashed tick, never a connecting line */}
          {gaps.map((gap) => {
            const midpoint = xFor((gap.start_time + gap.end_time) / 2);
            return (
              <line
                key={`${gap.before_segment_number}-${gap.after_segment_number}`}
                x1={midpoint}
                y1={MARGIN.top}
                x2={midpoint}
                y2={CHART_HEIGHT - MARGIN.bottom}
                stroke={GAP_LINE_COLOR}
                strokeDasharray="2,3"
              />
            );
          })}

          {/* High-outlier markers: a distinct shape (triangle), not color alone */}
          {outliers.map((outlier) => {
            const x = xFor(outlier.time);
            const y = yFor(outlier.flux);
            return (
              <g key={`${outlier.segmentNumber}-${outlier.sourceIndex}`}>
                <title>
                  {`Statistical high outlier — not a planet candidate. Segment ${outlier.segmentNumber}, `}
                  {`time ${outlier.time.toFixed(4)} BJD, robust score ${outlier.robustScore?.toFixed(2) ?? "n/a"}.`}
                </title>
                <polygon
                  points={`${x},${y - 6} ${x - 5.5},${y + 4.5} ${x + 5.5},${y + 4.5}`}
                  fill={OUTLIER_COLOR}
                  stroke="var(--page-plane)"
                  strokeWidth={1}
                />
              </g>
            );
          })}
        </svg>

        {/* Axis labels */}
        <span className="absolute bottom-0 left-14 text-[10px] text-ink-muted">
          {bounds.minTime.toFixed(2)} BJD
        </span>
        <span className="absolute bottom-0 right-4 text-[10px] text-ink-muted">
          {bounds.maxTime.toFixed(2)} BJD
        </span>
        <span className="absolute left-1 top-4 text-[10px] text-ink-muted">
          {bounds.maxFlux.toFixed(4)}
        </span>
        <span className="absolute bottom-7 left-1 text-[10px] text-ink-muted">
          {bounds.minFlux.toFixed(4)}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-ink-secondary">
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: ANALYZED_POINT_COLOR }}
          />
          Normalized observation
        </span>
        <span className="flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: UNANALYZED_POINT_COLOR }}
          />
          Segment too short for outlier analysis
        </span>
        <span className="flex items-center gap-2">
          <svg width="10" height="10" aria-hidden="true">
            <polygon points="5,0 0,10 10,10" fill={OUTLIER_COLOR} />
          </svg>
          Statistical high outlier — not a planet candidate
        </span>
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="inline-block h-2 w-px border-l border-dashed border-white/20" />
          Phase 3B gap boundary (not interpolated)
        </span>
      </div>

      <p className="text-xs text-ink-muted">
        Chart summary: {segments.length} independently plotted Phase 3B segments spanning{" "}
        {totalPoints.toLocaleString()} cadences, separated by {gaps.length} gaps shown as blank
        intervals with a dashed boundary marker. {outliers.length} point
        {outliers.length === 1 ? " is" : "s are"} marked as statistical high outliers (triangle
        markers) -- these are unusual measurements, not planet candidates. Zero low (downward)
        outliers are marked, since lower-side detection is disabled by default to avoid flagging a
        real transit-like dip. Every point shown is an actual displayed cadence; no downsampling
        was applied.
      </p>
    </div>
  );
}
