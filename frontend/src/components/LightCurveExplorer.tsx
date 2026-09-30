"use client";

import { useMemo, useRef, useState } from "react";
import type { DemoGap, DemoLightCurveSegment } from "@/lib/api";
import { LightCurveChart, type TimeDomain } from "@/components/LightCurveChart";
import { PhaseFoldChart } from "@/components/PhaseFoldChart";
import { Badge, Card, cx, ExternalLink, KindTag, buttonStyles } from "@/components/ui";
import { flattenSegments, predictTransits, type PredictedTransit } from "@/lib/lightcurve";
import { formatPercent } from "@/lib/format";
import type { TransitEphemeris } from "@/lib/reference";

type View = "time" | "fold";

function Switch({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="group inline-flex min-h-9 items-center gap-2 rounded-lg px-2 text-sm text-ink-secondary transition-colors hover:text-ink-primary"
    >
      <span
        aria-hidden="true"
        className={cx(
          "relative inline-flex h-[18px] w-8 shrink-0 items-center rounded-full border transition-colors",
          checked ? "border-accent/60 bg-accent-strong" : "border-line-strong bg-surface-3",
        )}
      >
        <span
          className={cx(
            "absolute h-3 w-3 rounded-full bg-white shadow transition-transform duration-150",
            checked ? "translate-x-[15px]" : "translate-x-[2px]",
          )}
        />
      </span>
      {label}
    </button>
  );
}

const VIEWS: { id: View; label: string }[] = [
  { id: "time", label: "Time series" },
  { id: "fold", label: "Folded on π Men c" },
];

export function LightCurveExplorer({
  segments,
  gaps,
  cadenceDays,
  ephemeris,
  domain,
  onDomainChange,
}: {
  segments: DemoLightCurveSegment[];
  gaps: DemoGap[];
  cadenceDays: number | null;
  ephemeris: TransitEphemeris;
  domain: TimeDomain | null;
  onDomainChange: (domain: TimeDomain | null) => void;
}) {
  const [view, setView] = useState<View>("time");
  const [showBinned, setShowBinned] = useState(true);
  const [showOutliers, setShowOutliers] = useState(true);
  const [showTransits, setShowTransits] = useState(true);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const flat = useMemo(() => flattenSegments(segments), [segments]);
  const transits = useMemo<PredictedTransit[]>(() => {
    if (flat.length === 0) return [];
    return predictTransits(ephemeris, flat.time[0], flat.time[flat.length - 1], flat, cadenceDays);
  }, [ephemeris, flat, cadenceDays]);

  const outliers = useMemo(
    () =>
      segments.flatMap((segment) =>
        segment.points
          .filter((p) => p.is_high_outlier)
          .map((p) => ({ ...p, segment_number: segment.segment_number })),
      ),
    [segments],
  );

  function focusOn(center: number, halfWidthDays: number) {
    setView("time");
    onDomainChange([center - halfWidthDays, center + halfWidthDays]);
  }

  function onTabKey(event: React.KeyboardEvent, index: number) {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = (index + (event.key === "ArrowRight" ? 1 : -1) + VIEWS.length) % VIEWS.length;
    setView(VIEWS[next].id);
    tabRefs.current[next]?.focus();
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 border-b border-line-hairline px-4 py-3 sm:px-5 lg:flex-row lg:items-center lg:justify-between">
          <div
            role="tablist"
            aria-label="Light curve view"
            className="inline-flex w-fit rounded-lg border border-line-hairline bg-page-plane/60 p-0.5"
          >
            {VIEWS.map((item, index) => (
              <button
                key={item.id}
                ref={(el) => {
                  tabRefs.current[index] = el;
                }}
                type="button"
                role="tab"
                id={`lc-tab-${item.id}`}
                aria-selected={view === item.id}
                aria-controls="lc-panel"
                tabIndex={view === item.id ? 0 : -1}
                onClick={() => setView(item.id)}
                onKeyDown={(event) => onTabKey(event, index)}
                className={cx(
                  "min-h-8 rounded-md px-3 text-sm font-medium transition-colors",
                  view === item.id
                    ? "bg-surface-3 text-ink-primary shadow-sm"
                    : "text-ink-muted hover:text-ink-primary",
                )}
              >
                {item.label}
              </button>
            ))}
          </div>

          {view === "time" ? (
            <div className="flex flex-wrap items-center gap-x-1 gap-y-1">
              <Switch checked={showBinned} onChange={setShowBinned} label="30-min bins" />
              <Switch checked={showOutliers} onChange={setShowOutliers} label="Outlier markers" />
              <Switch checked={showTransits} onChange={setShowTransits} label="Predicted transits" />
              <button
                type="button"
                onClick={() => onDomainChange(null)}
                disabled={domain === null}
                className={cx(buttonStyles.ghost, "ml-1")}
              >
                Reset zoom
              </button>
            </div>
          ) : (
            <p className="text-xs text-ink-muted">
              Folded with P = {ephemeris.periodDays} d, T₀ = {ephemeris.epochBtjd.toFixed(4)} BTJD
            </p>
          )}
        </div>

        <div
          id="lc-panel"
          role="tabpanel"
          aria-labelledby={`lc-tab-${view}`}
          className="px-3 pb-4 pt-4 sm:px-5"
        >
          {view === "time" ? (
            <>
              <p className="mb-3 text-xs text-ink-muted">
                <span className="hidden sm:inline">Drag across the chart to zoom, double-click to reset. </span>
                Focus the chart and use the arrow keys to step through individual cadences.
              </p>
              <LightCurveChart
                segments={segments}
                gaps={gaps}
                domain={domain}
                onDomainChange={onDomainChange}
                showBinned={showBinned}
                showOutliers={showOutliers}
                transits={showTransits ? transits : []}
                transitLabel={`Predicted ${ephemeris.planet} transit window`}
              />
            </>
          ) : (
            <>
              <div className="mb-4 rounded-lg border border-kind-reference/25 bg-kind-reference/[0.06] px-3.5 py-2.5 text-xs leading-relaxed text-ink-secondary">
                <KindTag kind="reference" className="mr-2" />
                This view folds the processed light curve on the <strong className="font-medium text-ink-primary">published</strong>{" "}
                ephemeris of {ephemeris.planet} (
                <ExternalLink href={ephemeris.source.href}>{ephemeris.source.label}</ExternalLink>
                ). This pipeline has not run a period search, transit search, or fit — any dip
                seen here is a visual comparison with the literature, not a detection.
              </div>
              <PhaseFoldChart segments={segments} ephemeris={ephemeris} />
            </>
          )}
        </div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-5">
        <Card as="section" aria-labelledby="transits-heading" className="p-4 sm:p-5 lg:col-span-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="transits-heading" className="text-sm font-semibold text-ink-primary">
              Predicted {ephemeris.planet} transits in this sector
            </h3>
            <KindTag kind="reference" />
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">
            Mid-times from the published ephemeris; coverage is the fraction of each ≈
            {ephemeris.durationHours}-hour window with retained cadences (calculated).
          </p>
          {transits.length === 0 ? (
            <p className="mt-4 text-sm text-ink-secondary">
              No predicted transits fall inside this observation.
            </p>
          ) : (
            <ul className="mt-3 divide-y divide-line-hairline">
              {transits.map((transit) => (
                <li key={transit.epoch} className="flex items-center gap-3 py-2.5 text-sm">
                  <span className="w-7 shrink-0 text-xs text-ink-muted tabular sm:w-12">E{transit.epoch}</span>
                  <span className="min-w-0 flex-1 tabular text-ink-primary">
                    {transit.midTime.toFixed(3)}
                    <span className="ml-1 hidden text-xs text-ink-muted sm:inline">BTJD</span>
                  </span>
                  <span className="hidden w-28 items-center gap-2 sm:flex" aria-hidden="true">
                    <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
                      <span
                        className="block h-full rounded-full bg-series-reference"
                        style={{ width: `${transit.coverage * 100}%` }}
                      />
                    </span>
                  </span>
                  <span className="shrink-0 text-right text-xs tabular sm:w-24">
                    {transit.cadencesInWindow === 0 ? (
                      <Badge tone="warning" icon="▲">In gap</Badge>
                    ) : (
                      <span className="text-ink-secondary">{formatPercent(transit.coverage, 0)} covered</span>
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={() => focusOn(transit.midTime, 0.35)}
                    disabled={transit.cadencesInWindow === 0}
                    className={cx(buttonStyles.ghost, "min-h-8 px-2.5 text-xs")}
                    aria-label={`Zoom the light curve to predicted transit E${transit.epoch}`}
                  >
                    Zoom
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card as="section" aria-labelledby="outliers-heading" className="p-4 sm:p-5 lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 id="outliers-heading" className="text-sm font-semibold text-ink-primary">
              Flagged high outliers
            </h3>
            <KindTag kind="calculated" />
          </div>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">
            Unusually bright single measurements. Not planet candidates — a transit is a dip,
            and downward flagging is disabled.
          </p>
          {outliers.length === 0 ? (
            <p className="mt-4 text-sm text-ink-secondary">No cadences were flagged.</p>
          ) : (
            <ul className="mt-3 divide-y divide-line-hairline">
              {outliers.map((outlier) => (
                <li key={outlier.source_index} className="flex items-center gap-3 py-2.5 text-sm">
                  <span aria-hidden="true" className="text-series-outlier">▲</span>
                  <span className="min-w-0 flex-1 tabular">
                    <span className="text-ink-primary">{outlier.time.toFixed(4)}</span>
                    <span className="ml-1 text-xs text-ink-muted">seg {outlier.segment_number}</span>
                  </span>
                  <span className="text-xs text-ink-secondary tabular">
                    {outlier.robust_score !== null ? `${outlier.robust_score.toFixed(1)}σ` : "—"}
                  </span>
                  <button
                    type="button"
                    onClick={() => focusOn(outlier.time, 0.08)}
                    className={cx(buttonStyles.ghost, "min-h-8 px-2.5 text-xs")}
                    aria-label={`Zoom the light curve to the outlier at ${outlier.time.toFixed(4)} BTJD`}
                  >
                    Zoom
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] text-ink-muted">σ = robust score (units of 1.4826 × MAD).</p>
        </Card>
      </div>
    </div>
  );
}
