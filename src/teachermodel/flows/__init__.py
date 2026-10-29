"""Page builders, one module per workflow, collected in one registry.

A builder takes the loaded `State` and a subject URI and returns the page specs for a human step (one per
signer). Each flow module registers its own builders with `@register(step_id)`; importing this package
imports every flow module, so `PAGE_SPECS` is complete once `teachermodel.flows` has been imported.
`app` reads `PAGE_SPECS` to write pages and to re-derive the inputs a sign-off must match.

A flow also registers the runner of an auto step (`@auto_step`) and the side effects of an approving sign-off
(`@on_signoff`); see `hooks.py`. A new workflow adds one module here and one import line below; nothing else in `app`
changes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .common import State
from .hooks import (  # noqa: F401 - the extension points, see hooks.py
    AUTO_STEPS,
    CONTENT_CHECKS,
    SIGNOFF_HOOKS,
    auto_step,
    content_check,
    content_reasons,
    on_signoff,
)

Builder = Callable[[State, str], list[dict[str, Any]]]

PAGE_SPECS: dict[str, Builder] = {}


def register(step_id: str) -> Callable[[Builder], Builder]:
    """Register `builder` as the page builder for a human step. One builder per step."""

    def decorate(builder: Builder) -> Builder:
        if step_id in PAGE_SPECS:
            raise ValueError(f"page builder for {step_id} is already registered")
        PAGE_SPECS[step_id] = builder
        return builder

    return decorate


# Imported for their registrations; they need `register` above, so they come last.
from . import (  # noqa: E402,F401
    audit,
    bench,
    calibration,
    clearance,
    dry_run,
    levels,
    observation,
    onboarding,
    override,
    rights,
    pathway,
    privacy_base,
    privacy_overlay,
    quality,
    setup,
)
from . import coaching, cpd  # noqa: E402,F401 - W7 coaching and W9 CPD (cpd needs observation and dry_run above)
