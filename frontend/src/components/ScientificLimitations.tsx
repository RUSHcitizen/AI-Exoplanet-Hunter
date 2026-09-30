import { Card } from "@/components/ui";

export function ScientificLimitations({ limitations }: { limitations: string[] }) {
  return (
    <Card
      as="section"
      aria-labelledby="limitations-heading"
      className="border-status-warning/25 p-4 sm:p-5"
    >
      <h3
        id="limitations-heading"
        className="flex items-center gap-2 text-sm font-semibold text-status-warning"
      >
        <span aria-hidden="true">▲</span>
        Scientific limitations
      </h3>
      <ul className="mt-3 flex flex-col gap-2 text-sm text-ink-secondary">
        {limitations.map((limitation) => (
          <li key={limitation} className="flex gap-2.5 leading-relaxed">
            <span aria-hidden="true" className="mt-2 h-1 w-1 shrink-0 rounded-full bg-ink-muted" />
            <span>{limitation}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
