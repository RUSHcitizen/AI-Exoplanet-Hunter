import Link from "next/link";
import { buttonStyles, Eyebrow } from "@/components/ui";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col items-start justify-center gap-4 px-4 py-24 sm:px-6">
      <Eyebrow>404 · No data at these coordinates</Eyebrow>
      <h1 className="text-2xl font-semibold tracking-tight">This page doesn&rsquo;t exist.</h1>
      <p className="max-w-md text-sm leading-relaxed text-ink-secondary">
        The address may be mistyped, or the page may belong to a pipeline phase that
        hasn&rsquo;t been built yet.
      </p>
      <div className="flex flex-wrap gap-2">
        <Link href="/" className={buttonStyles.primary}>
          Back to overview
        </Link>
        <Link href="/demo/pi-mensae" className={buttonStyles.secondary}>
          Open the Pi Mensae observation
        </Link>
      </div>
    </main>
  );
}
