import type {
  DemoNormalizationSummary,
  DemoOutlierSummary,
  DemoQualityFilterSummary,
  DemoSegmentationSummary,
  QualityBitDetail,
} from "@/lib/api";
import { formatFixed, formatInt, formatPercent, humanize } from "@/lib/format";
import { Card, Field, KindTag } from "@/components/ui";

function Panel({
  headingId,
  title,
  phase,
  children,
}: {
  headingId: string;
  title: string;
  phase: string;
  children: React.ReactNode;
}) {
  return (
    <Card as="section" aria-labelledby={headingId} className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 id={headingId} className="text-sm font-semibold text-ink-primary">
          {title}
        </h3>
        <span className="text-xs text-ink-muted">Phase {phase}</span>
      </div>
      {children}
    </Card>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="text-xs leading-relaxed text-ink-muted">{children}</p>;
}

/** Fall back to the undecoded counts from an older backend. */
function qualityBits(quality: DemoQualityFilterSummary): QualityBitDetail[] {
  if (quality.matched_quality_bits && quality.matched_quality_bits.length > 0) {
    return quality.matched_quality_bits;
  }
  return Object.entries(quality.matched_quality_bit_counts)
    .map(([value, count]) => ({
      bit_value: Number(value),
      bit_number: Math.log2(Number(value)) + 1,
      description: null,
      rejected_cadence_count: count,
    }))
    .sort((a, b) => a.bit_value - b.bit_value);
}

export function QualitySummary({ quality }: { quality: DemoQualityFilterSummary }) {
  const total = quality.retained_cadence_count + quality.rejected_cadence_count;
  const bits = qualityBits(quality);
  const maxBitCount = Math.max(1, ...bits.map((b) => b.rejected_cadence_count));
  const reasons = Object.entries(quality.rejection_counts_by_reason);

  return (
    <Panel headingId="quality-heading" title="Quality filtering" phase="3A">
      <div>
        <div className="flex items-baseline justify-between text-xs">
          <span className="text-ink-secondary">
            <span className="font-semibold text-ink-primary tabular">
              {formatInt(quality.retained_cadence_count)}
            </span>{" "}
            retained
          </span>
          <span className="text-ink-secondary">
            <span className="font-semibold text-ink-primary tabular">
              {formatInt(quality.rejected_cadence_count)}
            </span>{" "}
            rejected
          </span>
        </div>
        <div
          className="mt-2 flex h-2 gap-0.5 overflow-hidden rounded-full"
          role="img"
          aria-label={`${formatPercent(quality.retained_fraction)} of ${formatInt(total)} cadences retained`}
        >
          <span
            className="h-full rounded-l-full bg-series-observation"
            style={{ width: `${quality.retained_fraction * 100}%` }}
          />
          <span className="h-full flex-1 rounded-r-full bg-ink-muted/40" />
        </div>
        <p className="mt-1.5 text-xs text-ink-muted">
          {formatPercent(quality.retained_fraction)} of {formatInt(total)} cadences kept
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-3">
        <Field label="Policy" value={quality.quality_policy.toUpperCase()} hint="MAST-recommended" />
        <Field
          label="Mask"
          value={`${quality.quality_bitmask_decimal} (${quality.quality_bitmask_hex})`}
        />
      </dl>

      <div>
        <p className="text-xs font-medium text-ink-secondary">Rejections by reason</p>
        <ul className="mt-1.5 flex flex-col gap-1 text-xs">
          {reasons.map(([reason, count]) => (
            <li key={reason} className="flex justify-between gap-3 text-ink-secondary">
              <span>{humanize(reason)}</span>
              <span className="text-ink-primary tabular">{formatInt(count)}</span>
            </li>
          ))}
        </ul>
        {reasons.length > 1 && (
          <Note>
            A cadence can have more than one reason (e.g. flagged <em>and</em> non-finite), so
            these counts overlap and can sum to more than the {formatInt(quality.rejected_cadence_count)} rejected.
          </Note>
        )}
      </div>

      {bits.length > 0 && (
        <div>
          <p className="text-xs font-medium text-ink-secondary">TESS quality bits that matched</p>
          <ul className="mt-2 flex flex-col gap-2">
            {bits.map((bit) => (
              <li key={bit.bit_value} className="text-xs">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 text-ink-secondary">
                    <span className="font-mono text-ink-muted">bit {bit.bit_number}</span>{" "}
                    <span className="text-ink-primary">
                      {bit.description ?? `value ${bit.bit_value}`}
                    </span>
                  </span>
                  <span className="shrink-0 text-ink-primary tabular">
                    {formatInt(bit.rejected_cadence_count)}
                  </span>
                </div>
                <span aria-hidden="true" className="mt-1 block h-1 overflow-hidden rounded-full bg-surface-3">
                  <span
                    className="block h-full rounded-full bg-ink-muted/70"
                    style={{ width: `${(bit.rejected_cadence_count / maxBitCount) * 100}%` }}
                  />
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Note>
        Every rejected cadence remains traceable to its original row and matched quality bits —
        none were deleted from the source file.
      </Note>
    </Panel>
  );
}

export function SegmentationSummary({
  segmentation,
}: {
  segmentation: DemoSegmentationSummary;
}) {
  return (
    <Panel headingId="segmentation-heading" title="Segmentation" phase="3B">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="Segments" value={formatInt(segmentation.segment_count)} />
        <Field label="Gaps" value={formatInt(segmentation.gap_count)} />
        <Field
          label="Measured cadence"
          kind="calculated"
          value={
            segmentation.measured_nominal_cadence_seconds !== null
              ? `${segmentation.measured_nominal_cadence_seconds.toFixed(2)} s`
              : "unavailable"
          }
        />
        <Field
          label="Header cadence"
          kind="observed"
          value={
            segmentation.metadata_cadence_seconds !== null
              ? `${formatFixed(segmentation.metadata_cadence_seconds, 2)} s`
              : "unavailable"
          }
        />
        <Field
          label="Estimated missing cadences"
          value={formatInt(segmentation.estimated_missing_cadence_count)}
        />
      </dl>
      <Note>
        A gap is any interval longer than 5× the measured median cadence. Gaps are never filled or
        interpolated — each segment is normalized and analyzed independently of every other.
      </Note>
    </Panel>
  );
}

export function NormalizationSummary({
  normalization,
}: {
  normalization: DemoNormalizationSummary;
}) {
  return (
    <Panel headingId="normalization-heading" title="Normalization" phase="3C">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="Normalized segments" value={formatInt(normalization.normalized_segment_count)} />
        <Field
          label="Invalid-reference segments"
          value={formatInt(normalization.invalid_reference_segment_count)}
        />
        <Field
          label="Reference range (e⁻/s)"
          value={
            normalization.segment_reference_min !== null &&
            normalization.segment_reference_max !== null
              ? `${formatFixed(normalization.segment_reference_min, 0)} – ${formatFixed(normalization.segment_reference_max, 0)}`
              : "unavailable"
          }
        />
        <Field
          label="Reference median (e⁻/s)"
          value={formatFixed(normalization.segment_reference_median, 0)}
        />
      </dl>
      <Note>
        Each segment was divided by its own median PDCSAP flux, so every segment&rsquo;s baseline
        sits at ≈ 1.0 — no segment&rsquo;s normalization depends on any other segment&rsquo;s data.
      </Note>
    </Panel>
  );
}

export function OutlierSummary({ outliers }: { outliers: DemoOutlierSummary }) {
  const unanalyzed =
    outliers.insufficient_data_segment_count +
    outliers.zero_scale_segment_count +
    outliers.normalization_unavailable_segment_count;
  return (
    <Panel headingId="outlier-heading" title="Outlier flagging" phase="3D">
      <dl className="grid grid-cols-2 gap-3">
        <Field label="High outliers" value={formatInt(outliers.high_outlier_count)} />
        <Field label="Low outliers" value={formatInt(outliers.low_outlier_count)} />
        <Field label="Upper threshold" value={`${outliers.upper_threshold} × robust σ`} />
        <Field
          label="Lower-side detection"
          value={
            outliers.lower_detection_enabled
              ? `enabled (${outliers.lower_threshold})`
              : "disabled (default)"
          }
        />
        <Field label="Segments analyzed" value={formatInt(outliers.valid_segment_count)} />
        <Field
          label="Segments not analyzed"
          value={formatInt(unanalyzed)}
          hint={
            outliers.insufficient_data_segment_count > 0
              ? `${formatInt(outliers.insufficient_data_segment_count)} too short`
              : undefined
          }
        />
      </dl>
      <p className="flex gap-2 rounded-lg border border-status-warning/25 bg-status-warning/[0.06] px-3 py-2 text-xs font-medium leading-relaxed text-status-warning">
        <span aria-hidden="true">▲</span>
        <span>
          Lower-side (downward) outlier detection is disabled by default, so a real transit-like
          dip is never flagged as an artifact.
        </span>
      </p>
      <Note>
        This stage only flags cadences — every cadence, flagged or not, remains present in the data
        with its original value unchanged. <KindTag kind="calculated" className="ml-1 align-middle" />
      </Note>
    </Panel>
  );
}
