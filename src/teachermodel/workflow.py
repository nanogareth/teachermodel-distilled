"""Workflow engine: which steps are open, for whom, and when they fall due.

Pure and deterministic like rules.py: it takes the loaded workflows document and the event list, does
no I/O and calls no model. Spec: docs/specs/2026-10-24-workflow-automation-design.md section 4.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from . import due as due_registry

PROGRAMME = "tm:programme/teachermodel"
SYSTEM_ACTOR = "tm:system/teachermodel"  # the actor of every event the tooling itself writes
ROSTER_TYPES = frozenset({"sme-engineer", "professional", "contractor", "partner"})
# Subjects opened by a `subject` event (event@3, decision 0011; cycle, sample, bench and override from subject@2,
# decision 0014). Each carries `attrs.instructor`, which is how a need on an instructor-subject step resolves for them.
CHILD_KINDS = ("candidate", "assignment", "exercise", "cycle", "sample", "bench", "override", "appeal", "recalibration")
APPROVING = ("approve", "record")  # a sign-off with another decision never completes a step
REVOKE = "revoke"  # withdraws the approval in force of a `revocable` bound step (decision 0019)


@dataclass(frozen=True)
class Due:
    step: str  # step id
    workflow: str  # workflow id
    subject: str  # subject uri
    role: str
    due: date | None
    overdue: bool
    page: str | None
    type: str


def _day(event: dict[str, Any]) -> date:
    return date.fromisoformat(event["at"][:10])


class EventIndex:
    """The events of a log by `(kind, subject_uri)` and by `subject_uri`, each in log order, and the set of event ids.

    Built once from a list and extended in place (`add`), so the engine asks "the signoffs of this subject" without scanning
    the whole log for every (step, subject). It holds the list it was built from (`events`, not copied) and changes nothing
    in it; whoever extends the index appends to the list as well."""

    __slots__ = ("events", "ids", "_by_kind_subject", "_by_subject")

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = events
        self.ids: set[str] = set()
        self._by_kind_subject: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._by_subject: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            self._index(e)

    def _index(self, e: dict[str, Any]) -> None:
        self.ids.add(e["id"])
        self._by_kind_subject.setdefault((e["kind"], e["subject_uri"]), []).append(e)
        self._by_subject.setdefault(e["subject_uri"], []).append(e)

    def add(self, e: dict[str, Any]) -> None:
        """Append `e` to the index and to the list it was built from."""
        self.events.append(e)
        self._index(e)

    def of(self, kind: str, subject: str) -> list[dict[str, Any]]:
        """The events of `kind` about `subject`, in log order. Not to be changed."""
        return self._by_kind_subject.get((kind, subject), [])

    def for_subject(self, subject: str) -> list[dict[str, Any]]:
        """Every event about `subject`, in log order. Not to be changed."""
        return self._by_subject.get(subject, [])


def _idx(events: "Iterable[dict[str, Any]] | EventIndex") -> EventIndex:
    return events if isinstance(events, EventIndex) else EventIndex(events if isinstance(events, list) else list(events))


CurrentInput = Callable[[str, str], "str | None"]  # (step id, subject uri) -> hash of the inputs a page shows now


def jurisdiction_uri(code: str) -> str:
    """`US-CA` -> `tm:jurisdiction/us-ca`."""
    return f"tm:jurisdiction/{code.lower()}"


def candidate_uri(instructor: str, unit: str, mode: str) -> str:
    """`tm:instructor/k7m2q`, `sl:unit/example-agent-loop@1`, `remote` -> `tm:candidate/k7m2q--example-agent-loop-1--remote`."""
    slug, version = unit.split("/", 1)[1].rsplit("@", 1)
    return f"tm:candidate/{instructor.split('/', 1)[1]}--{slug}-{version}--{mode}"


def notice_variant(version: str, code: str, base_codes: Collection[str]) -> str:
    """The notice an instructor of `code` is owed: the base notice (`2026-11`) for a base code, else the
    jurisdiction's variant (`2026-11-us-ca`)."""
    if code.upper() in {c.upper() for c in base_codes}:
        return version
    return f"{version}-{code.lower()}"


def subjects(
    events: Iterable[dict[str, Any]], base_codes: Collection[str], notice_version: str | None = None
) -> dict[str, dict[str, Any]]:
    """The programme singleton, every instructor registered in the log (later events win), one
    `jurisdiction` subject for each registration jurisdiction the base profile does not cover, and the child subjects
    (candidate, assignment, exercise) opened by `subject` events.

    A child subject is `{kind: <subject_kind>, **attrs}`; the first event for a URI wins (its attrs are its identity),
    and an event with another subject_kind, no attrs object, or a URI already taken is ignored. The attrs cannot
    override `kind`.

    `base_codes` are the codes the base profile covers; the engine stays pure and has no default, so the caller
    supplies them. A jurisdiction subject exists only while some instructor's latest registration names it.
    Given `notice_version`, each instructor with a recorded jurisdiction also carries `notice_variant`, the
    notice they are owed (see `notice_variant`); `done_when.match` can name it as `${subject.notice_variant}`.
    """
    found: dict[str, dict[str, Any]] = {PROGRAMME: {"kind": "programme"}}
    log = list(events)
    for e in log:
        if e["kind"] == "registration" and isinstance(e["payload"].get("type"), str):
            info = {"kind": "instructor", "type": e["payload"]["type"], "level": e["payload"].get("level")}
            if isinstance(e["payload"].get("jurisdiction"), str):
                info["jurisdiction"] = e["payload"]["jurisdiction"]
            found[e["subject_uri"]] = info
    for e in log:
        p = e["payload"]
        if (e["kind"] == "subject" and p.get("subject_kind") in CHILD_KINDS and isinstance(p.get("attrs"), dict)
                and e["subject_uri"] not in found):
            found[e["subject_uri"]] = {"kind": p["subject_kind"], **{k: v for k, v in p["attrs"].items() if k != "kind"}}
    covered = {c.upper() for c in base_codes}
    codes = {i["jurisdiction"] for i in found.values() if i["kind"] == "instructor" and "jurisdiction" in i}
    for code in sorted(codes - covered):
        found[jurisdiction_uri(code)] = {"kind": "jurisdiction", "code": code}
    if notice_version is not None:
        for info in found.values():
            if info["kind"] == "instructor" and "jurisdiction" in info:
                info["notice_variant"] = notice_variant(notice_version, info["jurisdiction"], covered)
    return found


SUBJECT_TEMPLATE = re.compile(r"^\$\{subject\.(notice_variant)\}$")  # the only template form a match value may take


def _matches(payload: dict[str, Any], match: dict[str, Any], info: dict[str, Any]) -> bool:
    """Every field of `match` equals the payload's. A value `${subject.notice_variant}` stands for the subject's own
    value; a subject that has none matches nothing (fail closed)."""
    for key, want in match.items():
        if isinstance(want, str):
            template = SUBJECT_TEMPLATE.match(want)
            if template:
                want = info.get(template.group(1))
                if want is None:
                    return False
        if payload.get(key) != want:
            return False
    return True


def _completions(
    step: dict[str, Any],
    uri: str,
    events: "list[dict[str, Any]] | EventIndex",
    current_input: CurrentInput | None = None,
    info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    idx = _idx(events)
    want = step["done_when"]
    matching = [e for e in idx.of(want["kind"], uri) if _matches(e["payload"], want["match"], info or {})]
    found = [e for e in matching if want["kind"] != "signoff" or e["payload"].get("decision") in APPROVING]
    if want.get("bind") != "input":
        return found
    # Bound to its inputs: only the newest approving sign-off counts, and only while it covers the inputs as
    # they are now and no revocation came after it (decision 0019). No reader, or a reader that cannot say, means not
    # done (fail closed).
    if current_input is None:
        return []
    now = current_input(step["id"], uri)
    if not isinstance(now, str):
        return []
    newest = newest_decisive(e for e in matching if e["payload"].get("decision") in (*APPROVING, REVOKE))
    if newest is not None and newest["payload"].get("input_sha256") == now:
        return [newest]
    if want.get("skippable"):
        # A step that does not apply is closed by a `step` event marked skipped, which covers the same hash. Only the
        # system writes one: the same marker from anyone else is not a skip.
        skips = [
            e for e in idx.of("step", uri)
            if e["actor"] == SYSTEM_ACTOR
            and e["payload"].get("step") == step["id"] and e["payload"].get("skipped") is True
        ]
        if skips and skips[-1]["payload"].get("input_sha256") == now:
            return [skips[-1]]
    return []


def newest_decisive(signoffs: Iterable[dict[str, Any]]) -> dict[str, Any] | None:
    """The approval in force among `signoffs` (sign-off events of one step and subject, in log order, already filtered to
    approving and revoking decisions): the newest of them when it approves, None when it is a revocation or there is
    none (decision 0019)."""
    newest = None
    for e in signoffs:
        newest = e
    return newest if newest is not None and newest["payload"].get("decision") in APPROVING else None


def approval_in_force(
    step: dict[str, Any], uri: str, events: "list[dict[str, Any]] | EventIndex", current_input: CurrentInput | None,
    info: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """The approving sign-off that keeps a bound step done now, or None (not done, or done by a system skip)."""
    found = _completions(step, uri, events, current_input, info)
    return found[0] if found and found[0]["kind"] == "signoff" else None


def _effective(info: dict[str, Any], subj: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What `applies_to` and the vacuity test read for a subject. A child subject with an `instructor` attribute takes
    type, level and jurisdiction from that instructor's registration (its own attrs of those names never count); a child
    whose instructor is not registered has none of them, so no filter on them matches."""
    parent = info.get("instructor") if info.get("kind") in CHILD_KINDS else None
    if not isinstance(parent, str):
        return info
    out = {k: v for k, v in info.items() if k not in ("type", "level", "jurisdiction")}
    reg = subj.get(parent)
    if reg is not None and reg.get("kind") == "instructor":
        out.update({k: reg[k] for k in ("type", "level", "jurisdiction") if k in reg})
    return out


def _applies(step: dict[str, Any], info: dict[str, Any]) -> bool:
    flt = step.get("applies_to", {})
    if "type" in flt and info.get("type") not in flt["type"]:
        return False
    if "jurisdiction" in flt and info.get("jurisdiction", info.get("code")) not in flt["jurisdiction"]:
        return False
    return "level" not in flt or info.get("level") in flt["level"]


def _need_uri(need: dict[str, Any], uri: str, info: dict[str, Any], subj: dict[str, dict[str, Any]]) -> str | None:
    """The subject a need is checked against. A need on a programme-subject step is checked against the programme,
    whoever asks. A need on a jurisdiction-subject step, asked by an instructor, is checked against the instructor's
    own jurisdiction (`tm:jurisdiction/<code>`); None (unmet) when no jurisdiction is recorded, or when the asker is
    neither an instructor nor a jurisdiction (a programme step cannot depend on every jurisdiction).

    A child subject (candidate, assignment, exercise) asks its parent: a need on an instructor-subject step is checked
    against `attrs.instructor`, a need on a candidate-subject step against `attrs.candidate`, a need on a step of its own
    kind against itself. The parent must be a known subject of that kind, and the attribute a string; otherwise
    (including any other kind of step) the need is unmet."""
    if need["subject"] == "programme":
        return PROGRAMME
    if info.get("kind") in CHILD_KINDS:
        if need["subject"] == info["kind"]:
            return uri
        parent = info.get(need["subject"]) if need["subject"] in ("instructor", "candidate") else None
        if isinstance(parent, str) and subj.get(parent, {}).get("kind") == need["subject"]:
            return parent
        return None
    if need["subject"] != "jurisdiction" or info.get("kind") == "jurisdiction":
        return uri
    code = info.get("jurisdiction")
    if info.get("kind") != "instructor" or not isinstance(code, str):
        return None
    return jurisdiction_uri(code)


def _base_jurisdiction(need: dict[str, Any], info: dict[str, Any], subj: dict[str, dict[str, Any]]) -> bool:
    """A need on a jurisdiction-subject step, asked by an instructor whose recorded code the base profile covers: no
    overlay exists for that code (`subjects` makes one for every other code), so the need is vacuous."""
    code = info.get("jurisdiction")
    return (need["subject"] == "jurisdiction" and info.get("kind") == "instructor" and isinstance(code, str)
            and jurisdiction_uri(code) not in subj)


def _vacuous(need: dict[str, Any], info: dict[str, Any]) -> bool:
    """The need does not apply to this subject, and the subject is known well enough to say so: a known
    instructor type, and a recorded jurisdiction when the need filters on one (unknown means unmet)."""
    if need["subject"] == "programme" or info.get("type") not in ROSTER_TYPES:
        return False
    if "jurisdiction" in need.get("applies_to", {}) and not isinstance(info.get("jurisdiction"), str):
        return False
    return not _applies(need, info)


def _step_index(workflows_doc: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    """Step id -> (workflow id, step)."""
    return {st["id"]: (wf["id"], st) for wf in workflows_doc["workflows"] for st in wf["steps"]}


CLOSED = "closed"  # the `check` result by which the system closes a child subject (a bench exit closes the candidates)


def is_closed(uri: str, subj: dict[str, dict[str, Any]], idx: EventIndex) -> bool:
    """A child subject the system has closed: a `check` event on it by SYSTEM_ACTOR with result "closed" (decision 0015,
    integration review finding 3), or a child whose `candidate` attribute names a closed candidate (its assignments). A closed
    subject has no due steps and no met needs, so neither the queue nor a refresh runs anything for it."""
    info = subj.get(uri)
    if info is None or info.get("kind") not in CHILD_KINDS:
        return False
    if any(e["actor"] == SYSTEM_ACTOR and e["payload"].get("result") == CLOSED for e in idx.of("check", uri)):
        return True
    parent = info.get("candidate")
    return isinstance(parent, str) and parent != uri and subj.get(parent, {}).get("kind") == "candidate" and is_closed(
        parent, subj, idx)


def next_steps(
    workflows_doc: dict[str, Any],
    events: Iterable[dict[str, Any]],
    subj: dict[str, dict[str, Any]],
    today: date,
    current_input: CurrentInput | None = None,
    index: EventIndex | None = None,
) -> list[Due]:
    """Open, applicable steps whose needs are met, ordered by (due or never, step id, subject).

    `current_input(step, subject)` returns the hash of the inputs the step's page would show now; steps
    declaring `done_when.bind: input` are done only while their newest approving sign-off covers it.
    Without a reader such steps are never done. `index` is the `EventIndex` of `events` when the caller keeps one (a
    loaded state does); without it one is built here, once, for the whole call."""
    idx = index if index is not None else _idx(events)
    steps = _step_index(workflows_doc)
    closed = {uri for uri in subj if is_closed(uri, subj, idx)}
    out: list[Due] = []
    for wf_id, st in steps.values():
        kind = st["subject"]
        for uri, info in subj.items():
            if info["kind"] != kind or uri in closed or not _applies(st, _effective(info, subj)) \
                    or _completions(st, uri, idx, current_input, info):
                continue
            met, need_dates = _needs(st, steps, uri, info, idx, current_input, subj)
            if met:
                out.append(_due(wf_id, st, uri, info, need_dates, idx, today))
    return sorted(out, key=lambda d: (d.due or date.max, d.step, d.subject))


def _opened_by(idx: EventIndex, uri: str) -> str | None:
    """The step named by `opened_by` on the first `subject` event of a child subject; None when the log never opened it."""
    opening = idx.of("subject", uri)
    found = opening[0]["payload"].get("opened_by") if opening else None
    return found if isinstance(found, str) else None


def _needs(
    st: dict[str, Any],
    steps: dict[str, tuple[str, dict[str, Any]]],
    uri: str,
    info: dict[str, Any],
    log: "list[dict[str, Any]] | EventIndex",
    current_input: CurrentInput | None,
    subj: dict[str, dict[str, Any]],
) -> tuple[bool, list[date]]:
    """Whether every need of `st` is complete for the subject, and the dates they first became complete."""
    need_dates: list[date] = []
    eff = _effective(info, subj)
    waivers = st.get("needs_except_opened_by") or {}
    opener = _opened_by(_idx(log), uri) if waivers and info.get("kind") in CHILD_KINDS else None
    for need_id in st["needs"]:
        if need_id not in steps:
            raise ValueError(f"{st['id']} needs unknown step {need_id}")
        if opener is not None and opener in waivers.get(need_id, ()):
            continue  # waived: the step that opened this child stands in for the need (decision 0015, ad-hoc assignments)
        need = steps[need_id][1]
        if _vacuous(need, eff) or _base_jurisdiction(need, eff, subj):
            continue  # vacuous: the need does not apply to this (known) subject
        target = _need_uri(need, uri, eff, subj)
        done = _completions(need, target, log, current_input, subj.get(target, {})) if target is not None else []
        if not done:
            return False, []
        need_dates.append(min(_day(e) for e in done))  # when the need first became complete
    return True, need_dates


def needs_met(
    workflows_doc: dict[str, Any],
    events: Iterable[dict[str, Any]],
    subj: dict[str, dict[str, Any]],
    step_id: str,
    uri: str,
    current_input: CurrentInput | None = None,
    index: EventIndex | None = None,
) -> bool:
    """True when every need of the step is complete for the subject, whether or not the step itself is done.
    Lets a caller refresh a done, idempotent auto step only while its inputs are still in force."""
    steps = _step_index(workflows_doc)
    if step_id not in steps or uri not in subj:
        return False
    st = steps[step_id][1]
    if subj[uri]["kind"] != st["subject"] or not _applies(st, _effective(subj[uri], subj)):
        return False
    idx = index if index is not None else _idx(events)
    if is_closed(uri, subj, idx):
        return False
    return _needs(st, steps, uri, subj[uri], idx, current_input, subj)[0]


def opened_on(
    workflows_doc: dict[str, Any],
    events: Iterable[dict[str, Any]],
    subj: dict[str, dict[str, Any]],
    step_id: str,
    uri: str,
    current_input: CurrentInput | None = None,
    index: EventIndex | None = None,
) -> date | None:
    """The day the step opened for the subject, from the log alone (never from a sign-off's own `signed_at`).

    For a child subject (candidate, assignment, exercise) the day of the `subject` event that opened it. For any other
    subject the day the last of the step's needs first completed (`_needs`); None when the step has no needs, they are not met, or
    the step or subject is unknown. A sign-off cannot honestly be dated before this day."""
    steps = _step_index(workflows_doc)
    if step_id not in steps or uri not in subj:
        return None
    idx = index if index is not None else _idx(events)
    info = subj[uri]
    if info["kind"] in CHILD_KINDS:
        opening = idx.of("subject", uri)
        return _day(opening[0]) if opening else None
    met, need_dates = _needs(steps[step_id][1], steps, uri, info, idx, current_input, subj)
    return max(need_dates) if met and need_dates else None


def unmet_needs(
    workflows_doc: dict[str, Any],
    events: Iterable[dict[str, Any]],
    subj: dict[str, dict[str, Any]],
    step_id: str,
    uri: str,
    current_input: CurrentInput | None = None,
    index: EventIndex | None = None,
) -> list[str]:
    """The needs of the step that are not complete for the subject, in the order the step lists them (empty when
    `needs_met`). A step or subject that does not exist reports the step itself."""
    steps = _step_index(workflows_doc)
    if step_id not in steps or uri not in subj:
        return [step_id]
    log, info = (index if index is not None else _idx(events)), subj[uri]
    missing: list[str] = []
    for need_id in steps[step_id][1]["needs"]:
        one = {"id": step_id, "needs": [need_id], "needs_except_opened_by": steps[step_id][1].get("needs_except_opened_by")}
        if not _needs(one, steps, uri, info, log, current_input, subj)[0]:
            missing.append(need_id)
    return missing


def _due(
    wf_id: str,
    st: dict[str, Any],
    uri: str,
    info: dict[str, Any],
    need_dates: list[date],
    idx: EventIndex,
    today: date,
) -> Due:
    rule = st.get("due")
    due: date | None = None
    if isinstance(rule, str):
        # A rule name: resolved through the registry (due.py), which the flow modules fill. validate refuses an unknown
        # name, so one missing here is a setup error, not a step without a date.
        try:
            fn = due_registry.resolve(rule)
        except KeyError as exc:
            raise ValueError(f"{st['id']}: {exc.args[0]}") from None
        due = fn(st, uri, info, idx.events, today)
    elif isinstance(rule, dict):
        if need_dates:
            base = max(need_dates)
        else:
            own = [_day(e) for e in idx.for_subject(uri)]
            base = min(own) if own else today
        due = base + timedelta(days=rule["days"])
    return Due(
        step=st["id"],
        workflow=wf_id,
        subject=uri,
        role=st["role"],
        due=due,
        overdue=due is not None and today > due,
        page=st.get("page"),
        type=st["type"],
    )
