"""Render a :class:`~filament_meter.models.RunReport` to text.

Four formats are supported and share the same underlying model:

* ``table`` — human-readable ASCII (the default);
* ``json`` — ``RunReport.to_dict()`` with ``ensure_ascii=False``;
* ``csv`` — ``;``-separated, matching the legacy ``filament_report.csv``;
* ``md`` — a Markdown table with totals.

The output file format is chosen from the file extension by
:func:`output_format_for`; unknown extensions fall back to ``table``.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from filament_meter.models import PlateReport, RunReport
from filament_meter.parser import fmt_time

#: Format identifiers accepted by :func:`render`.
FORMATS: tuple[str, ...] = ("table", "json", "csv", "md")

#: Extension → format mapping for ``--output``.
_EXTENSION_FORMATS: dict[str, str] = {
    ".json": "json",
    ".csv": "csv",
    ".md": "md",
    ".markdown": "md",
    ".txt": "table",
    ".text": "table",
}

#: CSV column header, kept identical to the legacy report.
CSV_HEADER: list[str] = [
    "файл",
    "нарезан",
    "плашка",
    "id филамента",
    "тип",
    "цвет",
    "граммы",
    "метры",
    "время, с",
    "цена, ₽",
]


def output_format_for(path: str | Path) -> str:
    """Return the output format implied by ``path``'s extension."""
    return _EXTENSION_FORMATS.get(Path(path).suffix.lower(), "table")


def _format_number(value: float | None) -> str:
    """Render an optional float as ``"?.??"`` or ``"?"``."""
    return f"{value:.2f}" if value is not None else "?"


def render_table(run: RunReport) -> str:
    """Render the human-readable ASCII report."""
    lines: list[str] = []
    for report in run.files:
        lines.append("=" * 72)
        lines.append(f"{report.name}   ({report.size_bytes / 1048576:.2f} MB)")
        lines.append(f"  {report.path}")

        if not report.sliced:
            lines.append("  [!] not sliced - filament data is not present.")
            for note in report.notes:
                lines.append(f"      {note}")
            continue

        for plate in report.plates:
            lines.extend(_render_plate_lines(plate))

        lines.append(
            f"  TOTAL: {report.total_g:.2f} g, {report.total_m:.2f} m, "
            f"time ~{fmt_time(report.total_time_s)}"
        )
        if report.cost is not None and run.price_per_kg:
            lines.append(
                f"  cost at {run.price_per_kg:g} {run.currency}/kg: "
                f"{report.cost:.2f} {run.currency}"
            )
        for note in report.notes:
            lines.append(f"  ({note})")

    lines.append("=" * 72)
    lines.append(
        f"files: {len(run.files)} | sliced: {run.sliced_count} | failed: {run.failed_count}"
    )
    lines.append(
        f"TOTAL: {run.total_g:.2f} g, {run.total_m:.2f} m, time ~{fmt_time(run.total_time_s)}"
    )
    if run.total_cost is not None:
        lines.append(f"TOTAL cost: {run.total_cost:.2f} {run.currency}")
    return "\n".join(lines)


def _render_plate_lines(plate: PlateReport) -> list[str]:
    """Render a single plate block for the table format."""
    lines: list[str] = []
    head = f"  Plate {plate.index}"
    if plate.objects is not None:
        head += f" | objects: {plate.objects}"
    if plate.layer_height:
        head += f" | layer: {plate.layer_height:.2f} mm"
    if plate.nozzle:
        head += f" | nozzle: {plate.nozzle} mm"
    lines.append(head)
    if plate.bed_type:
        lines.append(f"      bed: {plate.bed_type}")

    if not plate.filaments:
        lines.append("      (no filament reported)")
        return lines

    lines.append(f"      {'#':<3}{'type':<10}{'color':<10}{'grams':>9}{'metres':>9}")
    for filament in plate.filaments:
        grams = _format_number(filament.used_g)
        metres = _format_number(filament.used_m)
        lines.append(
            f"      {filament.id:<3}{str(filament.type or '?'):<10}"
            f"{str(filament.color or '-'):<10}{grams:>9}{metres:>9}"
        )
    if plate.weight_g is not None:
        lines.append(
            f"      plate total: {plate.weight_g:.2f} g | time: {fmt_time(plate.prediction_s)}"
        )
    return lines


def render_json(run: RunReport) -> str:
    """Render the report as pretty-printed JSON."""
    return json.dumps(run.to_dict(), ensure_ascii=False, indent=2)


def _csv_rows(run: RunReport) -> list[list[object]]:
    """Build the CSV row matrix for ``run``."""
    rows: list[list[object]] = [list(CSV_HEADER)]
    for report in run.files:
        if not report.sliced or not report.plates:
            rows.append([report.name, "нет", "", "", "", "", "", "", "", ""])
            continue
        for plate in report.plates:
            filaments = plate.filaments or (None,)
            for filament in filaments:
                row_cost: object = ""
                if run.price_per_kg and filament is not None and filament.used_g:
                    row_cost = round(filament.used_g / 1000.0 * run.price_per_kg, 2)
                rows.append(
                    [
                        report.name,
                        "да",
                        plate.index,
                        filament.id if filament else "",
                        filament.type if filament else "",
                        filament.color if filament else "",
                        filament.used_g if filament else "",
                        filament.used_m if filament else "",
                        plate.prediction_s,
                        row_cost,
                    ]
                )
    return rows


def render_csv(run: RunReport) -> str:
    """Render the report as ``;``-separated CSV (without a BOM)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerows(_csv_rows(run))
    return buffer.getvalue()


def render_md(run: RunReport) -> str:
    """Render the report as a Markdown table with a totals footer."""
    lines: list[str] = []
    lines.append("# Filament usage report")
    lines.append("")
    lines.append(f"- Generated: {run.generated_at}")
    lines.append(f"- filament-meter: {run.tool_version}")
    if run.orca_version:
        lines.append(f"- OrcaSlicer: {run.orca_version}")
    if run.price_per_kg:
        lines.append(f"- Price: {run.price_per_kg:g} {run.currency}/kg")
    lines.append("")
    lines.append("| file | sliced | plate | filament | type | colour | grams | metres | time |")
    lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |")
    for report in run.files:
        if not report.sliced or not report.plates:
            lines.append(f"| {report.name} | no |  |  |  |  |  |  |  |")
            continue
        for plate in report.plates:
            filaments = plate.filaments or (None,)
            for filament in filaments:
                lines.append(
                    "| {name} | yes | {plate} | {fid} | {ftype} | {color} | "
                    "{grams} | {metres} | {time} |".format(
                        name=report.name,
                        plate=plate.index,
                        fid=filament.id if filament else "",
                        ftype=(filament.type if filament else "") or "",
                        color=(filament.color if filament else "") or "",
                        grams=_format_number(filament.used_g if filament else None),
                        metres=_format_number(filament.used_m if filament else None),
                        time=fmt_time(plate.prediction_s),
                    )
                )
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(
        f"- Files: {len(run.files)} (sliced: {run.sliced_count}, failed: {run.failed_count})"
    )
    lines.append(f"- Filament: **{run.total_g:.2f} g** / {run.total_m:.2f} m")
    lines.append(f"- Print time: ~{fmt_time(run.total_time_s)}")
    if run.total_cost is not None:
        lines.append(f"- Cost: **{run.total_cost:.2f} {run.currency}**")
    return "\n".join(lines)


def render(run: RunReport, fmt: str = "table") -> str:
    """Render ``run`` in the requested ``fmt``.

    Args:
        run: The report to render.
        fmt: One of :data:`FORMATS`.

    Returns:
        The rendered text.

    Raises:
        ValueError: If ``fmt`` is not a known format.
    """
    if fmt == "table":
        return render_table(run)
    if fmt == "json":
        return render_json(run)
    if fmt == "csv":
        return render_csv(run)
    if fmt == "md":
        return render_md(run)
    raise ValueError(f"unknown format: {fmt!r} (expected one of {', '.join(FORMATS)})")


def write_report(run: RunReport, output_path: str | Path, fmt: str | None = None) -> Path:
    """Render ``run`` to ``output_path``.

    Args:
        run: The report to render.
        output_path: Destination file.
        fmt: Explicit format; when ``None`` it is derived from the extension.

    Returns:
        The absolute path of the written file.
    """
    path = Path(output_path)
    resolved_fmt = fmt or output_format_for(path)
    text = render(run, resolved_fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if resolved_fmt == "csv" else "utf-8"
    path.write_text(text, encoding=encoding)
    return path.resolve()
