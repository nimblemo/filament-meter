# Contributing to filament-meter

Thanks for taking the time to contribute! This document describes the
local workflow and the conventions used across the project.

## Getting started

```bash
git clone https://github.com/nimblemo/filament-meter.git
cd filament-meter
uv sync --all-extras
uv run filament-meter --help
```

## Development checks

Before opening a pull request, make sure everything passes:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -q
uv build
```

Optional: install the git hooks so the checks run automatically.

```bash
uv run pre-commit install
```

## Conventions

- **Style**: [ruff](https://docs.astral.sh/ruff/) with `E`, `F`, `I`, `UP`,
  `B`, `SIM` and a line length of 100. `ruff format` owns formatting.
- **Typing**: `mypy` in strict mode over `src/`. Every public function and
  method carries full type hints.
- **Docs**: Google-style docstrings on modules, classes and public
  functions.
- **Tests**: hermetic and fast. No test may touch the network or launch a
  real OrcaSlicer; patch at the module boundary
  (`filament_meter.slicer.subprocess`, `filament_meter.orca`).

## Module boundaries

Please keep the existing separation of concerns:

| Module | Responsibility |
| --- | --- |
| `discovery` | Resolve a path/glob into a file list. |
| `parser` | Read filament data out of sliced files. |
| `slicer` | Drive the OrcaSlicer CLI. |
| `orca` | Find / download / provision OrcaSlicer. |
| `report` | Render a `RunReport`. |
| `cli` | Argument parsing and orchestration only. |

New behaviour belongs in the smallest module that owns it; `cli/app.py`
should stay thin.

## Adding a report format

1. Add a renderer to `report.py` and register it in `render()` and
   `FORMATS`.
2. Extend `_EXTENSION_FORMATS` if it maps to a file extension.
3. Add a focused test to `tests/test_report.py`.

## Commit messages

Use clear, imperative subjects (e.g. `parser: handle multi-plate gcode
fallback`). Keep the diff focused; avoid unrelated formatting churn.

## License

By contributing you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
