# filament-meter — full command reference

## Synopsis

```
filament-meter PATH [options]
```

`PATH` is the only positional argument. It may be:

- a **file** (`.3mf`, `.gcode`, `.stl`, `.obj`) — an explicitly named file is
  always processed, whatever its extension;
- a **directory** — scanned recursively for `*.3mf`, `*.stl`, `*.obj`
  (disable with `--no-recursive`, override the masks with `--glob`);
- a **glob** pattern such as `"D:/models/*.3mf"`.

## Flags

| Flag | Description |
| --- | --- |
| `-o, --output FILE` | Write the report to a file. Format from the extension (`.json` / `.csv` / `.md` / `.txt`). |
| `-f, --format {table,json,csv,md}` | Stdout format (default: `table`). |
| `--price FLOAT` | Filament price per kilogram, for cost calculation (persisted). |
| `--currency STR` | Currency code for cost figures (persisted; default: `RUB`). |
| `--no-recursive` | Do not walk directories recursively. |
| `--glob PATTERN` | File mask(s) used when `PATH` is a directory (repeatable). Overrides the default masks. |
| `--orca PATH` | Explicit OrcaSlicer executable. |
| `--orca-version STR` | OrcaSlicer version to download (default: `latest`). |
| `--install-orca` | Only download OrcaSlicer and exit (does not need `PATH`). |
| `--no-auto-install` | Never download OrcaSlicer automatically. |
| `--no-slice` | Parse only; never slice. Unsliced files are reported as "no data", not errors. |
| `--force-slice` | Slice again even if the file is already sliced. |
| `--machine STR` | Machine profile file name (default: Bambu Lab A1). |
| `--process STR` | Process profile file name (default: Bambu Lab A1). |
| `--filament STR` | Filament profile file name (default: Bambu Lab A1). |
| `--use-project-settings` | Do not pass profiles; rely on settings embedded in the project. |
| `--jobs INT` | Number of files to slice in parallel (default: 1). |
| `--timeout INT` | Per-file slicing timeout in seconds (default: 3600). |
| `--cache-dir PATH` | Override the OrcaSlicer and result-cache directories. |
| `--no-cache` | Disable the persistent result cache (neither read nor write). |
| `--keep-sliced DIR` | Copy freshly-sliced `.3mf` files into `DIR` (default: temp dir, removed after parsing). |
| `-q, --quiet` / `-v, --verbose` | Adjust logging verbosity. |
| `--version` | Print the version and exit. |
| `--check` | Run environment diagnostics (OrcaSlicer, cache, write access) and exit. |

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success — every file produced filament data. |
| `1` | Partial success — some files could not be processed. |
| `2` | Usage / environment error (bad path, OrcaSlicer missing with `--no-auto-install`). |
| `3` | Total failure — not a single file yielded filament data. |

## Output formats

| Format | Flag | Notes |
| --- | --- | --- |
| `table` | `-f table` | Human-readable ASCII, the default. |
| `json` | `-f json` | Full `RunReport`, `ensure_ascii=False`, 2-space indent. |
| `csv` | `-f csv` | `;`-separated, written with a UTF-8 BOM for Excel. |
| `md` | `-f md` | Markdown table plus a totals block. |

The CSV columns match the legacy `filament_report.csv`:

```
файл;нарезан;плашка;id филамента;тип;цвет;граммы;метры;время, с;цена, ₽
```

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `FILAMENT_METER_ORCA` | Path to an OrcaSlicer executable. | — |
| `FILAMENT_METER_CACHE_DIR` | Override the OrcaSlicer + result-cache directory. | platform cache dir |
| `FILAMENT_METER_CONFIG_DIR` | Override the settings-file directory. | platform config dir |

## Persistent state

- **Result cache** — `<cache-dir>/results/results.json`. Per-model figures keyed
  by **absolute path + file size**; an unchanged model is never sliced or
  re-parsed twice. Disable with `--no-cache`.
- **Settings** — `<config-dir>/settings.json`. The last `--currency` / `--price`
  values. Explicitly passed flags win over the stored values and are written back.

## OrcaSlicer discovery order

1. `--orca PATH`
2. `FILAMENT_METER_ORCA`
3. `orca-slicer` / `OrcaSlicer` on `PATH`
4. Well-known install locations (`%LOCALAPPDATA%\Programs\OrcaSlicer`,
   `/Applications/OrcaSlicer.app`, …)
5. The download cache

If none is found and `--no-auto-install` is not set, a portable build is
downloaded automatically.
