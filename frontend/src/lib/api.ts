/**
 * Typed client for the Exoplanet Hunter backend API.
 *
 * `NEXT_PUBLIC_API_URL` is read at build time and baked into the browser
 * bundle (any `NEXT_PUBLIC_*` var is), so it must point somewhere the
 * *browser* can reach -- e.g. `http://localhost:8000` in local dev, even
 * though inside Docker Compose the backend's hostname is `backend`.
 */
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface HealthResponse {
  status: string;
  app_name: string;
  environment: string;
  timestamp: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/health`, { cache: "no-store" });
  } catch (cause) {
    throw new ApiError("Could not reach the backend API.", cause);
  }

  if (!response.ok) {
    throw new ApiError(`Backend returned HTTP ${response.status}.`);
  }

  return (await response.json()) as HealthResponse;
}

/**
 * Typed contracts for the read-only Phase 4A Pi Mensae demo API
 * (`app/api/demo.py`). Field names mirror the backend response models
 * exactly, so a shape mismatch is a compile error here rather than a
 * silent `undefined` in the UI.
 */

export interface DemoIdentity {
  target_name: string;
  tic_id: number | null;
  sector: number | null;
  mission: string | null;
  source_filename: string;
  source_checksum_sha256: string;
  flux_column: string;
  pipeline: string | null;
}

export interface DemoRawStats {
  raw_cadence_count: number;
}

export interface DemoQualityFilterSummary {
  retained_cadence_count: number;
  rejected_cadence_count: number;
  retained_fraction: number;
  quality_policy: string;
  quality_bitmask_decimal: number;
  quality_bitmask_hex: string;
  rejection_counts_by_reason: Record<string, number>;
  matched_quality_bit_counts: Record<string, number>;
}

export interface DemoSegmentationSummary {
  segment_count: number;
  gap_count: number;
  measured_nominal_cadence_days: number | null;
  measured_nominal_cadence_seconds: number | null;
  metadata_cadence_days: number | null;
  metadata_cadence_seconds: number | null;
  estimated_missing_cadence_count: number;
}

export interface DemoNormalizationSummary {
  normalized_segment_count: number;
  invalid_reference_segment_count: number;
  segment_reference_min: number | null;
  segment_reference_median: number | null;
  segment_reference_max: number | null;
}

export interface DemoOutlierSummary {
  valid_segment_count: number;
  insufficient_data_segment_count: number;
  zero_scale_segment_count: number;
  normalization_unavailable_segment_count: number;
  high_outlier_count: number;
  low_outlier_count: number;
  lower_detection_enabled: boolean;
  upper_threshold: number;
  lower_threshold: number | null;
  outlier_fraction: number;
}

export interface ProcessingHistoryEntry {
  step: string;
  code_version: string;
  input_count: number;
  output_count: number;
  configuration_summary: string;
  source_checksum_sha256: string;
}

export interface DemoProvenance {
  processing_history: ProcessingHistoryEntry[];
  source_checksum_sha256: string;
  fits_file_unchanged_statement: string;
  deterministic_processing_statement: string;
}

export interface DemoSummaryResponse {
  identity: DemoIdentity;
  raw: DemoRawStats;
  quality_filter: DemoQualityFilterSummary;
  segmentation: DemoSegmentationSummary;
  normalization: DemoNormalizationSummary;
  outliers: DemoOutlierSummary;
  provenance: DemoProvenance;
  scientific_limitations: string[];
}

export interface DemoLightCurvePoint {
  time: number;
  normalized_flux: number | null;
  original_flux: number;
  source_index: number;
  is_high_outlier: boolean;
  robust_score: number | null;
}

export interface DemoLightCurveSegment {
  segment_number: number;
  start_time: number;
  end_time: number;
  cadence_count: number;
  analysis_status: string;
  points: DemoLightCurvePoint[];
}

export interface DemoGap {
  before_segment_number: number;
  after_segment_number: number;
  start_time: number;
  end_time: number;
  duration_days: number;
  duration_seconds: number;
  reasons: string[];
  estimated_missing_cadences: number | null;
}

export interface DemoLightCurveResponse {
  target_name: string;
  tic_id: number | null;
  sector: number | null;
  segments: DemoLightCurveSegment[];
  gaps: DemoGap[];
}

interface DemoApiErrorDetail {
  error: string;
  message: string;
}

/** True when the backend responded but with an unusable status (missing
 * demo file, invalid FITS, etc.) rather than being unreachable. Lets
 * callers show a specific message instead of a generic "offline" one. */
export class DemoApiError extends ApiError {
  constructor(
    message: string,
    public readonly status: number,
    public readonly errorCode: string | null,
  ) {
    super(message);
    this.name = "DemoApiError";
  }
}

async function fetchDemoJson<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  } catch (cause) {
    throw new ApiError("Could not reach the backend API.", cause);
  }

  if (!response.ok) {
    let detail: DemoApiErrorDetail | null = null;
    try {
      const body = (await response.json()) as { detail?: DemoApiErrorDetail };
      detail = body.detail ?? null;
    } catch {
      detail = null;
    }
    throw new DemoApiError(
      detail?.message ?? `Backend returned HTTP ${response.status}.`,
      response.status,
      detail?.error ?? null,
    );
  }

  try {
    return (await response.json()) as T;
  } catch (cause) {
    throw new ApiError("Backend returned a response that could not be parsed.", cause);
  }
}

export function fetchDemoSummary(): Promise<DemoSummaryResponse> {
  return fetchDemoJson<DemoSummaryResponse>("/api/v1/demo/pi-mensae");
}

export function fetchDemoLightCurve(): Promise<DemoLightCurveResponse> {
  return fetchDemoJson<DemoLightCurveResponse>("/api/v1/demo/pi-mensae/light-curve");
}
