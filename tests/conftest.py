"""Shared pytest fixtures for the ``filament-meter`` test-suite.

The suite is deliberately hermetic: no test touches the network or a real
OrcaSlicer binary. Every external call is monkeypatched at the module
boundary (see ``filament_meter.slicer.subprocess`` and
``filament_meter.orca``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``factories`` importable regardless of the pytest invocation dir.
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolate_persistent_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep settings and the result cache out of the user's real dirs.

    The CLI reads and writes a settings file and a result cache; both must
    land under ``tmp_path`` (and be discarded) so the suite never touches the
    developer's real configuration or cache.
    """
    from filament_meter.cli import app

    monkeypatch.setattr(app, "load_settings", lambda: {"price_per_kg": None, "currency": "RUB"})
    monkeypatch.setattr(app, "save_settings", lambda settings: None)
    monkeypatch.setattr(
        app,
        "results_cache_path",
        lambda override=None: tmp_path / "cache" / "results.json",
    )
