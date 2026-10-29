"""Page builders and sign-off hooks for the W1 onboarding workflow (standards/workflows/onboarding.yaml)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import events, signoff
from .. import pages as pagegen
from ..util import iso_seconds
from . import on_signoff, register
from .common import PEOPLE, TARGET_LEVEL, PageProblem, State, current_level, latest_level, per_signer, spec

LEVEL_STEP = "tm:step/lead-observed-level"


def _commitment(step_id: str):
    def build(st: State, subject: str):
        d = st.step_defs[step_id]
        reg = st.registrations.get(subject)
        signer = signoff.expected_signer_for(d, subject, reg)
        if signer is None:
            raise PageProblem(f"the registration names no {d['role']} for {subject}")
        if not any(r["person"] == signer and d["role"] in r["roles"] for r in st.people):
            raise PageProblem(f"{signer} is not in {PEOPLE} with role {d['role']}")
        inputs = {"instructor": subject, "type": reg["type"], "organisation": reg["organisation"],
                  "engagement": reg["engagement"]}
        return [spec(st, step_id, subject, signer, "approve", inputs,
                     intro="Confirm the engagement facts below, including protected teaching time.")]
    return build


@register("tm:step/baseline-self-assessment")
def _b_self_assessment(st: State, subject: str):
    inputs = {"instructor": subject, "framework_version": st.standards["framework"]["version"]}
    return [spec(st, "tm:step/baseline-self-assessment", subject, subject, "self_assessment", inputs,
                 pagegen.self_assessment_fields(st.standards),
                 intro="Score yourself against each domain. Your scores are not shared with your manager.")]


def _delivery(step_id: str):
    fields = [
        {"name": "date", "label": "Date", "kind": "date", "required": True},
        {"name": "delivery_ref", "label": "Delivery reference", "kind": "text", "required": True,
         "help": "The delivery id or session reference, not a person's name."},
        {"name": "note", "label": "Note", "kind": "textarea", "required": False},
    ]

    def build(st: State, subject: str):
        reg = st.registrations.get(subject) or {}
        inputs = {"instructor": subject, "type": reg.get("type"), "level": current_level(st, subject)}
        return per_signer(st, step_id, subject, "approve", inputs, fields,
                          intro="Record that this step has happened, with its date and delivery reference.")
    return build


@register(LEVEL_STEP)
def _b_lead_observed(st: State, subject: str):
    level = current_level(st, subject)
    rows = [{"key": subject, "summary": f"{subject}: level {level} to {TARGET_LEVEL}", "changed": True}]
    return per_signer(st, LEVEL_STEP, subject, "batch_approve", {"rows": rows},
                      intro="A level moves only by this decision.")


def level_change_id(signoff_id: str) -> str:
    """Deterministic event id for the level change a sign-off causes: a replay cannot add a second one."""
    return signoff.input_sha256({"level_change_for_signoff": signoff_id})[:32]


@on_signoff(LEVEL_STEP)
def _level_change(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """A `level_change` to TARGET_LEVEL for an approving sign-off of the level-change step. The actor is the signer;
    `from` is the level just before (`st.events` holds the earlier events of the same receipt)."""
    uri, p = signed["subject_uri"], signed["payload"]
    before = latest_level(st.registrations.get(uri), st.events, uri)
    if before == TARGET_LEVEL:
        return [], []
    change = events.make_event(
        "level_change", uri, signed["actor"],
        {"from": before, "to": TARGET_LEVEL, "basis": f"signoff {p['signoff_id']}"},
        id=level_change_id(p["signoff_id"]), at=iso_seconds(now),
    )
    return [change], []


for _step in ("tm:step/commitment-manager", "tm:step/commitment-partner-lead"):
    register(_step)(_commitment(_step))
for _step in ("tm:step/train-the-trainer", "tm:step/shadow-delivery", "tm:step/co-delivery"):
    register(_step)(_delivery(_step))
