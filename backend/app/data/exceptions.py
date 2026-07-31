"""Typed exceptions for TESS/MAST data acquisition, download, and FITS parsing."""


class MastError(Exception):
    """Base class for all TESS/MAST data-acquisition errors."""


class InvalidTargetError(MastError):
    """The target string is malformed; no network call was attempted."""


class TargetNotFoundError(MastError):
    """MAST was queried successfully but returned no matching observations
    or no downloadable product matching the requested filters."""


class MastServiceError(MastError):
    """The MAST service itself failed (timeout, connection, or unexpected
    response). Callers may retry a MastServiceError; it represents a
    transient failure rather than an invalid request."""


class DownloadError(MastError):
    """A product download failed for a reason other than retry exhaustion
    (e.g. the downloaded file was empty or the gateway reported failure)."""


class RetryExhaustedError(DownloadError):
    """A download was retried the configured number of times and every
    attempt raised a ``MastServiceError``."""


class ChecksumMismatchError(DownloadError):
    """A freshly downloaded file's size or checksum did not match what MAST
    reported for the product, indicating a corrupted or truncated transfer."""


class CorruptedCacheError(DownloadError):
    """A previously cached file no longer matches its stored checksum
    sidecar. Re-run with ``--force`` to discard it and download again."""


class FitsError(Exception):
    """Base class for all FITS-parsing errors."""


class InvalidFitsError(FitsError):
    """The file is not a well-formed FITS file, or its scientific data is
    structurally invalid (inconsistent array lengths, no rows, etc.)."""


class UnsupportedProductError(FitsError):
    """The file is valid FITS but is not a TESS light-curve product this
    parser supports (e.g. wrong mission, or a pipeline/schema this parser
    does not yet handle)."""


class MissingExtensionError(FitsError):
    """A FITS extension required by the supported light-curve format
    (e.g. ``LIGHTCURVE``) is not present in the file."""


class MissingColumnError(FitsError):
    """A column required by the supported light-curve format (e.g.
    ``TIME``, ``QUALITY``) is not present in the required extension."""


class ProcessingError(Exception):
    """Base class for light-curve processing errors (Phase 3A onward).

    Distinct from ``FitsError``: these are raised by steps that operate
    on an already-parsed light curve, not while reading a file.
    """


class InvalidLightCurveError(ProcessingError):
    """The input light curve is structurally invalid -- its columns have
    mismatched lengths, or it contains no cadences at all.

    ``parse_light_curve`` already rejects both conditions, so this
    guards light curves constructed directly in code (``RawLightCurve``
    validates each field independently and does not cross-check
    lengths)."""


class InvalidFilterConfigError(ProcessingError):
    """The supplied quality-filter configuration is not usable (unknown
    policy name, negative mask, or a custom mask that is missing or
    supplied alongside a named policy).

    Deliberately not a subclass of ``ValueError``: Pydantic v2 lets it
    propagate out of a model validator unchanged instead of rewrapping
    it as a ``ValidationError``, so callers see one consistent type."""


class GapSegmentationError(ProcessingError):
    """Base class for errors raised while detecting gaps in, and
    segmenting, an already quality-filtered light curve (Phase 3B)."""


class InvalidGapDetectionConfigError(GapSegmentationError):
    """The supplied ``GapDetectionConfig`` is not usable (a gap multiplier
    that would classify every interval as a gap, a negative tolerance,
    etc.)."""


class NonFiniteTimeError(GapSegmentationError):
    """The input light curve contains a nonfinite (NaN or +/-inf) TIME
    value. Gap detection cannot compute a time interval against a
    nonfinite value; Phase 3A's default configuration already removes
    these, so this indicates the light curve was filtered with
    ``require_finite_time=False`` or was constructed directly."""


class NonMonotonicTimeError(GapSegmentationError):
    """The input light curve's TIME values are not strictly increasing --
    a duplicate or decreasing consecutive TIME value was found.

    Phase 3B never reorders, deduplicates, or otherwise silently repairs
    measurements; a non-monotonic TIME sequence is reported as an error
    instead."""


class NormalizationError(ProcessingError):
    """Base class for errors raised while normalizing an already
    segmented light curve (Phase 3C).

    A segment whose median reference is zero, negative, or otherwise
    unusable is **not** one of these errors -- that is recorded per
    segment as a ``ReferenceIssue`` instead, so one bad segment never
    blocks the others. This class is reserved for conditions that make
    the whole run unusable (an invalid config, or a structurally
    malformed segment)."""


class InvalidNormalizationConfigError(NormalizationError):
    """The supplied ``NormalizationConfig`` is not usable (e.g. a
    negative ``zero_reference_tolerance``)."""
