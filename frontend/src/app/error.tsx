"use client";

import Link from "next/link";
import { buttonStyles, Eyebrow } from "@/components/ui";

/** Route-level error boundary for unexpected rendering failures (network
 * and API failures are handled in-page with their own retry states). */
export default function RouteError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col items-start justify-center gap-4 px-4 py-24 sm:px-6">
      <Eyebrow>Unexpected error</Eyebrow>
      <h1 className="text-2xl font-semibold tracking-tight">This view failed to render.</h1>
      <p className="max-w-md text-sm leading-relaxed text-ink-secondary">
        Nothing was changed on the server. Try again, or return to the overview.
        {error.digest ? (
          <span className="mt-2 block font-mono text-xs text-ink-muted">
            Reference: {error.digest}
          </span>
        ) : null}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => unstable_retry()} className={buttonStyles.primary}>
          Try again
        </button>
        <Link href="/" className={buttonStyles.secondary}>
          Back to overview
        </Link>
      </div>
    </main>
  );
}
