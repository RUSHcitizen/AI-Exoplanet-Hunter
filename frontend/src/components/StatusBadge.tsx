/**
 * A status indicator that always pairs color with an icon and a label --
 * per the project's dataviz conventions, status color never carries
 * meaning alone (colorblind users, and anyone on a washed-out screen,
 * must still be able to read the state).
 */
type Status = "good" | "warning" | "critical";

const STATUS_CONFIG: Record<Status, { color: string; icon: string; label: string }> = {
  good: { color: "var(--status-good)", icon: "●", label: "Online" },
  warning: { color: "var(--status-warning)", icon: "▲", label: "Degraded" },
  critical: { color: "var(--status-critical)", icon: "✕", label: "Offline" },
};

export function StatusBadge({ status }: { status: Status }) {
  const config = STATUS_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-2 text-sm font-medium">
      <span aria-hidden="true" style={{ color: config.color }}>
        {config.icon}
      </span>
      <span style={{ color: config.color }}>{config.label}</span>
    </span>
  );
}
