"""Tests for :mod:`filament_meter.slicer`."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from filament_meter import slicer
from filament_meter.errors import ProfileNotFoundError
from filament_meter.slicer import (
    DEFAULT_PROFILES,
    build_base_cmd,
    resolve_profiles,
    run_slice,
    short_reason,
    subprocess_hide_kwargs,
)


class _Proc:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_runner(behaviour: list[_Proc]) -> Any:
    """Return a fake ``subprocess.run`` that creates the exported file."""

    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> _Proc:
        calls.append(cmd)
        outcome = behaviour[min(len(calls) - 1, len(behaviour) - 1)]
        if outcome.returncode == 0:
            out_name = cmd[cmd.index("--export-3mf") + 1]
            cwd = Path(kwargs.get("cwd") or ".")
            (cwd / out_name).write_bytes(b"PK\x03\x04")
        return outcome

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def test_build_base_cmd_structure(tmp_path: Path) -> None:
    profiles = {"machine": "m.json", "process": "p.json", "filament": "f.json"}
    cmd = build_base_cmd("orca", profiles, tmp_path, {"tree_support_wall_count": "0"})
    assert cmd[0] == "orca"
    assert "--allow-newer-file" in cmd
    assert cmd[cmd.index("--load-settings") + 1] == "m.json;p.json"
    assert cmd[cmd.index("--load-filaments") + 1] == "f.json"
    assert cmd[cmd.index("--outputdir") + 1] == str(tmp_path)
    assert "--tree-support-wall-count=0" in cmd
    # export flag is NOT part of the base command
    assert "--export-3mf" not in cmd


def test_build_base_cmd_without_profiles(tmp_path: Path) -> None:
    cmd = build_base_cmd("orca", None, tmp_path, {})
    assert "--load-settings" not in cmd
    assert "--load-filaments" not in cmd


def test_resolve_profiles_missing(tmp_path: Path) -> None:
    orca = tmp_path / "orca-slicer.exe"
    orca.write_text("binary", encoding="utf-8")
    with pytest.raises(ProfileNotFoundError):
        resolve_profiles(orca, "m.json", "p.json", "f.json")


def test_resolve_profiles_ok(tmp_path: Path) -> None:
    orca = tmp_path / "orca-slicer.exe"
    orca.write_text("binary", encoding="utf-8")
    profile_root = tmp_path / "resources" / "profiles" / "BBL"
    for key, filename in (
        ("machine", DEFAULT_PROFILES["machine"]),
        ("process", DEFAULT_PROFILES["process"]),
        ("filament", DEFAULT_PROFILES["filament"]),
    ):
        target = profile_root / key / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}", encoding="utf-8")

    profiles = resolve_profiles(
        orca,
        DEFAULT_PROFILES["machine"],
        DEFAULT_PROFILES["process"],
        DEFAULT_PROFILES["filament"],
    )
    assert set(profiles) == {"machine", "process", "filament"}
    assert profiles["machine"].endswith(DEFAULT_PROFILES["machine"])


def test_run_slice_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.3mf"
    source.write_bytes(b"PK")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    monkeypatch.setattr(slicer, "_run_process", _fake_runner([_Proc(0)]))
    result = run_slice("orca", source, None, out_dir)

    assert result.ok is True
    assert result.out_3mf == out_dir / "model_sliced.3mf"
    assert result.out_3mf is not None and result.out_3mf.is_file()
    assert result.attempts == 1


def test_run_slice_retries_on_range_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.3mf"
    source.write_bytes(b"PK")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    range_log = "tree_support_wall_count: -1 not in range [0.000000, 2.000000]"
    runner = _fake_runner([_Proc(1, stdout=range_log), _Proc(0)])
    monkeypatch.setattr(slicer, "_run_process", runner)

    result = run_slice("orca", source, None, out_dir)
    assert result.ok is True
    assert result.attempts == 2
    # The retry must carry the auto-fixed override.
    assert "--tree-support-wall-count=0" in runner.calls[1]


def test_run_slice_failure_without_range(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.3mf"
    source.write_bytes(b"PK")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    monkeypatch.setattr(
        slicer, "_run_process", _fake_runner([_Proc(1, stderr="fatal error: boom")])
    )
    result = run_slice("orca", source, None, out_dir)
    assert result.ok is False
    assert result.out_3mf is None
    assert "boom" in result.reason


def test_run_slice_moves_gcode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "model.3mf"
    source.write_bytes(b"PK")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "plate_1.gcode").write_text("stale", encoding="utf-8")

    def runner(cmd: list[str], **kwargs: Any) -> _Proc:
        out_name = cmd[cmd.index("--export-3mf") + 1]
        cwd = Path(kwargs.get("cwd") or ".")
        (cwd / out_name).write_bytes(b"PK")
        (cwd / "plate_1.gcode").write_text("fresh", encoding="utf-8")
        return _Proc(0)

    monkeypatch.setattr(slicer, "_run_process", runner)
    result = run_slice("orca", source, None, out_dir, gcode_mode="keep")
    assert result.ok is True
    assert (out_dir / "gcode" / "model.gcode").read_text(encoding="utf-8") == "fresh"
    assert not (out_dir / "plate_1.gcode").exists()


def test_short_reason_extracts_message() -> None:
    log = "Slic3r::CLI::run found error\nsome info\nError: model is too large for the plate"
    assert "too large" in short_reason(log)


def test_short_reason_default() -> None:
    assert short_reason("nothing useful here") == "see log"


def test_subprocess_hide_kwargs_matches_platform() -> None:
    kwargs = subprocess_hide_kwargs()
    if os.name == "nt":
        assert "creationflags" in kwargs
        assert "startupinfo" in kwargs
    else:
        assert kwargs == {}


def test_run_slice_forwards_hide_kwargs_and_devnull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slicing must keep OrcaSlicer off the console and off our stdin."""
    source = tmp_path / "model.3mf"
    source.write_bytes(b"PK")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    seen: dict[str, Any] = {}

    def runner(cmd: list[str], **kwargs: Any) -> _Proc:
        seen.update(kwargs)
        out_name = cmd[cmd.index("--export-3mf") + 1]
        (Path(kwargs["cwd"]) / out_name).write_bytes(b"PK")
        return _Proc(0)

    monkeypatch.setattr(slicer, "_run_process", runner)
    monkeypatch.setattr(slicer, "subprocess_hide_kwargs", lambda: {"sentinel": True})

    result = run_slice("orca", source, None, out_dir)
    assert result.ok is True
    assert seen["sentinel"] is True
    assert seen["stdin"] == subprocess.DEVNULL
