import { Card, ExternalLink, KindTag, SectionHeader, Badge } from "@/components/ui";
import {
  HUANG_2018,
  NASA_EXOPLANET_ARCHIVE_PI_MEN,
  PI_MEN_PLANETS,
  PI_MEN_STAR_FACTS,
} from "@/lib/reference";

/** Published context about the target. Explicitly literature, not output. */
export function TargetReference() {
  return (
    <section aria-labelledby="target-heading" className="flex flex-col gap-4">
      <SectionHeader
        id="target-heading"
        eyebrow="Context"
        title="The Pi Mensae system"
        description={
          <>
            Published values for orientation only. None of these numbers were produced by this
            pipeline; see the{" "}
            <ExternalLink href={NASA_EXOPLANET_ARCHIVE_PI_MEN.href}>NASA Exoplanet Archive</ExternalLink>{" "}
            for current parameters and uncertainties.
          </>
        }
        actions={<KindTag kind="reference" />}
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="p-4 sm:p-5">
          <h3 className="text-sm font-semibold text-ink-primary">Host star</h3>
          <dl className="mt-3 flex flex-col divide-y divide-line-hairline text-sm">
            {PI_MEN_STAR_FACTS.map((fact) => (
              <div key={fact.label} className="flex items-baseline justify-between gap-4 py-2">
                <dt className="text-ink-muted">{fact.label}</dt>
                <dd className="text-right text-ink-primary tabular">
                  {fact.value}
                  {fact.note && <span className="block text-xs text-ink-muted">{fact.note}</span>}
                </dd>
              </div>
            ))}
          </dl>
        </Card>
        {PI_MEN_PLANETS.map((planet) => (
          <Card key={planet.name} className="flex flex-col p-4 sm:p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-ink-primary">{planet.name}</h3>
              <Badge tone="good" icon="✓">
                Confirmed planet
              </Badge>
            </div>
            <p className="mt-1 text-xs text-ink-muted">
              {planet.method} · {planet.discovery}
            </p>
            <dl className="mt-3 flex flex-col divide-y divide-line-hairline text-sm">
              {planet.facts.map((fact) => (
                <div key={fact.label} className="flex items-baseline justify-between gap-4 py-2">
                  <dt className="text-ink-muted">{fact.label}</dt>
                  <dd className="text-right text-ink-primary tabular">
                    {fact.value}
                    {fact.note && <span className="block text-xs text-ink-muted">{fact.note}</span>}
                  </dd>
                </div>
              ))}
            </dl>
            <p className="mt-auto pt-3 text-xs leading-relaxed text-ink-muted">
              {planet.transitsInTess
                ? "Transits every ~6.3 days — its predicted windows are overlaid on the light curve above. Confirmed by the literature, not by this pipeline."
                : "Does not transit; detected by the star's radial-velocity wobble, so it leaves no signature in this light curve."}
            </p>
          </Card>
        ))}
      </div>
      <p className="text-xs leading-relaxed text-ink-muted">
        A third, non-transiting planet (π Men d, P ≈ 125 d) has since been reported from radial
        velocities (Hatzes et al. 2022). Transit ephemeris: <ExternalLink href={HUANG_2018.href}>{HUANG_2018.label}</ExternalLink>.
      </p>
    </section>
  );
}
