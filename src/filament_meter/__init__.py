"""``filament-meter`` — measure 3D-print filament usage from sliced files.

Public API re-exports:

>>> from filament_meter import analyse, discover, render
"""

from __future__ import annotations

from filament_meter.discovery import DEFAULT_PATTERNS, discover
from filament_meter.errors import (
    DiscoveryError,
    FilamentMeterError,
    OrcaDownloadError,
    OrcaError,
    OrcaNotFoundError,
    OrcaProvisionError,
    ParseError,
    ProfileNotFoundError,
    SlicerError,
    UsageError,
)
from filament_meter.models import (
    FilamentUsage,
    FileReport,
    PlateReport,
    RunReport,
    SliceSource,
)
from filament_meter.orca import download_orca, ensure_orca, find_orca
from filament_meter.parser import (
    analyse,
    analyse_gcode_file,
    fmt_time,
    is_sliced_3mf,
    parse_time_text,
    to_float,
)
from filament_meter.report import FORMATS, render, write_report
from filament_meter.slicer import SliceResult, run_slice

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "DEFAULT_PATTERNS",
    "FileReport",
    "FilamentMeterError",
    "FilamentUsage",
    "FORMATS",
    "PlateReport",
    "RunReport",
    "SliceResult",
    "SliceSource",
    "DiscoveryError",
    "OrcaDownloadError",
    "OrcaError",
    "OrcaNotFoundError",
    "OrcaProvisionError",
    "ParseError",
    "ProfileNotFoundError",
    "SlicerError",
    "UsageError",
    "analyse",
    "analyse_gcode_file",
    "discover",
    "download_orca",
    "ensure_orca",
    "find_orca",
    "fmt_time",
    "is_sliced_3mf",
    "parse_time_text",
    "render",
    "run_slice",
    "to_float",
    "write_report",
]
