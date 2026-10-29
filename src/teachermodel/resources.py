"""Where the reference data (`standards/`, `contracts/`) lives.

Every module resolves those directories through `root()`, so there is one place to change when the data
moves. Today the data sits beside the source tree, so this only works from a checkout or an editable
install. The future path is packaged data (shipped inside the wheel, read through importlib.resources);
that change belongs here and nowhere else. Install behaviour is unchanged for now.

`TEACHERMODEL_ROOT` overrides the location, for tests and tools that point at a copy of the data.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_ROOT = "TEACHERMODEL_ROOT"


def root() -> Path:
    """The directory holding `standards/` and `contracts/`."""
    override = os.environ.get(ENV_ROOT)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2]
