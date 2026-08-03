/**
 * Shared error/empty-state panel for the demo page -- used whenever the
 * backend is unreachable, the cached FITS file is missing, or the
 * response could not be parsed. Never paired with fabricated zero
 * values: the caller renders this instead of the data panels, not
 * alongside them. `onRetry`, when given, renders a manual retry button
 * -- available for both a scientific/config error and a backend
 * failure that exhausted its bounded automatic retries.
 */
export function DemoErrorState({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-status-critical/40 bg-surface-1 p-5 text-sm"
    >
      <p className="font-medium text-status-critical">{title}</p>
      <p className="mt-2 text-ink-secondary">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-md border border-white/20 px-3 py-1.5 text-sm font-medium text-ink-primary hover:bg-white/5"
        >
          Retry
        </button>
      )}
    </div>
  );
}
