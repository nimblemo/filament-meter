"""Tests for :mod:`filament_meter.discovery`."""

from __future__ import annotations

from pathlib import Path

import pytest

import factories
from filament_meter.discovery import DEFAULT_PATTERNS, GCODE_FALLBACK_PATTERNS, discover
from filament_meter.errors import DiscoveryError


def test_discover_single_file(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "model.3mf")
    result = discover(model)
    assert result == [model]


def test_discover_directory_recursive(tmp_path: Path) -> None:
    factories.make_sliced_3mf(tmp_path / "a.3mf")
    nested = tmp_path / "sub"
    factories.make_sliced_3mf(nested / "b.3mf")
    (tmp_path / "note.txt").write_text("ignore me", encoding="utf-8")

    result = discover(tmp_path, recursive=True)
    names = sorted(p.name for p in result)
    assert names == ["a.3mf", "b.3mf"]


def test_discover_directory_non_recursive(tmp_path: Path) -> None:
    factories.make_sliced_3mf(tmp_path / "a.3mf")
    factories.make_sliced_3mf(tmp_path / "sub" / "b.3mf")

    result = discover(tmp_path, recursive=False)
    assert [p.name for p in result] == ["a.3mf"]


def test_discover_glob_pattern(tmp_path: Path) -> None:
    factories.make_sliced_3mf(tmp_path / "one.3mf")
    factories.make_sliced_3mf(tmp_path / "two.3mf")
    (tmp_path / "three.stl").write_text("mesh", encoding="utf-8")

    result = discover(str(tmp_path / "*.3mf"))
    assert sorted(p.name for p in result) == ["one.3mf", "two.3mf"]


def test_discover_deduplicates(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "model.3mf")
    # Passing the file twice (file + directory) must yield it once.
    result = discover(str(model))
    assert result.count(model) == 1


def test_discover_missing_path_raises(tmp_path: Path) -> None:
    with pytest.raises(DiscoveryError):
        discover(tmp_path / "does-not-exist.3mf")


def test_discover_custom_patterns(tmp_path: Path) -> None:
    factories.make_sliced_3mf(tmp_path / "model.3mf")
    (tmp_path / "mesh.stl").write_text("mesh", encoding="utf-8")
    result = discover(tmp_path, patterns=["*.stl"])
    assert [p.name for p in result] == ["mesh.stl"]


def test_default_patterns_exclude_gcode() -> None:
    """``*.gcode`` must not be a default: it would double-count sliced models."""
    assert "*.3mf" in DEFAULT_PATTERNS
    assert "*.stl" in DEFAULT_PATTERNS
    assert "*.obj" in DEFAULT_PATTERNS
    assert "*.gcode" not in DEFAULT_PATTERNS
    assert GCODE_FALLBACK_PATTERNS == ("*.gcode",)


def test_directory_with_gcode_byproduct_is_not_double_counted(tmp_path: Path) -> None:
    """A ``.3mf`` and its ``.gcode`` twin must resolve to a single model."""
    factories.make_sliced_3mf(tmp_path / "lamp_sliced.3mf")
    gcode_dir = tmp_path / "gcode"
    factories.make_gcode_file(gcode_dir / "lamp.gcode")

    result = discover(tmp_path, recursive=True)
    assert [p.name for p in result] == ["lamp_sliced.3mf"]


def test_gcode_only_directory_yields_nothing_by_default(tmp_path: Path) -> None:
    """Default masks skip a G-code-only directory (the CLI adds a fallback)."""
    factories.make_gcode_file(tmp_path / "plate_1.gcode")
    assert discover(tmp_path, recursive=True) == []
