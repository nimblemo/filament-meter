# filament-meter

> Measure 3D-print **filament usage** from sliced `.3mf` / `.gcode` files —
> grams, metres, print time and cost — from a single file or a whole
> library of models. OrcaSlicer is provisioned automatically when a model
> still needs slicing.

[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Repo](https://img.shields.io/badge/repo-nimblemo%2Ffilament--meter-blueviolet.svg)](https://github.com/nimblemo/filament-meter)

`filament-meter` answers one question and answers it well:

> **given a path (a file *or* a directory), how much filament will this print consume?**

It reads the numbers that slicers already write into sliced files
(`Metadata/slice_info.config`, or the G-code footer as a fallback),
aggregates them per plate, per file and per run, and prints them — or
writes them to a file in JSON / CSV / Markdown. If a model has not been
sliced yet, `filament-meter` finds (or downloads) OrcaSlicer, slices it in
a throw-away directory, and reports the result without ever touching your
model folder.

***

## Highlights

- **One flat command** — `filament-meter PATH`. A file, a directory or a
  glob pattern; no subcommands to remember.
- **Fast path first** — already-sliced `.3mf` files are parsed locally;
  OrcaSlicer is never launched when it is not needed.
- **Automatic OrcaSlicer provisioning** — a portable build is downloaded
  lazily into the user cache on first slice, or eagerly with
  `--install-orca`. No admin rights, no `pip install`-time downloads.
- **Never pollutes your models** — slicing happens in a temporary
  directory (or `--keep-sliced DIR`); no large files are written next to
  your sources.
- **Battle-tested slicing** — the same two OrcaSlicer workarounds proven
  on real Bambu Studio exports: `--allow-newer-file` and the adaptive
  `--<key>=<min>` retry for `not in range` errors.
- **Four output formats** — human table, JSON, CSV (`;`-separated,
  Excel-friendly) and Markdown.
- **Pure stdlib +** **`uvx`** — the only runtime dependency is
  `platformdirs`; run it anywhere Python 3.11+ exists.

***

## Table of contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Usage](#usage)
- [Output formats](#output-formats)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Releasing](#releasing)
- [License](#license)

***

## Requirements

- **Python** ≥ 3.11
- **`uv`** / **`uvx`** for the recommended install
  ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- **OrcaSlicer** — optional. If it is not installed, `filament-meter`
  downloads a portable build into its cache the first time it needs to
  slice something. Pre-installed locations are auto-detected.
- Outbound HTTPS to `api.github.com` and `github.com` **only** when
  OrcaSlicer has to be downloaded.

The project is **Windows / macOS / Linux** friendly.

***

## Installation

**From** **[PyPI](https://pypi.org/project/filament-meter/)** (recommended for users):

```bash
uv tool install filament-meter
filament-meter --help
```

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/) (or substitute `pipx` / `pip`).

For a one-shot run from a local checkout, `uvx` builds a temporary,
isolated environment that does not pollute the global Python:

```bash
# From the repository root
uvx --from . filament-meter "D:/models/part.3mf"
```

To install the checkout as a long-lived tool:

```bash
uv tool install .                # installs the `filament-meter` binary
filament-meter --version
```

For development, install in editable mode with all extras:

```bash
git clone https://github.com/nimblemo/filament-meter.git
cd filament-meter
uv sync --all-extras
uv run filament-meter --help
```

***

## Quick start

```bash
# 1. A single, already-sliced file — instant, no OrcaSlicer needed
filament-meter "D:/models/Gesha_sliced.3mf"

# 2. A whole folder, with cost estimation
filament-meter "D:/models" --price 2200 --currency RUB

# 3. A folder of *unsliced* projects — OrcaSlicer is fetched on demand
filament-meter "D:/projects" --price 2200

# 4. Machine-readable output to a file
filament-meter "D:/models" --price 2200 -o report.csv
```

A typical table run looks like this:

```text
========================================================================
Gesha_Bambu_sliced.3mf   (25.40 MB)
  D:\WOOD\locus-products\sliced\Gesha_Bambu_sliced.3mf
  Plate 1 | objects: 1 | layer: 0.20 mm | nozzle: 0.4 mm
      bed: textured_plate
      #  type      color         grams   metres
      4  PLA       #8E9089       96.54    31.85
      plate total: 96.54 g | time: 5h 57m
  TOTAL: 96.54 g, 31.85 m, time ~5h 57m
  cost at 2200 RUB/kg: 212.39 RUB
========================================================================
files: 1 | sliced: 1 | failed: 0
TOTAL: 96.54 g, 31.85 m, time ~5h 57m
TOTAL cost: 212.39 RUB
```

***

## Usage

```text
filament-meter PATH [options]
```

`PATH` is the only positional argument. It may be:

- a **file** (`.3mf`, `.gcode`, `.stl`, `.obj`, `.gcode.3mf`) — an explicitly
  named file is *always* processed, whatever its extension;
- a **directory** — scanned recursively for the default model masks
  `*.3mf`, `*.stl`, `*.obj` (disable the walk with `--no-recursive`, replace
  the masks with `--glob`);
- a **glob pattern** such as `"D:/models/*.3mf"`.

> **Why `.gcode` is not a default directory mask.** When a model is sliced
> the slicer drops a `plate_N.gcode` (or `<model>.gcode`) *next to* the
> `.3mf`. Scanning `*.gcode` together with `*.3mf` would therefore report the
> same object twice. If the default scan of a directory finds **nothing** but
> `*.gcode` files are present (e.g. a folder of slices downloaded from
> Printables), the tool automatically retries with `*.gcode` and notes
> `falling back to *.gcode` on stderr. Pass `--glob "*.gcode"` to opt into
> G-code explicitly.


For every file the tool decides between two paths:

- **fast path** — the `.3mf` is already sliced (`slice_info.config` has a
  real `<plate>` entry, or a `Metadata/plate_N.gcode` exists): it is
  parsed locally and OrcaSlicer is never started;
- **slice path** — otherwise (an unsliced project, or a bare `.stl` /
  `.obj`) OrcaSlicer is located, downloaded if needed, and the model is
  sliced in a temporary directory.

### Flags

| Flag | Description |
| --- | --- |
| `-o, --output FILE` | Write the report to a file. Format from the extension (`.json` / `.csv` / `.md` / `.txt`); unknown extensions fall back to `txt`. |
| `-f, --format {table,json,csv,md}` | Stdout format (default: `table`). |
| `--price FLOAT` | Filament price per kilogram, for cost calculation. |
| `--currency STR` | Currency code (default: `RUB`). |
| `--no-recursive` | Do not walk directories recursively. |
| `--glob PATTERN` | File mask(s) used when `PATH` is a directory (repeatable). Overrides the default masks (`*.3mf`, `*.stl`, `*.obj`). |
| `--orca PATH` | Explicit OrcaSlicer executable. |
| `--orca-version STR` | OrcaSlicer version to download (default: `latest`). |
| `--install-orca` | Only download OrcaSlicer and exit (does not need `PATH`). |
| `--no-auto-install` | Never download OrcaSlicer automatically. |
| `--no-slice` | Parse only; never slice. Unsliced files are reported as "no data", not as errors. |
| `--force-slice` | Slice again even if the file is already sliced. |
| `--machine / --process / --filament STR` | Profile file names (default: Bambu Lab A1 profiles). |
| `--use-project-settings` | Do not pass profiles; rely on settings embedded in the project. |
| `--jobs INT` | Number of files to slice in parallel (default: 1). |
| `--timeout INT` | Per-file slicing timeout in seconds (default: 3600). |
| `--cache-dir PATH` | Override the OrcaSlicer cache directory. |
| `--keep-sliced DIR` | Copy freshly-sliced `.3mf` files into `DIR` (default: temp dir, removed after parsing). |
| `-q, --quiet` / `-v, --verbose` | Adjust logging. |
| `--version` | Print the version and exit. |
| `--check` | Run environment diagnostics (OrcaSlicer, cache, write access) and exit. |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success — every file produced filament data. |
| `1` | Partial success — some files could not be processed. |
| `2` | Usage / environment error (bad path, OrcaSlicer missing with `--no-auto-install`). |
| `3` | Total failure — not a single file yielded filament data. |

***

## Output formats

| Format | Flag | Notes |
| --- | --- | --- |
| `table` | `-f table` | Human-readable ASCII, the default. |
| `json` | `-f json` | Full `RunReport`, `ensure_ascii=False`, 2-space indent. |
| `csv` | `-f csv` | `;`-separated, written with a UTF-8 BOM for Excel. |
| `md` | `-f md` | Markdown table plus a totals block. |

The CSV columns match the legacy `filament_report.csv` exactly:

```text
файл;нарезан;плашка;id филамента;тип;цвет;граммы;метры;время, с;цена, ₽
Gesha_Bambu_sliced.3mf;да;1;4;PLA;#8E9089;96.54;31.85;21439.0;212.39
```

***

## Configuration

`filament-meter` is configured entirely through flags and environment
variables. Nothing is written to disk except the report you ask for and
the OrcaSlicer cache.

| Variable | Purpose | Default |
| --- | --- | --- |
| `FILAMENT_METER_ORCA` | Path to an OrcaSlicer executable. | — |
| `FILAMENT_METER_CACHE_DIR` | Override the OrcaSlicer download cache. | platform cache dir |

The cache location (unless overridden) is:

- **Windows** — `%LOCALAPPDATA%\filament-meter\Cache\orca\<version>\`
- **macOS** — `~/Library/Caches/filament-meter/orca/<version>/`
- **Linux** — `~/.cache/filament-meter/orca/<version>/`

(`platformdirs` appends the `Cache` component on Windows, hence the
`…\filament-meter\Cache\orca\…` layout.)

### OrcaSlicer discovery order

1. `--orca PATH`
2. `FILAMENT_METER_ORCA`
3. `orca-slicer` / `OrcaSlicer` on `PATH`
4. Well-known install locations
   (`%LOCALAPPDATA%\Programs\OrcaSlicer`, `/Applications/OrcaSlicer.app`, …)
5. The download cache

If none is found and `--no-auto-install` is **not** set, a portable
OrcaSlicer build is downloaded automatically (no admin rights required).

### Diagnostics

`filament-meter --check` prints the resolved environment and exits without
touching any model. A real example on Windows:

```text
filament-meter 0.1.0
python: 3.12.14
platform: windows
cache dir: C:\Users\mikhe\AppData\Local\filament-meter\Cache\orca
cache writable: yes
OrcaSlicer: C:\Users\mikhe\AppData\Local\Programs\OrcaSlicer\orca-slicer.exe
OrcaSlicer version: unknown (CLI does not report --version)
```

The OrcaSlicer CLI does not answer `--version`, so the version line reads
`unknown (CLI does not report --version)` — this is expected, not an error.

***

## How it works

```
        ┌────────────┐      sliced?       ┌───────────────┐
PATH ─▶ │ discovery  │ ───────────────▶  │ parser        │ ─▶ FileReport
        └────────────┘   yes ┌───────────│ (slice_info / │
             │                │           │  gcode)       │
             │ no             │           └───────────────┘
             ▼                │
        ┌────────────┐        │
        │ orca       │ find / download OrcaSlicer
        └────────────┘        │
             ▼                │
        ┌────────────┐        │
        │ slicer     │ slice into a temp dir ──▶ sliced .3mf
        └────────────┘        │
             └────────────────┘
                      ▼
               ┌────────────┐
               │ report     │ table / json / csv / md
               └────────────┘
```

- **`discovery`** — turns a path/glob into a de-duplicated, sorted file
  list.
- **`parser`** — reads `Metadata/slice_info.config` first, then the
  `Metadata/plate_N.gcode` footer, and enriches plates with object / bed /
  nozzle data from `Metadata/plate_N.json`. A rough length→mass estimate
  is used only when nothing better exists.
- **`slicer`** — builds the OrcaSlicer command line and drives the
  adaptive retry loop.
- **`orca`** — locates, downloads and provisions OrcaSlicer.
- **`report`** — renders the aggregate `RunReport`.

***

## Project layout

```text
.
├── pyproject.toml
├── README.md
└── src/filament_meter/
    ├── __init__.py          # version + public API re-exports
    ├── __main__.py          # python -m filament_meter
    ├── models.py            # frozen dataclasses + SliceSource enum
    ├── errors.py            # exception hierarchy
    ├── discovery.py         # path (file/dir/glob) -> file list
    ├── parser.py            # sliced 3mf / gcode parsing
    ├── slicer.py            # OrcaSlicer CLI invocation
    ├── orca.py              # find / download / provision OrcaSlicer
    ├── report.py            # table / json / csv / md renderers
    └── cli/
        ├── __init__.py
        ├── app.py           # argparse + main()
        └── _common.py       # exit codes, console setup, logging
```

Runtime artefacts:

```text
<cache-dir>/orca/<version>/...     # downloaded OrcaSlicer build (if needed)
<temp-dir>/filament-meter-*/       # per-file slicing workspace (auto-removed)
```

***

## Troubleshooting

**"OrcaSlicer was not found"**
Either install OrcaSlicer, pass `--orca <path>`, set
`FILAMENT_METER_ORCA`, or drop `--no-auto-install` so the tool downloads
a portable build for you.

**The download seems to hang**
The first slice downloads a ~50 MB archive from GitHub into the cache.
Subsequent runs reuse it. Use `--install-orca` to fetch it up front, or
`--check` to see the cache location.

**Numbers differ from Bambu Studio**
For **project** `.3mf` files the settings embedded in the model always win
over `--load-settings` / `--load-filaments`; the flags only take effect
for bare `.stl` / `.obj` inputs. This is a slicer behaviour, not a bug —
and it means the reported numbers reflect the model author's intent.

**`--export-3mf` swallowed my file name**
Internally the export flag is always the *last* argument before the input
file. If you drive OrcaSlicer yourself, keep it last: it consumes the next
token as the output name.

**"not in range" errors from OrcaSlicer**
Models exported from a newer Bambu Studio can carry out-of-range values
(e.g. `tree_support_wall_count: -1`). `filament-meter` detects these in the
log and retries with `--<key>=<min>` automatically.

**A `.3mf` reports "not sliced"**
The file has only a `slice_info.config` header — it was never sliced, so it
physically contains no filament data. Drop `--no-slice` to let the tool
slice it first.

***

## Roadmap

- Optional machine-readable `--profile` presets beyond the Bambu Lab A1
  defaults.
- A persistent usage registry (append-only CSV) with de-duplication, like
  the legacy `filament-log.csv`.
- Multi-plate batch arrangement for large model libraries.
- Cost profiles per material (PLA / PETG / …).

***

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the local workflow. In short:

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
```

Keep changes minimal and respect the existing module boundaries
(`discovery`, `parser`, `slicer`, `orca`, `report`, `cli`).

***

## Releasing

Releases are fully automated via GitHub Actions (`.github/workflows/`):

- **`ci.yml`** — runs on every push to `main` and on every pull request.
  Matrix-builds the sdist + wheel on Python 3.11 / 3.12 / 3.13, lints,
  type-checks, tests, and smoke-tests the built wheel.
- **`release.yml`** — runs on a published GitHub Release, or manually via
  the *Run workflow* button. Builds the wheel, smoke-tests it, and pushes
  it to PyPI (or TestPyPI) using
  [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
  (OIDC). **No API tokens are stored in GitHub secrets.**

### One-time setup: register the trusted publisher on PyPI

1. Reserve the project name `filament-meter` on
   [PyPI](https://pypi.org/manage/projects/publish/).
2. Register the workflow as a *trusted publisher* on
   <https://pypi.org/manage/account/publishing/> with owner `nimblemo`,
   repository `filament-meter`, workflow `release.yml`, environment
   `pypi`. Repeat on TestPyPI with environment `testpypi`.
3. Create the matching `pypi` and `testpypi` environments in GitHub.

### Cutting a release

1. Bump `version` in `pyproject.toml` and `src/filament_meter/__init__.py`.
2. Add `.release-notes/vX.Y.Z.md` and update `CHANGELOG.md`.
3. Commit, push, and publish a GitHub Release tagged `vX.Y.Z`.

***

## License

[MIT](LICENSE) — see the [LICENSE](LICENSE) file for the full text.
