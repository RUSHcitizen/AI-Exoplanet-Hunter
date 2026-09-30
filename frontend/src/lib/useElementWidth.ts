"use client";

import { useEffect, useRef, useState } from "react";

/** Observes an element's content width (defaults until first measure,
 * which also keeps jsdom tests, lacking layout, deterministic). */
export function useElementWidth<T extends HTMLElement>(initial = 800, min = 240) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry && entry.contentRect.width > 0) {
        setWidth(Math.max(Math.floor(entry.contentRect.width), min));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [min]);
  return [ref, width] as const;
}
