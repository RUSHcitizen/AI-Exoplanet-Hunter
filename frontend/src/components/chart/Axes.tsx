/**
 * Shared SVG axis layer: solid hairline grid, a baseline, and tick
 * labels in tabular figures. Purely presentational (aria-hidden); each
 * chart supplies its own accessible summary.
 */

export interface PlotBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

export function Axes({
  box,
  xTicks,
  yTicks,
  xFor,
  yFor,
  formatX,
  formatY,
  xTitle,
  yTitle,
}: {
  box: PlotBox;
  xTicks: number[];
  yTicks: number[];
  xFor: (v: number) => number;
  yFor: (v: number) => number;
  formatX: (v: number) => string;
  formatY: (v: number) => string;
  xTitle: string;
  yTitle: string;
}) {
  const bottom = box.top + box.height;
  const right = box.left + box.width;
  return (
    <g aria-hidden="true" fontSize={10.5} fill="var(--ink-muted)" className="tabular">
      {yTicks.map((tick) => {
        const y = yFor(tick);
        if (y < box.top - 0.5 || y > bottom + 0.5) return null;
        return (
          <g key={`y${tick}`}>
            <line x1={box.left} x2={right} y1={y} y2={y} stroke="var(--grid-line)" />
            <text x={box.left - 8} y={y} dy="0.32em" textAnchor="end">
              {formatY(tick)}
            </text>
          </g>
        );
      })}
      {xTicks.map((tick) => {
        const x = xFor(tick);
        if (x < box.left - 0.5 || x > right + 0.5) return null;
        return (
          <g key={`x${tick}`}>
            <line x1={x} x2={x} y1={bottom} y2={bottom + 4} stroke="var(--axis-line)" />
            <text x={x} y={bottom + 16} textAnchor="middle">
              {formatX(tick)}
            </text>
          </g>
        );
      })}
      <line x1={box.left} x2={right} y1={bottom} y2={bottom} stroke="var(--axis-line)" />
      <text x={4} y={box.top - 12} textAnchor="start" fill="var(--ink-secondary)">
        {yTitle}
      </text>
      <text x={right} y={bottom + 32} textAnchor="end" fill="var(--ink-secondary)">
        {xTitle}
      </text>
    </g>
  );
}
