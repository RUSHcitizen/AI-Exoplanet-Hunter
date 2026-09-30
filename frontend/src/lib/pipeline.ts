/**
 * The project's pipeline stages and their real implementation status,
 * mirroring the roadmap in the repository README. Shown on the overview
 * and the observation page so both always agree about what exists.
 */

export interface PipelineStage {
  id: string;
  label: string;
  phase: string;
  description: string;
  status: "complete" | "planned";
}

export const PIPELINE_STAGES: PipelineStage[] = [
  {
    id: "parse",
    label: "Raw FITS parsed",
    phase: "2B",
    description: "SPOC light-curve product read verbatim: TIME, PDCSAP flux, errors, QUALITY.",
    status: "complete",
  },
  {
    id: "quality",
    label: "Quality filtered",
    phase: "3A",
    description: "Cadences rejected by documented TESS quality bits or non-finite values — every rejection traceable.",
    status: "complete",
  },
  {
    id: "segment",
    label: "Segmented",
    phase: "3B",
    description: "Observation gaps detected from the measured cadence; data split into contiguous segments.",
    status: "complete",
  },
  {
    id: "normalize",
    label: "Normalized",
    phase: "3C",
    description: "Each segment divided by its own median flux, never across a gap.",
    status: "complete",
  },
  {
    id: "outliers",
    label: "Outliers flagged",
    phase: "3D",
    description: "Robust (MAD-based) upward outliers flagged, never removed. Downward flagging off to protect transits.",
    status: "complete",
  },
  {
    id: "detrend",
    label: "Detrending",
    phase: "5",
    description: "Remove slow stellar and instrumental variability while preserving transit shapes.",
    status: "planned",
  },
  {
    id: "bls",
    label: "Transit search (Box Least Squares)",
    phase: "5",
    description: "Search for periodic box-shaped dips and report period, depth, duration, and SNR.",
    status: "planned",
  },
  {
    id: "features",
    label: "Candidate feature extraction",
    phase: "8",
    description: "Odd/even depth, secondary eclipse, shape and centroid diagnostics per signal.",
    status: "planned",
  },
  {
    id: "ml",
    label: "Machine-learning classification",
    phase: "9",
    description: "Rank candidate signals against false positives with a documented, validated model.",
    status: "planned",
  },
  {
    id: "crossmatch",
    label: "Known-planet cross-match",
    phase: "10",
    description: "Compare signals with catalogued planets and TOIs before anything is called new.",
    status: "planned",
  },
];
