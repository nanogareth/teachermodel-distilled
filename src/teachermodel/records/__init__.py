"""Record adapters: turn the event log into the plain data `rules.py` takes.

One module per kind of record, each owned by one stream (docs/plans/2026-10-24-increment-2-plan.md and
docs/plans/2026-10-25-increment-3-plan.md), each exposing a single public function of the same name. The package
re-exports the functions, so `from teachermodel.records import observations` gives the function;
`importlib.import_module("teachermodel.records.observations")` gives the module.

K0 fixed the names and signatures of the first four; K1 (decision 0014) fixed audits, cycles, cpd, outcomes and bench; the
integration added lapses (the audit referrals, decision 0015). Every body is written.

`bench_blocks` is the one module with more than one reader: the bench decisions that stop an instructor teaching
(decision 0015, amended for integration review findings 2 and 3). Import it as the module.
"""

from __future__ import annotations

from . import bench_blocks  # noqa: F401 - a module of readers, see its docstring
from .audits import audits
from .bench import bench
from .calibrations import calibrations
from .clearances import clearances
from .cpd import cpd
from .cycles import cycles
from .dry_runs import dry_runs
from .lapses import lapses
from .observations import observations
from .outcomes import outcomes
from .overrides import overrides

__all__ = ["audits", "bench", "calibrations", "clearances", "cpd", "cycles", "dry_runs", "lapses", "observations", "outcomes", "overrides"]
