"""Tests for :mod:`filament_meter.report`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from filament_meter.models import (
    FilamentUsage,
    FileReport,
    PlateReport,
    RunReport,
    SliceSource,
)
from filament_meter.report import (
    FORMATS,
    output_format_for,
    render,
    render_csv,
    render_json,
    render_md,
    render_table,
    write_report,
)


def _sample_run() -> RunReport:
    filament = FilamentUsage(id="1", type="PLA", color="#8E9089", used_g=96.54, used_m=31.85)
    plate = PlateReport(
        index="1",
        prediction_s=21439,
        weight_g=96.54,
        nozzle="0.4",
        layer_height=0.2,
        objects=1,
        object_names=("model.stl_A",),
        bed_type="textured_plate",
        filaments=(filament,),
        source=SliceSource.SLICE_INFO,
    )
    file_ok = FileReport(
        path=Path("/models/Gesha_sliced.3mf"),
        name="Gesha_sliced.3mf",
        size_bytes=26_631_548,
        sliced=True,
        plates=(plate,),
        total_g=96.54,
        total_m=31.85,
        total_time_s=21439,
        cost=212.39,
        notes=(),
    )
    file_skipped = FileReport(
        path=Path("/models/raw.3mf"),
        name="raw.3mf",
        size_bytes=1024,
        sliced=False,
        notes=("not sliced",),
    )
    return RunReport(
        generated_at="2026-10-05T00:00:00+00:00",
        tool_version="0.1.0",
        orca_version="2.4.2",
        price_per_kg=2200.0,
        currency="RUB",
        files=(file_ok, file_skipped),
        total_g=96.54,
        total_m=31.85,
        total_time_s=21439,
        total_cost=212.39,
        sliced_count=1,
        failed_count=0,
    )


def test_render_table_contains_totals() -> None:
    text = render_table(_sample_run())
    assert "Gesha_sliced.3mf" in text
    assert "96.54" in text
    assert "5h 57m" in text
    assert "not sliced" in text


def test_render_json_roundtrip() -> None:
    text = render_json(_sample_run())
    data = json.loads(text)
    assert data["total_g"] == pytest.approx(96.54)
    assert data["files"][0]["plates"][0]["filaments"][0]["type"] == "PLA"
    assert data["files"][1]["sliced"] is False


def test_render_csv_header_and_rows() -> None:
    text = render_csv(_sample_run())
    lines = text.strip().splitlines()
    assert lines[0].startswith("файл;нарезан;плашка")
    assert "Gesha_sliced.3mf;да;1;1;PLA;#8E9089;96.54;31.85" in lines[1]
    assert "raw.3mf;нет" in lines[2]


def test_render_md_contains_totals() -> None:
    text = render_md(_sample_run())
    assert "# Filament usage report" in text
    assert "**96.54 g**" in text


def test_render_dispatch_and_unknown_format() -> None:
    run = _sample_run()
    for fmt in FORMATS:
        assert isinstance(render(run, fmt), str)
    with pytest.raises(ValueError):
        render(run, "yaml")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("report.json", "json"),
        ("report.csv", "csv"),
        ("report.md", "md"),
        ("report.txt", "table"),
        ("report.weird", "table"),
        ("noextension", "table"),
    ],
)
def test_output_format_for(name: str, expected: str) -> None:
    assert output_format_for(name) == expected


def test_write_report_json(tmp_path: Path) -> None:
    target = tmp_path / "out" / "report.json"
    written = write_report(_sample_run(), target)
    assert written == target.resolve()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["tool_version"] == "0.1.0"


def test_write_report_csv_uses_bom(tmp_path: Path) -> None:
    target = tmp_path / "report.csv"
    write_report(_sample_run(), target)
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")


def test_write_report_unknown_extension_is_table(tmp_path: Path) -> None:
    target = tmp_path / "report.log"
    write_report(_sample_run(), target)
    assert "TOTAL" in target.read_text(encoding="utf-8")
