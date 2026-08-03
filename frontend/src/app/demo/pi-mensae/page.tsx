"use client";

import { useEffect, useState } from "react";
import {
  ApiError,
  DemoApiError,
  fetchDemoLightCurve,
  fetchDemoSummary,
  type DemoLightCurveResponse,
  type DemoSummaryResponse,
} from "@/lib/api";
import { StatTile } from "@/components/StatTile";
import { DemoHeader } from "@/components/DemoHeader";
import { DemoErrorState } from "@/components/DemoErrorState";
import { PipelineStageList } from "@/components/PipelineStageList";
import { LightCurveChart } from "@/components/LightCurveChart";
import {
  NormalizationSummary,
  OutlierSummary,
  QualitySummary,
  SegmentationSummary,
} from "@/components/PhasePanels";
import { ProcessingHistory } from "@/components/ProcessingHistory";
import { ScientificLimitations } from "@/components/ScientificLimitations";

type DemoState =
  | { kind: "loading" }
  | { kind: "error"; title: string; message: string }
  | { kind: "loaded"; summary: DemoSummaryResponse; lightCurve: DemoLightCurveResponse };

function describeError(error: unknown): { title: string; message: string } {
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

export default function PiMensaeDemoPage() {
  const [state, setState] = useState<DemoState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setState({ kind: "loading" });
      try {
        const [summary, lightCurve] = await Promise.all([
          fetchDemoSummary(),
          fetchDemoLightCurve(),
        ]);
        if (!cancelled) {
          setState({ kind: "loaded", summary, lightCurve });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ kind: "error", ...describeError(error) });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-6 py-12">
      {state.kind === "loaded" ? (
        <DemoHeader identity={state.summary.identity} />
      ) : (
        <header>
          <p className="text-xs font-medium uppercase tracking-widest text-ink-muted">
            AI Exoplanet Hunter
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-ink-primary">Pi Mensae Science Preview</h1>
          <p className="mt-1 text-sm text-ink-muted">TIC 261136679 · TESS Sector 1</p>
        </header>
      )}

      {state.kind === "loading" && (
        <p className="text-sm text-ink-muted" role="status">
          Loading pipeline results…
        </p>
      )}

      {state.kind === "error" && <DemoErrorState title={state.title} message={state.message} />}

      {state.kind === "loaded" && (
        <>
          <PipelineStageList />

          <section aria-labelledby="summary-heading" className="flex flex-col gap-3">
            <h2 id="summary-heading" className="text-sm font-medium text-ink-secondary">
              Summary statistics
            </h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <StatTile
                label="Raw cadences"
                value={state.summary.raw.raw_cadence_count.toLocaleString()}
                caption="Phase 2B"
              />
              <StatTile
                label="Retained cadences"
                value={state.summary.quality_filter.retained_cadence_count.toLocaleString()}
                caption="Phase 3A"
              />
              <StatTile
                label="Rejected cadences"
                value={state.summary.quality_filter.rejected_cadence_count.toLocaleString()}
                caption="Phase 3A"
              />
              <StatTile
                label="Segments"
                value={state.summary.segmentation.segment_count.toLocaleString()}
                caption="Phase 3B"
              />
              <StatTile
                label="Gaps"
                value={state.summary.segmentation.gap_count.toLocaleString()}
                caption="Phase 3B"
              />
              <StatTile
                label="Normalized segments"
                value={state.summary.normalization.normalized_segment_count.toLocaleString()}
                caption="Phase 3C"
              />
              <StatTile
                label="High outliers"
                value={state.summary.outliers.high_outlier_count.toLocaleString()}
                caption="Phase 3D — not planet candidates"
              />
              <StatTile
                label="Low outliers"
                value={state.summary.outliers.low_outlier_count.toLocaleString()}
                caption="Lower-side detection disabled"
              />
              <StatTile
                label="Quality policy"
                value={state.summary.quality_filter.quality_policy.toUpperCase()}
                caption="MAST-recommended"
              />
              <StatTile
                label="Quality mask"
                value={state.summary.quality_filter.quality_bitmask_decimal.toLocaleString()}
                caption={state.summary.quality_filter.quality_bitmask_hex}
              />
            </div>
          </section>

          <section aria-labelledby="chart-heading" className="flex flex-col gap-3">
            <h2 id="chart-heading" className="text-sm font-medium text-ink-secondary">
              Normalized light curve
            </h2>
            <div className="rounded-lg border border-white/10 bg-surface-1 p-5">
              <LightCurveChart
                segments={state.lightCurve.segments}
                gaps={state.lightCurve.gaps}
              />
            </div>
          </section>

          <section aria-labelledby="phase-detail-heading" className="flex flex-col gap-3">
            <h2 id="phase-detail-heading" className="text-sm font-medium text-ink-secondary">
              Phase detail
            </h2>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <QualitySummary quality={state.summary.quality_filter} />
              <SegmentationSummary segmentation={state.summary.segmentation} />
              <NormalizationSummary normalization={state.summary.normalization} />
              <OutlierSummary outliers={state.summary.outliers} />
            </div>
          </section>

          <ProcessingHistory history={state.summary.provenance.processing_history} />

          <ScientificLimitations limitations={state.summary.scientific_limitations} />
        </>
      )}
    </main>
  );
}
