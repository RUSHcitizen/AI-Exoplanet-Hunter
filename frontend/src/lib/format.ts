/** Shared number/label formatting so every screen speaks the same units. */

export function formatInt(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US");
}

export function formatPercent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatFixed(value: number | null | undefined, digits: number): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A duration in days, rendered in the most readable unit. */
export function formatDuration(days: number): string {
  if (!Number.isFinite(days)) return "—";
  const minutes = days * 1440;
  if (minutes < 60) return `${minutes.toFixed(minutes < 10 ? 1 : 0)} min`;
  const hours = minutes / 60;
  if (hours < 48) return `${hours.toFixed(hours < 10 ? 2 : 1)} h`;
  return `${days.toFixed(2)} d`;
}

/** Normalized flux (baseline ≈ 1) as a signed ppm offset from 1. */
export function formatPpmOffset(normalizedFlux: number): string {
  const ppm = (normalizedFlux - 1) * 1e6;
  const rounded = Math.round(ppm);
  return `${rounded > 0 ? "+" : rounded < 0 ? "−" : "±"}${Math.abs(rounded).toLocaleString("en-US")} ppm`;
}

/** "matched_quality_bits" → "Matched quality bits". */
export function humanize(identifier: string): string {
  const text = identifier.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}
