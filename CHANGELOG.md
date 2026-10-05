# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-10-06

### Fixed

- Removed the OrcaSlicer `--version` probe, which (on Windows, where the
  executable is a GUI application) dumped the full usage/help text — plus
  `setup params error` — to the parent console on every run. The version is
  now read from the `VERSION` marker file written next to provisioned
  builds; a system install reports `unknown`.

## [0.2.0] - 2026-10-06

### Added

- Persistent **result cache** keyed by a file's absolute path and size, so
  unchanged models are never sliced or re-parsed twice. Disable with
  `--no-cache`; relocate with `--cache-dir`.
- Persistent **settings** for `--currency` and `--price` (`settings.json`),
  applied as defaults on later runs when the flags are omitted.

### Changed

- OrcaSlicer's own console output (and its Windows console window) is now
  suppressed during slicing and version probing, so only `filament-meter`
  output reaches the terminal.
- `--currency` no longer hard-defaults to `RUB`; it is resolved from the
  persisted settings (falling back to `RUB`).

## [0.1.0] - 2026-10-05

### Added

- First public release of `filament-meter`.
- Flat CLI: `filament-meter PATH [options]` — a file, a directory or a glob
  pattern; no subcommands.
- Local parsing of sliced `.3mf` files (`Metadata/slice_info.config`) with a
  G-code footer fallback (`Metadata/plate_N.gcode`).
- Automatic OrcaSlicer discovery and lazy portable-build download into the
  user cache; eager download via `--install-orca`.
- Adaptive OrcaSlicer slicing with `--allow-newer-file` and the automatic
  `--<key>=<min>` retry for `not in range` errors.
- Four report formats: `table`, `json`, `csv` (`;`-separated, UTF-8 BOM) and
  `md`, selectable via `-f/--format` or by `-o/--output` extension.
- Cost estimation from a `--price` (per kilogram) and `--currency`.
- Parallel slicing with `--jobs`, per-file timeouts, and a `--check`
  environment diagnostic.
- Exit codes `0` / `1` / `2` / `3` for success / partial / usage / failure.
- Test-suite covering discovery, parsing, rendering, slicing, OrcaSlicer
  provisioning and the CLI (all external calls mocked).
- CI matrix (Python 3.11 / 3.12 / 3.13) and OIDC-based PyPI release
  workflow.

[Unreleased]: https://github.com/nimblemo/filament-meter/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/nimblemo/filament-meter/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/nimblemo/filament-meter/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nimblemo/filament-meter/releases/tag/v0.1.0
