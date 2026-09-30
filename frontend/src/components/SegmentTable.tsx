"use client";

import { useMemo, useState } from "react";
import type { DemoGap, DemoLightCurveSegment } from "@/lib/api";
import { Badge, Card, cx, buttonStyles } from "@/components/ui";
import { formatDuration, formatInt, humanize } from "@/lib/format";

type StatusFilter = "all" | "valid" | "other";
type SortKey = "segment" | "duration" | "cadences" | "outliers";

interface Row {
  segment: DemoLightCurveSegment;
  duration: number;
  outliers: number;
}

const FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "valid", label: "Analyzed" },
  { id: "other", label: "Not analyzed" },
];

function StatusBadgeFor({ status }: { status: string }) {
  if (status === "valid") return <Badge tone="good" icon="✓">Analyzed</Badge>;
  if (status === "insufficient_data") return <Badge tone="neutral" icon="–">Too short</Badge>;
  return <Badge tone="warning" icon="▲">{humanize(status)}</Badge>;
}

export function SegmentTable({
  segments,
  gaps,
  onZoom,
}: {
  segments: DemoLightCurveSegment[];
  gaps: DemoGap[];
  onZoom: (start: number, end: number) => void;
}) {
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "segment", desc: false });

  const rows = useMemo<Row[]>(
    () =>
      segments.map((segment) => ({
        segment,
        duration: segment.end_time - segment.start_time,
        outliers: segment.points.filter((p) => p.is_high_outlier).length,
      })),
    [segments],
  );

  const visible = useMemo(() => {
    const filtered = rows.filter((row) =>
      filter === "all"
        ? true
        : filter === "valid"
          ? row.segment.analysis_status === "valid"
          : row.segment.analysis_status !== "valid",
    );
    const value = (row: Row) =>
      sort.key === "segment"
        ? row.segment.segment_number
        : sort.key === "duration"
          ? row.duration
          : sort.key === "cadences"
            ? row.segment.cadence_count
            : row.outliers;
    return [...filtered].sort((a, b) => (value(a) - value(b)) * (sort.desc ? -1 : 1));
  }, [rows, filter, sort]);

  const counts = {
    all: rows.length,
    valid: rows.filter((r) => r.segment.analysis_status === "valid").length,
    other: rows.filter((r) => r.segment.analysis_status !== "valid").length,
  };

  function header(key: SortKey, label: string, align: "left" | "right" = "right") {
    const active = sort.key === key;
    return (
      <th
        scope="col"
        aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
        className={cx("px-3 py-2 font-medium", align === "right" ? "text-right" : "text-left")}
      >
        <button
          type="button"
          onClick={() => setSort({ key, desc: active ? !sort.desc : key !== "segment" })}
          className={cx(
            "relative inline-flex items-center rounded hover:text-ink-primary",
            active ? "text-ink-primary" : "text-ink-muted",
          )}
        >
          {label}
          {active && (
            <span aria-hidden="true" className="absolute -right-3 text-[10px]">
              {sort.desc ? "↓" : "↑"}
            </span>
          )}
        </button>
      </th>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-col gap-3 border-b border-line-hairline px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div role="group" aria-label="Filter segments by analysis status" className="flex flex-wrap gap-1.5">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
              className={cx(
                "inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors",
                filter === item.id
                  ? "border-accent/50 bg-accent/15 text-ink-primary"
                  : "border-line-hairline text-ink-secondary hover:border-line-strong hover:text-ink-primary",
              )}
            >
              {item.label}
              <span className={cx("tabular", filter === item.id ? "text-ink-secondary" : "text-ink-muted")}>
                {counts[item.id]}
              </span>
            </button>
          ))}
        </div>
        <p className="text-xs text-ink-muted" aria-live="polite">
          Showing {visible.length} of {rows.length} segments
        </p>
      </div>

      <div className="max-h-[420px] overflow-auto">
        <table className="w-full min-w-[620px] text-sm">
          <caption className="sr-only">
            Phase 3B segments with time range, duration, cadence count, outlier-analysis status, and
            flagged outliers. Column headers sort the table.
          </caption>
          <thead className="sticky top-0 z-10 bg-surface-2 text-xs">
            <tr className="border-b border-line-hairline">
              {header("segment", "#", "left")}
              <th scope="col" className="px-3 py-2 text-left font-medium text-ink-muted">
                Start – end (BTJD)
              </th>
              {header("duration", "Duration")}
              {header("cadences", "Cadences")}
              <th scope="col" className="px-3 py-2 text-left font-medium text-ink-muted">
                Status
              </th>
              {header("outliers", "Outliers")}
              <th scope="col" className="px-3 py-2">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="tabular">
            {visible.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-sm text-ink-muted">
                  No segments match this filter.
                </td>
              </tr>
            ) : (
              visible.map(({ segment, duration, outliers }) => (
                <tr
                  key={segment.segment_number}
                  className="border-b border-line-hairline/60 transition-colors last:border-0 hover:bg-white/[0.025]"
                >
                  <td className="px-3 py-2 text-ink-muted">{segment.segment_number}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-ink-primary">
                    {segment.start_time.toFixed(3)} – {segment.end_time.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right text-ink-secondary">{formatDuration(duration)}</td>
                  <td className="px-3 py-2 text-right text-ink-primary">{formatInt(segment.cadence_count)}</td>
                  <td className="px-3 py-2">
                    <StatusBadgeFor status={segment.analysis_status} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    {outliers > 0 ? (
                      <span className="text-series-outlier">▲ {outliers}</span>
                    ) : (
                      <span className="text-ink-muted">0</span>
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        const pad = Math.max(duration * 0.05, 0.01);
                        onZoom(segment.start_time - pad, segment.end_time + pad);
                      }}
                      className={cx(buttonStyles.ghost, "min-h-8 px-2.5 text-xs")}
                      aria-label={`Show segment ${segment.segment_number} in the light curve`}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {gaps.length > 0 && (
        <details className="group border-t border-line-hairline">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-4 text-sm text-ink-secondary hover:text-ink-primary sm:px-5">
            <span>
              {gaps.length} observation gaps between segments
            </span>
            <span aria-hidden="true" className="transition-transform group-open:rotate-180">
              ⌄
            </span>
          </summary>
          <div className="overflow-x-auto px-2 pb-3 sm:px-3">
            <table className="w-full min-w-[560px] text-xs tabular">
              <caption className="sr-only">Detected gaps between consecutive segments.</caption>
              <thead className="text-ink-muted">
                <tr className="border-b border-line-hairline">
                  <th scope="col" className="px-2 py-2 text-left font-medium">Between</th>
                  <th scope="col" className="px-2 py-2 text-left font-medium">Starts (BTJD)</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Duration</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium">Est. missing</th>
                  <th scope="col" className="px-2 py-2 text-left font-medium">Cause</th>
                </tr>
              </thead>
              <tbody>
                {gaps.map((gap) => (
                  <tr key={`${gap.before_segment_number}-${gap.after_segment_number}`} className="border-b border-line-hairline/50 last:border-0">
                    <td className="px-2 py-1.5 text-ink-secondary">
                      {gap.before_segment_number} → {gap.after_segment_number}
                    </td>
                    <td className="px-2 py-1.5 text-ink-primary">{gap.start_time.toFixed(3)}</td>
                    <td className="px-2 py-1.5 text-right text-ink-primary">{formatDuration(gap.duration_days)}</td>
                    <td className="px-2 py-1.5 text-right text-ink-secondary">
                      {gap.estimated_missing_cadences !== null ? formatInt(gap.estimated_missing_cadences) : "—"}
                    </td>
                    <td className="px-2 py-1.5 text-ink-secondary">
                      {gap.reasons.map((r) => humanize(r)).join(" + ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
    </Card>
  );
}
