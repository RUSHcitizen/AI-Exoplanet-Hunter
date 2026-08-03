/**
 * Shared error/empty-state panel for the demo page -- used whenever the
 * backend is unreachable, the cached FITS file is missing, or the
 * response could not be parsed. Never paired with fabricated zero
 * values: the caller renders this instead of the data panels, not
 * alongside them.
 */
export function DemoErrorState({ title, message }: { title: string; message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-status-critical/40 bg-surface-1 p-5 text-sm"
    >
      <p className="font-medium text-status-critical">{title}</p>
      <p className="mt-2 text-ink-secondary">{message}</p>
    </div>
  );
}
