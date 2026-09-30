import type { DemoProvenance } from "@/lib/api";
import { CopyButton } from "@/components/CopyButton";
import { Card } from "@/components/ui";
import { formatInt } from "@/lib/format";

const STEP_LABELS: Record<string, { label: string; output: string }> = {
  quality_filter: { label: "Quality filtered", output: "cadences retained" },
  gap_segmentation: { label: "Segmented", output: "segments" },
  flux_normalization: { label: "Normalized", output: "segments normalized" },
  outlier_flagging: { label: "Outliers flagged", output: "segments analyzed" },
};

export function ProcessingHistory({ provenance }: { provenance: DemoProvenance }) {
  const history = provenance.processing_history;
  return (
    <Card as="section" aria-labelledby="history-heading" className="p-4 sm:p-5">
      <h3 id="history-heading" className="text-sm font-semibold text-ink-primary">
        Processing history
      </h3>
      <ol className="relative mt-4 flex flex-col gap-5 border-l border-line-strong pl-5">
        {history.map((entry, index) => {
          const meta = STEP_LABELS[entry.step];
          return (
            <li key={entry.step} className="relative text-sm">
              <span
                aria-hidden="true"
                className="absolute -left-[26.5px] top-1 flex h-3 w-3 items-center justify-center rounded-full border border-status-good/60 bg-page-plane"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-status-good" />
              </span>
              <p className="text-ink-primary">
                <span className="text-ink-muted tabular">{index + 1}. </span>
                {meta?.label ?? entry.step}{" "}
                <span className="text-xs text-ink-muted">v{entry.code_version}</span>
              </p>
              <p className="mt-0.5 text-xs text-ink-secondary tabular">
                {formatInt(entry.input_count)} cadences in → {formatInt(entry.output_count)}{" "}
                {meta?.output ?? "out"}
              </p>
              <p className="mt-0.5 break-words font-mono text-[11px] text-ink-muted">{entry.configuration_summary}</p>
            </li>
          );
        })}
      </ol>
      <div className="mt-5 flex flex-col gap-2 border-t border-line-hairline pt-4 text-xs leading-relaxed text-ink-secondary">
        <p className="flex gap-2">
          <span aria-hidden="true" className="text-status-good">✓</span>
          {provenance.fits_file_unchanged_statement}
        </p>
        <p className="flex gap-2">
          <span aria-hidden="true" className="text-status-good">✓</span>
          {provenance.deterministic_processing_statement}
        </p>
        <div className="mt-1 flex min-w-0 items-center gap-2">
          <span className="shrink-0 text-ink-muted">Every step read</span>
          <span className="min-w-0 truncate font-mono text-[11px] text-ink-muted" title={provenance.source_checksum_sha256}>
            sha256:{provenance.source_checksum_sha256}
          </span>
          <CopyButton value={provenance.source_checksum_sha256} label="Copy SHA-256" />
        </div>
      </div>
    </Card>
  );
}
