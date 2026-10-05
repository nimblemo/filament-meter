"""Tests for :mod:`filament_meter.parser`."""

from __future__ import annotations

from pathlib import Path

import pytest

import factories
from filament_meter.models import SliceSource
from filament_meter.parser import (
    analyse,
    analyse_gcode_file,
    fmt_time,
    is_sliced_3mf,
    parse_time_text,
    to_float,
)


def test_analyse_slice_info_path(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(
        tmp_path / "Gesha.3mf", used_g=96.54, used_m=31.85, prediction=21439
    )
    report = analyse(model)
    assert report.sliced is True
    assert report.has_data is True
    assert report.total_g == pytest.approx(96.54)
    assert report.total_m == pytest.approx(31.85)
    assert report.total_time_s == pytest.approx(21439)
    assert report.plates[0].source is SliceSource.SLICE_INFO
    assert report.plates[0].filaments[0].type == "PLA"
    assert report.plates[0].objects == 1
    assert report.plates[0].layer_height == pytest.approx(0.2)


def test_analyse_gcode_fallback(tmp_path: Path) -> None:
    model = factories.make_gcode_3mf(tmp_path / "fallback.3mf")
    report = analyse(model)
    assert report.sliced is True
    assert report.total_g == pytest.approx(12.5)
    assert report.total_m == pytest.approx(4.2)
    assert report.plates[0].source is SliceSource.GCODE
    assert any("gcode" in note for note in report.notes)


def test_analyse_gcode_estimate_from_millimetres(tmp_path: Path) -> None:
    body = factories.gcode_body(grams=None, millimetres=1000.0)
    model = factories.write_3mf(
        tmp_path / "estimate.3mf",
        {
            "Metadata/plate_1.gcode": body,
            "Metadata/slice_info.config": factories.build_slice_info(None),
        },
    )
    report = analyse(model)
    assert report.sliced is True
    # 1000 mm -> 1 m -> 1.24 g with the documented density.
    assert report.total_g == pytest.approx(1.24)


def test_analyse_unsliced_file(tmp_path: Path) -> None:
    model = factories.make_unsliced_3mf(tmp_path / "raw.3mf")
    report = analyse(model)
    assert report.sliced is False
    assert report.has_data is False
    assert report.error is None
    assert any("not sliced" in note for note in report.notes)


def test_analyse_bad_zip(tmp_path: Path) -> None:
    bad = factories.make_bad_zip(tmp_path / "broken.3mf")
    report = analyse(bad)
    assert report.sliced is False
    assert report.error is not None
    assert "cannot read" in report.error


def test_analyse_multiple_plates_and_filaments(tmp_path: Path) -> None:
    model = factories.make_multi_filament_3mf(tmp_path / "multi.3mf")
    report = analyse(model)
    assert len(report.plates) == 2
    assert report.total_g == pytest.approx(35.0)
    assert report.total_m == pytest.approx(11.5)
    assert report.total_time_s == pytest.approx(5400)
    assert len(report.plates[0].filaments) == 2


def test_analyse_cost_calculation(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "cost.3mf", used_g=100.0)
    report = analyse(model, price_per_kg=2200.0)
    assert report.cost == pytest.approx(220.0)


def test_analyse_gcode_file(tmp_path: Path) -> None:
    gcode = factories.make_gcode_file(tmp_path / "standalone.gcode")
    report = analyse_gcode_file(gcode)
    assert report.sliced is True
    assert report.total_g == pytest.approx(12.5)
    assert report.plates[0].source is SliceSource.GCODE


def test_analyse_gcode_multi_slot_sums_all_values(tmp_path: Path) -> None:
    body = (
        "; HEADER\nG28\n"
        "; filament used [mm] = 0.00, 0.00, 0.00, 31853.89, 0.00\n"
        "; filament used [g] = 0.00, 0.00, 0.00, 96.54, 0.00\n"
        "; total estimated time: 5h 57m\n"
    )
    gcode = tmp_path / "multi_slot.gcode"
    gcode.write_text(body, encoding="utf-8")
    report = analyse_gcode_file(gcode)
    assert report.total_g == pytest.approx(96.54)
    assert report.total_m == pytest.approx(31.85)
    assert report.total_time_s == pytest.approx(21420)


def test_analyse_gcode_direct_grams_has_no_estimate_note(tmp_path: Path) -> None:
    """When `; filament used [g]` is present, no estimate note is added."""
    model = factories.make_gcode_3mf(tmp_path / "direct.3mf")
    report = analyse(model)
    assert report.total_g == pytest.approx(12.5)
    assert not any("estimated" in note for note in report.notes)


def test_analyse_gcode_length_only_has_estimate_note(tmp_path: Path) -> None:
    """When only a length is present, the mass is estimated and noted."""
    body = factories.gcode_body(grams=None, millimetres=1000.0)
    model = factories.write_3mf(
        tmp_path / "length_only.3mf",
        {
            "Metadata/plate_1.gcode": body,
            "Metadata/slice_info.config": factories.build_slice_info(None),
        },
    )
    report = analyse(model)
    assert report.total_g == pytest.approx(1.24)
    assert any("estimated" in note for note in report.notes)


def test_is_sliced_3mf(tmp_path: Path) -> None:
    sliced = factories.make_sliced_3mf(tmp_path / "sliced.3mf")
    raw = factories.make_unsliced_3mf(tmp_path / "raw.3mf")
    assert is_sliced_3mf(sliced) is True
    assert is_sliced_3mf(raw) is False


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "?"),
        (45, "45s"),
        (3600, "1h 00m"),
        (21439, "5h 57m"),
        ("not-a-number", "?"),
    ],
)
def test_fmt_time(seconds: object, expected: str) -> None:
    assert fmt_time(seconds) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, None),
        ("2137", 2137.0),
        ("35m 37s", 2137.0),
        ("1h 2m", 3720.0),
        ("nonsense", None),
    ],
)
def test_parse_time_text(text: object, expected: float | None) -> None:
    assert parse_time_text(text) == expected


def test_to_float() -> None:
    assert to_float("1,5") == pytest.approx(1.5)
    assert to_float(None) is None
    assert to_float("abc") is None
