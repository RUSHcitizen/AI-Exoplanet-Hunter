import type { ReactNode } from "react";
import { Card, KindTag, type ResultKind } from "@/components/ui";

/**
 * A bare stat tile (headline number, no plot) -- per the dataviz skill,
 * this form needs no legend or hover layer, just a clear label and a
 * value in proportional figures (tabular only where numbers align).
 */
export function StatTile({
  label,
  value,
  caption,
  kind,
  unit,
}: {
  label: string;
  value: string;
  caption?: ReactNode;
  kind?: ResultKind;
  unit?: string;
}) {
  return (
    <Card className="flex flex-col gap-1.5 p-4">
      <div className="flex flex-col-reverse items-start gap-1.5 sm:flex-row sm:justify-between sm:gap-2">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        {kind ? <KindTag kind={kind} /> : null}
      </div>
      <p className="text-2xl font-semibold tracking-tight text-ink-primary sm:text-[1.7rem]">
        {value}
        {unit ? <span className="ml-1 text-sm font-normal text-ink-muted">{unit}</span> : null}
      </p>
      {caption ? <p className="text-xs leading-relaxed text-ink-muted">{caption}</p> : null}
    </Card>
  );
}
