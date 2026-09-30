"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BrandMark } from "@/components/BrandMark";
import { cx } from "@/components/ui";

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/demo/pi-mensae", label: "Pi Mensae observation" },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b border-line-hairline bg-page-plane/80 backdrop-blur-md">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface-3 focus:px-3 focus:py-2 focus:text-sm"
      >
        Skip to content
      </a>
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5 rounded-md">
          <BrandMark />
          <span className="text-sm font-semibold tracking-tight text-ink-primary">
            Exoplanet Hunter
          </span>
        </Link>
        <nav aria-label="Primary">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => {
              const active = item.href === "/" ? pathname === "/" : pathname?.startsWith(item.href);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cx(
                      "inline-flex h-9 items-center rounded-md px-2.5 text-sm transition-colors sm:px-3",
                      active
                        ? "bg-white/[0.07] text-ink-primary"
                        : "text-ink-secondary hover:bg-white/[0.04] hover:text-ink-primary",
                    )}
                  >
                    {item.href === "/demo/pi-mensae" ? (
                      <>
                        <span className="sm:hidden">Pi Mensae</span>
                        <span className="hidden sm:inline">{item.label}</span>
                      </>
                    ) : (
                      item.label
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </header>
  );
}
