"""The W3 dry-run workflow (standards/workflows/dry-run.yaml): the page of `tm:step/dry-run`, the sign-off hook that writes
the `dry_run` event, and the helpers the records and the tests share.

A candidate (one instructor x unit x mode) is dry-run by a clearer who is not that instructor. A clearer here is a person
holding the clearer role who is mapped (people.yaml `instructor`) to an instructor at level clearer who is calibrated on the
day (`common.clearer_people`; integration review finding 5): the role in the people list alone is nothing. The page goes to
those people on the day of the log's newest event; the hook checks the signing day again. The page is built from the
unit file (standards/units, `units.load`): a checklist of preflight items (the unit's environment and step 1 of
standards/dry-run-protocol.md), the run sheet if the unit has one, the clock, the failure handled and the fallback exercised,
plus a required choice of the failure from the unit's failure_catalogue that was injected. Its inputs carry
`units.environment_sha256`, so the step is `bind: input`: a change to the unit's environment, failure catalogue or run sheet
reopens it, and `records.dry_runs` stops counting the earlier run.

Approving the page runs `_record`: it derives `passed` from the answers (never from a field the clearer typed) and appends a
`dry_run` event (tm:contract/dry-run@1). The clearer's notes go to a private document, never into the event.

Two things keep the engine and the records honest, both through the page inputs:
- a signed run that did not pass (or was refused, below) lists its sign-off id in `earlier_unsuccessful`, so the inputs it
  signed no longer match and the step reopens for another run;
- a sign-off by the candidate's own instructor is refused: no `dry_run` event, a `check` event {result: dry_run_refused}.
  The page is only built for the other clearers, but the sign-off document is whatever the sender attached, so the hook
  checks again (the instructor can hold a clearer role under another person URI, with the same mailbox).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .. import events, signoff, units, workflow
from ..standards import ROOT
from . import on_signoff, register
from .common import PageProblem, State, cached, clearer_people, latest_day, spec

STEP = "tm:step/dry-run"
REFUSED = "dry_run_refused"  # `result` of the check event written for a sign-off the hook refuses
NO_FAILURE = "none"  # the enum option for "I injected no failure"; the run then cannot pass

# Step 1 of standards/dry-run-protocol.md, after the unit's own environment item. (id, label); the labels use the
# protocol's words (tests/test_dry_run.py checks that they still do).
PREFLIGHT = (
    ("preflight-accounts", "Accounts: every learner account exists and can sign in"),
    ("preflight-api-keys", "Sandbox API keys are scoped to the sandbox, and their rate limits are known"),
    ("preflight-data", "Data: the lab data is in place"),
    ("preflight-network", "Network: the learner environment reaches everything the lab calls"),
    ("preflight-model", "The model version is pinned for the session"),
)
FAILURE_HANDLED = "failure-handled"
FALLBACK = "fallback-exercised"
CLOCK = "clock"


def dry_run_event_id(signoff_id: str) -> str:
    """Deterministic id of the `dry_run` event a sign-off causes: a replay cannot add a second one."""
    return signoff.input_sha256({"dry_run_for_signoff": signoff_id})[:32]


def refused_event_id(signoff_id: str) -> str:
    return signoff.input_sha256({"dry_run_refused_for_signoff": signoff_id})[:32]


def current_environment_hashes(unit_uris: Any, root: Path = ROOT) -> dict[str, str]:
    """`{unit uri: units.environment_sha256}` for each unit that can be read; the map `records.dry_runs` takes. A unit
    whose file is missing or invalid is left out, so a run on it does not count."""
    out: dict[str, str] = {}
    for uri in unit_uris:
        try:
            out[uri] = units.environment_sha256(units.load(uri, root))
        except units.UnitError:
            continue
    return out


def is_candidates_instructor(st: State, signer: str, instructor: str) -> bool:
    """True when `signer` is the candidate's instructor: the same URI, a person mapped to them (people.yaml `instructor`), or
    a person whose mailbox is the instructor's roster mailbox (one person can be both an instructor and, under a
    `tm:person` URI, a clearer)."""
    if signer == instructor or any(p["person"] == signer and p.get("instructor") == instructor for p in st.people):
        return True
    mailboxes = {i["identity"]["email"].strip().lower() for i in (st.roster or {}).get("instructors", [])
                 if i["instructor"] == instructor}
    return any(p["person"] == signer and p["email"].strip().lower() in mailboxes for p in st.people)


FROM_RECORDING = "from-recording"  # checklist item of a partner candidate's dry run (W11): done from a recording


def is_partner(st: State, instructor: str) -> bool:
    """True when the instructor's registration type is partner (W11): their dry run and observations are from recordings and
    their clearance is scoped to their partner organisation and regions."""
    return (st.registrations.get(instructor) or {}).get("type") == "partner"


def checklist_items(unit: dict[str, Any], recorded: bool = False) -> list[dict[str, str]]:
    """The items of the checklist, in page order: the unit's environment, for a partner's run (`recorded`, W11) that it was
    done from a recording, the protocol's preflight, the run sheet steps (when the unit has them), the clock, the failure
    handled and the fallback exercised."""
    items = [{"id": "preflight-environment",
              "label": f"The learner environment is as the unit describes it: {unit['environment']}"}]
    if recorded:
        items.append({"id": FROM_RECORDING,
                      "label": "This dry run was done from a recording of the run, as a partner instructor's clearance requires"})
    items += [{"id": i, "label": label} for i, label in PREFLIGHT]
    sheet = unit.get("run_sheet") or []
    for step in sheet:
        minutes = f" ({step['minutes']:g} min)" if "minutes" in step else ""
        items.append({"id": f"step-{step['id']}", "label": f"Run sheet: {step['action']}{minutes}"})
    items.append({"id": CLOCK, "label": "The run sheet was walked against the clock and the session fits its length"
                  if sheet else "The session was walked against the clock (the unit has no run sheet)"})
    items.append({"id": FAILURE_HANDLED,
                  "label": "The injected failure was handled live as the unit's failure catalogue expects"})
    items.append({"id": FALLBACK, "label": "The fallback path was exercised (recorded demo or pre-computed outputs)"})
    return items


def _earlier_unsuccessful(st: State, subject: str) -> list[str]:
    """The sign-off ids of this candidate's runs that did not pass, and of its sign-offs the hook refused."""
    found = set()
    for e in st.index.for_subject(subject):
        p = e["payload"]
        failed = e["kind"] == "dry_run" and p.get("passed") is not True
        refused = e["kind"] == "check" and p.get("step") == STEP and p.get("result") == REFUSED
        if (failed or refused) and isinstance(p.get("signoff_id"), str):
            found.add(p["signoff_id"])
    return sorted(found)


def _candidate_unit(st: State, subject: str) -> tuple[dict[str, Any], dict[str, Any]]:
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "candidate":
        raise PageProblem(f"{subject} is not a candidate")
    try:
        # once per unit for this state, not once per candidate: a unit has a candidate for every instructor and mode
        return info, cached(st, f"unit {info['unit']}", lambda: units.load(info["unit"], st.root))
    except units.UnitError as exc:
        raise PageProblem(str(exc)) from exc


@register(STEP)
def _b_dry_run(st: State, subject: str) -> list[dict[str, Any]]:
    info, unit = _candidate_unit(st, subject)
    clearers = [r for r in clearer_people(st, latest_day(st))
                if not is_candidates_instructor(st, r["person"], info["instructor"])]
    if not clearers:
        raise PageProblem(f"no calibrated clearer other than the instructor of {subject} holds the clearer role "
                          "(a clearer is a mapped person whose instructor is at level clearer and calibrated)")
    items = checklist_items(unit, recorded=is_partner(st, info["instructor"]))
    inputs: dict[str, Any] = {
        "candidate": subject, "instructor": info["instructor"], "unit": info["unit"], "mode": info["mode"],
        "environment": unit["environment"], "environment_sha256": units.environment_sha256(unit),
        "failure_catalogue": unit["failure_catalogue"],
    }
    if "run_sheet" in unit:
        inputs["run_sheet"] = unit["run_sheet"]
    inputs["checks"] = [i["id"] for i in items]
    inputs["earlier_unsuccessful"] = _earlier_unsuccessful(st, subject)
    fields = [
        {"name": "checks", "label": "Dry-run checklist", "kind": "checklist", "required": True, "items": items,
         "help": "Pass or fail every item; a failed item needs a note."},
        {"name": "failure_injected", "label": "Failure injected", "kind": "enum", "required": True,
         "options": [f["id"] for f in unit["failure_catalogue"]] + [NO_FAILURE],
         "help": f"The failure from the catalogue above that you injected. Choose {NO_FAILURE} only if you injected none: "
                 "the run then does not pass."},
        {"name": "note", "label": "Fixes or notes (private)", "kind": "textarea", "required": False,
         "help": "If the run needs more work, ask for changes and list the fixes here. Notes stay in the private store."},
    ]
    intro = (
        "Dry-run protocol (standards/dry-run-protocol.md): preflight the learner environment, walk the run sheet against "
        "the clock, inject one failure from the catalogue below and handle it live, then exercise the fallback path.\n\n"
        "A run passes only when every item passes, a failure was injected and handled, and the fallback was exercised. "
        "It counts until the unit's environment, failure catalogue or run sheet changes. Approve to sign the run off; "
        "ask for changes if it needs more work."
    )
    return [spec(st, STEP, subject, r["person"], "approve", inputs, fields, intro) for r in clearers]


def _aware(stamp: Any) -> datetime | None:
    """The sign-off's `signed_at` as a time zone aware datetime (UTC when it names none); None when unreadable."""
    try:
        dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _signed_at(stamp: Any, fallback: datetime) -> str:
    """The day the clearer signed, as the event time: the run date. The ingest time when the stamp is unreadable."""
    return (_aware(stamp) or fallback).isoformat(timespec="seconds")


def _signed_day(stamp: Any, fallback: datetime) -> date:
    """The UTC day of the sign-off's `signed_at`; the ingest day when the stamp is unreadable."""
    dt = _aware(stamp)
    return dt.astimezone(timezone.utc).date() if dt else fallback.date()


def _refuse(subject: str, signoff_id: str, reason: str, now: datetime) -> tuple[list[dict[str, Any]], list]:
    return [events.make_event(
        "check", subject, workflow.SYSTEM_ACTOR,
        {"step": STEP, "result": REFUSED, "reasons": [reason], "signoff_id": signoff_id},
        id=refused_event_id(signoff_id), at=now.isoformat(timespec="seconds"))], []


@on_signoff(STEP)
def _record(st: State, signed: dict[str, Any], document: dict[str, Any], now: datetime):
    """The `dry_run` event for an approving sign-off, and a private document with the clearer's notes."""
    subject, p, signer = signed["subject_uri"], signed["payload"], signed["actor"]
    sid = p["signoff_id"]
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "candidate":
        return [], []
    if is_candidates_instructor(st, signer, info["instructor"]):
        return _refuse(subject, sid, "the signer is the instructor of this candidate", now)
    if signer not in {r["person"] for r in clearer_people(st, _signed_day(p.get("signed_at"), now))}:
        return _refuse(subject, sid, "the signer is not a calibrated clearer on the day they signed", now)
    try:
        unit = units.load(info["unit"], st.root)
    except units.UnitError:
        return _refuse(subject, sid, "the unit cannot be read", now)
    raw = document.get("fields") if isinstance(document.get("fields"), dict) else {}
    given = raw.get("checks") if isinstance(raw.get("checks"), dict) else {}
    checks: dict[str, str] = {}
    notes: dict[str, str] = {}
    for item in checklist_items(unit, recorded=is_partner(st, info["instructor"])):
        entry = given.get(item["id"]) if isinstance(given.get(item["id"]), dict) else {}
        checks[item["id"]] = "pass" if entry.get("result") == "pass" else "fail"  # unanswered is failed
        if isinstance(entry.get("note"), str) and entry["note"].strip():
            notes[item["id"]] = entry["note"].strip()
    chosen = raw.get("failure_injected")
    injected = chosen if isinstance(chosen, str) and chosen in {f["id"] for f in unit["failure_catalogue"]} else None
    fallback = checks[FALLBACK] == "pass"
    passed = all(v == "pass" for v in checks.values()) and injected is not None and fallback
    run = events.make_event(
        "dry_run", subject, signer,
        {"candidate": subject, "instructor": info["instructor"], "unit": info["unit"], "mode": info["mode"],
         "passed": passed, "checks": checks, "failure_injected": injected, "fallback_exercised": fallback,
         "environment_sha256": units.environment_sha256(unit), "signoff_id": sid},
        id=dry_run_event_id(sid), at=_signed_at(p.get("signed_at"), now))
    private = {"signoff_id": sid, "candidate": subject, "failure_chosen": chosen if isinstance(chosen, str) else None,
               "notes": notes, "note": raw.get("note") if isinstance(raw.get("note"), str) else ""}
    return [run], [(f"dry-runs/{sid}.json", private)]
