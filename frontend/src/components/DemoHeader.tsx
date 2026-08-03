import type { DemoIdentity } from "@/lib/api";

export function DemoHeader({ identity }: { identity: DemoIdentity }) {
  return (
    <header className="flex flex-col gap-3">
      <p className="text-xs font-medium uppercase tracking-widest text-ink-muted">
        AI Exoplanet Hunter
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-ink-primary">Pi Mensae Science Preview</h1>
        <span className="inline-flex items-center rounded-full border border-status-good/40 bg-status-good/10 px-2.5 py-0.5 text-xs font-medium tracking-wide text-status-good">
          READ-ONLY REAL TESS DATA
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-ink-muted">TIC</dt>
          <dd className="text-ink-primary [font-variant-numeric:tabular-nums]">
            {identity.tic_id ?? "unknown"}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted">Sector</dt>
          <dd className="text-ink-primary">TESS Sector {identity.sector ?? "unknown"}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">Source file</dt>
          <dd className="text-ink-primary" title={identity.source_filename}>
            {identity.source_filename}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted">Source SHA-256</dt>
          <dd className="truncate text-ink-primary font-mono text-xs" title={identity.source_checksum_sha256}>
            {identity.source_checksum_sha256}
          </dd>
        </div>
      </dl>
    </header>
  );
}
