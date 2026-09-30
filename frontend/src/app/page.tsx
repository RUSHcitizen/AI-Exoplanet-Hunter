import Link from "next/link";
import { BackendStatusCard } from "@/components/BackendStatusCard";
import { ResultKindLegend } from "@/components/ResultKindLegend";
import { TransitIllustration } from "@/components/TransitIllustration";
import { Badge, buttonStyles, Card, Eyebrow, SectionHeader } from "@/components/ui";
import { PIPELINE_STAGES } from "@/lib/pipeline";

const PRINCIPLES = [
  {
    title: "Nothing is called a planet without confirmation",
    body: "Unmatched signals are reported as candidates, never as discoveries. Literature values are always labelled as such.",
  },
  {
    title: "Original observations are never modified",
    body: "Every stage flags or groups cadences; the source FITS file is opened read-only and checksummed.",
  },
  {
    title: "Every step is recorded and reproducible",
    body: "Processing history records code version, configuration, and counts in and out for each stage.",
  },
  {
    title: "Limitations are shown, not hidden",
    body: "Each result page lists what has not been done yet — no detrending, no transit search, no model inference.",
  },
];

export default function OverviewPage() {
  const completed = PIPELINE_STAGES.filter((s) => s.status === "complete");
  const planned = PIPELINE_STAGES.filter((s) => s.status === "planned");

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-16 px-4 pb-8 pt-10 sm:px-6 sm:pt-16">
      <section className="grid items-center gap-10 lg:grid-cols-[1.15fr_1fr]">
        <div className="flex flex-col gap-5">
          <Eyebrow>TESS light-curve research pipeline</Eyebrow>
          <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight text-ink-primary sm:text-5xl">
            Hunting for transiting exoplanets in NASA TESS photometry.
          </h1>
          <p className="max-w-xl text-base leading-relaxed text-ink-secondary">
            Exoplanet Hunter turns raw space-telescope light curves into analysis-ready data — one
            validated, fully traceable stage at a time. The preprocessing pipeline runs today on
            real observations; transit search and machine-learning candidate ranking are next.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Link href="/demo/pi-mensae" className={buttonStyles.primary}>
              Explore the Pi Mensae light curve
              <span aria-hidden="true">→</span>
            </Link>
            <a href="#roadmap" className={buttonStyles.secondary}>
              See what&rsquo;s built
            </a>
          </div>
        </div>
        <TransitIllustration />
      </section>

      <section aria-labelledby="featured-heading" className="flex flex-col gap-4">
        <SectionHeader
          id="featured-heading"
          eyebrow="Featured observation"
          title="Pi Mensae · TESS Sector 1"
        />
        <Link
          href="/demo/pi-mensae"
          className="group block rounded-xl focus-visible:outline-offset-4"
          aria-label="Open the Pi Mensae TESS Sector 1 observation"
        >
          <Card className="grid gap-6 p-5 transition-colors group-hover:border-line-strong sm:p-6 md:grid-cols-[1.4fr_1fr]">
            <div className="flex flex-col gap-3">
              <div className="flex flex-wrap gap-2">
                <Badge tone="good" icon="●">
                  Real TESS data
                </Badge>
                <Badge tone="reference">Host of confirmed planet π Men c</Badge>
              </div>
              <p className="text-sm leading-relaxed text-ink-secondary">
                A naked-eye, Sun-like star whose planet π Men c was among the first discovered by
                TESS. Browse ~28 days of 2-minute photometry, see where the published transits
                fall, and inspect every cadence the pipeline kept, flagged, or rejected.
              </p>
              <span className="mt-auto inline-flex items-center gap-1.5 text-sm font-medium text-accent-ink">
                Open observation
                <span aria-hidden="true" className="transition-transform group-hover:translate-x-0.5">
                  →
                </span>
              </span>
            </div>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              {[
                ["Target", "TIC 261136679"],
                ["Mission", "TESS · SPOC"],
                ["Sector", "1 (Jul–Aug 2018)"],
                ["Cadence", "2 minutes"],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt className="text-xs text-ink-muted">{label}</dt>
                  <dd className="mt-0.5 text-ink-primary">{value}</dd>
                </div>
              ))}
            </dl>
          </Card>
        </Link>
      </section>

      <section id="roadmap" aria-labelledby="roadmap-heading" className="flex flex-col gap-4">
        <SectionHeader
          id="roadmap-heading"
          eyebrow="Pipeline"
          title="What exists today, and what's next"
          description="Stages marked complete run on real data with tests against the cached observation. Planned stages are not implemented — no result on this site comes from them."
        />
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="p-4 sm:p-5">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink-primary">
              <span aria-hidden="true" className="text-status-good">✓</span>
              Complete
            </h3>
            <ol className="mt-3 flex flex-col divide-y divide-line-hairline">
              {completed.map((stage) => (
                <li key={stage.id} className="flex gap-3 py-2.5">
                  <span className="w-8 shrink-0 text-xs text-ink-muted tabular">{stage.phase}</span>
                  <div>
                    <p className="text-sm text-ink-primary">{stage.label}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{stage.description}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Card>
          <Card className="p-4 sm:p-5">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-ink-primary">
              <span aria-hidden="true" className="text-ink-muted">○</span>
              Planned
            </h3>
            <ol className="mt-3 flex flex-col divide-y divide-line-hairline">
              {planned.map((stage) => (
                <li key={stage.id} className="flex gap-3 py-2.5">
                  <span className="w-8 shrink-0 text-xs text-ink-muted tabular">{stage.phase}</span>
                  <div>
                    <p className="text-sm text-ink-secondary">{stage.label}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{stage.description}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </section>

      <section aria-labelledby="principles-heading" className="flex flex-col gap-4">
        <SectionHeader id="principles-heading" eyebrow="Scientific integrity" title="How results are reported" />
        <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
          <ul className="grid gap-3 sm:grid-cols-2">
            {PRINCIPLES.map((principle) => (
              <li key={principle.title}>
                <Card className="h-full p-4">
                  <p className="text-sm font-medium text-ink-primary">{principle.title}</p>
                  <p className="mt-1.5 text-xs leading-relaxed text-ink-secondary">{principle.body}</p>
                </Card>
              </li>
            ))}
          </ul>
          <ResultKindLegend compact />
        </div>
      </section>

      <BackendStatusCard />
    </main>
  );
}
