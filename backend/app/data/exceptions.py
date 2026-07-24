"""Typed exceptions for TESS/MAST target and observation discovery."""


class MastError(Exception):
    """Base class for all TESS/MAST data-acquisition errors."""


class InvalidTargetError(MastError):
    """The target string is malformed; no network call was attempted."""


class TargetNotFoundError(MastError):
    """MAST was queried successfully but returned no matching observations."""


class MastServiceError(MastError):
    """The MAST service itself failed (timeout, connection, or unexpected response)."""
