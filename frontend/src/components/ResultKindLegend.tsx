import { Card, KindTag, RESULT_KINDS, type ResultKind } from "@/components/ui";

/** Explains the provenance tags used next to values across the site. */
export function ResultKindLegend({ compact = false }: { compact?: boolean }) {
  const kinds = Object.keys(RESULT_KINDS) as ResultKind[];
  return (
    <Card as="section" aria-labelledby="kinds-heading" className="p-4 sm:p-5">
      <h3 id="kinds-heading" className="text-sm font-semibold text-ink-primary">
        How to read the values
      </h3>
      <dl className={compact ? "mt-3 flex flex-col gap-3" : "mt-3 grid gap-4 sm:grid-cols-2"}>
        {kinds.map((kind) => (
          <div key={kind} className="flex flex-col gap-1">
            <dt>
              <KindTag kind={kind} />
            </dt>
            <dd className="text-xs leading-relaxed text-ink-secondary">{RESULT_KINDS[kind].description}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
