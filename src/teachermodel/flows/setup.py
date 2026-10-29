"""Page builders and auto-step runners for the setup workflow (standards/workflows/setup.yaml)."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from .. import records
from .. import setup as tm_setup
from . import auto_step, register
from .common import PageProblem, State, generated, per_signer


def it_checklist(text: str) -> list[dict[str, str]]:
    """One checklist item per numbered item under "## What to set up" in the IT request: its first sentence, without
    the citation. IT ticks each one off as it is done (IT, 2026-10-26)."""
    m = re.search(r"^## What to set up\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    items: list[dict[str, str]] = []
    for n, body in enumerate(re.findall(r"^\d+\.\s+(.*?)(?=^\d+\.\s|\Z)", m.group(1) if m else "", re.S | re.M), start=1):
        flat = re.sub(r"\s+", " ", re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", body)).strip()
        items.append({"id": f"item-{n}", "label": re.split(r"(?<=\.)\s", flat, maxsplit=1)[0]})
    return items


@register("tm:step/it-done")
def _b_it_done(st: State, subject: str):
    text, _ = generated(st, tm_setup.STEP_IT_REQUEST)
    items = it_checklist(text)
    if not items:
        raise PageProblem("generated/it-request.md has no numbered items under '## What to set up'")
    fields = [
        {"name": "setup", "label": "What to set up", "kind": "checklist", "required": True, "items": items,
         "help": "Mark each item pass when it is done as the request describes; a failed item needs a note."},
        {"name": "copy-target", "label": "Nightly copy target", "kind": "text", "required": False,
         "help": "Where the nightly copy goes (item 6)."},
        {"name": "note", "label": "Note", "kind": "textarea", "required": False,
         "help": "Optional. Anything the programme owner should know."},
    ]
    return per_signer(st, "tm:step/it-done", subject, "approve", {"it_request_text": text}, fields,
                      intro="Confirm the library and security group exist and match this request. Tick each "
                            "section as you check it; your ticks and answers stay in this browser until you save.")


@register("tm:step/gap-list-approved")
def _b_gap_list(st: State, subject: str):
    text, _ = generated(st, tm_setup.STEP_GAP_LIST)
    try:
        rows = json.loads(text)["rows"]
    except (ValueError, KeyError, TypeError) as exc:
        raise PageProblem("generated/gap-list.json is unreadable") from exc
    return per_signer(st, "tm:step/gap-list-approved", subject, "batch_approve", {"rows": rows},
                      intro="Approve the unchanged rows in one step; decide each changed row.")


# --- auto steps: the outputs derive from files an edit can change, so the ones marked refresh re-run while their needs hold ---


@auto_step(tm_setup.STEP_IT_REQUEST, refresh=True)
def _run_it_request(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return tm_setup.it_request(st.private, st.events, st.settings, now, root=st.root)


@auto_step(tm_setup.STEP_ROPA, refresh=True)
def _run_ropa(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return tm_setup.ropa(st.private, st.events, st.settings, now, root=st.root)


@auto_step(tm_setup.STEP_NOTICE_TEXT, refresh=True)
def _run_notice_text(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return tm_setup.notice_text(st.private, st.events, st.settings, now, root=st.root)


# Run once for all instructors: an instructor whose notice is not usable gets a blocked check, not a draft. The drafts
# follow the approved text, so they are rebuilt when it differs from the one a draft was built from.
@auto_step(tm_setup.STEP_NOTICE_DRAFTS, refresh=True)
def _run_notice_drafts(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return tm_setup.notice_drafts(st.private, st.events, st.settings, now, root=st.root)


# Refreshed: a clearance issued, lapsed or expiring changes the rows (carry-over 15). A run whose rows are the same as the
# previous output appends nothing.
@auto_step(tm_setup.STEP_GAP_LIST, refresh=True)
def _run_gap_list(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return tm_setup.gap_list(st.private, st.events, st.settings, now, clearances=records.clearances(st.events),
                             rules=st.standards["rules"], root=st.root)
