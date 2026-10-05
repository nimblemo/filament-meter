"""Turn a user-supplied path (file, directory or glob) into a file list.

The entry point is :func:`discover`. It accepts a single path-like string
that may be:

* a regular file → returned as-is;
* a directory → scanned (recursively by default) for the default model
  patterns;
* a shell-style glob pattern (containing ``*``, ``?`` or ``[``) → expanded.

Results are de-duplicated by resolved path and returned in a stable,
case-insensitive order so that reports are reproducible.
"""

from __future__ import annotations

import glob as _glob
from collections.abc import Sequence
from pathlib import Path

from filament_meter.errors import DiscoveryError

#: File patterns scanned inside a directory by default.
DEFAULT_PATTERNS: tuple[str, ...] = (
    "*.3mf",
    "*.stl",
    "*.obj",
    "*.gcode",
    "*.gcode.3mf",
)

#: Characters that mark a path as a glob pattern.
_GLOB_MAGIC = "*?["


def _has_glob_magic(text: str) -> bool:
    """Return ``True`` when ``text`` looks like a glob pattern."""
    return any(ch in text for ch in _GLOB_MAGIC)


def _scan_directory(root: Path, recursive: bool, patterns: Sequence[str]) -> list[Path]:
    """Return every file under ``root`` matching any of ``patterns``."""
    found: list[Path] = []
    for pattern in patterns:
        iterator = root.rglob(pattern) if recursive else root.glob(pattern)
        found.extend(iterator)
    return found


def discover(
    path: str | Path,
    *,
    recursive: bool = True,
    patterns: Sequence[str] | None = None,
) -> list[Path]:
    """Resolve ``path`` into a sorted, de-duplicated list of files.

    Args:
        path: A file, a directory or a glob pattern.
        recursive: Whether directories are walked recursively.
        patterns: File masks used when ``path`` is a directory. Defaults to
            :data:`DEFAULT_PATTERNS`.

    Returns:
        A list of existing files, de-duplicated by resolved path.

    Raises:
        DiscoveryError: If ``path`` does not exist and is not a glob pattern.
    """
    active_patterns = tuple(patterns) if patterns else DEFAULT_PATTERNS
    raw = str(path)
    target = Path(raw).expanduser()

    collected: list[Path] = []
    if _has_glob_magic(raw):
        # Explicit patterns are always expanded recursively: the user typed
        # the mask on purpose, so ``**`` should behave as expected.
        collected.extend(Path(p) for p in _glob.glob(raw, recursive=True))
    elif target.is_dir():
        collected.extend(_scan_directory(target, recursive, active_patterns))
    elif target.is_file():
        collected.append(target)
    else:
        raise DiscoveryError(f"path not found: {raw}")

    seen: set[Path] = set()
    result: list[Path] = []
    for candidate in collected:
        if not candidate.is_file():
            continue
        key = candidate.resolve()
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)

    result.sort(key=lambda p: str(p).lower())
    return result
