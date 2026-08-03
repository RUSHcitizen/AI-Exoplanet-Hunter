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
  onRetryNow,
}: {
  attempt: number;
  onRetryNow: () => void;
}) {
  return (
    <div
      role="status"
      aria-label="Waking the science backend"
      className="rounded-lg border border-white/10 bg-surface-1 p-5 text-sm"
    >
      <p className="font-medium text-ink-primary">
        Waking the science backend. This can take up to about one minute on the free
        demonstration service.
      </p>
      <p className="mt-2 text-xs text-ink-muted">Retry attempt {attempt}…</p>
      <button
        type="button"
        onClick={onRetryNow}
        className="mt-4 rounded-md border border-white/20 px-3 py-1.5 text-sm font-medium text-ink-primary hover:bg-white/5"
      >
        Retry now
      </button>
    </div>
  );
}
