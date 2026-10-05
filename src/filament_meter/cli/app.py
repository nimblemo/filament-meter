"""Single flat entry point for the ``filament-meter`` CLI.

Usage::

    filament-meter PATH [options]

There are deliberately **no subcommands** — one positional ``PATH`` plus a
set of flags. ``PATH`` may be a file, a directory or a glob pattern. The
command either prints the report to stdout or writes it to ``--output``.

A handful of flags do not need ``PATH``: ``--version``, ``--check`` and
``--install-orca``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from filament_meter import __version__
from filament_meter.cli._common import (
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_USAGE,
    configure_console,
    error,
    log,
)
from filament_meter.discovery import discover
from filament_meter.errors import (
    FilamentMeterError,
    OrcaError,
    ProfileNotFoundError,
)
from filament_meter.models import FileReport, RunReport
from filament_meter.orca import (
    cache_root,
    detect_platform,
    ensure_orca,
    find_orca,
    orca_version,
)
from filament_meter.parser import analyse, analyse_gcode_file, is_sliced_3mf
from filament_meter.report import FORMATS, output_format_for, render, write_report
from filament_meter.slicer import DEFAULT_PROFILES, resolve_profiles, run_slice

PROG = "filament-meter"

#: Suffixes that always require slicing (they carry no filament data).
_MODEL_SUFFIXES_NEEDING_SLICE = {".stl", ".obj"}

_EPILOG = """\
exit codes:
  0  success
  1  partial success (some files could not be processed)
  2  usage / environment error (bad path, OrcaSlicer missing)
  3  total failure (no file yielded filament data)
"""


@dataclass(frozen=True)
class _Context:
    """Everything a single file needs in order to be processed."""

    price: float | None
    currency: str
    orca: Path | None
    profiles: dict[str, str] | None
    profile_error: str | None
    no_slice: bool
    force_slice: bool
    timeout: int
    verbose: bool
    quiet: bool
    keep_sliced: str | None
    needs: dict[Path, bool]


def build_parser() -> argparse.ArgumentParser:
    """Build the flat ``filament-meter`` argument parser."""
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Measure 3D-print filament usage from .3mf / .gcode files. "
            "Accepts a file, a directory or a glob pattern."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="file, directory or glob pattern to analyse (required unless "
        "--version / --check / --install-orca is used)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="write the report to FILE (format from extension: .json/.csv/.md/.txt)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format",
        choices=list(FORMATS),
        default=None,
        help="stdout output format (default: table)",
    )
    parser.add_argument(
        "--price",
        type=float,
        default=None,
        help="filament price per kilogram (used for cost calculation)",
    )
    parser.add_argument(
        "--currency",
        default="RUB",
        help="currency code for cost figures (default: RUB)",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="do not walk directories recursively",
    )
    parser.add_argument(
        "--glob",
        dest="globs",
        action="append",
        default=None,
        metavar="PATTERN",
        help="file mask(s) used when PATH is a directory (repeatable)",
    )
    parser.add_argument(
        "--orca",
        default=None,
        metavar="PATH",
        help="explicit OrcaSlicer executable",
    )
    parser.add_argument(
        "--orca-version",
        dest="orca_version",
        default="latest",
        help="OrcaSlicer version to download (default: latest)",
    )
    parser.add_argument(
        "--install-orca",
        action="store_true",
        help="only download OrcaSlicer and exit (does not require PATH)",
    )
    parser.add_argument(
        "--no-auto-install",
        action="store_true",
        help="never download OrcaSlicer automatically",
    )
    parser.add_argument(
        "--no-slice",
        action="store_true",
        help="parse only; never slice",
    )
    parser.add_argument(
        "--force-slice",
        action="store_true",
        help="slice again even if the file is already sliced",
    )
    parser.add_argument("--machine", default=None, help="machine profile file name")
    parser.add_argument("--process", default=None, help="process profile file name")
    parser.add_argument("--filament", default=None, help="filament profile file name")
    parser.add_argument(
        "--use-project-settings",
        action="store_true",
        help="do not pass profiles; rely on settings embedded in the project",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="number of files to slice in parallel (default: 1)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=3600,
        help="per-file slicing timeout in seconds (default: 3600)",
    )
    parser.add_argument(
        "--cache-dir",
        dest="cache_dir",
        default=None,
        metavar="PATH",
        help="override the OrcaSlicer cache directory",
    )
    parser.add_argument(
        "--keep-sliced",
        dest="keep_sliced",
        default=None,
        metavar="DIR",
        help="copy freshly-sliced .3mf files into DIR (default: use a temp dir)",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument(
        "--check",
        action="store_true",
        help="run environment diagnostics and exit",
    )
    return parser


def _safe_size(path: Path) -> int:
    """Return the size of ``path`` in bytes, or ``0`` if it is unreadable."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _needs_slice(path: Path, force: bool) -> bool:
    """Decide whether ``path`` must be sliced before it can be reported."""
    if force:
        return True
    suffix = path.suffix.lower()
    if suffix == ".gcode":
        return False
    if suffix in _MODEL_SUFFIXES_NEEDING_SLICE:
        return True
    if suffix == ".3mf":
        if not zipfile.is_zipfile(path):
            # A corrupt archive is reported as an error during processing;
            # it must never be sent to the slicer.
            return False
        return not is_sliced_3mf(path)
    return False


def _skipped_report(path: Path) -> FileReport:
    """Build a report for a file that was intentionally not sliced."""
    return FileReport(
        path=path,
        name=path.name,
        size_bytes=_safe_size(path),
        sliced=False,
        notes=("not sliced, filament data unavailable (--no-slice)",),
    )


def _error_report(path: Path, message: str) -> FileReport:
    """Build a report for a file that could not be processed."""
    return FileReport(
        path=path,
        name=path.name,
        size_bytes=_safe_size(path),
        sliced=False,
        notes=(message,),
        error=message,
    )


def _slice_and_analyse(path: Path, ctx: _Context) -> FileReport:
    """Slice ``path`` in a throw-away directory and analyse the result."""
    tmp_dir = tempfile.mkdtemp(prefix="filament-meter-")
    out_dir = Path(tmp_dir)
    try:
        result = run_slice(
            ctx.orca,  # type: ignore[arg-type]  # guaranteed non-None by caller
            path,
            ctx.profiles,
            out_dir,
            timeout=ctx.timeout,
            gcode_mode="drop",
            verbose=ctx.verbose,
        )
        if not result.ok or result.out_3mf is None:
            return _error_report(path, result.reason or "slicing failed")
        if ctx.keep_sliced:
            keep_dir = Path(ctx.keep_sliced)
            keep_dir.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(result.out_3mf, keep_dir / result.out_3mf.name)
            except OSError as exc:
                log(PROG, f"could not keep sliced file: {exc}", quiet=ctx.quiet)
        report = analyse(result.out_3mf, price_per_kg=ctx.price, currency=ctx.currency)
        return FileReport(
            path=path,
            name=path.name,
            size_bytes=_safe_size(path),
            sliced=report.sliced,
            plates=report.plates,
            total_g=report.total_g,
            total_m=report.total_m,
            total_time_s=report.total_time_s,
            cost=report.cost,
            notes=report.notes,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _process(path: Path, ctx: _Context) -> FileReport:
    """Process a single input file into a :class:`FileReport`."""
    try:
        suffix = path.suffix.lower()
        if suffix == ".3mf" and not zipfile.is_zipfile(path):
            return _error_report(path, "not a valid 3mf archive")
        if suffix == ".gcode":
            return analyse_gcode_file(path, price_per_kg=ctx.price, currency=ctx.currency)
        if not ctx.needs.get(path, False):
            return analyse(path, price_per_kg=ctx.price, currency=ctx.currency)
        if ctx.no_slice:
            return _skipped_report(path)
        if ctx.profile_error:
            return _error_report(path, ctx.profile_error)
        if ctx.orca is None:
            return _error_report(path, "OrcaSlicer is required but was not found")
        return _slice_and_analyse(path, ctx)
    except FilamentMeterError as exc:
        return _error_report(path, str(exc))
    except Exception as exc:  # defensive: a single bad file must not kill the batch
        return _error_report(path, f"unexpected error: {exc}")


def _process_all(files: list[Path], ctx: _Context, jobs: int) -> list[FileReport]:
    """Process every file, optionally slicing in parallel."""
    if jobs <= 1 or len(files) <= 1:
        results: list[FileReport] = []
        for index, path in enumerate(files, 1):
            if ctx.needs.get(path, False) and not ctx.quiet:
                log(PROG, f"[{index}/{len(files)}] {path.name}", quiet=False)
            results.append(_process(path, ctx))
        return results
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        return list(executor.map(lambda item: _process(item, ctx), files))


def _build_run(
    reports: list[FileReport],
    args: argparse.Namespace,
    orca_ver: str | None,
) -> RunReport:
    """Aggregate per-file reports into a :class:`RunReport`."""
    total_g = round(sum(report.total_g for report in reports), 2)
    total_m = round(sum(report.total_m for report in reports), 2)
    total_time = round(sum(report.total_time_s for report in reports), 2)
    total_cost = None
    if args.price and total_g:
        total_cost = round(total_g / 1000.0 * args.price, 2)
    return RunReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        tool_version=__version__,
        orca_version=orca_ver,
        price_per_kg=args.price,
        currency=args.currency,
        files=tuple(reports),
        total_g=total_g,
        total_m=total_m,
        total_time_s=total_time,
        total_cost=total_cost,
        sliced_count=sum(1 for report in reports if report.has_data),
        failed_count=sum(1 for report in reports if report.error is not None),
    )


def _emit(run: RunReport, args: argparse.Namespace) -> None:
    """Write the report to ``--output`` or stdout."""
    if args.output:
        fmt = args.format or output_format_for(args.output)
        written = write_report(run, args.output, fmt)
        log(PROG, f"report written: {written}", quiet=args.quiet)
    else:
        fmt = args.format or "table"
        print(render(run, fmt))
    log(
        PROG,
        f"files={len(run.files)} sliced={run.sliced_count} failed={run.failed_count}",
        quiet=args.quiet,
    )


def _exit_code(run: RunReport) -> int:
    """Map a finished run onto a process exit code."""
    if run.sliced_count == 0:
        return EXIT_FAILURE
    if run.failed_count > 0:
        return EXIT_PARTIAL
    return EXIT_OK


def _run_check(args: argparse.Namespace) -> int:
    """Print environment diagnostics and return an exit code."""
    print(f"{PROG} {__version__}")
    print(f"python: {sys.version.split()[0]}")
    print(f"platform: {detect_platform()}")

    cache = cache_root(args.cache_dir)
    print(f"cache dir: {cache}")
    try:
        cache.mkdir(parents=True, exist_ok=True)
        probe = cache / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        print(f"cache writable: no ({exc})")
    else:
        print("cache writable: yes")

    found = find_orca(args.orca)
    if found is None:
        print("OrcaSlicer: not found")
        print("  it will be downloaded automatically on first run (unless --no-auto-install)")
        return EXIT_USAGE
    print(f"OrcaSlicer: {found}")
    version = orca_version(found)
    if version:
        print(f"OrcaSlicer version: {version}")
    else:
        print("OrcaSlicer version: unknown (CLI does not report --version)")
    return EXIT_OK


def _run_install_orca(args: argparse.Namespace) -> int:
    """Download (or locate) OrcaSlicer and return an exit code."""
    try:
        binary = ensure_orca(
            args.orca,
            auto_install=True,
            version=args.orca_version,
            cache_dir=args.cache_dir,
            progress=not args.quiet,
        )
    except FilamentMeterError as exc:
        error(PROG, str(exc))
        return EXIT_USAGE
    print(f"OrcaSlicer ready: {binary}")
    return EXIT_OK


def _run(args: argparse.Namespace) -> int:
    """Execute the parsed arguments."""
    if args.version:
        print(f"{PROG} {__version__}")
        return EXIT_OK
    if args.check:
        return _run_check(args)
    if args.install_orca:
        return _run_install_orca(args)
    if not args.path:
        error(PROG, "PATH is required (or use --version / --check / --install-orca)")
        return EXIT_USAGE

    patterns = tuple(args.globs) if args.globs else None
    try:
        files = discover(args.path, recursive=not args.no_recursive, patterns=patterns)
    except FilamentMeterError as exc:
        error(PROG, str(exc))
        return EXIT_USAGE
    if not files:
        error(PROG, f"no model files found at {args.path!r}")
        return EXIT_USAGE

    needs = {path: _needs_slice(path, args.force_slice) for path in files}
    any_needs = any(needs.values())

    orca_path: Path | None = None
    profiles: dict[str, str] | None = None
    profile_error: str | None = None

    if any_needs and not args.no_slice:
        try:
            orca_path = ensure_orca(
                args.orca,
                auto_install=not args.no_auto_install,
                version=args.orca_version,
                cache_dir=args.cache_dir,
                progress=not args.quiet,
            )
        except OrcaError as exc:
            error(PROG, str(exc))
            return EXIT_USAGE
        log(PROG, f"OrcaSlicer: {orca_path}", quiet=args.quiet)
        if not args.use_project_settings:
            try:
                profiles = resolve_profiles(
                    orca_path,
                    args.machine or DEFAULT_PROFILES["machine"],
                    args.process or DEFAULT_PROFILES["process"],
                    args.filament or DEFAULT_PROFILES["filament"],
                )
            except ProfileNotFoundError as exc:
                profile_error = str(exc)

    orca_ver = orca_version(orca_path) if orca_path is not None else None

    ctx = _Context(
        price=args.price,
        currency=args.currency,
        orca=orca_path,
        profiles=profiles,
        profile_error=profile_error,
        no_slice=args.no_slice,
        force_slice=args.force_slice,
        timeout=args.timeout,
        verbose=args.verbose,
        quiet=args.quiet,
        keep_sliced=args.keep_sliced,
        needs=needs,
    )

    reports = _process_all(files, ctx, args.jobs)
    run = _build_run(reports, args, orca_ver)
    _emit(run, args)
    return _exit_code(run)


def main(argv: list[str] | None = None) -> int:
    """Entry point declared in ``pyproject.toml`` under ``[project.scripts]``."""
    configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return _run(args)
    except KeyboardInterrupt:
        sys.stderr.write(f"\n{PROG}: interrupted by user\n")
        return 130
    except FilamentMeterError as exc:
        error(PROG, str(exc))
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
