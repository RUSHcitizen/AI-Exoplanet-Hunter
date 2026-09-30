"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  assertDemoResponses,
  DemoApiError,
  fetchDemoLightCurve,
  fetchDemoSummary,
  isRetryableApiError,
  MalformedResponseError,
  type DemoLightCurveResponse,
  type DemoSummaryResponse,
} from "@/lib/api";
import { StatTile } from "@/components/StatTile";
import { ObservationHeader } from "@/components/ObservationHeader";
import { DemoErrorState } from "@/components/DemoErrorState";
import { DemoSkeleton, LoadingNotice } from "@/components/DemoStates";
import { BackendWakingNotice } from "@/components/BackendWakingNotice";
import { PipelineStageList } from "@/components/PipelineStageList";
import { LightCurveExplorer } from "@/components/LightCurveExplorer";
import type { TimeDomain } from "@/components/LightCurveChart";
import {
  NormalizationSummary,
  OutlierSummary,
  QualitySummary,
  SegmentationSummary,
} from "@/components/PhasePanels";
import { SegmentTable } from "@/components/SegmentTable";
import { TargetReference } from "@/components/TargetReference";
import { ProcessingHistory } from "@/components/ProcessingHistory";
import { ResultKindLegend } from "@/components/ResultKindLegend";
import { ScientificLimitations } from "@/components/ScientificLimitations";
import { SectionNav } from "@/components/SectionNav";
import { SectionHeader } from "@/components/ui";
import { formatDuration, formatInt, formatPercent } from "@/lib/format";
import { robustScatterPpm } from "@/lib/lightcurve";
import { PI_MEN_C_EPHEMERIS } from "@/lib/reference";

// Bounded auto-retry for the public deployment's cold-start experience:
// a Render free-tier instance waking from sleep looks like a network
// error (or an occasional 5xx) for up to roughly a minute, not a
// permanent failure. Retrying forever, or too fast, would just create
// unnecessary API traffic -- so this stops after MAX_AUTO_RETRY_MS and
// hands control to a manual "Retry" button instead.
export const RETRY_INTERVAL_MS = 5_000;
export const MAX_AUTO_RETRY_MS = 60_000;

type DemoState =
  | { kind: "loading" }
  | { kind: "waking"; attempt: number; elapsedMs: number }
  | { kind: "error"; title: string; message: string }
  | { kind: "loaded"; summary: DemoSummaryResponse; lightCurve: DemoLightCurveResponse };

const SECTIONS = [
  { id: "light-curve", label: "Light curve" },
  { id: "pipeline", label: "Pipeline" },
  { id: "phase-detail", label: "Stage detail" },
  { id: "segments", label: "Segments" },
  { id: "target", label: "Target" },
  { id: "provenance", label: "Provenance" },
];

function describeError(error: unknown): { title: string; message: string } {
  if (error instanceof MalformedResponseError) {
    return { title: "Unexpected response from the backend", message: error.message };
  }
  if (error instanceof DemoApiError) {
    if (error.status === 404) {
      return {
        title: "Demo FITS file missing",
        message: error.message,
      };
    }
    return { title: "Backend rejected the request", message: error.message };
  }
  if (error instanceof ApiError) {
    return {
      title: "Backend unavailable",
      message: `${error.message} Is the backend running at ${
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
      }?`,
    };
  }
  return { title: "Unexpected error", message: "The demo page could not load its data." };
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export default function PiMensaeDemoPage() {
  const [state, setState] = useState<DemoState>({ kind: "loading" });
  const [retryToken, setRetryToken] = useState(0);
  const [domain, setDomain] = useState<TimeDomain | null>(null);

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();

    function wait(ms: number): Promise<void> {
      return new Promise((resolve) => setTimeout(resolve, ms));
    }

    async function attempt(attemptNumber: number): Promise<void> {
      try {
        const [summary, lightCurve] = await Promise.all([
          fetchDemoSummary(),
          fetchDemoLightCurve(),
        ]);
        assertDemoResponses(summary, lightCurve);
        if (!cancelled) {
          setState({ kind: "loaded", summary, lightCurve });
        }
      } catch (error) {
        if (cancelled) {
          return;
        }
        const elapsed = Date.now() - startedAt;
        if (isRetryableApiError(error) && elapsed < MAX_AUTO_RETRY_MS) {
          setState({ kind: "waking", attempt: attemptNumber, elapsedMs: elapsed });
          await wait(RETRY_INTERVAL_MS);
          if (!cancelled) {
            await attempt(attemptNumber + 1);
          }
          return;
        }
        setState({ kind: "error", ...describeError(error) });
      }
    }

    void attempt(1);

    return () => {
      cancelled = true;
    };
  }, [retryToken]);

  function handleRetry() {
    setState({ kind: "loading" });
    setRetryToken((token) => token + 1);
  }

  const zoomTo = useCallback((start: number, end: number) => {
    setDomain([start, end]);
    document.getElementById("light-curve")?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "start",
    });
  }, []);

  const derived = useMemo(() => {
    if (state.kind !== "loaded") return null;
    const segments = state.lightCurve.segments;
    const first = segments[0]?.start_time;
    const last = segments[segments.length - 1]?.end_time;
    return {
      baselineDays: first !== undefined && last !== undefined ? last - first : null,
      scatterPpm: robustScatterPpm(segments),
    };
  }, [state]);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-10 px-4 pb-8 pt-8 sm:px-6 sm:pt-10">
      <ObservationHeader identity={state.kind === "loaded" ? state.summary.identity : undefined} />

      {state.kind === "loading" && (
        <div className="flex flex-col gap-6">
          <LoadingNotice />
          <DemoSkeleton />
        </div>
      )}

      {state.kind === "waking" && (
        <BackendWakingNotice
          attempt={state.attempt}
          elapsedMs={state.elapsedMs}
          maxMs={MAX_AUTO_RETRY_MS}
          onRetryNow={handleRetry}
        />
      )}

      {state.kind === "error" && (
        <DemoErrorState title={state.title} message={state.message} onRetry={handleRetry} />
      )}

      {state.kind === "loaded" && derived && (
        <div className="flex animate-fade-in flex-col gap-12">
          <SectionNav sections={SECTIONS} />

          <section aria-label="Key figures" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              label="Cadences retained"
              value={formatInt(state.summary.quality_filter.retained_cadence_count)}
              caption={`of ${formatInt(state.summary.raw.raw_cadence_count)} raw · ${formatPercent(state.summary.quality_filter.retained_fraction)}`}
              kind="observed"
            />
            <StatTile
              label="Time baseline"
              value={derived.baselineDays !== null ? derived.baselineDays.toFixed(1) : "—"}
              unit="days"
              caption={`${formatInt(state.summary.segmentation.segment_count)} segments, ${formatInt(state.summary.segmentation.gap_count)} gaps`}
              kind="calculated"
            />
            <StatTile
              label="Robust scatter per cadence"
              value={derived.scatterPpm !== null ? formatInt(Math.round(derived.scatterPpm)) : "—"}
              unit="ppm"
              caption={`vs. ≈ ${PI_MEN_C_EPHEMERIS.depthPpm} ppm published π Men c transit depth`}
              kind="calculated"
            />
            <StatTile
              label="High outliers flagged"
              value={formatInt(state.summary.outliers.high_outlier_count)}
              caption="Unusual bright points — not planet candidates"
              kind="calculated"
            />
          </section>

          <section id="light-curve" aria-labelledby="chart-heading" className="flex flex-col gap-4">
            <SectionHeader
              id="chart-heading"
              eyebrow="Observation"
              title="Normalized light curve"
              description={
                <>
                  Brightness of Pi Mensae over {derived.baselineDays !== null ? formatDuration(derived.baselineDays) : "the sector"}{" "}
                  after Phases 3A–3D, as parts-per-million deviation from each segment&rsquo;s
                  median. Blank stretches are real gaps in the data, never interpolated.
                </>
              }
            />
            <LightCurveExplorer
              segments={state.lightCurve.segments}
              gaps={state.lightCurve.gaps}
              cadenceDays={state.summary.segmentation.measured_nominal_cadence_days}
              ephemeris={PI_MEN_C_EPHEMERIS}
              domain={domain}
              onDomainChange={setDomain}
            />
          </section>

          <div id="pipeline">
            <PipelineStageList summary={state.summary} />
          </div>

          <section id="phase-detail" aria-labelledby="phase-detail-heading" className="flex flex-col gap-4">
            <SectionHeader
              id="phase-detail-heading"
              eyebrow="Stage detail"
              title="What each stage did"
              description="Exact counts and configuration reported by the backend for every implemented stage."
            />
            <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2">
              <QualitySummary quality={state.summary.quality_filter} />
              <div className="flex flex-col gap-4">
                <SegmentationSummary segmentation={state.summary.segmentation} />
                <NormalizationSummary normalization={state.summary.normalization} />
              </div>
              <div className="md:col-span-2">
                <OutlierSummary outliers={state.summary.outliers} />
              </div>
            </div>
          </section>

          <section id="segments" aria-labelledby="segments-heading" className="flex flex-col gap-4">
            <SectionHeader
              id="segments-heading"
              eyebrow="Structure"
              title="Segments and gaps"
              description="Contiguous stretches of data found by Phase 3B. Segments shorter than the outlier stage's minimum are kept and plotted but not scored."
            />
            <SegmentTable
              segments={state.lightCurve.segments}
              gaps={state.lightCurve.gaps}
              onZoom={zoomTo}
            />
          </section>

          <div id="target">
            <TargetReference />
          </div>

          <section id="provenance" aria-labelledby="provenance-heading" className="flex flex-col gap-4">
            <SectionHeader
              id="provenance-heading"
              eyebrow="Reproducibility"
              title="Provenance and limitations"
              description="Every result on this page can be regenerated from the source file below with the same code version and configuration."
            />
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="min-w-0 lg:col-span-2">
                <ProcessingHistory provenance={state.summary.provenance} />
              </div>
              <ResultKindLegend compact />
            </div>
            <ScientificLimitations limitations={state.summary.scientific_limitations} />
          </section>
        </div>
      )}
    </main>
  );
}
