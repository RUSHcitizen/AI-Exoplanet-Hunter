import { Card } from "@/components/ui";

/** Layout-shaped placeholder so the page doesn't jump when data arrives. */
export function DemoSkeleton() {
  return (
    <div className="flex flex-col gap-10" aria-hidden="true">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i} className="flex flex-col gap-3 p-4">
            <span className="skeleton h-3 w-24" />
            <span className="skeleton h-7 w-20" />
            <span className="skeleton h-3 w-28" />
          </Card>
        ))}
      </div>
      <Card className="p-5">
        <span className="skeleton block h-8 w-64" />
        <span className="skeleton mt-5 block h-[300px] w-full" />
      </Card>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }, (_, i) => (
          <Card key={i} className="flex flex-col gap-3 p-4">
            <span className="skeleton h-3 w-16" />
            <span className="skeleton h-4 w-28" />
            <span className="skeleton h-6 w-16" />
          </Card>
        ))}
      </div>
    </div>
  );
}

export function LoadingNotice() {
  return (
    <p role="status" className="flex items-center gap-2.5 text-sm text-ink-secondary">
      <span
        aria-hidden="true"
        className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent/30 border-t-accent"
      />
      Loading pipeline results…
    </p>
  );
}
