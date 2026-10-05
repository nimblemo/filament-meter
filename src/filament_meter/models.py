"""Immutable data model for ``filament-meter``.

The model is deliberately flat and frozen so reports can be built,
merged and serialised without accidental mutation. Every container
exposes :meth:`to_dict` for JSON serialisation and a ``has_data``
property that answers "do we actually know anything useful here?".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class SliceSource(StrEnum):
    """Where the filament numbers for a plate were read from."""

    SLICE_INFO = "slice_info.config"
    GCODE = "gcode"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FilamentUsage:
    """Filament consumption for a single filament slot on a plate.

    Attributes:
        id: Filament slot id as reported by the slicer (e.g. ``"1"``).
        type: Material type (``PLA``, ``PETG``, ...) if known.
        color: Hex colour string (``#RRGGBB``) if known.
        tray_info_idx: Slicer-specific tray/profile index if known.
        used_g: Consumed mass in grams, if known.
        used_m: Consumed length in metres, if known.
    """

    id: str
    type: str | None = None
    color: str | None = None
    tray_info_idx: str | None = None
    used_g: float | None = None
    used_m: float | None = None

    @property
    def has_data(self) -> bool:
        """Return ``True`` when at least one consumption figure is present."""
        return self.used_g is not None or self.used_m is not None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this filament slot."""
        return {
            "id": self.id,
            "type": self.type,
            "color": self.color,
            "tray_info_idx": self.tray_info_idx,
            "used_g": self.used_g,
            "used_m": self.used_m,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilamentUsage:
        """Rebuild a :class:`FilamentUsage` from :meth:`to_dict` output."""
        return cls(
            id=str(data.get("id", "")),
            type=data.get("type"),
            color=data.get("color"),
            tray_info_idx=data.get("tray_info_idx"),
            used_g=data.get("used_g"),
            used_m=data.get("used_m"),
        )


@dataclass(frozen=True)
class PlateReport:
    """Filament usage and metadata for a single build plate.

    Attributes:
        index: Plate index as reported by the slicer.
        prediction_s: Estimated print time in seconds, if known.
        weight_g: Total plate weight in grams, if known.
        nozzle: Nozzle diameter (as a string, e.g. ``"0.4"``), if known.
        layer_height: Layer height in millimetres, if known.
        objects: Number of objects on the plate, if known.
        object_names: Names of (up to eight) objects on the plate.
        bed_type: Build-plate / bed type string, if known.
        filaments: Per-slot filament usage entries.
        source: Where the numbers came from.
    """

    index: str
    prediction_s: float | None = None
    weight_g: float | None = None
    nozzle: str | None = None
    layer_height: float | None = None
    objects: int | None = None
    object_names: tuple[str, ...] = ()
    bed_type: str | None = None
    filaments: tuple[FilamentUsage, ...] = ()
    source: SliceSource = SliceSource.UNKNOWN

    @property
    def has_data(self) -> bool:
        """Return ``True`` when the plate carries any filament figures."""
        return bool(self.filaments) and any(f.has_data for f in self.filaments)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this plate."""
        return {
            "index": self.index,
            "prediction_s": self.prediction_s,
            "weight_g": self.weight_g,
            "nozzle": self.nozzle,
            "layer_height": self.layer_height,
            "objects": self.objects,
            "object_names": list(self.object_names),
            "bed_type": self.bed_type,
            "filaments": [f.to_dict() for f in self.filaments],
            "source": self.source.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlateReport:
        """Rebuild a :class:`PlateReport` from :meth:`to_dict` output."""
        return cls(
            index=str(data.get("index", "1")),
            prediction_s=data.get("prediction_s"),
            weight_g=data.get("weight_g"),
            nozzle=data.get("nozzle"),
            layer_height=data.get("layer_height"),
            objects=data.get("objects"),
            object_names=tuple(data.get("object_names") or ()),
            bed_type=data.get("bed_type"),
            filaments=tuple(FilamentUsage.from_dict(f) for f in data.get("filaments") or ()),
            source=SliceSource(data.get("source") or SliceSource.UNKNOWN.value),
        )


@dataclass(frozen=True)
class FileReport:
    """Analysis result for a single input file.

    Attributes:
        path: Path to the analysed (source) file.
        name: Base name of the file.
        size_bytes: Size of the source file in bytes.
        sliced: Whether filament data was available for the file.
        plates: Per-plate reports.
        total_g: Total filament mass in grams.
        total_m: Total filament length in metres.
        total_time_s: Total estimated print time in seconds.
        cost: Estimated cost for this file, if a price was supplied.
        notes: Human-readable notes (warnings, fallbacks, ...).
        error: Error message when the file could not be processed.
    """

    path: Path
    name: str
    size_bytes: int = 0
    sliced: bool = False
    plates: tuple[PlateReport, ...] = ()
    total_g: float = 0.0
    total_m: float = 0.0
    total_time_s: float = 0.0
    cost: float | None = None
    notes: tuple[str, ...] = ()
    error: str | None = None

    @property
    def has_data(self) -> bool:
        """Return ``True`` when the file carries usable filament figures."""
        return self.sliced and (self.total_g > 0 or self.total_m > 0)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of this file report."""
        return {
            "path": str(self.path),
            "name": self.name,
            "size_bytes": self.size_bytes,
            "sliced": self.sliced,
            "plates": [p.to_dict() for p in self.plates],
            "total_g": self.total_g,
            "total_m": self.total_m,
            "total_time_s": self.total_time_s,
            "cost": self.cost,
            "notes": list(self.notes),
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileReport:
        """Rebuild a :class:`FileReport` from :meth:`to_dict` output."""
        return cls(
            path=Path(data.get("path", "")),
            name=str(data.get("name", "")),
            size_bytes=int(data.get("size_bytes", 0)),
            sliced=bool(data.get("sliced", False)),
            plates=tuple(PlateReport.from_dict(p) for p in data.get("plates") or ()),
            total_g=float(data.get("total_g", 0.0)),
            total_m=float(data.get("total_m", 0.0)),
            total_time_s=float(data.get("total_time_s", 0.0)),
            cost=data.get("cost"),
            notes=tuple(data.get("notes") or ()),
            error=data.get("error"),
        )


@dataclass(frozen=True)
class RunReport:
    """Aggregate report for a whole CLI invocation.

    Attributes:
        generated_at: ISO-8601 UTC timestamp of report generation.
        tool_version: Version of ``filament-meter`` that produced the report.
        orca_version: Detected OrcaSlicer version, if any.
        price_per_kg: Filament price per kilogram, if supplied.
        currency: Currency code used for cost calculations.
        files: Per-file reports.
        total_g: Aggregate filament mass in grams.
        total_m: Aggregate filament length in metres.
        total_time_s: Aggregate estimated print time in seconds.
        total_cost: Aggregate estimated cost, if a price was supplied.
        sliced_count: Number of files that yielded filament data.
        failed_count: Number of files that failed to process.
    """

    generated_at: str
    tool_version: str
    orca_version: str | None = None
    price_per_kg: float | None = None
    currency: str = "RUB"
    files: tuple[FileReport, ...] = ()
    total_g: float = 0.0
    total_m: float = 0.0
    total_time_s: float = 0.0
    total_cost: float | None = None
    sliced_count: int = 0
    failed_count: int = 0

    @property
    def has_data(self) -> bool:
        """Return ``True`` when at least one file yielded filament data."""
        return self.sliced_count > 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the whole run."""
        return {
            "generated_at": self.generated_at,
            "tool_version": self.tool_version,
            "orca_version": self.orca_version,
            "price_per_kg": self.price_per_kg,
            "currency": self.currency,
            "files": [f.to_dict() for f in self.files],
            "total_g": self.total_g,
            "total_m": self.total_m,
            "total_time_s": self.total_time_s,
            "total_cost": self.total_cost,
            "sliced_count": self.sliced_count,
            "failed_count": self.failed_count,
        }
