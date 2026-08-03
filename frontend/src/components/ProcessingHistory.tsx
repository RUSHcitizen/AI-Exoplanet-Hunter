import type { ProcessingHistoryEntry } from "@/lib/api";

const STEP_LABELS: Record<string, string> = {
  quality_filter: "Quality filtered",
  gap_segmentation: "Segmented",
  flux_normalization: "Normalized",
  outlier_flagging: "Outliers flagged",
};

export function ProcessingHistory({ history }: { history: ProcessingHistoryEntry[] }) {
  return (
    <section
      aria-labelledby="history-heading"
      className="rounded-lg border border-white/10 bg-surface-1 p-5"
    >
      <h3 id="history-heading" className="text-sm font-medium text-ink-secondary">
        Processing history
      </h3>
      <ol className="mt-3 flex flex-col gap-3">
        {history.map((entry, index) => (
          <li key={entry.step} className="border-t border-white/5 pt-3 text-sm first:border-0 first:pt-0">
            <p className="text-ink-primary">
              <span className="text-ink-muted [font-variant-numeric:tabular-nums]">
                {index + 1}.{" "}
              </span>
              {STEP_LABELS[entry.step] ?? entry.step} —{" "}
              <span className="text-ink-secondary">v{entry.code_version}</span>
            </p>
            <p className="text-xs text-ink-secondary">
              {entry.input_count.toLocaleString()} in → {entry.output_count.toLocaleString()} out
              · {entry.configuration_summary}
            </p>
            <p className="truncate font-mono text-[10px] text-ink-muted" title={entry.source_checksum_sha256}>
              source {entry.source_checksum_sha256}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
