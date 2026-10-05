"""End-to-end tests for the ``filament-meter`` CLI.

Every test calls :func:`filament_meter.cli.app.main` directly (no
subprocess) and mocks OrcaSlicer so the suite never slices for real.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import factories
from filament_meter import slicer
from filament_meter.cli import app
from filament_meter.errors import ProfileNotFoundError
from filament_meter.slicer import SliceResult


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    code = app.main(["--version"])
    assert code == 0
    assert "filament-meter 0.2.0" in capsys.readouterr().out


def test_no_path_is_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    code = app.main([])
    assert code == 2
    assert "PATH is required" in capsys.readouterr().err


def test_missing_path_is_usage_error(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code = app.main([str(tmp_path / "nope.3mf")])
    assert code == 2
    assert "path not found" in capsys.readouterr().err


def test_check_when_orca_present(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(app, "cache_root", lambda override=None: tmp_path / "cache")
    fake_orca = Path("/fake/orca")
    monkeypatch.setattr(app, "find_orca", lambda explicit=None: fake_orca)
    monkeypatch.setattr(app, "orca_version", lambda binary: "2.4.2")

    code = app.main(["--check"])
    out = capsys.readouterr().out
    assert code == 0
    assert f"OrcaSlicer: {fake_orca}" in out
    assert "2.4.2" in out


def test_check_when_orca_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.setattr(app, "cache_root", lambda override=None: tmp_path / "cache")
    monkeypatch.setattr(app, "find_orca", lambda explicit=None: None)

    code = app.main(["--check"])
    assert code == 2
    assert "not found" in capsys.readouterr().out


def test_install_orca(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    code = app.main(["--install-orca"])
    assert code == 0
    assert "OrcaSlicer ready" in capsys.readouterr().out


def test_install_orca_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom(*args: object, **kwargs: object) -> Path:
        raise ProfileNotFoundError("no network")

    monkeypatch.setattr(app, "ensure_orca", boom)
    code = app.main(["--install-orca"])
    assert code == 2
    assert "no network" in capsys.readouterr().err


def test_run_sliced_file_success(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "Gesha_sliced.3mf", used_g=96.54, used_m=31.85)
    code = app.main([str(model)])
    out = capsys.readouterr().out
    assert code == 0
    assert "96.54" in out
    assert "31.85" in out


def test_run_unsliced_with_no_slice_is_failure(tmp_path: Path) -> None:
    model = factories.make_unsliced_3mf(tmp_path / "raw.3mf")
    code = app.main([str(model), "--no-slice"])
    assert code == 3


def test_corrupt_3mf_reports_error_without_slicing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """A non-zip .3mf must be flagged as an error, never sent to OrcaSlicer."""
    bad = factories.make_bad_zip(tmp_path / "broken.3mf")

    sliced_calls: list[object] = []
    orca_calls: list[object] = []
    monkeypatch.setattr(slicer, "_run_process", lambda *a, **k: sliced_calls.append(a))
    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: orca_calls.append(a))

    code = app.main([str(bad)])
    out = capsys.readouterr().out
    assert code == 3
    assert sliced_calls == []
    assert orca_calls == []
    assert "not a valid 3mf archive" in out


def test_stl_still_goes_to_slicer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A bare .stl is not a zip and must still be sliced."""
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "part_out.3mf", used_g=5.0, used_m=1.65)

    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: None)
    monkeypatch.setattr(
        app, "resolve_profiles", lambda *a, **k: {"machine": "m", "process": "p", "filament": "f"}
    )
    calls: list[object] = []

    def fake_slice(*args: object, **kwargs: object) -> SliceResult:
        calls.append(args)
        return SliceResult(True, sliced, "log", 1)

    monkeypatch.setattr(app, "run_slice", fake_slice)

    code = app.main([str(source)])
    assert code == 0
    assert len(calls) == 1


def test_run_partial_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factories.make_sliced_3mf(tmp_path / "good_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_bad_zip(tmp_path / "broken.3mf")

    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: None)

    def no_profiles(*args: object, **kwargs: object) -> dict[str, str]:
        raise ProfileNotFoundError("profiles missing")

    monkeypatch.setattr(app, "resolve_profiles", no_profiles)

    code = app.main([str(tmp_path)])
    assert code == 1


def test_run_slice_flow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "sliced_out.3mf", used_g=42.0, used_m=13.86)

    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: "2.4.2")
    monkeypatch.setattr(
        app, "resolve_profiles", lambda *a, **k: {"machine": "m", "process": "p", "filament": "f"}
    )
    monkeypatch.setattr(app, "run_slice", lambda *a, **k: SliceResult(True, sliced, "log", 1))

    code = app.main([str(source)])
    out = capsys.readouterr().out
    assert code == 0
    assert "42.00" in out
    assert "part.stl" in out


def test_output_written_to_file(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "model_sliced.3mf", used_g=55.0, used_m=18.0)
    out_file = tmp_path / "report.json"
    code = app.main([str(model), "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["total_g"] == pytest.approx(55.0)
    assert data["files"][0]["name"] == "model_sliced.3mf"


def test_output_csv_extension(tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "model_sliced.3mf")
    out_file = tmp_path / "report.csv"
    code = app.main([str(model), "-o", str(out_file)])
    assert code == 0
    assert out_file.read_bytes().startswith(b"\xef\xbb\xbf")


def test_force_slice_calls_slicer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    model = factories.make_sliced_3mf(tmp_path / "already_sliced.3mf", used_g=1.0, used_m=0.3)
    sliced = factories.make_sliced_3mf(tmp_path / "again_sliced.3mf", used_g=2.0, used_m=0.6)

    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: None)
    monkeypatch.setattr(
        app, "resolve_profiles", lambda *a, **k: {"machine": "m", "process": "p", "filament": "f"}
    )
    calls: list[object] = []

    def fake_slice(*args: object, **kwargs: object) -> SliceResult:
        calls.append(args)
        return SliceResult(True, sliced, "log", 1)

    monkeypatch.setattr(app, "run_slice", fake_slice)

    code = app.main([str(model), "--force-slice"])
    assert code == 0
    assert len(calls) == 1


def test_use_project_settings_skips_profiles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "out_sliced.3mf", used_g=3.0, used_m=0.9)

    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: None)

    def must_not_call(*args: object, **kwargs: object) -> dict[str, str]:
        raise AssertionError("resolve_profiles must not be called with --use-project-settings")

    monkeypatch.setattr(app, "resolve_profiles", must_not_call)
    monkeypatch.setattr(app, "run_slice", lambda *a, **k: SliceResult(True, sliced, "log", 1))

    code = app.main([str(source), "--use-project-settings"])
    assert code == 0


def test_standalone_gcode_file(tmp_path: Path) -> None:
    gcode = factories.make_gcode_file(tmp_path / "part.gcode")
    code = app.main([str(gcode)])
    assert code == 0


def test_directory_does_not_double_count_gcode_byproduct(tmp_path: Path) -> None:
    """A sliced ``.3mf`` plus its ``.gcode`` twin must count once."""
    factories.make_sliced_3mf(tmp_path / "lamp_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_gcode_file(tmp_path / "gcode" / "lamp.gcode")

    out_file = tmp_path / "report.json"
    code = app.main([str(tmp_path), "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "lamp_sliced.3mf"
    assert data["total_g"] == pytest.approx(10.0)


def test_directory_gcode_fallback(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """A G-code-only directory is picked up via the ``*.gcode`` fallback."""
    factories.make_gcode_file(tmp_path / "plate_1.gcode")

    code = app.main([str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert "falling back to *.gcode" in captured.err


def test_explicit_gcode_file_always_processed(tmp_path: Path) -> None:
    """An explicitly named ``.gcode`` is processed even next to a ``.3mf``."""
    factories.make_sliced_3mf(tmp_path / "lamp_sliced.3mf", used_g=10.0, used_m=3.3)
    gcode = factories.make_gcode_file(tmp_path / "lamp.gcode")

    out_file = tmp_path / "report.json"
    code = app.main([str(gcode), "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "lamp.gcode"


def test_glob_overrides_default_patterns(tmp_path: Path) -> None:
    """An explicit ``--glob`` replaces the default directory masks."""
    factories.make_sliced_3mf(tmp_path / "lamp_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_gcode_file(tmp_path / "lamp.gcode")

    out_file = tmp_path / "report.json"
    code = app.main([str(tmp_path), "--glob", "*.gcode", "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert [f["name"] for f in data["files"]] == ["lamp.gcode"]


def test_many_models_with_gcode_twins_aggregate_once_each(tmp_path: Path) -> None:
    """N sliced models plus their N ``gcode/`` twins must total N models.

    This mirrors the real ``sliced/`` / ``sliced-table-lamp/`` layout, where
    each ``<model>_sliced.3mf`` has a ``gcode/<model>.gcode`` sibling: the
    aggregate must be the sum over models, never twice that.
    """
    for name, grams in (("a", 10.0), ("b", 20.0), ("c", 30.0)):
        factories.make_sliced_3mf(tmp_path / f"{name}_sliced.3mf", used_g=grams, used_m=grams / 3)
        factories.make_gcode_file(tmp_path / "gcode" / f"{name}.gcode")

    out_file = tmp_path / "report.json"
    code = app.main([str(tmp_path), "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data["files"]) == 3
    assert data["total_g"] == pytest.approx(60.0)


def test_orphan_gcode_next_to_models_is_not_counted(tmp_path: Path) -> None:
    """An unpaired ``.gcode`` beside models is deliberately skipped.

    ``.gcode`` is not a default directory mask, so a G-code that has no
    ``.3mf`` twin in a directory that *does* contain models is not reported.
    Pass ``--glob "*.gcode"`` (or the file directly) to opt in explicitly.
    """
    factories.make_sliced_3mf(tmp_path / "model_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_gcode_file(tmp_path / "orphan.gcode")

    out_file = tmp_path / "report.json"
    code = app.main([str(tmp_path), "-o", str(out_file)])
    assert code == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert [f["name"] for f in data["files"]] == ["model_sliced.3mf"]
    assert data["total_g"] == pytest.approx(10.0)


def test_skipped_gcode_hint_in_verbose_mode(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Verbose mode warns about orphan ``.gcode`` left out of the default scan."""
    factories.make_sliced_3mf(tmp_path / "model_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_gcode_file(tmp_path / "orphan.gcode")

    code = app.main([str(tmp_path), "-v"])
    captured = capsys.readouterr()
    assert code == 0
    assert "1 .gcode file(s) skipped" in captured.err


def test_skipped_gcode_hint_absent_without_verbose(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Without ``-v`` the hint stays silent so routine runs are not noisy."""
    factories.make_sliced_3mf(tmp_path / "model_sliced.3mf", used_g=10.0, used_m=3.3)
    factories.make_gcode_file(tmp_path / "orphan.gcode")

    code = app.main([str(tmp_path)])
    captured = capsys.readouterr()
    assert code == 0
    assert ".gcode file(s) skipped" not in captured.err


def test_no_gcode_hint_when_no_gcode_present(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A directory without any ``.gcode`` must not emit the hint, even with ``-v``."""
    factories.make_sliced_3mf(tmp_path / "model_sliced.3mf", used_g=10.0, used_m=3.3)

    code = app.main([str(tmp_path), "-v"])
    captured = capsys.readouterr()
    assert code == 0
    assert ".gcode file(s) skipped" not in captured.err


def _patch_slicing(monkeypatch: pytest.MonkeyPatch, sliced: Path) -> list[object]:
    """Patch the slicing path so tests can count real slice invocations."""
    monkeypatch.setattr(app, "ensure_orca", lambda *a, **k: Path("/fake/orca"))
    monkeypatch.setattr(app, "orca_version", lambda binary: None)
    monkeypatch.setattr(
        app, "resolve_profiles", lambda *a, **k: {"machine": "m", "process": "p", "filament": "f"}
    )
    calls: list[object] = []

    def fake_slice(*args: object, **kwargs: object) -> SliceResult:
        calls.append(args)
        return SliceResult(True, sliced, "log", 1)

    monkeypatch.setattr(app, "run_slice", fake_slice)
    return calls


def test_slice_result_is_cached_and_reused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An unchanged (path, size) model is never sliced twice."""
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "out.3mf", used_g=5.0, used_m=1.65)
    calls = _patch_slicing(monkeypatch, sliced)

    assert app.main([str(source)]) == 0
    assert len(calls) == 1
    # Second run on the same (path, size) must hit the cache, not the slicer.
    assert app.main([str(source)]) == 0
    assert len(calls) == 1


def test_cache_invalidated_when_size_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A different file size means a different model, so the cache is bypassed."""
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "out.3mf", used_g=5.0, used_m=1.65)
    calls = _patch_slicing(monkeypatch, sliced)

    assert app.main([str(source)]) == 0
    assert len(calls) == 1
    source.write_text("mesh-but-different", encoding="utf-8")
    assert app.main([str(source)]) == 0
    assert len(calls) == 2


def test_no_cache_disables_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--no-cache`` disables both reading and writing of the cache."""
    source = tmp_path / "part.stl"
    source.write_text("mesh", encoding="utf-8")
    sliced = factories.make_sliced_3mf(tmp_path / "out.3mf", used_g=5.0, used_m=1.65)
    calls = _patch_slicing(monkeypatch, sliced)

    assert app.main([str(source), "--no-cache"]) == 0
    assert app.main([str(source), "--no-cache"]) == 0
    assert len(calls) == 2


def test_price_and_currency_are_persisted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit ``--price`` / ``--currency`` flags are written back."""
    saved: list[dict] = []
    monkeypatch.setattr(app, "load_settings", lambda: {"price_per_kg": None, "currency": "RUB"})
    monkeypatch.setattr(app, "save_settings", lambda settings: saved.append(settings))

    model = factories.make_sliced_3mf(tmp_path / "m.3mf", used_g=10.0, used_m=3.3)
    code = app.main([str(model), "--price", "2200", "--currency", "USD"])
    assert code == 0
    assert saved == [{"price_per_kg": 2200.0, "currency": "USD"}]


def test_saved_price_and_currency_used_as_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """When flags are omitted, persisted values become the defaults."""
    monkeypatch.setattr(app, "load_settings", lambda: {"price_per_kg": 2200.0, "currency": "USD"})
    monkeypatch.setattr(app, "save_settings", lambda settings: None)

    model = factories.make_sliced_3mf(tmp_path / "m.3mf", used_g=100.0, used_m=33.0)
    code = app.main([str(model)])
    out = capsys.readouterr().out
    assert code == 0
    # cost = 100 g / 1000 * 2200 = 220.00 USD
    assert "220.00 USD" in out


def test_explicit_price_overrides_saved_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """An explicit flag wins over a persisted value."""
    monkeypatch.setattr(app, "load_settings", lambda: {"price_per_kg": 1000.0, "currency": "USD"})
    monkeypatch.setattr(app, "save_settings", lambda settings: None)

    model = factories.make_sliced_3mf(tmp_path / "m.3mf", used_g=100.0, used_m=33.0)
    code = app.main([str(model), "--price", "200"])
    out = capsys.readouterr().out
    assert code == 0
    assert "20.00 USD" in out
