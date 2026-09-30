"use client";

import { useEffect, useRef, useState } from "react";
import { cx } from "@/components/ui";

/** Copies `value` to the clipboard and confirms (visually and to screen
 * readers) for a moment; reports failure instead of pretending to work. */
export function CopyButton({
  value,
  label = "Copy",
  className,
}: {
  value: string;
  label?: string;
  className?: string;
}) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
    } catch {
      setState("failed");
    }
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 1800);
  }

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`${label}: ${value}`}
      className={cx(
        "inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-line-hairline px-2 text-[11px] font-medium text-ink-secondary transition-colors hover:border-line-strong hover:text-ink-primary",
        state === "copied" && "border-status-good/40 text-status-good",
        state === "failed" && "border-status-critical/40 text-status-critical",
        className,
      )}
    >
      <span aria-hidden="true">{state === "copied" ? "✓" : state === "failed" ? "✕" : "⧉"}</span>
      <span aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : "Copy"}
      </span>
    </button>
  );
}
