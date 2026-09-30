/**
 * A schematic of how a transit dims a star. Explicitly an illustration:
 * idealized geometry and an idealized curve, not observational data.
 */
export function TransitIllustration() {
  // Idealized trapezoidal transit with limb-darkening-like rounding.
  const points: string[] = [];
  for (let i = 0; i <= 120; i += 1) {
    const x = (i / 120) * 360;
    const u = (x - 180) / 70;
    const inTransit = Math.abs(u) < 1;
    const depth = inTransit ? 30 * Math.sqrt(Math.max(0, 1 - u ** 8)) * (0.85 + 0.15 * (1 - u * u)) : 0;
    points.push(`${x.toFixed(1)},${(40 + depth).toFixed(1)}`);
  }
  return (
    <figure className="relative mx-auto w-full max-w-md">
      <div className="relative overflow-hidden rounded-2xl border border-line-hairline bg-surface-1 p-6">
        <svg viewBox="0 0 360 250" className="w-full" aria-hidden="true">
          <defs>
            <radialGradient id="star-limb" cx="50%" cy="50%" r="50%">
              <stop offset="0%" stopColor="#fff8e7" />
              <stop offset="70%" stopColor="#f6d9a0" />
              <stop offset="100%" stopColor="#d9a55a" />
            </radialGradient>
          </defs>
          <g transform="translate(180 82)">
            <circle r="58" fill="url(#star-limb)" />
            <ellipse rx="150" ry="14" fill="none" stroke="rgba(85,152,231,0.45)" strokeWidth="1" />
            <circle cx="-8" cy="12" r="9" fill="#0a0b0d" />
          </g>
          <g transform="translate(0 168)">
            <line x1="0" x2="360" y1="40" y2="40" stroke="#24262b" />
            <polyline points={points.join(" ")} fill="none" stroke="#b7d3f6" strokeWidth="2" />
            <text x="0" y="28" fontSize="10" fill="#8d8c86">brightness</text>
            <text x="360" y="80" fontSize="10" fill="#8d8c86" textAnchor="end">time →</text>
          </g>
        </svg>
      </div>
      <figcaption className="mt-2 text-center text-xs text-ink-muted">
        Schematic only — a planet crossing its star blocks a tiny fraction of the light. For π Men c
        the real dip is ≈ 0.03%, far shallower than drawn.
      </figcaption>
    </figure>
  );
}
