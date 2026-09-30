import type { DemoSummaryResponse } from "@/lib/api";
import { formatInt, formatPercent } from "@/lib/format";
import { PIPELINE_STAGES } from "@/lib/pipeline";
import { Card, SectionHeader } from "@/components/ui";

function stageResult(
  id: string,
  summary: DemoSummaryResponse | undefined,
): { value: string; caption: string } | null {
  if (!summary) return null;
  switch (id) {
    case "parse":
      return { value: formatInt(summary.raw.raw_cadence_count), caption: "cadences read" };
    case "quality":
      return {
        value: formatInt(summary.quality_filter.retained_cadence_count),
        caption: `retained · ${formatPercent(summary.quality_filter.retained_fraction)}`,
      };
    case "segment":
      return {
        value: formatInt(summary.segmentation.segment_count),
        caption: `segments · ${formatInt(summary.segmentation.gap_count)} gaps`,
      };
    case "normalize":
      return {
        value: `${formatInt(summary.normalization.normalized_segment_count)}/${formatInt(summary.segmentation.segment_count)}`,
        caption: "segments normalized",
      };
    case "outliers":
      return {
        value: formatInt(summary.outliers.high_outlier_count),
        caption: "high outliers flagged",
      };
    default:
      return null;
  }
}

/** Implemented stages as a left-to-right flow with their real outputs,
 * followed by the planned stages -- which are explicitly not run. */
export function PipelineStageList({ summary }: { summary?: DemoSummaryResponse }) {
  const completed = PIPELINE_STAGES.filter((stage) => stage.status === "complete");
  const planned = PIPELINE_STAGES.filter((stage) => stage.status === "planned");

  return (
    <section aria-labelledby="pipeline-heading" className="flex flex-col gap-4">
      <SectionHeader
        id="pipeline-heading"
        eyebrow="Processing"
        title="Pipeline status"
        description="Every implemented stage ran on this observation with its project-default configuration. Nothing past outlier flagging has been run."
      />
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {completed.map((stage, index) => {
          const result = stageResult(stage.id, summary);
          return (
            <li key={stage.id} className="relative">
              <Card className="flex h-full flex-col gap-2 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-1.5 text-xs font-medium text-status-good">
                    <span aria-hidden="true">✓</span>
                    <span>Phase {stage.phase}</span>
                  </span>
                  <span className="text-[11px] text-ink-muted tabular" aria-hidden="true">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                </div>
                <p className="text-sm font-semibold text-ink-primary">{stage.label}</p>
                {result && (
                  <p className="text-ink-primary">
                    <span className="text-xl font-semibold tracking-tight">{result.value}</span>
                    <span className="ml-1.5 text-xs text-ink-muted">{result.caption}</span>
                  </p>
                )}
                <p className="mt-auto text-xs leading-relaxed text-ink-muted">{stage.description}</p>
              </Card>
            </li>
          );
        })}
      </ol>
      <div>
        <p className="text-xs font-medium text-ink-muted">Future pipeline stages (not yet implemented)</p>
        <ul className="mt-2 flex flex-wrap gap-2">
          {planned.map((stage) => (
            <li
              key={stage.id}
              title={stage.description}
              className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-line-strong px-3 py-1 text-xs text-ink-muted"
            >
              <span aria-hidden="true">○</span>
              {stage.label}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
