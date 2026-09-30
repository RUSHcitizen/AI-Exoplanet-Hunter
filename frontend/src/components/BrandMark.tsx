/** Project mark: a star with a transiting planet on a tilted orbit. */
export function BrandMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="5.2" fill="#f3f3f1" />
      <ellipse
        cx="12"
        cy="12"
        rx="10.5"
        ry="3.6"
        fill="none"
        stroke="#5598e7"
        strokeWidth="1.2"
        transform="rotate(-18 12 12)"
      />
      <circle cx="9.4" cy="13.2" r="1.7" fill="#0a0b0d" />
    </svg>
  );
}
