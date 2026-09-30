/**
 * Small, dependency-free design-system primitives. Every screen composes
 * these instead of re-declaring border/radius/spacing classes, so the
 * app reads as one product.
 */

import type { ReactNode } from "react";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function Card({
  children,
  className,
  as: Tag = "div",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article" | "aside";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      className={cx(
        "rounded-xl border border-line-hairline bg-surface-1 shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset,0_8px_24px_-12px_rgba(0,0,0,0.6)]",
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
  );
}

export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={cx(
        "text-[11px] font-medium uppercase tracking-[0.14em] text-ink-muted",
        className,
      )}
    >
      {children}
    </p>
  );
}

/** Section heading: eyebrow, title, optional description and actions. */
export function SectionHeader({
  id,
  eyebrow,
  title,
  description,
  actions,
  level = 2,
}: {
  id?: string;
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  level?: 2 | 3;
}) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-3xl">
        {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
        <Heading
          id={id}
          className={cx(
            "font-semibold tracking-tight text-ink-primary",
            level === 2 ? "mt-1 text-lg sm:text-xl" : "text-base",
          )}
        >
          {title}
        </Heading>
        {description ? (
          <div className="mt-1.5 text-sm leading-relaxed text-ink-secondary">{description}</div>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap gap-2">{actions}</div> : null}
    </div>
  );
}

type BadgeTone = "neutral" | "good" | "warning" | "critical" | "accent" | "reference";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "border-line-strong text-ink-secondary bg-white/[0.03]",
  good: "border-status-good/35 text-status-good bg-status-good/10",
  warning: "border-status-warning/35 text-status-warning bg-status-warning/10",
  critical: "border-status-critical/35 text-status-critical bg-status-critical/10",
  accent: "border-accent/35 text-accent-ink bg-accent/10",
  reference: "border-kind-reference/35 text-kind-reference bg-kind-reference/10",
};

export function Badge({
  children,
  tone = "neutral",
  icon,
  className,
}: {
  children: ReactNode;
  tone?: BadgeTone;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-medium",
        BADGE_TONES[tone],
        className,
      )}
    >
      {icon ? <span aria-hidden="true">{icon}</span> : null}
      {children}
    </span>
  );
}

/**
 * Where a displayed value comes from. Shown next to numbers so a reader
 * can always tell a measurement from a derived statistic, a published
 * literature value, or (in later phases) a model output.
 */
export type ResultKind = "observed" | "calculated" | "reference" | "model";

export const RESULT_KINDS: Record<
  ResultKind,
  { label: string; description: string; className: string; glyph: string }
> = {
  observed: {
    label: "Observed",
    description: "Measured by TESS and read directly from the FITS file.",
    className: "text-kind-observed border-kind-observed/30",
    glyph: "●",
  },
  calculated: {
    label: "Calculated",
    description:
      "Derived deterministically from the observed data by this pipeline or for display (counts, medians, bins).",
    className: "text-kind-calculated border-kind-calculated/30",
    glyph: "◆",
  },
  reference: {
    label: "Literature",
    description:
      "Published values from peer-reviewed papers. Not produced or verified by this pipeline.",
    className: "text-kind-reference border-kind-reference/30",
    glyph: "■",
  },
  model: {
    label: "Model prediction",
    description:
      "Output of a trained model. No machine-learning model is part of the pipeline yet, so nothing on this site carries this tag.",
    className: "text-kind-model border-kind-model/30",
    glyph: "▲",
  },
};

export function KindTag({ kind, className }: { kind: ResultKind; className?: string }) {
  const config = RESULT_KINDS[kind];
  return (
    <span
      title={config.description}
      className={cx(
        "inline-flex items-center gap-1 rounded border px-1.5 py-px text-[10px] font-medium uppercase tracking-wider",
        config.className,
        className,
      )}
    >
      <span aria-hidden="true" className="text-[8px]">
        {config.glyph}
      </span>
      {config.label}
    </span>
  );
}

const BUTTON_BASE =
  "inline-flex min-h-9 items-center justify-center gap-2 rounded-lg px-3.5 text-sm font-medium transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50";

export const buttonStyles = {
  primary: cx(
    BUTTON_BASE,
    "bg-accent-strong text-white hover:bg-[#2a78d6] active:bg-[#1c5cab] shadow-[0_1px_0_0_rgba(255,255,255,0.12)_inset]",
  ),
  secondary: cx(
    BUTTON_BASE,
    "border border-line-strong bg-white/[0.03] text-ink-primary hover:border-white/25 hover:bg-white/[0.06]",
  ),
  ghost: cx(BUTTON_BASE, "text-ink-secondary hover:bg-white/[0.05] hover:text-ink-primary"),
};

/** Definition-list row used across stat panels. */
export function Field({
  label,
  value,
  kind,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  kind?: ResultKind;
  hint?: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1.5 text-xs text-ink-muted">
        {label}
        {kind ? <KindTag kind={kind} className="scale-90" /> : null}
      </dt>
      <dd className="mt-0.5 truncate text-sm text-ink-primary tabular">{value}</dd>
      {hint ? <dd className="mt-0.5 text-xs text-ink-muted">{hint}</dd> : null}
    </div>
  );
}

export function ExternalLink({
  href,
  children,
  className,
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        "inline-flex items-center gap-1 text-accent-ink underline decoration-accent/40 underline-offset-2 hover:decoration-accent-ink",
        className,
      )}
    >
      {children}
      <svg aria-hidden="true" width="10" height="10" viewBox="0 0 10 10" className="opacity-70">
        <path d="M3 1h6v6M9 1L1 9" fill="none" stroke="currentColor" strokeWidth="1.3" />
      </svg>
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}
