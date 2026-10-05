"""Persistent user settings — currency and filament price.

The ``--currency`` and ``--price`` flags are remembered across runs. When
either flag is passed it is written to a small JSON file in the user config
directory; on later runs the stored values become the defaults whenever the
flags are omitted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import platformdirs

#: Application name used for the platform config directory.
APP_NAME = "filament-meter"

#: Environment variable overriding the settings file directory.
ENV_CONFIG = "FILAMENT_METER_CONFIG_DIR"

#: File name of the on-disk settings file.
SETTINGS_FILENAME = "settings.json"

#: Settings keys and their defaults.
DEFAULT_SETTINGS: dict[str, Any] = {
    "price_per_kg": None,
    "currency": "RUB",
}


def settings_path(override: str | Path | None = None) -> Path:
    """Return the path of the settings file.

    Resolution order: ``override`` argument → ``FILAMENT_METER_CONFIG_DIR``
    env var → the platform config directory (via :mod:`platformdirs`).
    """
    if override:
        base = Path(override).expanduser()
    else:
        env_value = os.getenv(ENV_CONFIG)
        if env_value:
            base = Path(env_value).expanduser()
        else:
            base = Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))
    return base / SETTINGS_FILENAME


def load_settings(override: str | Path | None = None) -> dict[str, Any]:
    """Load persisted settings, falling back to :data:`DEFAULT_SETTINGS`.

    A missing or corrupt file yields the defaults. Unknown keys are ignored;
    known keys are validated and normalised.
    """
    try:
        raw = settings_path(override).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)

    settings = dict(DEFAULT_SETTINGS)
    price = data.get("price_per_kg")
    try:
        settings["price_per_kg"] = float(price) if price is not None else None
    except (TypeError, ValueError):
        settings["price_per_kg"] = None
    currency = data.get("currency")
    if isinstance(currency, str) and currency.strip():
        settings["currency"] = currency.strip()
    return settings


def save_settings(settings: dict[str, Any], override: str | Path | None = None) -> None:
    """Persist ``settings`` to disk atomically."""
    path = settings_path(override)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
