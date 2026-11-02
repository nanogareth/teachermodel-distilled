"""Intervention chains and the outbox they fill (decision 0029; standards/chains.yaml).

    interventions.build(scope)            the outbox as of now: every action the chains would send (outbox@1)
    interventions.write(private, scope)   outbox/outbox.json and the head of training's Outbox page

A chain starts when its condition holds. Conditions are pure functions over what the role surfaces already read (the
index, the schedule, the feeds, the freshness register) and the workflow's due steps; no model decides whether one
holds. Each holding condition is an *instance*: a subject (an instructor, a session, a delivery, a source) and an anchor
date (the trigger's day, the session's first day, the delivery's day...). A step falls due `due_days` after the anchor;
past due plus the chain's `escalate_after` working days, the instance escalates to `escalate_to`.

The outbox is derived, never stored state: each run computes it afresh, and an action's id is a hash of its chain,
subject, anchor, step, kind and recipient, so the same action has the same id on every run. When the condition stops
holding, its actions leave the outbox. Mode is dry-run: nothing is sent. Ids only: recipients are tm: ids, or the role
when nobody holds it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from . import app, surfaces
from .flows.common import calibrations, clearer_instructors, is_calibrated_on
from .standards import ROOT, load_schema, load_yaml

CHAINS = Path("standards") / "chains.yaml"
OUTBOX = Path("outbox") / "outbox.json"
RECEIVED = Path("outbox") / "received"
SCHEMA = "tm:contract/outbox@1"
CHANNEL = {"notify": "chat.post", "propose": "calendar.propose", "decide": "signed-page", "act": "claude.act"}
POLICY = {"notify": "auto-after-shadow", "propose": "auto-after-shadow", "decide": "person", "act": "approve-each-call"}
COACH_STEPS = ("tm:step/coach-observe", "tm:step/coach-feedback", "tm:step/practice-task", "tm:step/coach-reobserve")
RISKS = {"session-at-risk": ("not-cleared", "clearance-expires", "recheck-due"),
         "lab-failing": ("lab-failing", "lab-unchecked")}


class InterventionError(Exception):
    pass


@dataclass(frozen=True)
class Instance:
    subject: str
    anchor: date | None
    people: dict[str, tuple[str, ...]] = field(default_factory=dict)  # role -> ids, for roles the subject names
    facts: dict[str, Any] = field(default_factory=dict)  # ids, dates and counts only


@dataclass
class Scope:
    """What every condition reads, gathered once per run."""
    ctx: surfaces.Context
    st: app.State
    week: dict[str, Any]
    board: dict[str, Any]

    @property
    def today(self) -> date:
        return self.ctx.on


def scope(ctx: surfaces.Context, root: Path = ROOT) -> Scope:
    return Scope(ctx, app.load_state(ctx.private, root), surfaces.this_week(ctx), surfaces.coordinator_board(ctx))


# --- the standards file -------------------------------------------------------------------------------------------


def chains_doc(root: Path = ROOT) -> dict[str, Any]:
    return load_yaml(Path(root) / CHAINS) or {}


def problems(doc: Any, root: Path = ROOT) -> list[str]:
    """Schema problems, then cross-references: conditions, buttons and each drafting button's schema file."""
    errors = sorted(Draft202012Validator(load_schema("chains.schema.json", root)).iter_errors(doc),
                    key=lambda e: [str(p) for p in e.absolute_path])
    out = [f"{'/'.join(str(p) for p in e.absolute_path) or 'the file'}: {e.message}" for e in errors]
    if out:
        return out
    buttons = {b["id"]: b for b in doc["buttons"]}
    for chain in doc["chains"]:
        if chain["condition"] not in CONDITIONS and chain["condition"] != "not-connected":
            out.append(f"{chain['id']}: no condition {chain['condition']!r} in interventions.CONDITIONS")
        if chain["condition"] == "not-connected" and not chain.get("waiting_for"):
            out.append(f"{chain['id']}: a chain that is not connected says what it is waiting for")
        out += [f"{chain['id']}/{s['id']}: no button {s['button']!r}" for s in chain["steps"]
                if s.get("button") and s["button"] not in buttons]
    for b in doc["buttons"]:
        servers = set(b["reads"]) | set(b.get("writes") or {})
        out += [f"buttons/{b['id']}: no connector {s!r}" for s in sorted(servers - set(doc["connectors"]))]
        if b["kind"] == "draft" and not (Path(root) / "contracts" / "drafts" / f"{b['id']}.schema.json").is_file():
            out.append(f"buttons/{b['id']}: a drafting button needs contracts/drafts/{b['id']}.schema.json")
        if b["kind"] == "draft" and b.get("writes"):
            out.append(f"buttons/{b['id']}: a drafting button reads only")
        if b["kind"] == "act" and not b.get("writes"):
            out.append(f"buttons/{b['id']}: an acting button names the write tools a person approves")
    return out


# --- conditions: each returns the instances that hold today -------------------------------------------------------


def _coach(scope: Scope, instructor: str) -> tuple[str, ...]:
    row = scope.ctx.con.execute("SELECT coach FROM cycles WHERE instructor = ? AND coach IS NOT NULL ORDER BY number "
                                "DESC LIMIT 1", (instructor,)).fetchone()
    return (row[0],) if row else ()


def _quality_trigger(scope: Scope) -> list[Instance]:
    return [Instance(t["instructor"], date.fromisoformat(t["raised"]),
                     {"instructor": (t["instructor"],), "coach": _coach(scope, t["instructor"])},
                     {"trigger": t["trigger"], "earlier": t.get("earlier", 0)})
            for t in scope.week["decisions"]["quality_triggers"]]


def _risks(kinds: tuple[str, ...]) -> Callable[[Scope], list[Instance]]:
    def condition(scope: Scope) -> list[Instance]:
        ahead = {a["session"]: a for a in scope.week.get("ahead") or []}
        out = []
        for r in scope.week["risks"]:
            session = ahead.get(r["session"])
            if r["kind"] not in kinds or session is None:
                continue
            out.append(Instance(r["session"], date.fromisoformat(session["from"]), {"lead": (session["lead"],)},
                                {"risk": r["kind"], "on": r["on"], **({"lab": r["lab"]} if r.get("lab") else {})}))
        return out
    return condition


def _calibration_lapsed(scope: Scope) -> list[Instance]:
    st, today = scope.st, scope.today
    dates = calibrations(st)
    out = []
    for c in clearer_instructors(st.registrations, st.events, st.people):
        if not is_calibrated_on(st, c, today):
            last = max(dates.get(c) or [], default=None)
            out.append(Instance(c, last, {"observer": (c,)}, {"last_calibrated": last.isoformat() if last else None}))
    return out


def _results(missing: bool) -> Callable[[Scope], list[Instance]]:
    def condition(scope: Scope) -> list[Instance]:
        out = []
        for d in scope.board["deliveries"]:
            on = date.fromisoformat(d["date"])
            holds = (not d.get("received") and on < scope.today) if missing else bool(d.get("unreadable"))
            if holds:
                out.append(Instance(d["session"], on, {"lead": (d["lead"],)},
                                    {"expected": d.get("expected"), "received": d.get("received") or 0,
                                     "unreadable": d.get("unreadable") or 0}))
        return out
    return condition


def _source_stale(scope: Scope) -> list[Instance]:
    return [Instance(s.source.id, s.last.date() if s.last else None, {},
                     {"state": s.state, "owner_role": s.source.owner, "days_late": s.days_late})
            for s in scope.ctx.freshness if s.state in ("stale", "never")]


def _audition_form_overdue(scope: Scope) -> list[Instance]:
    out = []
    for aid, rec, res, _, decided in surfaces._auditions(scope.ctx):
        folder = scope.ctx.private / "auditions" / aid
        waiting = tuple(o for o in rec.get("observers") or []
                        if not (folder / f"score--{o.split('/')[-1]}.yaml").exists())
        if rec.get("assigned") and waiting and res is None and not decided:
            out.append(Instance(aid, date.fromisoformat(str(rec["assigned"])), {"observer": waiting},
                                {"forms_in": len(rec["observers"]) - len(waiting)}))
    return out


def _due_steps(steps: tuple[str, ...], overdue_only: bool, role: str) -> Callable[[Scope], list[Instance]]:
    def condition(scope: Scope) -> list[Instance]:
        out = []
        for d in app.due_steps(scope.st, scope.today):
            if d.step not in steps or (overdue_only and not d.overdue):
                continue
            info = scope.st.subjects.get(d.subject) or {}
            instructor = d.subject if d.subject.startswith("tm:instructor/") else info.get("instructor")
            people = {"instructor": (instructor,) if instructor else ()}
            if role == "coach":
                people["coach"] = (info["coach"],) if info.get("coach") else _coach(scope, instructor or "")
            out.append(Instance(d.subject, d.due, people, {"step": d.step}))
        return out
    return condition


def _cpd_not_logged(scope: Scope) -> list[Instance]:
    if scope.today.day < 10:  # the month's activity is asked for from the 10th (as the simulator does)
        return []
    tenth = scope.today.replace(day=10)
    return [Instance(i.subject, tenth, i.people, i.facts)
            for i in _due_steps(("tm:step/log-activity",), False, "instructor")(scope)]


CONDITIONS: dict[str, Callable[[Scope], list[Instance]]] = {
    "quality-trigger": _quality_trigger,
    "session-at-risk": _risks(RISKS["session-at-risk"]),
    "calibration-lapsed": _calibration_lapsed,
    "lab-failing": _risks(RISKS["lab-failing"]),
    "results-missing": _results(missing=True),
    "results-unreadable": _results(missing=False),
    "source-stale": _source_stale,
    "audition-form-overdue": _audition_form_overdue,
    "coaching-step-overdue": _due_steps(COACH_STEPS, True, "coach"),
    "cpd-not-logged": _cpd_not_logged,
    "appeal-open": _due_steps(("tm:step/appeal-decision",), False, "instructor"),
}


# --- the outbox ---------------------------------------------------------------------------------------------------


def _id(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def add_working_days(day: date, n: int) -> date:
    while n > 0:
        day += timedelta(days=1)
        n -= day.weekday() < 5
    return day


def _people_with(st: app.State, role: str) -> tuple[str, ...]:
    return tuple(sorted(p["person"] for p in st.people if role in p.get("roles", [])))


def _recipients(scope: Scope, inst: Instance, role: str) -> tuple[str | None, ...]:
    if role == "owner":
        role = inst.facts.get("owner_role", role)
    found = inst.people.get(role) if role in inst.people else _people_with(scope.st, role)
    return tuple(found) or (None,)


def build(scope: Scope, root: Path = ROOT) -> dict[str, Any]:
    """Every action the chains would send now, ordered by state, due day and chain."""
    doc = chains_doc(root)
    buttons = {b["id"]: b for b in doc["buttons"]}
    today, actions, waiting = scope.today, [], []
    for chain in doc["chains"]:
        if chain["condition"] == "not-connected":
            waiting.append({"chain": chain["id"], "title": chain["title"], "waiting_for": chain["waiting_for"]})
            continue
        for inst in CONDITIONS[chain["condition"]](scope):
            instance = _id(chain["id"], inst.subject, inst.anchor)
            anchor = inst.anchor.isoformat() if inst.anchor else None
            first_due, produced = None, 0
            for step in chain["steps"]:
                due = inst.anchor + timedelta(days=step["due_days"]) if inst.anchor else None
                if due is not None and due > today:
                    continue
                first_due = min(filter(None, (first_due, due)), default=None)
                produced += 1
                for role in step["to"]:
                    found = _recipients(scope, inst, role)
                    # A message reaches everyone in the role; a step one person acts on goes to its first holder,
                    # so two coordinators never open two tickets for one delivery.
                    for to in found[:1] if step["kind"] in ("act", "decide") else found:
                        action = {"action_id": _id(instance, step["id"], step["kind"], to or role),
                                  "chain": chain["id"], "instance": instance, "step": step["id"], "kind": step["kind"],
                                  "channel": CHANNEL[step["kind"]], "role": role, "to": to, "subject": inst.subject,
                                  "anchor": anchor, "due": due.isoformat() if due else None,
                                  "state": "overdue" if due is not None and due < today else "due",
                                  "policy": POLICY[step["kind"]], "facts": inst.facts}
                        if step.get("button") and step["button"] in buttons:
                            action["button"] = step["button"]
                        actions.append(action)
            after = chain.get("escalate_after")
            if after is not None and produced:
                # Past the first step's due day by `after` working days; with no anchor (a source that never
                # reported) only an at-once chain escalates, since the wait cannot be counted.
                start = first_due or today
                when = add_working_days(start, after)
                if when <= today and (first_due is not None or after == 0):
                    for to in _recipients(scope, inst, chain["escalate_to"]):
                        actions.append({"action_id": _id(instance, "escalate", to or chain["escalate_to"]),
                                        "chain": chain["id"], "instance": instance, "step": "escalate",
                                        "kind": "escalate", "channel": "chat.post", "role": chain["escalate_to"],
                                        "to": to, "subject": inst.subject, "anchor": anchor,
                                        "due": when.isoformat(), "state": "escalated", "policy": "auto-after-shadow",
                                        "facts": inst.facts})
    order = {"escalated": 0, "overdue": 1, "due": 2}
    actions.sort(key=lambda a: (order[a["state"]], a["due"] or "", a["chain"], a["subject"], a["step"], a["role"]))
    return {"schema": SCHEMA, "mode": doc.get("mode", "dry-run"), "as_of": scope.ctx.now.isoformat(),
            "actions": actions, "waiting": waiting}


def received(private: Path | str) -> dict[str, list[dict[str, Any]]]:
    """Drafts, session records and commands kept from the inbox, by action id (feeds.py)."""
    out: dict[str, list[dict[str, Any]]] = {}
    base = Path(private) / RECEIVED
    for path in sorted(base.glob("*/*.json")) if base.is_dir() else []:
        doc = json.loads(path.read_text(encoding="utf-8"))
        out.setdefault(doc.get("action_id", ""), []).append(doc)
    return out


def write(private: Path | str, outbox: dict[str, Any]) -> Path:
    """outbox/outbox.json, written only when it changed."""
    from .util import write_if_changed

    path = Path(private) / OUTBOX
    write_if_changed(path, (json.dumps(outbox, indent=1, sort_keys=True) + "\n").encode("utf-8"))
    return path
