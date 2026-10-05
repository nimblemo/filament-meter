"""Tests for :mod:`filament_meter.orca` (all network access is mocked)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest

from filament_meter import orca
from filament_meter.errors import OrcaDownloadError, OrcaNotFoundError

_REAL_ASSETS = [
    "OrcaSlicer_Windows_V2.4.2_x64_portable.zip",
    "OrcaSlicer_Windows_V2.4.2_arm64_portable.zip",
    "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage",
    "OrcaSlicer_Mac_universal_V2.4.2.dmg",
    "OrcaSlicer_Windows_Installer_V2.4.2_x64.exe",
]


def _release(assets: list[str]) -> dict[str, Any]:
    return {
        "tag_name": "v2.4.2",
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://example.invalid/{name}",
                "size": 128,
            }
            for name in assets
        ],
    }


def test_select_asset_windows_prefers_portable_x64() -> None:
    asset = orca.select_asset(_release(_REAL_ASSETS), "windows", "x64")
    assert asset["name"] == "OrcaSlicer_Windows_V2.4.2_x64_portable.zip"


def test_select_asset_windows_arm64() -> None:
    asset = orca.select_asset(_release(_REAL_ASSETS), "windows", "arm64")
    assert asset["name"] == "OrcaSlicer_Windows_V2.4.2_arm64_portable.zip"


def test_select_asset_linux() -> None:
    asset = orca.select_asset(_release(_REAL_ASSETS), "linux", "x64")
    assert asset["name"] == "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"


def test_select_asset_macos() -> None:
    asset = orca.select_asset(_release(_REAL_ASSETS), "macos", "x64")
    assert asset["name"] == "OrcaSlicer_Mac_universal_V2.4.2.dmg"


#: Real GitHub asset ordering for v2.4.2 — note the aarch64 AppImage is
#: listed *before* the x86_64 one, which is exactly the trap below.
_REAL_LINUX_ORDER = [
    "OrcaSlicer-Linux-flatpak_V2.4.2_aarch64.flatpak",
    "OrcaSlicer-Linux-flatpak_V2.4.2_x86_64.flatpak",
    "OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V2.4.2.AppImage",
    "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage",
]


def test_select_asset_linux_x64_never_picks_aarch64() -> None:
    """Regression: an x64 host must not download the aarch64 AppImage.

    GitHub lists ``..._Ubuntu2404_aarch64_...AppImage`` before the x86_64
    build, so a naive first-match on ``Linux``+``Ubuntu2404`` would hand an
    x64 machine an ARM binary that cannot run.
    """
    asset = orca.select_asset(_release(_REAL_LINUX_ORDER), "linux", "x64")
    assert asset["name"] == "OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.4.2.AppImage"
    assert "aarch64" not in asset["name"]


def test_select_asset_linux_arm64_prefers_aarch64() -> None:
    asset = orca.select_asset(_release(_REAL_LINUX_ORDER), "linux", "arm64")
    assert asset["name"] == "OrcaSlicer_Linux_AppImage_Ubuntu2404_aarch64_V2.4.2.AppImage"


def test_select_asset_no_match() -> None:
    with pytest.raises(OrcaDownloadError):
        orca.select_asset(_release(["something-else.tar.gz"]), "windows", "x64")


def test_select_asset_empty_release() -> None:
    with pytest.raises(OrcaDownloadError):
        orca.select_asset({"assets": []}, "linux", "x64")


def test_cache_root_override(tmp_path: Path) -> None:
    assert orca.cache_root(tmp_path) == tmp_path / "orca"


def test_cache_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILAMENT_METER_CACHE_DIR", str(tmp_path))
    assert orca.cache_root() == tmp_path / "orca"


def test_find_orca_explicit(tmp_path: Path) -> None:
    binary = tmp_path / "orca-slicer.exe"
    binary.write_text("x", encoding="utf-8")
    assert orca.find_orca(binary) == binary
    assert orca.find_orca(tmp_path / "missing.exe") is None


def test_find_orca_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "orca-slicer"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setenv("FILAMENT_METER_ORCA", str(binary))
    assert orca.find_orca() == binary


def test_find_orca_from_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FILAMENT_METER_ORCA", raising=False)
    monkeypatch.setattr(orca.shutil, "which", lambda _name: None)
    monkeypatch.setattr(orca, "_platform_candidates", lambda: [])
    monkeypatch.setattr(orca, "detect_platform", lambda: "linux")

    cached = tmp_path / "orca" / "2.4.2"
    cached.mkdir(parents=True)
    binary = cached / "orca-slicer"
    binary.write_text("x", encoding="utf-8")

    monkeypatch.setattr(orca, "cache_root", lambda _override=None: tmp_path / "orca")
    assert orca.find_orca() == binary


def test_download_orca_provisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orca, "detect_platform", lambda: "windows")
    monkeypatch.setattr(orca, "machine_arch", lambda: "x64")
    monkeypatch.setattr(orca, "fetch_release", lambda version="latest": _release(_REAL_ASSETS))

    downloads: list[Path] = []

    def fake_download(url: str, dest: Path, *, progress: bool, expected: int | None = None) -> None:
        downloads.append(dest)
        with zipfile.ZipFile(dest, "w") as archive:
            archive.writestr("orca-slicer.exe", b"binary")

    monkeypatch.setattr(orca, "_download_file", fake_download)

    binary = orca.download_orca("latest", cache_dir=tmp_path, progress=False)
    assert binary.name == "orca-slicer.exe"
    assert binary.is_file()
    assert (binary.parent / "VERSION").read_text(encoding="utf-8").strip() == "v2.4.2"
    assert len(downloads) == 1

    # Second call must be served from the cache (no second download).
    again = orca.download_orca("latest", cache_dir=tmp_path, progress=False)
    assert again == binary
    assert len(downloads) == 1


def test_download_orca_pinned_skips_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orca, "detect_platform", lambda: "linux")
    cached = tmp_path / "orca" / "2.4.2"
    cached.mkdir(parents=True)
    binary = cached / "orca-slicer"
    binary.write_text("x", encoding="utf-8")

    def boom(version: str = "latest") -> dict[str, Any]:
        raise AssertionError("fetch_release must not be called for a cached pinned version")

    monkeypatch.setattr(orca, "fetch_release", boom)
    assert orca.download_orca("2.4.2", cache_dir=tmp_path, progress=False) == binary


def test_ensure_orca_no_auto_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orca, "find_orca", lambda explicit=None: None)
    with pytest.raises(OrcaNotFoundError):
        orca.ensure_orca(auto_install=False)


def test_ensure_orca_returns_existing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    binary = tmp_path / "orca-slicer"
    binary.write_text("x", encoding="utf-8")
    monkeypatch.setattr(orca, "find_orca", lambda explicit=None: binary)
    assert orca.ensure_orca() == binary


def test_orca_version_reads_marker_file(tmp_path: Path) -> None:
    binary = tmp_path / "orca-slicer.exe"
    binary.write_text("x", encoding="utf-8")
    (tmp_path / "VERSION").write_text("2.4.2\n", encoding="utf-8")
    assert orca.orca_version(binary) == "2.4.2"


def test_orca_version_finds_marker_in_parent_dir(tmp_path: Path) -> None:
    """The download writes ``VERSION`` to the target dir, above the binary."""
    target = tmp_path / "OrcaSlicer"
    target.mkdir()
    binary = target / "orca-slicer.exe"
    binary.write_text("x", encoding="utf-8")
    (tmp_path / "VERSION").write_text("v2.4.2\n", encoding="utf-8")
    assert orca.orca_version(binary) == "2.4.2"


def test_orca_version_missing_marker(tmp_path: Path) -> None:
    """A system install has no ``VERSION`` file, so the version is unknown."""
    binary = tmp_path / "orca-slicer.exe"
    binary.write_text("x", encoding="utf-8")
    assert orca.orca_version(binary) is None
