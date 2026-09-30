import { ExternalLink } from "@/components/ui";

export function SiteFooter() {
  return (
    <footer className="relative z-10 mt-16 border-t border-line-hairline">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-8 text-xs leading-relaxed text-ink-muted sm:flex-row sm:justify-between sm:px-6">
        <p className="max-w-xl">
          Photometry from NASA&rsquo;s Transiting Exoplanet Survey Satellite (TESS), SPOC pipeline
          products retrieved from the{" "}
          <ExternalLink href="https://archive.stsci.edu/missions-and-data/tess">
            Mikulski Archive for Space Telescopes
          </ExternalLink>
          . This project never labels a signal a confirmed planet without authoritative
          confirmation.
        </p>
        <p className="shrink-0">AI Exoplanet Hunter · MIT License</p>
      </div>
    </footer>
  );
}
