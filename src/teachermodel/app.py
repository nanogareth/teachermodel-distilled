"""Orchestration: the store layout, the commands behind the CLI, and every file read or write.

`cli.py` stays thin and calls the `do_*` functions here. Nothing in this module decides anything the
pure modules (workflow, signoff, bridge, setup, rules) decide: it loads their inputs from the private
store (decision 0006), calls them, and writes what they return. No model is involved.

Store layout under the private dir:
    events/events.jsonl            append-only log (references only, decision 0003)
    identities/people.yaml         people who act, with roles          (names and emails)
    identities/roster.yaml         instructor identities, from the roster import (names and emails)
    settings.yaml                  deployment settings (tm:contract/settings@1)
    generated/                     auto step outputs (requests, ROPA, notice text and drafts, gap list)
    pages/                         sign-off pages (`<stem>.html`) and their input sidecars (`<stem>.input.json`,
                                   a written record only: ingest re-derives the inputs from the current state)
    plans/                         read plans `<created>.json`, `latest.json`, `latest.sha256`
    receipts/                      driver receipts (named by their run_at, UTC)
    signoffs/                      accepted sign-off documents (full, with free text)
    imports/                       roster files as received

Spec: docs/specs/2026-10-24-workflow-automation-design.md sections 4 to 7.
"""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import bridge, config, events, privacy, setup, signoff, staffing, workflow
from . import roster as roster_module
from . import pages as pagegen
from .flows import AUTO_STEPS, PAGE_SPECS, SIGNOFF_HOOKS, content_reasons
from .flows.coaching import derive_cycles
from .flows.hooks import AutoStep
from .flows.common import PEOPLE, PageProblem, State, clearer_instructors, current_level  # noqa: F401 - current_level is part of app's surface
from .flows.onboarding import level_change_id  # noqa: F401 - re-exported: the id of a level change
from .standards import ROOT, load_standards, load_yaml, validate
from .workflow import PROGRAMME, Due
from .util import slug as _slug

QUEUE_SCHEMA = "tm:contract/queue@1"
RECEIPT_SCHEMA = "tm:contract/receipt@1"
SIGNOFF_SCHEMA = "tm:contract/signoff@1"
EVENT_LOG = "events/events.jsonl"
MAILBOX_READ = "mailbox_read"  # result of the `check` event that records an ingested sign-off mailbox read
LOOKBACK = timedelta(days=2)  # the next mailbox search starts this long before the last good read
DEFAULT_DRIVERS = ("connector", "graph")


class AppError(Exception):
    """A command refused its input; the message says what to fix."""


@dataclass
class Report:
    """What a command prints: detail lines, then one summary line."""

    lines: list[str] = field(default_factory=list)
    summary: str = ""
    ok: bool = True

    def all_lines(self) -> list[str]:
        return [*self.lines, self.summary]


# --- state ---------------------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _compact(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_events(private: Path) -> list[dict[str, Any]]:
    path = private / EVENT_LOG
    return list(events.read(path)) if path.is_file() else []


def load_state(private_dir: Path | str, root: Path = ROOT) -> State:
    """Everything the engine needs, read from the store. Raises ConfigError or SetupError when a file is
    missing or invalid, and AppError when the identity sources clash."""
    private = Path(private_dir)
    log = read_events(private)
    standards = load_standards(root)
    wf = standards["workflows"]
    roster_path = private / setup.IDENTITIES
    roster = load_yaml(roster_path) if roster_path.is_file() else None
    people = config.people(private)
    regs: dict[str, dict[str, Any]] = {}
    for e in log:
        if e["kind"] == "registration":
            regs[e["subject_uri"]] = e["payload"]
    try:
        # instructors at level clearer hold the clearer role (decision 0012)
        ids = signoff.identities(people, roster, clearer_instructors(regs, log, people))
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    try:
        base_codes = privacy.base_codes(root)  # the jurisdictions the base profile covers; the others are overlays
    except privacy.PrivacyError as exc:
        raise AppError(str(exc)) from exc
    settings = setup.load_settings(private)
    return State(
        private=private,
        root=root,
        events=log,
        standards=standards,
        workflows=wf,
        step_defs={st["id"]: st for w in wf["workflows"] for st in w["steps"]},
        subjects=derive_cycles(workflow.subjects(log, base_codes, settings["notice_version"]), log,
                               standards["rules"]["coaching"]),
        registrations=regs,
        people=people,
        roster=roster,
        identities=ids,
        settings=settings,
        base_codes=tuple(base_codes),
    )


def advance_state(st: State, new: Iterable[dict[str, Any]]) -> State:
    """The state after `new` events were appended to the log, derived from `st` in memory: nothing is read from the store.

    The events, the subjects they open or change, the registrations and the identities (a level change makes a clearer) are
    re-derived from the extended log; the people, roster, settings and standards are the ones `st` already holds, and the
    answers cached on `st` (page specs, current inputs) are not carried over: they were derived from the old events."""
    log = [*st.events, *new]
    regs = dict(st.registrations)
    for e in new:
        if e["kind"] == "registration":
            regs[e["subject_uri"]] = e["payload"]
    try:
        ids = signoff.identities(st.people, st.roster, clearer_instructors(regs, log, st.people))
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    return replace(st, events=log, registrations=regs, identities=ids, cache={},
                   subjects=derive_cycles(workflow.subjects(log, st.base_codes, st.settings["notice_version"]), log,
                                          st.standards["rules"]["coaching"]))


def append_new(private: Path, new: Iterable[dict[str, Any]], seen: set[str] | None = None) -> list[dict[str, Any]]:
    """Append events whose id is not already in the log. Returns those appended.

    `seen` is the set of ids the caller already knows are in the log (a loaded state's `index.ids`); it is brought up to date
    in place and the log is not read. Without it the ids are read from the log."""
    path = private / EVENT_LOG
    if seen is None:
        seen = {e["id"] for e in read_events(private)}
    added = []
    for e in new:
        if e["id"] in seen:
            continue
        events.append(path, e)
        seen.add(e["id"])
        added.append(e)
    return added


def due_steps(st: State, today: date) -> list[Due]:
    """The open steps for `today`, worked out once per State and day (run, plan, pages and next of a tick share a state)."""
    memo = st.cache.setdefault("due_steps", {})
    if today not in memo:
        memo[today] = workflow.next_steps(st.workflows, st.events, st.subjects, today, _current_input_reader(st), st.index)
    return memo[today]


def _page_specs(st: State, step: str, subject: str) -> list[dict[str, Any]] | None:
    """The page specs the builder of `step` builds for `subject`, built once per State: a tick asks for the same
    (step, subject) from the queue, the pages, the plan and the ingest. None when the step has no builder. A builder's
    error is kept and raised again, so every caller sees what the first one saw."""
    memo = st.cache.setdefault("page_specs", {})
    key = (step, subject)
    if key not in memo:
        builder = PAGE_SPECS.get(step)
        if builder is None:
            memo[key] = None
        else:
            try:
                memo[key] = builder(st, subject)
            except Exception as exc:  # noqa: BLE001 - kept and raised again below, not swallowed
                memo[key] = exc
    found = memo[key]
    if isinstance(found, Exception):
        raise found
    return found


# --- next ----------------------------------------------------------------------------------------


def queue_document(dues: Iterable[Due], now: datetime) -> dict[str, Any]:
    """tm:contract/queue@1: tm URIs, step ids, roles and dates; never a name."""
    return {
        "schema": QUEUE_SCHEMA,
        "generated_at": now.isoformat(timespec="seconds"),
        "items": [
            {
                "step": d.step,
                "workflow": d.workflow,
                "subject": d.subject,
                "role": d.role,
                "type": d.type,
                "due": d.due.isoformat() if d.due else None,
                "overdue": d.overdue,
                "page": d.page,
            }
            for d in dues
        ],
    }


def do_next(
    private_dir: Path | str, *, role: str | None = None, json_path: Path | None = None,
    now: datetime | None = None, root: Path = ROOT,
) -> Report:
    now = now or _utcnow()
    if role is not None and role not in config.ROLES:
        raise AppError(f"unknown role {role!r}; known roles are {list(config.ROLES)}")
    return _next(load_state(private_dir, root), now, role=role, json_path=json_path)


def _next(st: State, now: datetime, *, role: str | None = None, json_path: Path | None = None) -> Report:
    dues = [d for d in due_steps(st, now.date()) if role is None or d.role == role]
    rep = Report()
    for d in dues:
        flag = "  OVERDUE" if d.overdue else ""
        rep.lines.append(f"{d.due.isoformat() if d.due else '-':<10}  {d.step}  {d.subject}  {d.role}  {d.type}{flag}")
    doc = queue_document(dues, now)
    errors = validate(doc, "queue.schema.json", st.root)
    if errors:
        raise AppError("queue document invalid: " + "; ".join(errors))
    if json_path is not None:
        json_path = Path(json_path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_bytes((json.dumps(doc, indent=2) + "\n").encode("utf-8"))
    overdue = sum(1 for d in dues if d.overdue)
    rep.summary = f"next: {len(dues)} due ({overdue} overdue)"
    return rep


# --- import-roster -------------------------------------------------------------------------------


def do_import_roster(
    private_dir: Path | str, path: Path | str, *, now: datetime | None = None, root: Path = ROOT
) -> Report:
    now = now or _utcnow()
    private, src = Path(private_dir), Path(path)
    if not src.is_file():
        raise AppError(f"{src}: no such roster file")
    # No real data before the base workflow is complete (0006, Before real data): the engine's own `needs` of the
    # roster-import step decide, so the command and `next` can never disagree. setup.import_roster checks the facts again.
    st = load_state(private, root)
    missing = workflow.unmet_needs(st.workflows, st.events, st.subjects, setup.STEP_ROSTER_IMPORT, PROGRAMME,
                                   _current_input_reader(st), st.index)
    if missing:
        raise AppError("import-roster refused: these steps are not complete yet: " + ", ".join(missing))
    # A pilot store refuses real instructors before the file is copied in (decision 0016).
    try:
        setup.pilot_check(private, st.settings, roster_module.load(src))
    except setup.SetupError as exc:
        raise AppError(str(exc)) from exc
    imports = private / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    copy = imports / f"roster-{_compact(now)}{src.suffix or '.yaml'}"
    shutil.copy2(src, copy)
    new = setup.import_roster(private, copy, st.events, now, root=root, settings=st.settings,
                              retention_path=setup.retention_file(private, st.settings, root))
    added = append_new(private, new, set(st.index.ids))
    return Report(summary=f"import-roster: {len(added)} event(s) appended; copy kept in imports/")


# --- run -----------------------------------------------------------------------------------------


def _attempt_key(step: str, subject: str) -> str:
    """A step runs once per call; a step registered per subject, once per subject."""
    auto = AUTO_STEPS.get(step)
    return step if auto is None or auto.per == "programme" else f"{step}|{subject}"


def do_run(private_dir: Path | str, *, now: datetime | None = None, root: Path = ROOT) -> Report:
    """Execute due auto steps until no new one falls due. A step runs at most once per call.

    The store is read once. Each round runs on the state the previous round left (`advance_state`), and events are
    appended with the ids already known, so nothing is read from disk again however many rounds the chain takes."""
    return _run(load_state(private_dir, root), now or _utcnow())[0]


def _run(st: State, now: datetime) -> tuple[Report, State]:
    """`do_run` on a loaded state. Returns the report and the state after everything the run appended (the refreshed
    steps' events included), derived in memory, so `do_tick` can go on with it instead of reading the store again."""
    rep = Report()
    attempted: set[str] = set()
    executed = appended = blocked = waiting = 0
    seen = set(st.index.ids)
    for _ in range(len(config.ROLES) * 4):  # a bound; chains of auto steps are short
        todo = [d for d in due_steps(st, now.date())
                if d.type == "auto" and _attempt_key(d.step, d.subject) not in attempted]
        if not todo:
            break
        fresh: list[dict[str, Any]] = []
        for d in todo:
            key = _attempt_key(d.step, d.subject)
            if key in attempted:
                continue
            attempted.add(key)
            if d.step == setup.STEP_ROSTER_IMPORT:
                rep.lines.append(f"waiting: run teachermodel import-roster <path> ({d.step})")
                waiting += 1
                continue
            auto = AUTO_STEPS.get(d.step)
            if auto is None:
                rep.lines.append(f"no runner for {d.step}")
                continue
            per_programme = auto.per == "programme"
            new = append_new(st.private, auto.run(st, PROGRAMME if per_programme else d.subject, now), seen)
            fresh.extend(new)
            label = d.step if per_programme else f"{d.step} {d.subject}"
            executed += 1
            appended += len(new)
            was_blocked = any(e["kind"] == "check" and e["payload"].get("result") == "blocked" for e in new)
            blocked += was_blocked
            rep.lines.append(f"{label}: {len(new)} event(s) appended" + (" (blocked)" if was_blocked else ""))
        st = advance_state(st, fresh)
    refreshed, fresh = _refresh(st, now, attempted, rep, seen)
    appended += refreshed
    if fresh:
        st = advance_state(st, fresh)
    rep.summary = f"run: {executed} auto step(s) executed, {appended} event(s) appended, {blocked} blocked, {waiting} waiting"
    return rep, st


def _refresh(st: State, now: datetime, attempted: set[str], rep: Report, seen: set[str]) -> tuple[int, list[dict[str, Any]]]:
    """Run the registered `refresh` auto steps again when they are done but their needs are still met. Their outputs
    derive from files an edit can change (purposes, the profile, retention, the approved notice text); a run whose
    output is unchanged appends nothing. A step whose needs lapsed (the profile was edited, so the retention approval
    reopened) waits until they are met again. A `per="programme"` step runs once, when any subject of its workflow
    kind qualifies (notice-drafts: any instructor); a per-subject step runs for each qualifying subject, in URI order.
    `st` is the state after the main rounds and `seen` the ids of its log (see `do_run`)."""
    reader = _current_input_reader(st)
    appended = 0
    fresh: list[dict[str, Any]] = []

    def met(step: str, subject: str) -> bool:
        return workflow.needs_met(st.workflows, st.events, st.subjects, step, subject, reader, st.index)

    once: list[tuple[AutoStep, list[str]]] = []
    each: list[tuple[str, int, AutoStep]] = []
    for index, auto in enumerate(a for a in AUTO_STEPS.values() if a.refresh):
        step_def = st.step_defs.get(auto.step)
        if step_def is None:
            continue
        kind = step_def["subject"]
        candidates = [PROGRAMME] if kind == "programme" else sorted(u for u, i in st.subjects.items() if i["kind"] == kind)
        if auto.per == "programme":
            once.append((auto, candidates))
        else:
            each.extend((u, index, auto) for u in candidates)
    for auto, candidates in once:
        if auto.step in attempted or not any(met(auto.step, c) for c in candidates):
            continue
        new = append_new(st.private, auto.run(st, PROGRAMME, now), seen)
        if new:
            rep.lines.append(f"{auto.step}: refreshed, {len(new)} event(s) appended")
            appended += len(new)
            fresh += new
    for uri, _, auto in sorted(each, key=lambda t: t[:2]):
        if _attempt_key(auto.step, uri) in attempted or not met(auto.step, uri):
            continue
        new = append_new(st.private, auto.run(st, uri, now), seen)
        if new:
            rep.lines.append(f"{auto.step} {uri}: refreshed, {len(new)} event(s) appended")
            appended += len(new)
            fresh += new
    return appended, fresh


# --- pages ---------------------------------------------------------------------------------------


def page_stem(step: str, subject: str, signer: str) -> str:
    # lowercase: a sample's URI carries its quarter (`2026Q4`, subject@2), and a page file name is lowercase only (pages._NAME)
    return f"{_slug(step)}--{_slug(subject)}--{_slug(signer)}".lower()


def do_pages(private_dir: Path | str, *, now: datetime | None = None, root: Path = ROOT) -> Report:
    return _pages(load_state(private_dir, root), now or _utcnow())


def _pages(st: State, now: datetime) -> Report:
    channel = {"kind": "mail", "to": st.settings["mailbox"]}
    rep = Report()
    written = unchanged = 0
    problems = 0
    for d in due_steps(st, now.date()):
        if d.type != "human":
            continue
        if d.step not in PAGE_SPECS:
            rep.lines.append(f"problem: no page builder for {d.step}")
            problems += 1
            continue
        try:
            specs = _page_specs(st, d.step, d.subject) or []
        except PageProblem as exc:
            rep.lines.append(f"problem: {d.step} {d.subject}: {exc}")
            problems += 1
            continue
        for spec in specs:
            page_html, _ = pagegen.render(**spec, channel=channel, root=st.root)
            *_, changed = pagegen.write_page_if_changed(
                st.private / "pages", page_stem(spec["step"], spec["subject_uri"], spec["signer"]), page_html, spec["inputs"])
            written += changed
            unchanged += not changed
    rep.summary = f"pages: {written} written, {unchanged} unchanged, {problems} problem(s)"
    return rep


# --- plan ----------------------------------------------------------------------------------------


def mailbox_read_id(plan_digest: str) -> str:
    """Deterministic id of the event recording that a receipt for this plan read the mailbox."""
    return signoff.input_sha256({"mailbox_read_for_plan": plan_digest})[:32]


def last_mailbox_read(log: Iterable[dict[str, Any]]) -> datetime | None:
    """The latest `run_at` of an ingested receipt whose sign-off mailbox read came back ok."""
    latest: datetime | None = None
    for e in log:
        if e["kind"] != "check" or e["payload"].get("result") != MAILBOX_READ:
            continue
        try:
            t = datetime.fromisoformat(str(e["payload"]["run_at"]))
        except (KeyError, ValueError):
            continue
        if t.tzinfo is not None and (latest is None or t > latest):
            latest = t
    return latest


def plan_settings(st: State, today: date) -> dict[str, str]:
    """The mailbox search starts LOOKBACK before the last ok read; before any read, a day before the first event."""
    read = last_mailbox_read(st.events)
    if read is not None:
        since = (read.astimezone(timezone.utc) - LOOKBACK).date()
    else:
        first = min((e["at"][:10] for e in st.events), default=None)
        since = (date.fromisoformat(first) - timedelta(days=1)) if first else today
    return {
        "library": st.settings["library"],
        "mailbox": st.settings["mailbox"],
        "signoff_tag": bridge.SIGNOFF_SEARCH,
        "notice_tag": f"[tm-notice {st.settings['notice_version']}]",
        "since": since.isoformat(),
    }


def do_plan(private_dir: Path | str, *, now: datetime | None = None, root: Path = ROOT) -> Report:
    return _plan(load_state(private_dir, root), now or _utcnow())


def _plan(st: State, now: datetime) -> Report:
    recipients = {
        i["instructor"]: i["identity"]["email"] for i in (st.roster or {}).get("instructors", [])
    }
    variants = {uri: info["notice_variant"] for uri, info in st.subjects.items() if "notice_variant" in info}
    try:
        plan, problems = bridge.build_plan(
            due_steps(st, now.date()), settings=plan_settings(st, now.date()), recipients=recipients,
            created=now.isoformat(timespec="seconds"), variants=variants,
        )
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    errors = validate(plan, "plan.schema.json", st.root)
    if errors:
        raise AppError("plan invalid: " + "; ".join(errors))
    digest = bridge.plan_sha256(plan)
    plans = st.private / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(plan, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    (plans / f"{_compact(now)}.json").write_bytes(data)
    (plans / "latest.json").write_bytes(data)
    (plans / "latest.sha256").write_bytes((digest + "\n").encode("ascii"))
    rep = Report(lines=[f"problem: {p}" for p in problems])
    rep.summary = f"plan: {len(plan['ops'])} op(s), {len(problems)} problem(s), sha256 {digest[:12]}"
    return rep


# --- ingest --------------------------------------------------------------------------------------


def _matching_plan(private: Path, digest: str) -> dict[str, Any] | None:
    for p in sorted((private / "plans").glob("*.json")):
        if p.name == "latest.json":
            continue
        try:
            plan = json.loads(p.read_text(encoding="utf-8"))
            if bridge.plan_sha256(plan) == digest:
                return plan
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return None


def _specs_or_none(st: State, step: str, subject: str) -> list[dict[str, Any]] | None:
    """`_page_specs`, or None when the builder cannot build a page for (step, subject)."""
    try:
        return _page_specs(st, step, subject)
    except (PageProblem, setup.SetupError, KeyError, TypeError, ValueError, OSError):
        return None


def _current_input_reader(st: State) -> Callable[[str, str], str | None]:
    """The hash of the inputs a page for (step, subject) would show right now, re-derived from the current
    state by the same builder `pages` uses. The `pages/*.input.json` sidecars are a written record only and
    are never read here. None (so the sign-off is rejected) when there is no builder, the builder cannot
    build a page, or the signers' pages would disagree about the inputs."""

    memo = st.cache.setdefault("current_input", {})

    def current(step: str, subject: str) -> str | None:
        key = (step, subject)
        if key not in memo:
            specs = _specs_or_none(st, step, subject)
            hashes = {signoff.input_sha256(spec["inputs"]) for spec in specs or ()}
            memo[key] = hashes.pop() if len(hashes) == 1 else None
        return memo[key]

    return current


def _opened_on_reader(st: State) -> Callable[[str, str], date | None]:
    """The UTC day a step opened for a subject, from the log (`workflow.opened_on`): the `subject` event's day for a child
    subject, else the day the last of the step's needs was met. A sign-off cannot be dated before it. None when unknown."""

    memo = st.cache.setdefault("opened_on", {})
    reader = _current_input_reader(st)

    def opened(step: str, subject: str) -> date | None:
        key = (step, subject)
        if key not in memo:
            memo[key] = workflow.opened_on(st.workflows, st.events, st.subjects, step, subject, reader, st.index)
        return memo[key]

    return opened


def _current_rows_reader(st: State) -> Callable[[str, str], set[str] | None]:
    """The row keys a batch page for (step, subject) would show right now, from the same builder as
    `_current_input_reader`. None when unknown, which rejects the sign-off."""

    memo = st.cache.setdefault("current_rows", {})

    def rows(step: str, subject: str) -> set[str] | None:
        key = (step, subject)
        if key not in memo:
            specs = _specs_or_none(st, step, subject)
            keys = {frozenset(r["key"] for r in spec["inputs"].get("rows", [])) for spec in specs or ()}
            memo[key] = set(keys.pop()) if specs is not None and len(keys) == 1 else None
        return memo[key]

    return rows


# --- revoking a bound approval (decision 0019) -------------------------------------------------------------------

REVOKE_PREFIX = "revoke--"  # a revoke page's file stem: revoke--<step>--<subject>--<signer>
REVOKE_FIELDS = [{"name": "reason", "label": "Reason", "kind": "textarea", "required": True,
                  "help": "Why this approval no longer stands, in a sentence or two. The sign-off file keeps it in the "
                          "private store; the log holds a hash."}]


def revocable_step(step_def: dict[str, Any]) -> bool:
    """A step whose approval in force a holder of its role may withdraw: `done_when.revocable` on a bound step with no
    fixed signers, no sign-off hook and no single-decision rule. A hook has already acted on the approval (a clearance,
    an event), so withdrawing the sign-off would not undo it."""
    done = step_def["done_when"]
    return (done.get("revocable") is True and done.get("bind") == "input" and step_def.get("signer") is None
            and step_def["id"] not in SIGNOFF_HOOKS and step_def["id"] not in signoff.SINGLE_DECISION_STEPS)


def revocable_in_force(st: State) -> set[tuple[str, str]]:
    """(step, subject) of every revocable step whose approval is in force now (not a system skip)."""
    reader = _current_input_reader(st)
    out: set[tuple[str, str]] = set()
    for step_id, d in st.step_defs.items():
        if not revocable_step(d):
            continue
        for uri, info in st.subjects.items():
            if info["kind"] == d["subject"] and workflow.approval_in_force(d, uri, st.index, reader, info) is not None:
                out.add((step_id, uri))
    return out


def do_revoke_page(
    private_dir: Path | str, *, step: str, subject: str = PROGRAMME, now: datetime | None = None, root: Path = ROOT,
) -> Report:
    """Write a revoke page for each holder of the step's role (decision 0019): the same inputs as the approval in force,
    a required reason and the single decision `revoke`. Signed and returned like any sign-off, it reopens the step. The
    system prepares the page; only a person revokes."""
    st = load_state(private_dir, root)
    d = st.step_defs.get(step)
    if d is None:
        raise AppError(f"unknown step {step!r}")
    if not revocable_step(d):
        raise AppError(f"{step} is not revocable: only an approval marked revocable, with no sign-off hook, can be "
                       "withdrawn (decision 0019)")
    if subject not in st.subjects:
        raise AppError(f"unknown subject {subject!r}")
    if (step, subject) not in revocable_in_force(st):
        raise AppError(f"{step} has no approval in force for {subject}; there is nothing to revoke")
    try:
        specs = _page_specs(st, step, subject) or []
    except PageProblem as exc:
        raise AppError(f"{step} {subject}: {exc}") from exc
    channel = {"kind": "mail", "to": st.settings["mailbox"]}
    rep = Report()
    for spec in specs:
        page = {**spec, "template": "revoke", "fields": REVOKE_FIELDS, "title": f"Revoke: {spec['title']}",
                "intro": ("Revoking withdraws the approval in force for exactly the inputs below. The step opens again and "
                          "its approval page comes back on the next tick; nothing it already released is undone. Give the "
                          "reason, then send the sign-off as usual.\n\n" + spec["intro"])}
        page_html, _ = pagegen.render(**page, channel=channel, root=st.root)
        stem = REVOKE_PREFIX + page_stem(step, subject, spec["signer"])
        path, *_ = pagegen.write_page_if_changed(st.private / "pages", stem, page_html, spec["inputs"])
        rep.lines.append(f"page: {path.name} for {spec['signer']}")
    rep.summary = f"revoke-page: {len(specs)} page(s) for {step} {subject}"
    return rep


def _accepted_signers(st: State) -> dict[tuple[str, str], set[str]]:
    """(step, subject) -> the signers with an approving sign-off in the log: a step whose `signer` is named by the subject
    (decision 0012) takes one sign-off from each of them."""
    out: dict[tuple[str, str], set[str]] = {}
    for e in st.events:
        p = e["payload"]
        if e["kind"] == "signoff" and p.get("decision") in workflow.APPROVING and isinstance(p.get("step"), str):
            out.setdefault((p["step"], e["subject_uri"]), set()).add(e["actor"])
    return out


def _write_private(target: Path, document: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def _store_documents(private: Path, docs: list[tuple[str, dict[str, Any]]], *, under: str = "signoffs") -> int:
    """Write private documents under `under`/ (an idempotent overwrite): the sign-off documents under signoffs/, and,
    with `under=""`, what a sign-off hook returns, anywhere in the private dir except events/. Every path is checked
    before the first write. Returns how many were written."""
    unique = dict(docs)
    targets = []
    base = (private / under).resolve()
    log_dir = (private / EVENT_LOG).resolve().parent
    for rel, document in unique.items():
        target = (private / rel).resolve()
        if not target.is_relative_to(base) or target.is_relative_to(log_dir):
            raise AppError(f"refusing to write outside {under or 'the private dir'}/ (or into events/): {rel}")
        targets.append((target, document))
    for target, document in targets:
        _write_private(target, document)
    return len(targets)


def _missing_copies(st: State, applied: bridge.Applied) -> list[tuple[str, dict[str, Any]]]:
    """Stored copies to restore: a sign-off re-read from the mailbox whose id is already in the log but whose
    signoffs/<id>.json is gone. It is restored only if it is the very document that was accepted (same
    subject, signer and payload as the logged event), so a different document under a known id is never stored."""
    logged = {e["payload"]["signoff_id"]: e for e in st.events if e["kind"] == "signoff" and "signoff_id" in e["payload"]}
    out: list[tuple[str, dict[str, Any]]] = []
    for doc in applied.duplicates:
        e = logged.get(doc.get("id"))
        if e is None or validate(doc, "signoff.schema.json", st.root):
            continue
        want = signoff.to_event(doc, "")
        if (want["subject_uri"], want["actor"], want["payload"]) != (e["subject_uri"], e["actor"], e["payload"]):
            continue
        rel = f"signoffs/{doc['id']}.json"
        if not (st.private / rel).is_file():
            out.append((rel, doc))
    return out


def _bound_inputs(st: State, applied: bridge.Applied) -> list[tuple[str, dict[str, Any]]]:
    """For each accepted approving sign-off of a `bind: input` step, the inputs it covered, kept beside the stored
    sign-off as signoffs/<id>.inputs.json. The sign-off document has no inputs of its own; this copy lets the next
    review page show what changed since (the profile diff). The inputs are re-derived by the builder, which ingest
    has just checked against the sign-off's hash."""
    out: list[tuple[str, dict[str, Any]]] = []
    for e in applied.events:
        p = e["payload"]
        step_def = st.step_defs.get(p.get("step", ""))
        if (e["kind"] != "signoff" or p.get("decision") not in workflow.APPROVING or step_def is None
                or step_def["done_when"].get("bind") != "input"):
            continue
        builder = PAGE_SPECS.get(p["step"])
        if builder is None:
            continue
        try:
            inputs = builder(st, e["subject_uri"])[0]["inputs"]
        except (PageProblem, setup.SetupError, KeyError, IndexError, TypeError, ValueError, OSError):
            continue
        if signoff.input_sha256(inputs) == p["input_sha256"]:
            out.append((f"signoffs/{p['signoff_id']}.inputs.json", {
                "step": p["step"], "subject_uri": e["subject_uri"], "input_sha256": p["input_sha256"],
                "inputs": inputs}))
    return out


def _signoff_hooks(
    st: State, applied: bridge.Applied, now: datetime
) -> tuple[list[dict[str, Any]], list[tuple[str, dict[str, Any]]]]:
    """Run the registered `on_signoff` hooks for each accepted approving sign-off in `applied`, in event order. A hook
    sees a State whose events hold the log, the accepted events up to and including its sign-off, and what earlier
    hooks returned. Returns (events, documents) in the order the hooks produced them."""
    stored = {rel: doc for rel, doc in applied.private}
    out: list[dict[str, Any]] = []
    documents: list[tuple[str, dict[str, Any]]] = []
    for n, e in enumerate(applied.events):
        p = e["payload"]
        hooks = SIGNOFF_HOOKS.get(p.get("step", "")) if e["kind"] == "signoff" else None
        if not hooks or p.get("decision") not in workflow.APPROVING:
            continue
        document = stored.get(f"signoffs/{p['signoff_id']}.json")
        if document is None:
            raise AppError(f"no stored document for accepted sign-off {p['signoff_id']}")
        for hook in hooks:
            view = replace(st, events=[*st.events, *applied.events[:n + 1], *out], cache={})
            result = hook(view, e, document, now)
            if not (isinstance(result, tuple) and len(result) == 2):
                raise AppError(f"sign-off hook {hook.__name__} for {p['step']} must return (events, documents)")
            out.extend(result[0])
            documents.extend(result[1])
    return out, documents


def _programme_owner_email(st: State) -> str:
    owners = [r for r in st.people if "programme-owner" in r["roles"]]
    if len(owners) != 1:
        raise AppError(f"{PEOPLE} must list exactly one programme-owner, found {len(owners)}")
    return owners[0]["email"]


def do_graph_read(
    private_dir: Path | str, *, cfg: Any = None, transport: Any = None, now: datetime | None = None,
    tick: bool = False, root: Path = ROOT,
) -> Report:
    """Run the latest plan through the Graph driver (graph.py), write its receipt under receipts/ and ingest it; with
    `tick`, tick after, as the connector skill does. `cfg` defaults to the environment, `transport` to HTTPS. No model
    runs here."""
    from . import graph

    now = (now or _utcnow()).replace(microsecond=0)
    private = Path(private_dir)
    plan_path = private / "plans" / "latest.json"
    if not plan_path.is_file():
        raise AppError("no plan yet: run `teachermodel tick` first")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    st = load_state(private, root)
    owner = _programme_owner_email(st)
    try:
        receipt = graph.run_plan(plan, cfg=cfg or graph.config_from_env(), owner=owner,
                                 transport=transport or graph.urllib_transport, now=now)
    except graph.GraphError as exc:
        raise AppError(str(exc)) from exc
    errors = validate(receipt, "receipt.schema.json", root)
    if errors:
        raise AppError("graph receipt invalid: " + "; ".join(errors))
    path = private / "receipts" / f"{_compact(now)}.json"
    _write_private(path, receipt)
    failed = [r["op_id"] for r in receipt["results"] if r["status"] != "ok"]
    rep = Report(lines=[f"receipt: {path.name}", *[f"problem: op {oid} failed" for oid in failed]])
    ingested = do_ingest(private, path, now=now, root=root)
    rep.lines.append(ingested.summary)
    if tick:
        rep.lines += [r.summary for r in do_tick(private, now=now, root=root)]
    rep.summary = f"graph-read: {len(receipt['results'])} op(s), {len(failed)} failed"
    rep.ok = not failed and ingested.ok
    return rep


def do_ingest(
    private_dir: Path | str, receipt_path: Path | str, *, now: datetime | None = None,
    allowed_drivers: Collection[str] = DEFAULT_DRIVERS, root: Path = ROOT,
) -> Report:
    """Apply a driver receipt. Sign-offs are accepted only inside a receipt, whose sender is verified by the
    driver. `allowed_drivers` is a keyword the CLI does not expose (tests add "fixture")."""
    now = now or _utcnow()
    private, path = Path(private_dir), Path(receipt_path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AppError(f"{path}: not readable as JSON") from exc
    schema = doc.get("schema") if isinstance(doc, dict) else None
    if schema == SIGNOFF_SCHEMA:
        raise AppError("sign-offs arrive only via a receipt (verified sender); refusing a direct sign-off file")
    if schema != RECEIPT_SCHEMA:
        raise AppError(f"{path.name}: not a receipt (schema must be {RECEIPT_SCHEMA})")
    digest = doc.get("plan_sha256")
    plan = _matching_plan(private, digest) if isinstance(digest, str) else None
    if plan is None:
        raise AppError("no plan in plans/ matches the receipt's plan_sha256")

    st = load_state(private, root)
    owner = _programme_owner_email(st)
    st.cache["now"] = now  # the ingest clock, for content checks that bound a sign-off's signed_at (flows/clearance.py)
    open_steps = {(d.step, d.subject) for d in due_steps(st, now.date()) if d.type == "human"}
    seen = {e["payload"]["signoff_id"] for e in st.events if e["kind"] == "signoff" and "signoff_id" in e["payload"]}
    applied = bridge.apply_receipt(
        doc, plan,
        workflows=st.workflows,
        identities=st.identities,
        current_input=_current_input_reader(st),
        current_rows=_current_rows_reader(st),
        subjects=st.subjects,
        registrations=st.registrations,
        open_steps=open_steps,
        seen_ids=seen,
        existing_ids=st.index.ids,
        known_templates={pagegen.template_sha256(t) for t in pagegen.TEMPLATES},
        owner_email=owner,
        notice_version=st.settings["notice_version"],
        now=now,
        allowed_drivers=allowed_drivers,
        content_check=lambda document: content_reasons(st, document),
        accepted_signers=_accepted_signers(st),
        opened_on=_opened_on_reader(st),
        revocable=revocable_in_force(st),
    )
    hook_events, hook_documents = _signoff_hooks(st, applied, now)
    new = [*applied.events, *hook_events]
    # A pilot receipt (pilot-sign, decision 0016) did not read the real sign-off mailbox, so it must not move the
    # start of the connector's next search past real sign-offs it has not seen.
    if applied.mailbox_read_at is not None and doc.get("driver") != "pilot":
        new.append(events.make_event(
            "check", PROGRAMME, bridge.SYSTEM_ACTOR,
            {"step": None, "result": MAILBOX_READ, "run_at": applied.mailbox_read_at.isoformat(timespec="seconds"),
             "plan_sha256": digest},
            id=mailbox_read_id(digest), at=now.isoformat(timespec="seconds")))
    documents = _store_documents(private, [*applied.private, *_missing_copies(st, applied), *_bound_inputs(st, applied)])
    _store_documents(private, hook_documents, under="")
    added = append_new(private, new, set(st.index.ids))  # after the documents: a failed write leaves the log untouched
    kinds = Counter(e["kind"] for e in added)
    detail = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none"
    rep = Report(lines=[f"rejected: {r}" for r in applied.rejected])
    rep.summary = (f"ingest: {len(added)} event(s) appended ({detail}), {len(applied.rejected)} rejected, "
                   f"{documents} sign-off document(s) stored")
    rep.ok = bool(added) or not applied.rejected  # a receipt refused whole produces no events
    return rep


# --- staffing-check ------------------------------------------------------------------------------


def do_staffing_check(private_dir: Path | str, request: dict[str, Any], *, root: Path = ROOT,
                      detail: bool = False) -> dict[str, Any]:
    """The staffing-check@2 response for `request` over the store's log (`staffing.check`). Reads the log and the
    rules only: no people list or settings are needed, so it answers on a store that has nothing else yet. The reasons are
    the outbound ones unless `detail` (decision 0005). Raises AppError when the request does not fit the contract."""
    try:
        return staffing.check(read_events(Path(private_dir)), request, load_standards(root)["rules"], root, detail=detail)
    except staffing.RequestError as exc:
        raise AppError(str(exc)) from exc


# --- tick ----------------------------------------------------------------------------------------


def do_tick(private_dir: Path | str, *, now: datetime | None = None, root: Path = ROOT) -> list[Report]:
    """run, plan, pages, next, in that order, on one loaded state: the store is read once, `run` hands the state it ended
    on (derived in memory from what it appended) to the other three, which share its page specs and input hashes."""
    now = now or _utcnow()
    run_report, st = _run(load_state(private_dir, root), now)
    return [run_report, _plan(st, now), _pages(st, now), _next(st, now)]
