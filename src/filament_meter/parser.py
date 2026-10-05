"""Parse filament usage out of sliced ``.3mf`` archives and ``.gcode`` files.

This module is a faithful, typed port of the proven ``filament_report.py``
prototype. The guiding rule stays the same: filament data only exists in a
*sliced* file. When ``Metadata/slice_info.config`` carries real ``<plate>``
entries we read them; otherwise we fall back to the G-code header/tail
(``; filament used [g]`` etc.) and, as a last resort, to a rough estimate
from the extruded length.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from filament_meter.models import FilamentUsage, FileReport, PlateReport, SliceSource

#: Assumed PLA density in g/cm³, used for the rough length→mass estimate.
PLA_DENSITY_G_PER_CM3 = 1.24

#: Assumed filament diameter in millimetres (only used for documentation).
FILAMENT_DIAMETER_MM = 1.75

#: Matches ``Metadata/plate_<n>.gcode`` entries inside a 3MF archive.
_PLATE_GCODE_RE = re.compile(r"Metadata/plate_(\d+)\.gcode$")

#: Matches ``Metadata/plate_<n>.json`` entries inside a 3MF archive.
_PLATE_JSON_RE = re.compile(r"Metadata/plate_(\d+)\.json$")

#: Number of bytes read from the head and tail of a G-code stream.
_GCODE_SAMPLE_BYTES = 60_000

#: Pattern for the human-readable estimate note.
_ESTIMATE_NOTE = (
    "mass estimated from extruded length "
    f"(density {PLA_DENSITY_G_PER_CM3} g/cm3, diameter {FILAMENT_DIAMETER_MM} mm)"
)


def to_float(value: Any) -> float | None:
    """Best-effort conversion of ``value`` to ``float``.

    Accepts both ``.`` and ``,`` as the decimal separator (Bambu Studio
    localises some numbers). Returns ``None`` when the value is missing or
    not numeric.
    """
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def fmt_time(seconds: float | int | str | None) -> str:
    """Format a number of seconds as a compact human string.

    Examples: ``3563`` → ``"59m 23s"``, ``21439`` → ``"5h 57m"``. Returns
    ``"?"`` when the value is missing or not numeric.
    """
    if seconds is None:
        return "?"
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "?"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def parse_time_text(text: Any) -> float | None:
    """Parse a free-form duration string into seconds.

    Handles ``"35m 37s"``, ``"1h 2m"`` and plain numeric strings such as
    ``"2137"``. Returns ``None`` when nothing parseable is found.
    """
    if text is None:
        return None
    value = str(text).strip()
    if re.fullmatch(r"\d+(\.\d+)?", value):
        return float(value)
    total = 0.0
    found = False
    for amount, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([hms])", value):
        found = True
        total += float(amount) * {"h": 3600, "m": 60, "s": 1}[unit]
    return total if found else None


def _format_nozzle(value: Any) -> str | None:
    """Normalise a nozzle diameter to a short string such as ``"0.4"``."""
    number = to_float(value)
    if number is None:
        return str(value) if value is not None else None
    return f"{number:.2f}".rstrip("0").rstrip(".")


def parse_slice_info(archive: zipfile.ZipFile) -> tuple[list[PlateReport], bool]:
    """Read ``Metadata/slice_info.config`` from ``archive``.

    Returns:
        A ``(plates, sliced)`` tuple. ``sliced`` is ``True`` only when at
        least one ``<plate>`` element was present, which is the reliable
        signal that the file has actually been sliced.
    """
    try:
        raw = archive.read("Metadata/slice_info.config")
    except KeyError:
        return [], False
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [], False

    plates: list[PlateReport] = []
    for plate in root.findall("plate"):
        metadata = {m.get("key"): m.get("value") for m in plate.findall("metadata")}
        filaments = tuple(
            FilamentUsage(
                id=filament.get("id") or "",
                type=filament.get("type"),
                color=filament.get("color"),
                tray_info_idx=filament.get("tray_info_idx"),
                used_g=to_float(filament.get("used_g")),
                used_m=to_float(filament.get("used_m")),
            )
            for filament in plate.findall("filament")
        )
        plates.append(
            PlateReport(
                index=metadata.get("index") or "1",
                prediction_s=to_float(metadata.get("prediction")),
                weight_g=to_float(metadata.get("weight")),
                nozzle=metadata.get("nozzle_diameters"),
                filaments=filaments,
                source=SliceSource.SLICE_INFO,
            )
        )
    return plates, bool(plates)


def _sum_values(raw: str) -> float | None:
    """Sum a comma-separated list of numbers, tolerating blanks.

    Slicers write per-extruder figures such as
    ``; filament used [g] = 0.00, 0.00, 0.00, 96.54, 0.00`` — the total is
    the sum across all slots, not the first entry. Returns ``None`` when no
    numeric value is present.
    """
    total = 0.0
    found = False
    for part in raw.split(","):
        number = to_float(part)
        if number is not None:
            found = True
            total += number
    return total if found else None


def _parse_gcode_blob(
    blob: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Extract ``(grams, metres, cm3, seconds)`` from a G-code text chunk."""
    grams = millimetres = cubic_cm = None
    time_s = None
    for key, raw_value in re.findall(r";\s*([^=:\n]+?)\s*[=:]\s*([^\n;]+)", blob):
        lowered = key.strip().lower()
        value = raw_value.strip()
        if lowered == "filament used [g]":
            grams = _sum_values(value)
        elif lowered == "filament used [mm]":
            millimetres = _sum_values(value)
        elif lowered == "filament used [cm3]":
            cubic_cm = _sum_values(value)
        elif lowered.startswith("total estimated time") or lowered.startswith(
            "estimated printing time"
        ):
            time_s = parse_time_text(value)
    metres = millimetres / 1000.0 if millimetres is not None else None
    return grams, metres, cubic_cm, time_s


def _gcode_grams(
    grams: float | None,
    metres: float | None,
    cubic_cm: float | None,
) -> tuple[float | None, bool]:
    """Resolve the mass for a G-code plate.

    Returns ``(grams, estimated)`` where ``estimated`` is ``True`` only when
    the mass had to be *derived* from a length/volume (i.e. no
    ``; filament used [g]`` line was present). A directly reported mass is
    returned untouched and never flagged as an estimate.
    """
    if grams is not None:
        return grams, False
    if cubic_cm is not None:
        return cubic_cm * PLA_DENSITY_G_PER_CM3, True
    if metres is not None:
        return metres * PLA_DENSITY_G_PER_CM3, True
    return None, False


def _parse_gcode_plates(archive: zipfile.ZipFile) -> tuple[list[PlateReport], bool]:
    """Parse every ``Metadata/plate_N.gcode`` into plates.

    Returns ``(plates, estimated)`` where ``estimated`` reports whether any
    plate's mass had to be derived from the extruded length/volume.
    """
    results: list[PlateReport] = []
    estimated_any = False
    names = [name for name in archive.namelist() if _PLATE_GCODE_RE.match(name)]
    for name in sorted(names):
        match = _PLATE_GCODE_RE.search(name)
        plate_no = match.group(1) if match else "1"

        with archive.open(name) as handle:
            head = handle.read(_GCODE_SAMPLE_BYTES).decode("utf-8", "replace")
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _GCODE_SAMPLE_BYTES))
            tail = handle.read().decode("utf-8", "replace")

        grams: float | None = None
        metres: float | None = None
        cubic_cm: float | None = None
        time_s: float | None = None
        for blob in (tail, head):
            blob_grams, blob_metres, blob_cm3, blob_time = _parse_gcode_blob(blob)
            grams = blob_grams if blob_grams is not None else grams
            metres = blob_metres if blob_metres is not None else metres
            cubic_cm = blob_cm3 if blob_cm3 is not None else cubic_cm
            time_s = blob_time if blob_time is not None else time_s

        if grams is None and metres is None and cubic_cm is None:
            continue

        grams, estimated = _gcode_grams(grams, metres, cubic_cm)
        estimated_any = estimated_any or estimated

        results.append(
            PlateReport(
                index=plate_no,
                prediction_s=time_s,
                weight_g=grams,
                filaments=(FilamentUsage(id="1", type="?", used_g=grams, used_m=metres),),
                source=SliceSource.GCODE,
            )
        )
    return results, estimated_any


def parse_gcode(archive: zipfile.ZipFile) -> list[PlateReport]:
    """Fallback parser reading filament data from ``Metadata/plate_N.gcode``."""
    plates, _ = _parse_gcode_plates(archive)
    return plates


def parse_plate_json(archive: zipfile.ZipFile, plate_no: str) -> dict[str, Any] | None:
    """Read and decode ``Metadata/plate_<n>.json`` from ``archive``."""
    try:
        raw = archive.read(f"Metadata/plate_{plate_no}.json")
    except KeyError:
        return None
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _enrich_plate(archive: zipfile.ZipFile, plate: PlateReport) -> PlateReport:
    """Merge object / bed / nozzle metadata from ``plate_N.json``."""
    data = parse_plate_json(archive, plate.index)
    if data is None:
        return plate

    objects = data.get("bbox_objects") or []
    names = tuple(str(obj.get("name")) for obj in objects[:8] if obj.get("name"))
    layer_height = objects[0].get("layer_height") if objects else None

    nozzle = plate.nozzle
    if not nozzle:
        nozzle = _format_nozzle(data.get("nozzle_diameter"))

    weight = plate.weight_g
    if weight is None and plate.filaments:
        total = sum(f.used_g or 0 for f in plate.filaments)
        weight = round(total, 2) if total else None

    return replace(
        plate,
        objects=len(objects),
        object_names=names,
        layer_height=layer_height,
        bed_type=data.get("bed_type"),
        nozzle=nozzle,
        weight_g=weight,
    )


def _summarise(plates: list[PlateReport]) -> tuple[float, float, float]:
    """Return ``(total_g, total_m, total_time_s)`` across ``plates``."""
    total_g = 0.0
    total_m = 0.0
    total_time = 0.0
    for plate in plates:
        for filament in plate.filaments:
            total_g += filament.used_g or 0.0
            total_m += filament.used_m or 0.0
        total_time += plate.prediction_s or 0.0
    return total_g, total_m, total_time


def analyse(
    path: str | Path,
    *,
    price_per_kg: float | None = None,
    currency: str = "RUB",
) -> FileReport:
    """Analyse a single ``.3mf`` archive and return a :class:`FileReport`.

    Args:
        path: Path to the ``.3mf`` file.
        price_per_kg: Optional filament price for cost calculation.
        currency: Currency code recorded in the report.

    Returns:
        A :class:`FileReport`. Unreadable or unsliced files are reported
        with ``sliced=False`` and a human-readable note rather than raising.
    """
    file_path = Path(path)
    notes: list[str] = []
    try:
        size_bytes = file_path.stat().st_size
    except OSError:
        size_bytes = 0

    try:
        archive = zipfile.ZipFile(file_path)
    except (zipfile.BadZipFile, OSError) as exc:
        message = f"cannot read as zip/3mf: {exc}"
        return FileReport(
            path=file_path,
            name=file_path.name,
            size_bytes=size_bytes,
            sliced=False,
            notes=(message,),
            error=message,
        )

    estimated = False
    with archive:
        plates, sliced = parse_slice_info(archive)
        if not sliced:
            plates, estimated = _parse_gcode_plates(archive)
            if plates:
                sliced = True
                notes.append("filament data taken from gcode (slice_info.config is empty)")
        enriched = [_enrich_plate(archive, plate) for plate in plates]

    total_g, total_m, total_time = _summarise(enriched)

    if estimated:
        notes.append(_ESTIMATE_NOTE)
    if not sliced:
        notes.append(
            "file is not sliced (slice_info.config has only a header) - "
            "filament data is not present"
        )

    total_g = round(total_g, 2)
    total_m = round(total_m, 2)

    cost: float | None = None
    if price_per_kg and total_g:
        cost = round(total_g / 1000.0 * price_per_kg, 2)

    return FileReport(
        path=file_path,
        name=file_path.name,
        size_bytes=size_bytes,
        sliced=sliced,
        plates=tuple(enriched),
        total_g=total_g,
        total_m=total_m,
        total_time_s=round(total_time, 2),
        cost=cost,
        notes=tuple(notes),
    )


def analyse_gcode_file(
    path: str | Path,
    *,
    price_per_kg: float | None = None,
    currency: str = "RUB",
) -> FileReport:
    """Analyse a standalone ``.gcode`` file (not wrapped in a 3MF)."""
    file_path = Path(path)
    notes: list[str] = []
    try:
        size_bytes = file_path.stat().st_size
    except OSError:
        size_bytes = 0

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        message = f"cannot read gcode file: {exc}"
        return FileReport(
            path=file_path,
            name=file_path.name,
            size_bytes=size_bytes,
            sliced=False,
            notes=(message,),
            error=message,
        )

    sample = text[:_GCODE_SAMPLE_BYTES] + text[-_GCODE_SAMPLE_BYTES:]
    grams, metres, cubic_cm, time_s = _parse_gcode_blob(sample)

    plates: list[PlateReport] = []
    if grams is not None or metres is not None or cubic_cm is not None:
        grams, estimated = _gcode_grams(grams, metres, cubic_cm)
        plates.append(
            PlateReport(
                index="1",
                prediction_s=time_s,
                weight_g=grams,
                filaments=(FilamentUsage(id="1", type="?", used_g=grams, used_m=metres),),
                source=SliceSource.GCODE,
            )
        )
        if estimated:
            notes.append(_ESTIMATE_NOTE)

    sliced = bool(plates)
    if not sliced:
        notes.append("no filament data found in gcode header/tail")

    total_g, total_m, total_time = _summarise(plates)
    total_g = round(total_g, 2)
    total_m = round(total_m, 2)

    cost: float | None = None
    if price_per_kg and total_g:
        cost = round(total_g / 1000.0 * price_per_kg, 2)

    return FileReport(
        path=file_path,
        name=file_path.name,
        size_bytes=size_bytes,
        sliced=sliced,
        plates=tuple(plates),
        total_g=total_g,
        total_m=total_m,
        total_time_s=round(total_time, 2),
        cost=cost,
        notes=tuple(notes),
    )


def is_sliced_3mf(path: str | Path) -> bool:
    """Return ``True`` when ``path`` is a sliced 3MF with filament data.

    A file counts as sliced when ``slice_info.config`` carries at least one
    ``<plate>`` element or when a ``Metadata/plate_N.gcode`` entry exists.
    Unreadable archives simply return ``False``.
    """
    file_path = Path(path)
    try:
        with zipfile.ZipFile(file_path) as archive:
            _, sliced = parse_slice_info(archive)
            if sliced:
                return True
            return bool(parse_gcode(archive))
    except (zipfile.BadZipFile, OSError):
        return False
