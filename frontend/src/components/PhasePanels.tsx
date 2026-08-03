import type {
  DemoNormalizationSummary,
  DemoOutlierSummary,
  DemoQualityFilterSummary,
  DemoSegmentationSummary,
} from "@/lib/api";

function Panel({
  headingId,
  title,
  children,
}: {
  headingId: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-white/10 bg-surface-1 p-5"
    >
      <h3 id={headingId} className="text-sm font-medium text-ink-secondary">
        {title}
      </h3>
      {children}
    </section>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink-muted">{label}</dt>
      <dd className="text-sm text-ink-primary [font-variant-numeric:tabular-nums]">{value}</dd>
    </div>
  );
}

export function QualitySummary({ quality }: { quality: DemoQualityFilterSummary }) {
  return (
    <Panel headingId="quality-heading" title="Quality filtering (Phase 3A)">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="Policy" value={quality.quality_policy} />
        <Field
          label="Mask"
          value={`${quality.quality_bitmask_decimal} (${quality.quality_bitmask_hex})`}
        />
        <Field label="Retained" value={quality.retained_cadence_count.toLocaleString()} />
        <Field label="Rejected" value={quality.rejected_cadence_count.toLocaleString()} />
      </dl>
      <div>
        <p className="text-xs text-ink-muted">Rejections by reason</p>
        <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-secondary">
          {Object.entries(quality.rejection_counts_by_reason).map(([reason, count]) => (
            <li key={reason}>
              {reason.replaceAll("_", " ")}: {count.toLocaleString()}
            </li>
          ))}
        </ul>
      </div>
      <p className="text-xs text-ink-muted">
        Every rejected cadence remains traceable to its original row and matched quality bits --
        none were deleted from the source file.
      </p>
    </Panel>
  );
}

export function SegmentationSummary({
  segmentation,
}: {
  segmentation: DemoSegmentationSummary;
}) {
  return (
    <Panel headingId="segmentation-heading" title="Segmentation (Phase 3B)">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="Segments" value={segmentation.segment_count} />
        <Field label="Gaps" value={segmentation.gap_count} />
        <Field
          label="Measured cadence"
          value={
            segmentation.measured_nominal_cadence_seconds !== null
              ? `${segmentation.measured_nominal_cadence_seconds.toFixed(2)} s`
              : "unavailable"
          }
        />
        <Field
          label="Estimated missing cadences"
          value={segmentation.estimated_missing_cadence_count.toLocaleString()}
        />
      </dl>
      <p className="text-xs text-ink-muted">
        Gaps are never filled or interpolated -- each segment is normalized and analyzed
        independently of every other.
      </p>
    </Panel>
  );
}

export function NormalizationSummary({
  normalization,
}: {
  normalization: DemoNormalizationSummary;
}) {
  return (
    <Panel headingId="normalization-heading" title="Normalization (Phase 3C)">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="Normalized segments" value={normalization.normalized_segment_count} />
        <Field
          label="Invalid-reference segments"
          value={normalization.invalid_reference_segment_count}
        />
        <Field
          label="Reference range"
          value={
            normalization.segment_reference_min !== null &&
            normalization.segment_reference_max !== null
              ? `${normalization.segment_reference_min.toLocaleString()} – ${normalization.segment_reference_max.toLocaleString()}`
              : "unavailable"
          }
        />
        <Field
          label="Reference median"
          value={normalization.segment_reference_median?.toLocaleString() ?? "unavailable"}
        />
      </dl>
      <p className="text-xs text-ink-muted">
        Each segment was normalized independently to its own median flux -- no segment&rsquo;s
        normalization depends on any other segment&rsquo;s data.
      </p>
    </Panel>
  );
}

export function OutlierSummary({ outliers }: { outliers: DemoOutlierSummary }) {
  return (
    <Panel headingId="outlier-heading" title="Outlier flagging (Phase 3D)">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="High outliers" value={outliers.high_outlier_count} />
        <Field label="Low outliers" value={outliers.low_outlier_count} />
        <Field label="Upper threshold" value={outliers.upper_threshold} />
        <Field
          label="Lower-side detection"
          value={
            outliers.lower_detection_enabled
              ? `enabled (${outliers.lower_threshold})`
              : "disabled (default)"
          }
        />
      </dl>
      <p className="text-xs font-medium text-status-warning">
        Lower-side (downward) outlier detection is disabled by default, so a real transit-like dip
        is never flagged as an artifact.
      </p>
      <p className="text-xs text-ink-muted">
        This stage only flags cadences -- every cadence, flagged or not, remains present in the
        data with its original value unchanged.
      </p>
    </Panel>
  );
}
