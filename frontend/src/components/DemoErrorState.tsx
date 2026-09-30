import { buttonStyles, Card } from "@/components/ui";

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
    <Card className="border-status-critical/35">
      <div role="alert" className="flex items-start gap-3 p-5 text-sm">
        <span
          aria-hidden="true"
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-status-critical/15 text-xs text-status-critical"
        >
          ✕
        </span>
        <div className="min-w-0">
          <p className="font-medium text-status-critical">{title}</p>
          <p className="mt-1 leading-relaxed text-ink-secondary">{message}</p>
          <p className="mt-2 text-xs text-ink-muted">
            No values are shown because none were received — this page never substitutes
            placeholder data.
          </p>
          {onRetry && (
            <button type="button" onClick={onRetry} className={`${buttonStyles.secondary} mt-4`}>
              Retry
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
