"use client";

import { useEffect, useState } from "react";
import { cx } from "@/components/ui";

/** In-page section navigation; highlights the section in view. */
export function SectionNav({ sections }: { sections: { id: string; label: string }[] }) {
  const [active, setActive] = useState(sections[0]?.id);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]) setActive(visible[0].target.id);
      },
      { rootMargin: "-120px 0px -60% 0px" },
    );
    for (const section of sections) {
      const el = document.getElementById(section.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [sections]);

  return (
    <nav
      aria-label="On this page"
      className="sticky top-14 z-30 -mx-4 border-b border-line-hairline bg-page-plane/85 px-4 backdrop-blur-md sm:-mx-6 sm:px-6"
    >
      <ul className="scrollbar-none flex gap-1 overflow-x-auto py-2">
        {sections.map((section) => (
          <li key={section.id} className="shrink-0">
            <a
              href={`#${section.id}`}
              aria-current={active === section.id ? "location" : undefined}
              className={cx(
                "inline-flex h-8 items-center rounded-md px-2.5 text-xs font-medium transition-colors",
                active === section.id
                  ? "bg-white/[0.07] text-ink-primary"
                  : "text-ink-muted hover:text-ink-primary",
              )}
            >
              {section.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
