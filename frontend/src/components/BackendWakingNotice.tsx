import { buttonStyles, Card } from "@/components/ui";

/**
 * Shown while the demo page is auto-retrying a request that looks like
 * a temporarily unavailable backend (network error or 5xx) -- most
 * often a Render free-tier instance still waking from sleep. This is
 * deliberately not an error state: it uses `role="status"`, not
 * `role="alert"`, and never implies the pipeline has already returned
 * (or failed to return) real data.
 */
export function BackendWakingNotice({
  attempt,
  elapsedMs,
  maxMs,
  onRetryNow,
}: {
  attempt: number;
  elapsedMs?: number;
  maxMs?: number;
  onRetryNow: () => void;
}) {
  const progress =
    elapsedMs !== undefined && maxMs ? Math.min(1, Math.max(0.04, elapsedMs / maxMs)) : null;
  return (
    <Card>
      <div role="status" aria-label="Waking the science backend" className="p-5 text-sm">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-0.5 h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
          />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-ink-primary">Waking the science backend</p>
            <p className="mt-1 leading-relaxed text-ink-secondary">
              The free demonstration server sleeps when idle and can take up to about one minute
              to start. No data is shown until the real pipeline responds.
            </p>
            {progress !== null && (
              <div className="mt-3 h-1 overflow-hidden rounded-full bg-surface-3" aria-hidden="true">
                <div
                  className="h-full rounded-full bg-accent transition-[width] duration-700 ease-out"
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
            )}
            <p className="mt-2 text-xs text-ink-muted">Retry attempt {attempt}…</p>
          </div>
        </div>
        <button type="button" onClick={onRetryNow} className={`${buttonStyles.secondary} mt-4`}>
          Retry now
        </button>
      </div>
    </Card>
  );
}
