/**
 * A bare stat tile (headline number, no plot) -- per the dataviz skill,
 * this form needs no legend or hover layer, just a clear label and a
 * value in tabular figures so future real numbers align vertically.
 */
export function StatTile({
  label,
  value,
  caption,
}: {
  label: string;
  value: string;
  caption?: string;
}) {
  return (
    <div className="rounded-lg border border-white/10 bg-surface-1 p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-2 text-3xl font-semibold text-ink-primary [font-variant-numeric:tabular-nums]">
        {value}
      </p>
      {caption ? <p className="mt-1 text-xs text-ink-muted">{caption}</p> : null}
    </div>
  );
}
