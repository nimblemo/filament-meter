"""Builders for synthetic ``.3mf`` archives and G-code files.

Everything is assembled in memory with :mod:`zipfile` so the tests stay
fast and dependency-free. The shapes mirror real Bambu Studio /
OrcaSlicer output closely enough for the parser to be exercised on every
code path.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

_SLICE_INFO_HEADER = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="OrcaSlicer-Version" value="2.4.2"/>
  </header>
{plates}</config>
"""

_PLATE_TEMPLATE = """  <plate>
    <metadata key="index" value="{index}"/>
    <metadata key="nozzle_diameters" value="{nozzle}"/>
    <metadata key="prediction" value="{prediction}"/>
    <metadata key="weight" value="{weight}"/>
{filaments}  </plate>
"""

_FILAMENT_TEMPLATE = (
    '    <filament id="{fid}" tray_info_idx="{tray}" type="{ftype}" '
    'color="{color}" used_m="{used_m}" used_g="{used_g}"/>\n'
)


def _filament_xml(
    *,
    fid: str,
    ftype: str,
    color: str,
    used_g: float,
    used_m: float,
    tray: str = "GFA00",
) -> str:
    return _FILAMENT_TEMPLATE.format(
        fid=fid, ftype=ftype, color=color, used_g=used_g, used_m=used_m, tray=tray
    )


def build_slice_info(
    plates: list[dict[str, object]] | None,
) -> str:
    """Return a ``slice_info.config`` body for the given plates.

    Each plate dict accepts the keys ``index``, ``nozzle``, ``prediction``,
    ``weight`` and ``filaments`` (a list of filament dicts).
    """
    if not plates:
        return _SLICE_INFO_HEADER.format(plates="")
    chunks: list[str] = []
    for plate in plates:
        filaments = plate.get("filaments") or []
        filament_xml = "".join(
            _filament_xml(
                fid=str(fil.get("id", "1")),
                ftype=str(fil.get("type", "PLA")),
                color=str(fil.get("color", "#FFFFFF")),
                used_g=float(fil.get("used_g", 0.0)),
                used_m=float(fil.get("used_m", 0.0)),
                tray=str(fil.get("tray", "GFA00")),
            )
            for fil in filaments
        )
        chunks.append(
            _PLATE_TEMPLATE.format(
                index=plate.get("index", "1"),
                nozzle=plate.get("nozzle", "0.4"),
                prediction=plate.get("prediction", 0),
                weight=plate.get("weight", 0),
                filaments=filament_xml,
            )
        )
    return _SLICE_INFO_HEADER.format(plates="".join(chunks))


def plate_json(
    *,
    name: str = "model.stl_A",
    layer_height: float = 0.2,
    nozzle: float = 0.4,
    bed_type: str = "textured_plate",
    objects: int = 1,
) -> str:
    """Return a ``plate_N.json`` body with ``objects`` bounding boxes."""
    bbox_objects = [
        {"name": f"{name}_{i}", "layer_height": layer_height, "id": i} for i in range(objects)
    ]
    payload = {
        "bbox_all": [0.0, 0.0, 10.0, 10.0],
        "bbox_objects": bbox_objects,
        "bed_type": bed_type,
        "nozzle_diameter": nozzle,
        "filament_colors": ["#FFFFFF"],
        "version": 2,
    }
    return json.dumps(payload)


def gcode_body(
    *,
    grams: float | None = 12.5,
    millimetres: float | None = 4200.0,
    cubic_cm: float | None = None,
    time_text: str = "1h 2m 3s",
) -> str:
    """Return a minimal G-code body with the filament footer comments."""
    lines = ["; HEADER_BLOCK_START", "G28", "G1 X0 Y0"]
    if grams is not None:
        lines.append(f"; filament used [g] = {grams}")
    if millimetres is not None:
        lines.append(f"; filament used [mm] = {millimetres}")
    if cubic_cm is not None:
        lines.append(f"; filament used [cm3] = {cubic_cm}")
    lines.append(f"; total estimated time: {time_text}")
    lines.append("; HEADER_BLOCK_END")
    return "\n".join(lines) + "\n"


def write_3mf(path: str | Path, entries: dict[str, str | bytes]) -> Path:
    """Write a ``.3mf`` (zip) file at ``path`` with ``entries``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(name, data)
    return target


def make_sliced_3mf(
    path: str | Path,
    *,
    used_g: float = 96.54,
    used_m: float = 31.85,
    prediction: float = 21439,
    ftype: str = "PLA",
    color: str = "#8E9089",
    fid: str = "4",
    index: str = "1",
    nozzle: str = "0.4",
    weight: float | None = None,
    with_plate_json: bool = True,
    objects: int = 1,
    layer_height: float = 0.2,
) -> Path:
    """Create a *sliced* ``.3mf`` carrying one plate and one filament."""
    if weight is None:
        weight = used_g
    slice_info = build_slice_info(
        [
            {
                "index": index,
                "nozzle": nozzle,
                "prediction": prediction,
                "weight": weight,
                "filaments": [
                    {
                        "id": fid,
                        "type": ftype,
                        "color": color,
                        "used_g": used_g,
                        "used_m": used_m,
                    }
                ],
            }
        ]
    )
    entries: dict[str, str | bytes] = {"Metadata/slice_info.config": slice_info}
    if with_plate_json:
        entries[f"Metadata/plate_{index}.json"] = plate_json(
            layer_height=layer_height, objects=objects
        )
    return write_3mf(path, entries)


def make_multi_filament_3mf(path: str | Path) -> Path:
    """Create a sliced ``.3mf`` with two plates and multiple filaments."""
    slice_info = build_slice_info(
        [
            {
                "index": "1",
                "prediction": 3600,
                "weight": 30.0,
                "filaments": [
                    {"id": "1", "type": "PLA", "color": "#FF0000", "used_g": 10.0, "used_m": 3.3},
                    {"id": "2", "type": "PETG", "color": "#00FF00", "used_g": 20.0, "used_m": 6.6},
                ],
            },
            {
                "index": "2",
                "prediction": 1800,
                "weight": 5.0,
                "filaments": [
                    {"id": "1", "type": "PLA", "color": "#0000FF", "used_g": 5.0, "used_m": 1.6},
                ],
            },
        ]
    )
    return write_3mf(
        path,
        {
            "Metadata/slice_info.config": slice_info,
            "Metadata/plate_1.json": plate_json(objects=2),
            "Metadata/plate_2.json": plate_json(objects=1),
        },
    )


def make_unsliced_3mf(path: str | Path) -> Path:
    """Create a ``.3mf`` whose ``slice_info.config`` has only a header."""
    return write_3mf(
        path,
        {
            "Metadata/slice_info.config": build_slice_info(None),
            "Metadata/plate_1.json": plate_json(),
        },
    )


def make_gcode_3mf(path: str | Path, *, with_slice_info_header: bool = True) -> Path:
    """Create a ``.3mf`` that only carries filament data in the G-code."""
    entries: dict[str, str | bytes] = {
        "Metadata/plate_1.gcode": gcode_body(),
        "Metadata/plate_1.json": plate_json(),
    }
    if with_slice_info_header:
        entries["Metadata/slice_info.config"] = build_slice_info(None)
    return write_3mf(path, entries)


def make_gcode_file(path: str | Path) -> Path:
    """Create a standalone ``.gcode`` file with a filament footer."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(gcode_body(), encoding="utf-8")
    return target


def make_bad_zip(path: str | Path) -> Path:
    """Create a file that is not a valid zip archive."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"this is definitely not a zip archive")
    return target
