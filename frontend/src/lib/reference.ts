/**
 * Published literature values for the Pi Mensae system.
 *
 * Nothing in this file is produced by this project's pipeline. These are
 * reference values from peer-reviewed papers, shown so a reader can put
 * the processed light curve in context -- every place they appear in the
 * UI is tagged "Literature" and cites its source. The pipeline has not
 * performed a period search, a transit search, or any fit, and nothing
 * here should ever be presented as if it had.
 */

export interface Citation {
  label: string;
  href: string;
}

export const HUANG_2018: Citation = {
  label: "Huang et al. 2018, ApJL 868, L39",
  href: "https://doi.org/10.3847/2041-8213/aaef91",
};

export const NASA_EXOPLANET_ARCHIVE_PI_MEN: Citation = {
  label: "NASA Exoplanet Archive — pi Men",
  href: "https://exoplanetarchive.ipac.caltech.edu/overview/pi%20Men",
};

export const MAST_PORTAL_TIC: Citation = {
  label: "MAST Portal — TIC 261136679",
  href: "https://mast.stsci.edu/portal/Mashup/Clients/Mast/Portal.html?searchQuery=TIC%20261136679",
};

/** TESS light-curve TIME is Barycentric TESS Julian Date: BJD_TDB − 2457000. */
export const BTJD_OFFSET = 2457000;

export interface TransitEphemeris {
  planet: string;
  /** Orbital period in days. */
  periodDays: number;
  /** Reference mid-transit time, in BTJD (days). */
  epochBtjd: number;
  /** Approximate total transit duration (first to fourth contact), hours. */
  durationHours: number;
  /** Approximate transit depth, parts per million. */
  depthPpm: number;
  source: Citation;
}

/**
 * π Men c transit ephemeris from the TESS discovery paper (Huang et al.
 * 2018): P = 6.2679 d, T0 = 2458325.5034 BJD_TDB. Duration and depth are
 * rounded, approximate values implied by the published geometry
 * (Rp/R★ ≈ 0.017, a/R★ ≈ 13.1, i ≈ 87.5°) and are used only to draw an
 * indicative window, never for any calculation that is reported as a
 * measurement.
 */
export const PI_MEN_C_EPHEMERIS: TransitEphemeris = {
  planet: "π Men c",
  periodDays: 6.2679,
  epochBtjd: 2458325.5034 - BTJD_OFFSET,
  durationHours: 3.0,
  depthPpm: 290,
  source: HUANG_2018,
};

export interface ReferenceFact {
  label: string;
  value: string;
  note?: string;
}

export const PI_MEN_STAR_FACTS: ReferenceFact[] = [
  { label: "Other designations", value: "HD 39091 · TIC 261136679" },
  { label: "Spectral type", value: "G0 V", note: "Sun-like dwarf" },
  { label: "Visual magnitude", value: "V ≈ 5.65", note: "visible to the naked eye" },
  { label: "Distance", value: "≈ 18.3 pc", note: "≈ 60 light-years" },
  { label: "Effective temperature", value: "≈ 6,040 K" },
  { label: "Radius", value: "≈ 1.10 R☉" },
  { label: "Mass", value: "≈ 1.09 M☉" },
];

export interface ReferencePlanet {
  name: string;
  status: "confirmed";
  method: string;
  discovery: string;
  facts: ReferenceFact[];
  transitsInTess: boolean;
}

export const PI_MEN_PLANETS: ReferencePlanet[] = [
  {
    name: "π Men b",
    status: "confirmed",
    method: "Radial velocity",
    discovery: "Jones et al. 2002",
    transitsInTess: false,
    facts: [
      { label: "Period", value: "≈ 2,090 d" },
      { label: "Minimum mass", value: "≈ 10 MJup" },
      { label: "Eccentricity", value: "≈ 0.64" },
    ],
  },
  {
    name: "π Men c",
    status: "confirmed",
    method: "Transit (TESS)",
    discovery: "Huang et al. 2018; Gandolfi et al. 2018",
    transitsInTess: true,
    facts: [
      { label: "Period", value: "6.2679 d" },
      { label: "Radius", value: "≈ 2.04 R⊕", note: "a super-Earth / sub-Neptune" },
      { label: "Transit depth", value: "≈ 290 ppm" },
      { label: "Transit duration", value: "≈ 3 h" },
    ],
  },
];
