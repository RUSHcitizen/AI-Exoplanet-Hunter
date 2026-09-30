import Link from "next/link";
import type { DemoIdentity } from "@/lib/api";
import { CopyButton } from "@/components/CopyButton";
import { Badge, ExternalLink } from "@/components/ui";
import { MAST_PORTAL_TIC } from "@/lib/reference";

export function ObservationHeader({ identity }: { identity?: DemoIdentity }) {
  const sector = identity?.sector ?? 1;
  const tic = identity?.tic_id ?? 261136679;
  const location =
    identity?.camera != null && identity?.ccd != null
      ? ` · Camera ${identity.camera}, CCD ${identity.ccd}`
      : "";

  return (
    <header className="flex flex-col gap-5">
      <nav aria-label="Breadcrumb" className="text-xs text-ink-muted">
        <ol className="flex items-center gap-1.5">
          <li>
            <Link href="/" className="rounded hover:text-ink-primary">
              Overview
            </Link>
          </li>
          <li aria-hidden="true">/</li>
          <li aria-current="page" className="text-ink-secondary">
            Pi Mensae
          </li>
        </ol>
      </nav>

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="good" icon="●">
            Real TESS data
          </Badge>
          <Badge tone="neutral">Read-only</Badge>
          <Badge tone="warning" icon="▲">
            Preprocessing only — no transit search yet
          </Badge>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight text-ink-primary sm:text-4xl">
          Pi Mensae
          <span className="ml-3 align-middle text-base font-normal text-ink-muted sm:text-lg">
            π Men · HD 39091
          </span>
        </h1>
        <p className="max-w-3xl text-sm leading-relaxed text-ink-secondary sm:text-base">
          A bright, Sun-like star 18 parsecs away known to host at least two planets. This page shows
          its TESS Sector {sector} light curve after quality filtering, gap-aware segmentation,
          per-segment normalization, and robust outlier flagging — the stages of this pipeline
          that exist today.
        </p>
        <p className="text-sm text-ink-muted tabular">
          TIC {tic} · TESS Sector {sector}
          {location} · {identity?.pipeline ?? "SPOC"} 2-minute cadence ·{" "}
          {identity?.flux_column ?? "PDCSAP_FLUX"}
        </p>
      </div>

      {identity && (
        <dl className="grid gap-x-6 gap-y-3 rounded-xl border border-line-hairline bg-surface-1/60 p-4 text-sm sm:grid-cols-2 lg:grid-cols-[1.2fr_2fr_auto]">
          <div className="min-w-0">
            <dt className="text-xs text-ink-muted">Source file</dt>
            <dd className="mt-0.5 truncate font-mono text-xs text-ink-primary" title={identity.source_filename}>
              {identity.source_filename}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs text-ink-muted">Source SHA-256</dt>
            <dd className="mt-0.5 flex items-center gap-2">
              <span
                className="min-w-0 truncate font-mono text-xs text-ink-primary"
                title={identity.source_checksum_sha256}
              >
                {identity.source_checksum_sha256}
              </span>
              <CopyButton value={identity.source_checksum_sha256} label="Copy SHA-256" />
            </dd>
          </div>
          <div>
            <dt className="text-xs text-ink-muted">Archive</dt>
            <dd className="mt-0.5 text-xs">
              <ExternalLink href={MAST_PORTAL_TIC.href}>MAST Portal</ExternalLink>
            </dd>
          </div>
        </dl>
      )}
    </header>
  );
}
