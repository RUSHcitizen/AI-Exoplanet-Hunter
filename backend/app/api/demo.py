"""Read-only Phase 4A demo endpoints for the fixed Pi Mensae science
preview.

These endpoints never accept a caller-supplied path, never write
anything, and never run any processing beyond the already-implemented
and validated Phase 3A-3D pipeline (``app.services.demo_pipeline``).
Response models here are API-specific display shapes, kept separate
from the core scientific models in ``app.data.models`` -- nothing here
feeds back into scientific processing.
"""

import statistics
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.data.exceptions import FitsError, ProcessingError
from app.data.models import (
    GapDetectionStep,
    NormalizationStep,
    OutlierAnalysisStatus,
    OutlierDetectionStep,
    OutlierFlaggedSegment,
    ProcessingStep,
)
from app.services.demo_pipeline import (
    PI_MENSAE_TARGET_NAME,
    DemoFitsNotFoundError,
    DemoPipelineResult,
    run_demo_pipeline,
)

router = APIRouter(prefix="/demo/pi-mensae", tags=["demo"])

_SECONDS_PER_DAY = 86400.0

SCIENTIFIC_LIMITATIONS: tuple[str, ...] = (
    "This dashboard does not identify or confirm planets.",
    "Statistical outliers are not planet candidates or transit signals.",
    "Downward (low-side) outlier detection is disabled by default, to avoid flagging "
    "a real transit-like dip as an artifact.",
    "The light curve has not been detrended.",
    "No period search has been performed.",
    "No Box Least Squares transit search has been performed.",
    "No machine-learning inference or prediction has been performed.",
    "This page shows one fixed, cached, local Pi Mensae demonstration observation.",
)


def get_demo_fits_path(settings: Settings = Depends(get_settings)) -> Path:
    """Resolve the fixed Pi Mensae demo FITS path from typed settings.

    Never derived from a request parameter -- overridden in tests via
    ``app.dependency_overrides``, the same pattern any other FastAPI
    dependency uses.
    """
    return Path(settings.pi_mensae_demo_fits_path)


def _load_pipeline_result(fits_path: Path) -> DemoPipelineResult:
    try:
        return run_demo_pipeline(fits_path)
    except DemoFitsNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "demo_fits_missing",
                "message": (
                    "The cached Pi Mensae demonstration FITS file is not present on "
                    "this server. It is not downloaded automatically."
                ),
            },
        ) from exc
    except FitsError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "demo_fits_invalid", "message": str(exc)},
        ) from exc
    except ProcessingError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error": "demo_processing_failed", "message": str(exc)},
        ) from exc


# --- Summary response models -------------------------------------------------


class DemoIdentity(BaseModel):
    target_name: str
    tic_id: int | None
    sector: int | None
    mission: str | None
    source_filename: str
    source_checksum_sha256: str
    flux_column: str
    pipeline: str | None


class DemoRawStats(BaseModel):
    raw_cadence_count: int


class DemoQualityFilterSummary(BaseModel):
    retained_cadence_count: int
    rejected_cadence_count: int
    retained_fraction: float
    quality_policy: str
    quality_bitmask_decimal: int
    quality_bitmask_hex: str
    rejection_counts_by_reason: dict[str, int]
    matched_quality_bit_counts: dict[int, int]


class DemoSegmentationSummary(BaseModel):
    segment_count: int
    gap_count: int
    measured_nominal_cadence_days: float | None
    measured_nominal_cadence_seconds: float | None
    metadata_cadence_days: float | None
    metadata_cadence_seconds: float | None
    estimated_missing_cadence_count: int


class DemoNormalizationSummary(BaseModel):
    normalized_segment_count: int
    invalid_reference_segment_count: int
    segment_reference_min: float | None
    segment_reference_median: float | None
    segment_reference_max: float | None


class DemoOutlierSummary(BaseModel):
    valid_segment_count: int
    insufficient_data_segment_count: int
    zero_scale_segment_count: int
    normalization_unavailable_segment_count: int
    high_outlier_count: int
    low_outlier_count: int
    lower_detection_enabled: bool
    upper_threshold: float
    lower_threshold: float | None
    outlier_fraction: float


class ProcessingHistoryEntry(BaseModel):
    step: str
    code_version: str
    input_count: int
    output_count: int
    configuration_summary: str
    source_checksum_sha256: str


class DemoProvenance(BaseModel):
    processing_history: tuple[ProcessingHistoryEntry, ...]
    source_checksum_sha256: str
    fits_file_unchanged_statement: str
    deterministic_processing_statement: str


class DemoSummaryResponse(BaseModel):
    identity: DemoIdentity
    raw: DemoRawStats
    quality_filter: DemoQualityFilterSummary
    segmentation: DemoSegmentationSummary
    normalization: DemoNormalizationSummary
    outliers: DemoOutlierSummary
    provenance: DemoProvenance
    scientific_limitations: tuple[str, ...]


# --- Light-curve response models ---------------------------------------------


class DemoLightCurvePoint(BaseModel):
    time: float
    normalized_flux: float | None
    original_flux: float
    source_index: int
    is_high_outlier: bool
    robust_score: float | None


class DemoLightCurveSegment(BaseModel):
    segment_number: int
    start_time: float
    end_time: float
    cadence_count: int
    analysis_status: str
    points: tuple[DemoLightCurvePoint, ...]


class DemoGap(BaseModel):
    before_segment_number: int
    after_segment_number: int
    start_time: float
    end_time: float
    duration_days: float
    duration_seconds: float
    reasons: tuple[str, ...]
    estimated_missing_cadences: int | None


class DemoLightCurveResponse(BaseModel):
    target_name: str
    tic_id: int | None
    sector: int | None
    segments: tuple[DemoLightCurveSegment, ...]
    gaps: tuple[DemoGap, ...]


# --- Builders ------------------------------------------------------------


def _configuration_summary(
    step: ProcessingStep | GapDetectionStep | NormalizationStep | OutlierDetectionStep,
) -> str:
    if isinstance(step, ProcessingStep):
        return f"quality_policy={step.quality_policy.value}, bitmask={step.active_quality_bitmask}"
    if isinstance(step, GapDetectionStep):
        return f"gap_multiplier={step.config.gap_multiplier}, gaps={step.output_gap_count}"
    if isinstance(step, NormalizationStep):
        return f"zero_reference_tolerance={step.config.zero_reference_tolerance}"
    lower = (
        f"lower_threshold={step.config.lower_threshold}"
        if step.config.lower_threshold is not None
        else "lower_threshold=disabled"
    )
    return f"upper_threshold={step.config.upper_threshold}, {lower}"


def _output_count(
    step: ProcessingStep | GapDetectionStep | NormalizationStep | OutlierDetectionStep,
) -> int:
    if isinstance(step, ProcessingStep):
        return step.output_cadences
    if isinstance(step, GapDetectionStep):
        return step.output_segment_count
    if isinstance(step, NormalizationStep):
        return step.normalized_segment_count
    return step.analyzed_segment_count


def build_summary_response(result: DemoPipelineResult) -> DemoSummaryResponse:
    """Translate a completed ``DemoPipelineResult`` into the API's typed
    summary response. Every value is read from the pipeline objects --
    nothing here is hard-coded."""
    filtered, segmented, normalized, flagged = (
        result.filtered,
        result.segmented,
        result.normalized,
        result.flagged,
    )
    quality_step = filtered.history[0]
    assert isinstance(quality_step, ProcessingStep)
    outlier_step = flagged.history[-1]
    assert isinstance(outlier_step, OutlierDetectionStep)

    references = [
        entry.stats.reference for entry in normalized.segments if entry.stats.reference is not None
    ]

    unanalyzed = flagged.stats.unanalyzed_by_status
    total_outliers = flagged.stats.total_high_outliers + flagged.stats.total_low_outliers
    outlier_fraction = total_outliers / flagged.cadence_count if flagged.cadence_count else 0.0

    history = tuple(
        ProcessingHistoryEntry(
            step=step.step,
            code_version=step.code_version,
            input_count=step.input_cadences,
            output_count=_output_count(step),
            configuration_summary=_configuration_summary(step),
            source_checksum_sha256=step.input_checksum_sha256,
        )
        for step in flagged.history
    )

    return DemoSummaryResponse(
        identity=DemoIdentity(
            target_name=PI_MENSAE_TARGET_NAME,
            tic_id=flagged.provenance.tic_id,
            sector=flagged.provenance.sector,
            mission=flagged.provenance.mission,
            source_filename=flagged.provenance.source_filename,
            source_checksum_sha256=flagged.provenance.source_checksum_sha256,
            flux_column=flagged.flux_column,
            pipeline=flagged.provenance.author,
        ),
        raw=DemoRawStats(raw_cadence_count=filtered.stats.total_cadences),
        quality_filter=DemoQualityFilterSummary(
            retained_cadence_count=filtered.stats.retained_cadences,
            rejected_cadence_count=filtered.stats.rejected_cadences,
            retained_fraction=filtered.stats.retained_fraction,
            quality_policy=quality_step.quality_policy.value,
            quality_bitmask_decimal=quality_step.active_quality_bitmask,
            quality_bitmask_hex=f"0x{quality_step.active_quality_bitmask:04X}",
            rejection_counts_by_reason={
                reason.value: count for reason, count in filtered.stats.rejected_by_reason.items()
            },
            matched_quality_bit_counts=dict(filtered.stats.rejected_by_quality_bit),
        ),
        segmentation=DemoSegmentationSummary(
            segment_count=segmented.stats.segment_count,
            gap_count=segmented.stats.gap_count,
            measured_nominal_cadence_days=segmented.stats.measured_nominal_cadence,
            measured_nominal_cadence_seconds=(
                segmented.stats.measured_nominal_cadence * _SECONDS_PER_DAY
                if segmented.stats.measured_nominal_cadence is not None
                else None
            ),
            metadata_cadence_days=segmented.stats.metadata_cadence_native,
            metadata_cadence_seconds=segmented.stats.metadata_cadence_seconds,
            estimated_missing_cadence_count=segmented.stats.total_estimated_missing_cadences,
        ),
        normalization=DemoNormalizationSummary(
            normalized_segment_count=normalized.stats.normalized_segment_count,
            invalid_reference_segment_count=normalized.stats.invalid_segment_count,
            segment_reference_min=min(references) if references else None,
            segment_reference_median=statistics.median(references) if references else None,
            segment_reference_max=max(references) if references else None,
        ),
        outliers=DemoOutlierSummary(
            valid_segment_count=flagged.stats.analyzed_segment_count,
            insufficient_data_segment_count=unanalyzed.get(
                OutlierAnalysisStatus.INSUFFICIENT_DATA, 0
            ),
            zero_scale_segment_count=unanalyzed.get(OutlierAnalysisStatus.ZERO_SCALE, 0),
            normalization_unavailable_segment_count=unanalyzed.get(
                OutlierAnalysisStatus.NORMALIZATION_UNAVAILABLE, 0
            ),
            high_outlier_count=flagged.stats.total_high_outliers,
            low_outlier_count=flagged.stats.total_low_outliers,
            lower_detection_enabled=outlier_step.config.lower_threshold is not None,
            upper_threshold=outlier_step.config.upper_threshold,
            lower_threshold=outlier_step.config.lower_threshold,
            outlier_fraction=outlier_fraction,
        ),
        provenance=DemoProvenance(
            processing_history=history,
            source_checksum_sha256=flagged.provenance.source_checksum_sha256,
            fits_file_unchanged_statement=(
                "The source FITS file is opened read-only for every request and is "
                "never modified, replaced, or deleted."
            ),
            deterministic_processing_statement=(
                "Every stage is a pure function of the source file and its fixed "
                "default configuration, so repeated requests return identical results."
            ),
        ),
        scientific_limitations=SCIENTIFIC_LIMITATIONS,
    )


def _point_robust_score(
    entry: OutlierFlaggedSegment, position: int, normalized_flux: float | None
) -> float | None:
    """Recompute the same per-cadence robust score Phase 3D itself
    defines (``(value - center) / robust_scale``), for display -- not a
    new statistic. Only defined where Phase 3D itself would compute one:
    a ``VALID`` segment with a finite normalized-flux value."""
    stats = entry.stats
    if (
        stats.status is not OutlierAnalysisStatus.VALID
        or normalized_flux is None
        or stats.center is None
        or stats.robust_scale is None
    ):
        return None
    return (normalized_flux - stats.center) / stats.robust_scale


def build_light_curve_response(result: DemoPipelineResult) -> DemoLightCurveResponse:
    """Translate a completed ``DemoPipelineResult`` into the API's
    gap-aware, segment-grouped chart response. Every Phase 3B segment is
    kept separate so a chart can never draw a line across a gap."""
    flagged = result.flagged

    segments = tuple(
        DemoLightCurveSegment(
            segment_number=entry.normalized.segment.segment_number,
            start_time=entry.normalized.segment.start_time,
            end_time=entry.normalized.segment.end_time,
            cadence_count=entry.normalized.segment.cadence_count,
            analysis_status=entry.stats.status.value,
            points=tuple(
                DemoLightCurvePoint(
                    time=entry.normalized.segment.time[position],
                    normalized_flux=(
                        entry.normalized.normalized_flux[position]
                        if entry.normalized.normalized_flux is not None
                        else None
                    ),
                    original_flux=entry.normalized.segment.flux[position],
                    source_index=entry.normalized.segment.source_indices[position],
                    is_high_outlier=entry.high_outlier_mask[position],
                    robust_score=_point_robust_score(
                        entry,
                        position,
                        (
                            entry.normalized.normalized_flux[position]
                            if entry.normalized.normalized_flux is not None
                            else None
                        ),
                    ),
                )
                for position in range(entry.normalized.segment.cadence_count)
            ),
        )
        for entry in flagged.segments
    )

    gaps = tuple(
        DemoGap(
            before_segment_number=segments[index].segment_number,
            after_segment_number=segments[index + 1].segment_number,
            start_time=gap.time_before,
            end_time=gap.time_after,
            duration_days=gap.actual_interval,
            duration_seconds=gap.actual_interval * _SECONDS_PER_DAY,
            reasons=tuple(reason.value for reason in gap.reasons),
            estimated_missing_cadences=gap.estimated_missing_cadences,
        )
        for index, gap in enumerate(flagged.gaps)
    )

    return DemoLightCurveResponse(
        target_name=PI_MENSAE_TARGET_NAME,
        tic_id=flagged.provenance.tic_id,
        sector=flagged.provenance.sector,
        segments=segments,
        gaps=gaps,
    )


# --- Routes ----------------------------------------------------------------


@router.get("", response_model=DemoSummaryResponse)
def get_demo_summary(fits_path: Path = Depends(get_demo_fits_path)) -> DemoSummaryResponse:
    """Pipeline summary (identity, per-phase statistics, provenance, and
    scientific limitations) for the fixed Pi Mensae demonstration light
    curve. Read-only: performs no writes and accepts no path parameter."""
    result = _load_pipeline_result(fits_path)
    return build_summary_response(result)


@router.get("/light-curve", response_model=DemoLightCurveResponse)
def get_demo_light_curve(
    fits_path: Path = Depends(get_demo_fits_path),
) -> DemoLightCurveResponse:
    """Gap-aware, segment-grouped normalized light curve for the fixed
    Pi Mensae demonstration observation, for chart rendering."""
    result = _load_pipeline_result(fits_path)
    return build_light_curve_response(result)
