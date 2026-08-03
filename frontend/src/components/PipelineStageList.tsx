const COMPLETED_STAGES = [
  "Raw FITS parsed",
  "Quality filtered",
  "Segmented",
  "Normalized",
  "Outliers flagged",
];

const FUTURE_STAGES = [
  "Detrending",
  "Transit search (Box Least Squares)",
  "Candidate feature extraction",
  "Machine-learning classification",
];

export function PipelineStageList() {
  return (
    <section aria-labelledby="pipeline-heading" className="flex flex-col gap-3">
      <h2 id="pipeline-heading" className="text-sm font-medium text-ink-secondary">
        Pipeline status
      </h2>
      <ol className="flex flex-wrap gap-2">
        {COMPLETED_STAGES.map((stage) => (
          <li
            key={stage}
            className="flex items-center gap-1.5 rounded-full border border-status-good/30 bg-status-good/10 px-3 py-1 text-xs text-status-good"
          >
            <span aria-hidden="true">●</span>
            {stage}
          </li>
        ))}
      </ol>
      <div>
        <p className="text-xs text-ink-muted">Future pipeline stages (not yet implemented)</p>
        <ul className="mt-1.5 flex flex-wrap gap-2">
          {FUTURE_STAGES.map((stage) => (
            <li
              key={stage}
              className="rounded-full border border-white/10 px-3 py-1 text-xs text-ink-muted"
            >
              {stage}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
