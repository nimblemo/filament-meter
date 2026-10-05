"""Tests for :mod:`filament_meter.settings`."""

from __future__ import annotations

from pathlib import Path

from filament_meter.settings import (
    DEFAULT_SETTINGS,
    load_settings,
    save_settings,
    settings_path,
)


def test_settings_path_override(tmp_path: Path) -> None:
    assert settings_path(tmp_path) == tmp_path / "settings.json"


def test_load_settings_defaults_when_missing(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "missing.json") == DEFAULT_SETTINGS


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    save_settings({"price_per_kg": 2200.0, "currency": "USD"}, tmp_path)
    loaded = load_settings(tmp_path)
    assert loaded == {"price_per_kg": 2200.0, "currency": "USD"}


def test_load_settings_ignores_unknown_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"price_per_kg": 100, "currency": "EUR", "junk": true}', encoding="utf-8")
    loaded = load_settings(tmp_path)
    assert loaded["price_per_kg"] == 100.0
    assert loaded["currency"] == "EUR"
    assert "junk" not in loaded


def test_load_settings_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{{{{", encoding="utf-8")
    assert load_settings(tmp_path) == DEFAULT_SETTINGS


def test_load_settings_normalises_bad_price(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"price_per_kg": "abc", "currency": ""}', encoding="utf-8")
    loaded = load_settings(tmp_path)
    assert loaded["price_per_kg"] is None
    assert loaded["currency"] == "RUB"
