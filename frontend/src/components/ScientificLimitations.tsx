export function ScientificLimitations({ limitations }: { limitations: string[] }) {
  return (
    <section
      aria-labelledby="limitations-heading"
      className="rounded-lg border border-status-warning/30 bg-surface-1 p-5"
    >
      <h3 id="limitations-heading" className="text-sm font-medium text-status-warning">
        Scientific limitations
      </h3>
      <ul className="mt-3 flex flex-col gap-1.5 text-sm text-ink-secondary">
        {limitations.map((limitation) => (
          <li key={limitation} className="flex gap-2">
            <span aria-hidden="true">–</span>
            <span>{limitation}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
