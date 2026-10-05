"""Shared helpers for the ``filament-meter`` CLI.

Holds the exit-code constants, console configuration (UTF-8 on Windows)
and the tiny stderr logger so the message format is defined in one place.
"""

from __future__ import annotations

import contextlib
import sys

#: Everything succeeded.
EXIT_OK = 0

#: Partial success — some files could not be processed.
EXIT_PARTIAL = 1

#: Usage / environment error (bad path, missing OrcaSlicer, ...).
EXIT_USAGE = 2

#: Total failure — not a single file yielded filament data.
EXIT_FAILURE = 3


def configure_console() -> None:
    """Force UTF-8 with replacement on stdout/stderr where supported."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def log(prog: str, message: str, *, quiet: bool = False) -> None:
    """Write ``[<prog>] <message>`` to stderr unless ``quiet`` is set."""
    if quiet:
        return
    sys.stderr.write(f"[{prog}] {message}\n")
    sys.stderr.flush()


def error(prog: str, message: str) -> None:
    """Write ``<prog>: error: <message>`` to stderr."""
    sys.stderr.write(f"{prog}: error: {message}\n")
    sys.stderr.flush()
