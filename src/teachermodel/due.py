"""Due-rule registry: a workflow step's `due` may name a rule instead of a number of days.

A rule is a pure function `(step, subject_uri, subject_info, events, today) -> date | None`:
- `step` is the step definition (the dict from standards/workflows/*.yaml);
- `subject_uri` and `subject_info` are the subject the step is open for and its engine info (`workflow.subjects`);
- `events` is the whole event log (a list); `today` the date the queue is being worked out for;
- it returns the date the step falls due, or None when it has no date (yet).

Rules register with `@due_rule("name")` where they are defined, in the flow module of the workflow that uses them
(`teachermodel.flows.*`, imported by `teachermodel.flows`). The engine resolves a string `due` through `resolve`;
`standards.check_workflows` imports `teachermodel.flows` and refuses a name that is not registered. Rules must be
deterministic and take no model, no clock and no I/O beyond their arguments.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import date
from typing import Any

Rule = Callable[[dict[str, Any], str, dict[str, Any], Sequence[dict[str, Any]], date], "date | None"]

_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")  # the same pattern as `due` in contracts/workflows.schema.json
_RULES: dict[str, Rule] = {}


def due_rule(name: str) -> Callable[[Rule], Rule]:
    """Register the decorated function as the due rule `name`. A name registers once."""
    if not isinstance(name, str) or not _NAME.match(name):
        raise ValueError(f"due rule name {name!r} must match {_NAME.pattern}")

    def decorate(fn: Rule) -> Rule:
        if name in _RULES:
            raise ValueError(f"due rule {name!r} is already registered")
        _RULES[name] = fn
        return fn

    return decorate


def resolve(name: str) -> Rule:
    """The rule registered as `name`; KeyError naming it when there is none."""
    try:
        return _RULES[name]
    except KeyError:
        raise KeyError(f"no due rule registered as {name!r}") from None


def names() -> frozenset[str]:
    """Every registered rule name."""
    return frozenset(_RULES)
