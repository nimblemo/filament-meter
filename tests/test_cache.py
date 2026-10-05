"""Tests for :mod:`filament_meter.cache`."""

from __future__ import annotations

from pathlib import Path

import pytest

from filament_meter.cache import ResultCache, cache_key, results_cache_path
from filament_meter.models import FileReport


def _report(path: str, used_g: float = 10.0) -> FileReport:
    return FileReport(
        path=Path(path),
        name=Path(path).name,
        size_bytes=100,
        sliced=True,
        total_g=used_g,
        total_m=3.3,
        total_time_s=60.0,
        cost=1.0,
    )


def test_cache_key_includes_absolute_path_and_size(tmp_path: Path) -> None:
    a = tmp_path / "part.3mf"
    b = tmp_path / "part.3mf"
    assert cache_key(a, 42) == cache_key(b, 42)
    # Same path, different size -> different key.
    assert cache_key(a, 42) != cache_key(a, 43)
    # Different path, same size -> different key.
    assert cache_key(a, 42) != cache_key(tmp_path / "other.3mf", 42)


def test_cache_key_reads_size_from_disk(tmp_path: Path) -> None:
    model = tmp_path / "part.3mf"
    model.write_bytes(b"x" * 17)
    assert cache_key(model) == cache_key(model, 17)


def test_results_cache_path_override(tmp_path: Path) -> None:
    assert results_cache_path(tmp_path) == tmp_path / "results" / "results.json"


def test_results_cache_path_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FILAMENT_METER_CACHE_DIR", str(tmp_path))
    assert results_cache_path() == tmp_path / "results" / "results.json"


def test_cache_roundtrip_and_persistence(tmp_path: Path) -> None:
    path = tmp_path / "results" / "results.json"
    cache = ResultCache(path)
    key = cache_key(tmp_path / "part.3mf", 42)
    cache.put(key, _report(str(tmp_path / "part.3mf")))
    cache.save()

    # A fresh instance reads the same data back from disk.
    reloaded = ResultCache(path)
    got = reloaded.get(key)
    assert got is not None
    assert got.total_g == 10.0
    assert got.sliced is True
    assert got.path == tmp_path / "part.3mf"


def test_cache_get_missing_returns_none(tmp_path: Path) -> None:
    cache = ResultCache(tmp_path / "results.json")
    assert cache.get(cache_key(tmp_path / "nope.3mf", 1)) is None


def test_cache_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    cache = ResultCache(path)
    assert cache.get(cache_key(tmp_path / "x.3mf", 1)) is None
    assert len(cache) == 0


def test_cache_get_ignores_malformed_entry(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    cache = ResultCache(path)
    key = cache_key(tmp_path / "x.3mf", 1)
    cache.put(key, _report(str(tmp_path / "x.3mf")))
    # Corrupt the stored entry directly.
    cache._load()[key] = {"path": 12345}  # type: ignore[assignment]
    assert cache.get(key) is None
