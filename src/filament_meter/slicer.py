"""Headless slicing through the OrcaSlicer CLI.

This is a 1:1 port of the proven ``slice_batch.py`` logic: the same command
line, the same two workarounds (``--allow-newer-file`` and the adaptive
``--<key>=<min>`` retry for "not in range" errors), and the same handling of
the ``plate_N.gcode`` file that OrcaSlicer always drops into the output
directory and overwrites for every model.
"""

from __future__ import annotations

import contextlib
import glob
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filament_meter.errors import ProfileNotFoundError

#: Default profile names shipped with OrcaSlicer for the Bambu Lab A1.
DEFAULT_PROFILES: dict[str, str] = {
    "machine": "Bambu Lab A1 0.4 nozzle.json",
    "process": "0.20mm Standard @BBL A1.json",
    "filament": "Bambu PLA Basic @BBL A1.json",
}

#: Relative path of the bundled BBL profiles inside an OrcaSlicer install.
PROFILE_SUBDIR = ("resources", "profiles", "BBL")

#: Matches ``tree_support_wall_count: -1 not in range [0.000000, 2.000000]``.
RE_RANGE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\S+\s+not in range\s*\[\s*([-\d.eE+]+)\s*,")

#: Log substrings that hint at a human-readable failure reason.
_REASON_HINTS = (
    "error",
    "failed",
    "not in range",
    "unknown",
    "can not",
    "cannot",
    "too large",
    "outside",
)


@dataclass(frozen=True)
class SliceResult:
    """Outcome of a :func:`run_slice` call.

    Attributes:
        ok: Whether slicing succeeded.
        out_3mf: Path to the exported ``_sliced.3mf`` on success.
        log: Combined stdout/stderr of the last attempt.
        attempts: Number of attempts that were made.
        reason: Short human-readable failure reason (``""`` on success).
    """

    ok: bool
    out_3mf: Path | None
    log: str
    attempts: int
    reason: str = ""


def resolve_profiles(
    orca: str | Path,
    machine: str,
    process: str,
    filament: str,
) -> dict[str, str]:
    """Resolve the three OrcaSlicer profile files next to the binary.

    Args:
        orca: Path to the OrcaSlicer executable.
        machine: Machine profile file name.
        process: Process profile file name.
        filament: Filament profile file name.

    Returns:
        A mapping with ``machine`` / ``process`` / ``filament`` keys pointing
        at absolute profile paths.

    Raises:
        ProfileNotFoundError: If any of the three profiles is missing.
    """
    profile_root = Path(orca).resolve().parent.joinpath(*PROFILE_SUBDIR)
    profiles: dict[str, str] = {}
    for key, filename in (
        ("machine", machine),
        ("process", process),
        ("filament", filament),
    ):
        candidate = profile_root / key / filename
        if not candidate.is_file():
            raise ProfileNotFoundError(f"profile not found: {candidate}")
        profiles[key] = str(candidate)
    return profiles


def build_base_cmd(
    orca: str | Path,
    profiles: Mapping[str, str] | None,
    outdir: str | Path,
    overrides: Mapping[str, str],
    logfile: str | Path | None = None,
) -> list[str]:
    """Build the OrcaSlicer command line (without the input file / export).

    Args:
        orca: Path to the OrcaSlicer executable.
        profiles: Resolved profile paths, or ``None`` to rely on settings
            embedded in the project file.
        outdir: Output directory passed to ``--outputdir``.
        overrides: Extra ``--<key>=<value>`` overrides.
        logfile: Optional ``--logfile`` target.

    Returns:
        The argument vector as a list of strings.
    """
    cmd: list[str] = [str(orca), "--allow-newer-file"]
    if profiles:
        cmd += [
            "--load-settings",
            f"{profiles['machine']};{profiles['process']}",
            "--load-filaments",
            profiles["filament"],
        ]
    cmd += [
        "--arrange",
        "1",
        "--outputdir",
        str(outdir),
        "--slice",
        "0",
    ]
    if logfile:
        # Without --logfile Orca writes 00000.log into the current directory.
        cmd += ["--logfile", str(logfile)]
    for key, value in overrides.items():
        cmd.append(f"--{key.replace('_', '-')}={value}")
    return cmd


def _cleanup_stale_gcode(outdir: Path) -> None:
    """Remove leftover ``plate_*.gcode`` files from a previous model."""
    for stale in glob.glob(str(outdir / "plate_*.gcode")):
        with contextlib.suppress(OSError):
            os.remove(stale)


def _handle_gcode(outdir: Path, stem: str, gcode_mode: str) -> None:
    """Move or delete the ``plate_N.gcode`` file OrcaSlicer always writes."""
    plates = sorted(glob.glob(str(outdir / "plate_*.gcode")))
    if not plates:
        return
    if gcode_mode == "drop":
        for plate in plates:
            with contextlib.suppress(OSError):
                os.remove(plate)
        return

    gcode_dir = outdir / "gcode"
    gcode_dir.mkdir(parents=True, exist_ok=True)
    for plate in plates:
        match = re.search(r"plate_(\d+)\.gcode$", plate)
        suffix = f"_plate{match.group(1)}" if match and match.group(1) != "1" else ""
        with contextlib.suppress(OSError):
            shutil.move(plate, str(gcode_dir / f"{stem}{suffix}.gcode"))


def _run_process(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` via :func:`subprocess.run`.

    A thin indirection so tests can patch :data:`_run_process` instead of the
    global :func:`subprocess.run` (which would also affect unrelated callers).
    """
    result: subprocess.CompletedProcess[str] = subprocess.run(cmd, **kwargs)
    return result


def subprocess_hide_kwargs() -> dict[str, Any]:
    """Return subprocess kwargs that keep OrcaSlicer off the console.

    On Windows the slicer is a console-subsystem executable that can pop a
    console window and write its own progress straight to the terminal.
    ``CREATE_NO_WINDOW`` plus a hidden ``STARTUPINFO`` keeps it silent, so
    only ``filament-meter`` output reaches the console. On other platforms
    the child's output is already captured, so an empty mapping is returned.
    """
    if os.name != "nt":
        return {}
    # Windows only: these ``subprocess`` members exist only on ``nt``, hence
    # the per-line ignores (so mypy stays green when run on POSIX CI).
    startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    startupinfo.wShowWindow = 0  # SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
        "startupinfo": startupinfo,
    }


def short_reason(log: str) -> str:
    """Extract a short human-readable failure reason from an OrcaSlicer log."""
    for line in log.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("Slic3r::CLI::run found error"):
            continue
        if stripped.startswith("Slic3r::") and "found error" in stripped:
            continue
        lowered = stripped.lower()
        if any(word in lowered for word in _REASON_HINTS):
            return stripped[:200]
    return "see log"


def run_slice(
    orca: str | Path,
    src: str | Path,
    profiles: Mapping[str, str] | None,
    outdir: str | Path,
    *,
    timeout: int = 3600,
    max_retries: int = 4,
    gcode_mode: str = "drop",
    verbose: bool = False,
    on_retry: Callable[[Mapping[str, str]], None] | None = None,
) -> SliceResult:
    """Slice ``src`` with OrcaSlicer, self-healing ``not in range`` errors.

    Args:
        orca: Path to the OrcaSlicer executable.
        src: Source model to slice.
        profiles: Resolved profile paths, or ``None`` for project settings.
        outdir: Directory OrcaSlicer writes its output into.
        timeout: Per-attempt timeout in seconds.
        max_retries: Maximum number of attempts.
        gcode_mode: ``"drop"`` to delete ``plate_N.gcode`` or ``"keep"`` to
            move it into an ``gcode/`` sub-directory.
        verbose: Emit a note whenever settings are auto-corrected.
        on_retry: Optional callback invoked with the overrides on each retry.

    Returns:
        A :class:`SliceResult`.
    """
    out_path = Path(outdir)
    source = Path(src)
    stem = source.stem
    out_name = f"{stem}_sliced.3mf"
    out_3mf = out_path / out_name

    log_dir = out_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / f"{stem}.log"

    overrides: dict[str, str] = {}
    last_log = ""

    for attempt in range(1, max_retries + 1):
        _cleanup_stale_gcode(out_path)

        cmd = build_base_cmd(orca, profiles, out_path, overrides, logfile)
        # --export-3mf MUST stay last: it consumes the next token as filename.
        cmd += ["--export-3mf", out_name, str(source)]

        try:
            proc = _run_process(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(out_path),
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                **subprocess_hide_kwargs(),
            )
        except subprocess.TimeoutExpired:
            return SliceResult(False, None, "slicing timed out", attempt, "slicing timed out")

        last_log = (proc.stdout or "") + (proc.stderr or "")

        if proc.returncode == 0 and out_3mf.is_file():
            _handle_gcode(out_path, stem, gcode_mode)
            with contextlib.suppress(OSError):
                logfile.unlink()
            return SliceResult(True, out_3mf, last_log, attempt)

        bad = RE_RANGE.findall(last_log)
        if not bad:
            return SliceResult(False, None, last_log, attempt, short_reason(last_log))

        added = False
        for key, min_value in bad:
            if key not in overrides:
                try:
                    low = float(min_value)
                except ValueError:
                    continue
                overrides[key] = f"{low:g}"
                added = True
        if not added:
            return SliceResult(False, None, last_log, attempt, short_reason(last_log))

        if verbose:
            print(f"    ~ auto-fixing settings: {', '.join(sorted(overrides))}")
        if on_retry is not None:
            on_retry(dict(overrides))

    return SliceResult(False, None, last_log, max_retries, short_reason(last_log))
