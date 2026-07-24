"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchHealth, type HealthResponse } from "@/lib/api";
import { StatusBadge } from "@/components/StatusBadge";
import { StatTile } from "@/components/StatTile";

type ConnectionState =
  | { kind: "loading" }
  | { kind: "online"; health: HealthResponse }
  | { kind: "offline"; message: string };

export default function MissionControlPage() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const health = await fetchHealth();
        if (!cancelled) {
          setConnection({ kind: "online", health });
          setCheckedAt(new Date().toLocaleTimeString());
        }
      } catch (error) {
        if (!cancelled) {
          const message = error instanceof ApiError ? error.message : "Unknown error.";
          setConnection({ kind: "offline", message });
          setCheckedAt(new Date().toLocaleTimeString());
        }
      }
    }

    void checkHealth();
    const interval = setInterval(checkHealth, 15_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-8 px-6 py-12">
      <header>
        <p className="text-xs font-medium uppercase tracking-widest text-ink-muted">
          AI Exoplanet Hunter
        </p>
        <h1 className="mt-1 text-2xl font-semibold text-ink-primary">Mission Control</h1>
      </header>

      <section
        aria-labelledby="system-status-heading"
        className="rounded-lg border border-white/10 bg-surface-1 p-5"
      >
        <div className="flex items-center justify-between">
          <h2 id="system-status-heading" className="text-sm font-medium text-ink-secondary">
            Backend connection
          </h2>
          {connection.kind === "loading" ? (
            <span className="text-sm text-ink-muted">Checking…</span>
          ) : (
            <StatusBadge status={connection.kind === "online" ? "good" : "critical"} />
          )}
        </div>

        {connection.kind === "online" && (
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-ink-muted">Service</dt>
              <dd className="text-ink-primary">{connection.health.app_name}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Environment</dt>
              <dd className="text-ink-primary">{connection.health.environment}</dd>
            </div>
            <div>
              <dt className="text-ink-muted">Last checked</dt>
              <dd className="text-ink-primary">{checkedAt}</dd>
            </div>
          </dl>
        )}

        {connection.kind === "offline" && (
          <p className="mt-4 text-sm text-ink-secondary">
            {connection.message} Is the backend running at{" "}
            <code className="text-ink-primary">
              {process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}
            </code>
            ?
          </p>
        )}
      </section>

      <section aria-labelledby="overview-heading" className="flex flex-col gap-3">
        <h2 id="overview-heading" className="text-sm font-medium text-ink-secondary">
          Mission overview
        </h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile label="Targets processed" value="—" caption="Phase 2" />
          <StatTile label="Candidates detected" value="—" caption="Phase 4" />
          <StatTile label="Known planets recovered" value="—" caption="Phase 9" />
          <StatTile label="Unmatched signals" value="—" caption="Phase 9" />
        </div>
        <p className="text-xs text-ink-muted">
          These panels are wired up now and will populate once the data pipeline (Phase 2
          onward) starts writing to the database.
        </p>
      </section>
    </main>
  );
}
