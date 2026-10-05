"""Persistent result cache for already-analysed models.

Slicing a model is the expensive step, and parsing a large ``.3mf`` is not
free either. Both are pure functions of the file's bytes, so results are
keyed by the **absolute path** and the **file size**: a cache entry is only
reused when both still match, which means an edited or re-exported model is
automatically re-processed.

The cached report deliberately never stores the ``cost`` of a run — cost
depends on the current ``--price`` — so it is recomputed on every hit.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import platformdirs

from filament_meter.models import FileReport

#: Application name used for the platform cache directory.
APP_NAME = "filament-meter"

#: Environment variable overriding the cache directory (shared with OrcaSlicer).
ENV_CACHE = "FILAMENT_METER_CACHE_DIR"

#: File name of the on-disk results cache.
CACHE_FILENAME = "results.json"


def results_cache_path(override: str | Path | None = None) -> Path:
    """Return the path of the persistent results cache file.

    Resolution order: ``override`` argument → ``FILAMENT_METER_CACHE_DIR``
    env var → the platform cache directory (via :mod:`platformdirs`). A
    ``results`` sub-directory keeps the file separate from the downloaded
    OrcaSlicer builds under ``orca/``.
    """
    if override:
        base = Path(override).expanduser()
    else:
        env_value = os.getenv(ENV_CACHE)
        if env_value:
            base = Path(env_value).expanduser()
        else:
            base = Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))
    return base / "results" / CACHE_FILENAME


def cache_key(path: str | Path, size_bytes: int | None = None) -> str:
    """Return the cache key for ``path``: its absolute path plus file size.

    Args:
        path: The model file path.
        size_bytes: The file size in bytes; when ``None`` it is read from
            disk (a file that cannot be stat-ed gets ``-1``).

    JSON-encoding makes the key unambiguous regardless of ``::`` or any
    other character appearing in the path.
    """
    resolved = Path(path).resolve()
    if size_bytes is None:
        try:
            size_bytes = resolved.stat().st_size
        except OSError:
            size_bytes = -1
    return json.dumps([str(resolved), size_bytes], ensure_ascii=True)


class ResultCache:
    """A JSON-file-backed store of per-file analysis results.

    The whole store is loaded into memory on first use and written back with
    :meth:`save`. Reads and writes are guarded by a lock so the ``--jobs``
    parallel path can share a single instance safely.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self._data is None:
                self._data = self._read()
            return self._data

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            parsed = json.loads(raw)
        except (OSError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def get(self, key: str) -> FileReport | None:
        """Return the cached report for ``key``, or ``None`` on miss/error."""
        data = self._load().get(key)
        if not isinstance(data, dict):
            return None
        try:
            return FileReport.from_dict(data)
        except (KeyError, TypeError, ValueError):
            return None

    def put(self, key: str, report: FileReport) -> None:
        """Store ``report`` under ``key`` (in memory; call :meth:`save` to persist)."""
        with self._lock:
            self._load()[key] = report.to_dict()

    def save(self) -> None:
        """Atomically write the store back to disk (no-op when untouched)."""
        with self._lock:
            if self._data is None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._load())
