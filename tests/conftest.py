"""Shared pytest fixtures for the ``filament-meter`` test-suite.

The suite is deliberately hermetic: no test touches the network or a real
OrcaSlicer binary. Every external call is monkeypatched at the module
boundary (see ``filament_meter.slicer.subprocess`` and
``filament_meter.orca``).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make ``factories`` importable regardless of the pytest invocation dir.
sys.path.insert(0, str(Path(__file__).parent))
