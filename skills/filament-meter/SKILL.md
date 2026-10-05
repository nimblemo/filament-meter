---
name: filament-meter
description: Install and operate the `filament-meter` CLI — a PyPI package that measures 3D-print filament usage (grams, metres, print time, cost) from .3mf/.gcode/.stl/.obj files and auto-provisions OrcaSlicer to slice unsliced models. This skill should be used when the user asks how much filament a model uses (расход филамента / сколько грамм / себестоимость печати / стоимость печати), wants to install, run, update or troubleshoot filament-meter, or needs its installation order, command-line flags, exit codes or output formats.
agent_created: true
---

# filament-meter — installation & command reference

## Overview

`filament-meter` is a single flat command that answers one question: *given a
path (a file, a directory or a glob), how much filament will this print
consume?* It reads the numbers slicers already write into sliced files
(`Metadata/slice_info.config`, with a G-code footer fallback) and — when a
model has not been sliced yet — provisions OrcaSlicer automatically to slice
it in a throw-away directory, without touching the model folder.

Prefer this packaged CLI over the raw scripts. The deep OrcaSlicer slicing
gotchas (flag order, `--allow-newer-file`, out-of-range config overrides, the
per-extruder gcode list trap) live in the `orcaslicer-filament-batch` skill.

## Installation order

Perform the steps in order. Skip a step only when its dependency is already
present.

1. **Python ≥ 3.11** — `python --version`. The package does not support older
   interpreters (CI matrix: 3.11 / 3.12 / 3.13).

2. **uv** (recommended runner) —
   <https://docs.astral.sh/uv/getting-started/installation/>. `pipx` or `pip`
   are valid substitutes.

3. **Install the tool** — pick one:
   - Users: `uv tool install filament-meter`
     (upgrade an existing install: `uv tool update filament-meter`).
   - One-shot, no global install: `uvx filament-meter "D:/models" --price 2200`.
   - From a local checkout: `uv tool install .`
     (development: `git clone https://github.com/nimblemo/filament-meter.git &&
     cd filament-meter && uv sync --all-extras && uv run filament-meter --help`).

4. **OrcaSlicer** — optional and auto-provisioned. Not needed for already-sliced
   `.3mf` files. On the first slice the tool downloads a portable build into the
   user cache (no admin rights). Pre-fetch with `filament-meter --install-orca`.
   Pre-installed locations are auto-detected; `--no-auto-install` forbids the
   download.

5. **Verify** — `filament-meter --version`, then `filament-meter --check` (prints
   the resolved Python, platform, cache and OrcaSlicer paths).

## Command reference (summary)

`filament-meter PATH [options]` — the only positional argument is `PATH` (a file,
a directory or a glob). The full flag-by-flag table, exit codes, output formats
and environment variables are in `references/commands.md`.

Flags grouped by concern:

- **Cost:** `--price FLOAT` (per kg), `--currency STR` — both persisted across runs.
- **Output:** `-o, --output FILE` (format from extension), `-f, --format {table,json,csv,md}`.
- **Discovery:** `--no-recursive`, `--glob PATTERN` (repeatable).
- **Slicing control:** `--no-slice`, `--force-slice`, `--keep-sliced DIR`,
  `--timeout INT`, `--jobs INT`.
- **Profiles:** `--machine`, `--process`, `--filament`, `--use-project-settings`.
- **OrcaSlicer:** `--orca PATH`, `--orca-version`, `--install-orca`,
  `--no-auto-install`, `--cache-dir PATH`.
- **Result cache:** `--no-cache` (disable), `--cache-dir PATH` (relocate).
- **Diagnostics:** `--check`, `--version`; verbosity `-q` / `-v`.

## Usage examples

```bash
filament-meter "D:/models/Gesha_sliced.3mf"                 # one sliced file, instant
filament-meter "D:/models" --price 2200 --currency RUB      # a folder + cost (persisted)
filament-meter "D:/projects" --price 2200                   # unsliced → auto-slice
filament-meter "D:/models" -o report.csv                    # write a report (CSV, UTF-8 BOM)
filament-meter "D:/models" -f json                          # JSON to stdout
filament-meter --install-orca                               # pre-fetch OrcaSlicer
filament-meter --check                                      # environment diagnostics
```

## Key facts

- **Filament data only exists in a SLICED file.** An unsliced project `.3mf` has
  no `<plate>`/`<filament>` in `slice_info.config`; `filament-meter` slices it
  first (drop `--no-slice` to allow that).
- **Results are cached, cost is not.** Results are cached by absolute path +
  file size (`--no-cache` to disable). `--price`/`--currency` are re-applied on
  every hit, so price changes always show up.
- **Exit codes:** `0` success · `1` partial (some files failed) · `2`
  usage/environment error · `3` total failure (no file produced data).
- **A directory scan deliberately ignores `*.gcode`** — a sliced model leaves a
  gcode twin, so scanning both would double-count. Pass `--glob "*.gcode"` (or
  the file path) to opt in; a gcode-only folder is picked up automatically.

## Local checkout

This skill lives inside the package repository at
`D:/WOOD/locus-products/filament-meter/skills/filament-meter/`.
