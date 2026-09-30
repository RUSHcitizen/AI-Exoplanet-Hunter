"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchHealth, type HealthResponse } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { buttonStyles, Card } from "@/components/ui";

type ConnectionState =
  | { kind: "loading" }
  | { kind: "online"; health: HealthResponse }
  | { kind: "offline"; message: string };

const POLL_INTERVAL_MS = 15_000;

/** Live backend health. Polls only while the tab is visible. */
export function BackendStatusCard() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const health = await fetchHealth();
        if (!cancelled) setConnection({ kind: "online", health });
      } catch (error) {
        if (cancelled) return;
        const message = error instanceof ApiError ? error.message : "Unknown error.";
        setConnection({ kind: "offline", message });
      } finally {
        if (!cancelled) {
          setCheckedAt(new Date().toLocaleTimeString());
          setChecking(false);
        }
      }
    }

    void check();
    const interval = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState === "visible") {
        void check();
      }
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [nonce]);

  return (
    <Card as="section" aria-labelledby="system-status-heading" className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="system-status-heading" className="text-sm font-semibold text-ink-primary">
            Backend connection
          </h2>
          <p className="mt-0.5 text-xs text-ink-muted">The science API that serves pipeline results.</p>
        </div>
        <div className="flex items-center gap-3" aria-live="polite">
          {connection.kind === "loading" ? (
            <span className="text-sm text-ink-muted">Checking…</span>
          ) : (
            <StatusBadge status={connection.kind === "online" ? "good" : "critical"} />
          )}
          <button
            type="button"
            onClick={() => {
              setChecking(true);
              setNonce((n) => n + 1);
            }}
            disabled={checking}
            className={`${buttonStyles.ghost} min-h-8 px-2.5 text-xs`}
          >
            {checking ? "Checking…" : "Check again"}
          </button>
        </div>
      </div>

      {connection.kind === "online" && (
        <dl className="mt-4 grid grid-cols-2 gap-4 border-t border-line-hairline pt-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-ink-muted">Service</dt>
            <dd className="mt-0.5 text-ink-primary">{connection.health.app_name}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-muted">Environment</dt>
            <dd className="mt-0.5 text-ink-primary">{connection.health.environment}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-muted">Last checked</dt>
            <dd className="mt-0.5 text-ink-primary tabular">{checkedAt}</dd>
          </div>
        </dl>
      )}

      {connection.kind === "offline" && (
        <p className="mt-4 border-t border-line-hairline pt-4 text-sm leading-relaxed text-ink-secondary">
          {connection.message} Is the backend running at{" "}
          <code className="rounded bg-surface-3 px-1 py-0.5 font-mono text-xs text-ink-primary">
            {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
          </code>
          ? A free-tier deployment may take up to a minute to wake.
        </p>
      )}
    </Card>
  );
}
