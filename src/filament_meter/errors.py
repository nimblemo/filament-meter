"""Exception hierarchy for :mod:`filament_meter`.

Every error raised by the package derives from :class:`FilamentMeterError`
so the CLI can catch a single base class and turn it into a clean message
plus a stable exit code instead of a traceback.
"""

from __future__ import annotations


class FilamentMeterError(Exception):
    """Base class for all errors raised by ``filament-meter``."""


class DiscoveryError(FilamentMeterError):
    """Raised when an input path cannot be resolved or yields no files."""


class ParseError(FilamentMeterError):
    """Raised when a sliced file cannot be parsed."""


class SlicerError(FilamentMeterError):
    """Raised when slicing a model with OrcaSlicer fails."""


class ProfileNotFoundError(SlicerError):
    """Raised when a required OrcaSlicer profile file is missing."""


class OrcaError(FilamentMeterError):
    """Base class for OrcaSlicer provisioning errors."""


class OrcaNotFoundError(OrcaError):
    """Raised when OrcaSlicer cannot be found and auto-install is disabled."""


class OrcaDownloadError(OrcaError):
    """Raised when downloading an OrcaSlicer release fails."""


class OrcaProvisionError(OrcaError):
    """Raised when installing / provisioning an OrcaSlicer build fails."""


class UsageError(FilamentMeterError):
    """Raised on invalid CLI usage or an unusable environment."""
