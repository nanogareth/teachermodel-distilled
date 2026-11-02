"""`teachermodel dev-simulate`: a complete simulated store, end to end (design docs/specs/2026-10-27-dev-simulation-design.md,
decision 0020).

A fresh pilot store marked `simulated: true` is filled by months of simulated use on the repository's real standards:
weekdays from `end - weeks` to `end`, two rounds a day (07:30 and 13:30 UTC). A round ticks, answers the read plan as the
mailbox would (the library exists, the owner has sent each notice draft, people return sign-offs from their own addresses)
with a fixture receipt, and ingests it through `app.do_ingest`. The people sign every due page, with answers shaped by the
persona of the instructor the page is about; between the rounds the organisation acts on fixed rules (roster import,
calibration exercises, monthly outcome exports and CPD, an ad-hoc assignment per quarter, an override after a return to
co-teaching). Every choice is a hash of fixed inputs, never a random draw: the same arguments write the same store.

A rejected sign-off is a simulator defect: the run stops and names it (SimulationError).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from . import util
from . import app, config, course, devsign, pilot, records, roster as roster_module, staffing
from .flows.bench import request_bench
from .flows.common import clearer_instructors
from .flows.calibration import STEP_SCORE, open_exercise
from .flows.override import request_override
from .flows.quality import import_outcomes
from .standards import ROOT, load_standards, validate

UNIT = pilot.UNIT
OWNER = "tm:person/sim-owner"
HEAD = "tm:person/sim-head"
MARKER = "simulation.json"  # in the store root: says the store is the simulator's, so --reset may clear it
LOG = "simulation.log"
ROUNDS = (time(7, 30), time(13, 30))
NOTICE_VERSION = "2026-11"
BASELINE = 70.0

STEP_ROSTER_IMPORT = "tm:step/roster-import"
OBSERVE = "tm:step/observe"
SECOND_SCORE = "tm:step/second-score"
COACH_OBSERVE = "tm:step/coach-observe"
COACH_REOBSERVE = "tm:step/coach-reobserve"
D1, D2, HEAD_RESOLVES = "tm:step/clearer-decision-1", "tm:step/clearer-decision-2", "tm:step/head-resolves"
BENCH_DECISION = "tm:step/bench-decision"
OVERRIDE_DECISION = "tm:step/override-decision"
LOG_ACTIVITY = "tm:step/log-activity"
ASSIGN_OBSERVER = "tm:step/assign-observer"
TRAIN_THE_TRAINER = "tm:step/train-the-trainer"
REPLY = "tm:step/reply-or-appeal"
OPTIONAL = frozenset({LOG_ACTIVITY, ASSIGN_OBSERVER, REPLY})  # signed only when an initiative asks for it
ASSIGNMENTS_APPROVED = "tm:step/assignments-approved"
# How many days people take to act on a page, counted from the first day that version of the page is seen: (least, most),
# the day picked by hash. Sessions are scheduled, coaching runs over weeks, office approvals take a day or three.
DELAYS = {
    OBSERVE: (3, 9), "tm:step/self-assessment": (0, 2), COACH_OBSERVE: (5, 10), "tm:step/coach-feedback": (1, 2),
    "tm:step/practice-task": (1, 3), COACH_REOBSERVE: (10, 18), D1: (2, 5), D2: (2, 5), HEAD_RESOLVES: (2, 4),
    STEP_SCORE: (3, 7), "tm:step/dry-run": (4, 10), SECOND_SCORE: (5, 10), BENCH_DECISION: (5, 10),
    OVERRIDE_DECISION: (1, 2), ASSIGNMENTS_APPROVED: (1, 4),
}
DEFAULT_DELAY = (1, 3)
WEEKLY = {ASSIGNMENTS_APPROVED: 0}  # steps a person handles on one weekday only (0 = Monday): the coordinator's batch

# The office: one generated person per role (the owner is the programme owner only).
_OFFICE = [
    ("sim-owner", "Sim Programme Owner", ["programme-owner"]),
    ("sim-head", "Sim Head of Training", ["head-of-training"]),
    ("sim-it", "Sim IT Administrator", ["it"]),
    ("sim-dpo", "Sim Data Protection Officer", ["dpo"]),
    ("sim-legal", "Sim Legal Counsel", ["legal"]),
    ("sim-manager", "Sim Engineering Manager", ["manager"]),
    ("sim-partner-lead", "Sim Partner Lead", ["partner-lead"]),
    ("sim-coord-1", "Sim Coordinator One", ["coordinator"]),
    ("sim-coord-2", "Sim Coordinator Two", ["coordinator"]),
]


@dataclass(frozen=True)
class Instructor:
    slug: str
    kind: str
    level: str
    jurisdiction: str
    persona: str
    contract_ends_days_before_end: int | None = None  # a contractor whose contract ends inside the window


# 14 instructors, IE and US-CA only (decision 0020: only jurisdictions with a profile). Stable, meaningless slugs.
INSTRUCTORS = [
    Instructor("a1c4f", "professional", "clearer", "IE", "strong"),
    Instructor("d7h2k", "professional", "clearer", "IE", "solid"),
    Instructor("q3m8v", "sme-engineer", "clearer", "IE", "strong"),
    Instructor("w5r1z", "contractor", "clearer", "US-CA", "solid"),
    Instructor("e8n3b", "professional", "cleared", "IE", "solid"),
    Instructor("j2t6x", "professional", "cleared", "IE", "developing"),
    Instructor("p9k4s", "sme-engineer", "lead-observed", "IE", "solid"),
    Instructor("r6w2c", "sme-engineer", "lead-observed", "IE", "developing"),
    Instructor("u4f7m", "sme-engineer", "lead-observed", "IE", "struggling"),
    Instructor("g1x9d", "sme-engineer", "co-deliver", "IE", "solid"),
    Instructor("y7b5q", "sme-engineer", "co-deliver", "IE", "developing"),
    Instructor("n3c8h", "contractor", "lead-observed", "US-CA", "solid", contract_ends_days_before_end=20),
    Instructor("s5v2t", "contractor", "co-deliver", "IE", "struggling"),
    Instructor("k8d6w", "partner", "shadow", "IE", "solid"),
    Instructor("h6z1r", "professional", "lead-observed", "IE", "solid"),  # a professional taken through the pathway
]
PERSONA = {f"tm:instructor/{i.slug}": i.persona for i in INSTRUCTORS}
# Coaches, each mapped to their instructor: between them they coach everyone (spec: every active instructor in a cycle).
COACHES = [("sim-coach-e8n3b", "e8n3b", ["r6w2c", "u4f7m", "y7b5q", "k8d6w", "h6z1r"]),
           ("sim-coach-d7h2k", "d7h2k", ["j2t6x", "s5v2t", "p9k4s", "g1x9d", "a1c4f"]),
           ("sim-coach-a1c4f", "a1c4f", ["d7h2k", "q3m8v", "w5r1z", "e8n3b", "n3c8h"])]
SCORES = {"strong": (3, 4), "solid": (3, 3), "developing": (2, 3), "struggling": (2, 2)}
IMPROVED = (3, 4)  # a developing instructor's scores once they have improved (IMPROVES_AFTER weeks into the run)
IMPROVES_AFTER = timedelta(weeks=8)
OUTCOME_DELTA = {"strong": (2, 6), "solid": (-2, 3), "developing": (-6, 0), "struggling": (-14, -10)}


class SimulationError(Exception):
    """The simulation cannot start, or a round went wrong (a rejected sign-off is a simulator defect)."""


def _h(*parts: Any) -> int:
    """A deterministic number from fixed inputs: every simulated choice comes from it."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:12], 16)


def _uri(slug: str) -> str:
    return f"tm:instructor/{slug}"


def _email(slug: str) -> str:
    return f"sim.{slug}@example.com"


# --- the store -----------------------------------------------------------------------------------------------------


def roster_doc(start: date, end: date) -> dict[str, Any]:
    rows = []
    for n, i in enumerate(INSTRUCTORS, start=1):
        row: dict[str, Any] = {
            "instructor": _uri(i.slug),
            "identity": {"name": f"Sim {pilot._TITLES[i.kind]} {n:02d}", "email": _email(i.slug)},
            "type": i.kind,
            "organisation": {"partner": "tm:org/sim-partner", "contractor": "tm:org/sim-training-ltd"}
                            .get(i.kind, "tm:org/example"),
            "level": i.level,
            "languages": ["en"],
            "regions": [i.jurisdiction],
            "jurisdiction": i.jurisdiction,
            "engagement": {"start": (start - timedelta(days=400)).isoformat(), "status": "active"},
        }
        if i.kind == "sme-engineer":
            row["engagement"].update(manager="tm:person/sim-manager", protected_hours_per_month=16)
        if i.kind == "contractor":
            ends = end - timedelta(days=i.contract_ends_days_before_end) if i.contract_ends_days_before_end else \
                end + timedelta(days=365)
            row["engagement"].update(end=ends.isoformat(), agreement_ref=f"agreements/{i.slug}-sim")
        if i.kind == "partner":
            row["engagement"]["nominated_by"] = "tm:person/sim-partner-lead"
        # Everyone lists the unit they deliver, or are preparing to deliver (a candidate opens once their level allows)
        row["delivers"] = [{"unit": UNIT, "modes": ["in-person", "remote", "hybrid"],
                            "last_delivered": (start - timedelta(days=10)).isoformat()}]
        rows.append(row)
    return {"schema": "tm:contract/roster@2", "as_of": start.isoformat(), "source": "Generated by teachermodel dev-simulate",
            "prepared_by": OWNER, "instructors": rows}


def people_doc() -> dict[str, Any]:
    people: list[dict[str, Any]] = [{"person": f"tm:person/{slug}", "name": name, "email": f"{slug}@example.com",
                                     "roles": roles} for slug, name, roles in _OFFICE]
    for i in INSTRUCTORS:
        if i.level == "clearer":
            people.append({"person": f"tm:person/sim-clearer-{i.slug}", "name": f"Sim Clearer {i.slug}",
                           "email": f"sim.clearer.{i.slug}@example.com", "roles": ["clearer"], "instructor": _uri(i.slug)})
    for slug, mapped, coached in COACHES:  # one person per instructor: a clearer who coaches holds both roles
        row = next((p for p in people if p.get("instructor") == _uri(mapped)), None)
        if row is None:
            row = {"person": f"tm:person/{slug}", "name": f"Sim Coach {mapped}", "email": f"{slug}@example.com",
                   "roles": [], "instructor": _uri(mapped)}
            people.append(row)
        row["roles"] = [*row["roles"], "coach"]
        row["coaches"] = [_uri(c) for c in coached]
    return {"schema": "tm:contract/people@1", "people": people}


def settings_doc(store: Path) -> dict[str, Any]:
    return {"schema": "tm:contract/settings@1", "library": "teachermodel-sim", "mailbox": "sim-signoffs@example.com",
            "it_email": "sim-it@example.com", "dpo_email": "sim-dpo@example.com", "notice_version": NOTICE_VERSION,
            "pilot": True, "simulated": True}


def _dump(doc: Any) -> str:
    return "# Generated by teachermodel dev-simulate (decision 0020). Simulated data only.\n" + \
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)


def init_store(store: Path, start: date, end: date, *, reset: bool = False, root: Path = ROOT) -> None:
    """Create the simulated store: layout, settings, people and the generated inputs. Raises SimulationError for a store
    that holds anything but a previous simulation (which `reset` clears)."""
    try:
        store = config._assert_not_appdata(config.assert_outside_repo(Path(store)))
    except config.ConfigError as exc:
        raise SimulationError(str(exc)) from exc
    if store.exists() and any(store.iterdir()):
        if not (store / MARKER).is_file():
            raise SimulationError(f"{store} is not empty and is not a simulated store; give an empty or new directory")
        if not reset:
            raise SimulationError(f"{store} already holds a simulation; pass --reset to replace it")
        shutil.rmtree(store)
    for d in (*pilot.LAYOUT, "logs"):
        (store / d).mkdir(parents=True, exist_ok=True)
    docs = {"settings.yaml": (settings_doc(store), "settings.schema.json"),
            "identities/people.yaml": (people_doc(), "people.schema.json"),
            "inputs/roster.yaml": (roster_doc(start, end), "roster.schema.json")}
    for rel, (doc, schema) in docs.items():
        errors = validate(doc, schema, root)
        if errors:
            raise RuntimeError(f"dev-simulate generated an invalid {schema}: {errors}")
        (store / rel).write_text(_dump(doc), encoding="utf-8", newline="\n")
    refusals = roster_module.check_roster(docs["inputs/roster.yaml"][0], root) + \
        roster_module.pilot_refusals(docs["inputs/roster.yaml"][0])
    if refusals:
        raise RuntimeError(f"dev-simulate generated a roster that would be refused: {refusals}")
    (store / "inputs" / "calibration-reference.yaml").write_text(_dump(pilot.generated_reference(root)), encoding="utf-8",
                                                                 newline="\n")
    (store / "inputs" / "retention.yaml").write_text(_dump(pilot.generated_retention(root)), encoding="utf-8", newline="\n")
    (store / MARKER).write_text(json.dumps({"start": start.isoformat(), "end": end.isoformat()}, indent=2) + "\n",
                                encoding="utf-8", newline="\n")
    config.people(store)


# --- the simulation ------------------------------------------------------------------------------------------------


@dataclass
class _Run:
    store: Path
    root: Path
    start: date
    counts: Counter = field(default_factory=Counter)
    exercises: list[date] = field(default_factory=list)
    adhoc_quarters: set[str] = field(default_factory=set)
    cpd_months: set[tuple[str, str]] = field(default_factory=set)
    exported: set[str] = field(default_factory=set)
    overridden: set[str] = field(default_factory=set)
    wanted: set[tuple[str, str]] = field(default_factory=set)  # optional (step, subject) pages to sign this round
    first_seen: dict[tuple[str, str, str], date] = field(default_factory=dict)  # (step, subject, input hash) -> day
    first_exercise: str | None = None
    rejections: Counter = field(default_factory=Counter)
    appeals: dict[str, str] = field(default_factory=dict)  # instructor -> the decision (event id) they appeal
    notes: list[str] = field(default_factory=list)  # this day's log notes from the rounds
    _readers: dict[int, Any] = field(default_factory=dict)

    # --- reading the state

    def state(self) -> app.State:
        return app.load_state(self.store, self.root)

    @staticmethod
    def instructor_of(st: app.State, subject: str) -> str | None:
        info = st.subjects.get(subject) or {}
        if info.get("kind") == "instructor":
            return subject
        inst = info.get("instructor")
        return inst if isinstance(inst, str) else None

    def email_of(self, st: app.State, uri: str, role: str) -> str:
        """The mailbox that signs as `uri` with `role`: a mapped person's own address when the role is theirs (a coach,
        a clearer), else the first mailbox that reaches the URI."""
        holding = sorted(e for e, entries in st.identities.items() if any(i["uri"] == uri and role in i["roles"]
                                                                          for i in entries))
        found = holding or sorted(e for e, entries in st.identities.items() if any(i["uri"] == uri for i in entries))
        if not found:
            raise SimulationError(f"no mailbox for {uri}")
        return found[0]

    # --- answers

    def score(self, inst: str | None, domain: str, day: date, bump: int = 0) -> int:
        persona = PERSONA.get(inst or "", "solid")
        later = day >= self.start + IMPROVES_AFTER
        if persona == "struggling":  # sound at first (they clear), then declining
            lo, hi = SCORES["struggling"] if later else SCORES["solid"]
        else:
            lo, hi = IMPROVED if persona == "developing" and later else SCORES.get(persona, (3, 3))
        base = lo if _h("score", inst, domain, day) % 2 == 0 else hi
        return max(1, min(4, base + bump))

    def answers(self, st: app.State, data: dict[str, Any], at: datetime, turn: int) -> dict[str, Any]:
        step, subject, signer = data["step"], data["subject_uri"], data["signer"]
        day = at.date()
        scores = None
        if step == STEP_SCORE:
            reference = devsign._reference(self.store, subject)
            scores = devsign.like_a_person(reference, subject, signer)
            if reference and subject == self.first_exercise and signer == self._first_clearer(st):
                scores = {d: (s + 2 if s <= 2 else s - 2) for d, s in reference.items()}  # one clearer misses the first time
        fields = devsign.answers(data, day, note="Simulated evidence", scores=scores, turn=turn)
        inst = self.instructor_of(st, subject)
        persona = PERSONA.get(inst or "", "solid")
        evidence = [f["name"] for f in data["fields"] if f["kind"] == "evidence_score"]
        if step in (OBSERVE, SECOND_SCORE, COACH_OBSERVE, COACH_REOBSERVE):
            bump = -1 if step == COACH_OBSERVE and persona in ("developing", "struggling") else 0
            if step == COACH_REOBSERVE and persona == "developing":
                bump = 1
            # A second scorer watches the same recording: they score the session the first observer saw, so they agree.
            scored_on = self.observed_on(st, subject) if step == SECOND_SCORE else day
            for name in evidence:
                fields[name] = {"score": self.score(inst, name, scored_on or day, bump),
                                "note": f"Simulated evidence for {name} on {day.isoformat()}."}
        if step == OBSERVE and any(f["name"] == "from_recording" for f in data["fields"]) \
                and (st.registrations.get(inst or "") or {}).get("type") == "partner":
            fields["from_recording"] = True  # a partner instructor is cleared remotely, from recordings (spec, phase 6)
        for f in data["fields"]:
            if f["name"] == "unit" and f["kind"] in ("text", "enum") and f.get("value") is None:
                fields["unit"] = UNIT if f["kind"] == "text" or UNIT in (f.get("options") or []) else fields.get("unit")
        if step in (D1, D2):
            declined = persona == "struggling" and day >= self.start + IMPROVES_AFTER
            not_yet = declined or (persona == "developing" and step == D2)
            fields["outcome"] = "not_yet" if not_yet else "cleared"
            if not_yet:
                fields["actions"] = "Two more observed sessions on the weakest domains."
        elif step == HEAD_RESOLVES:
            fields.update(outcome="cleared_with_conditions", conditions="Pace the practical; check every learner's lab.",
                          recheck=(day + timedelta(days=90)).isoformat())
        elif step == BENCH_DECISION:
            fields.update(decision="return-to-co-teaching" if persona == "struggling" else "renew",
                          rationale=f"Simulated rationale for a {persona} instructor.")
        elif step == OVERRIDE_DECISION:
            fields.update(decision="approve", reason="Simulated: no other cleared lead is free that day.")
        elif step == REPLY and subject in self.appeals:
            fields.update(decision=self.appeals[subject], kind="appeal",
                          text="Simulated appeal: the deliveries behind the triggers had a new lab image.")
        elif step == LOG_ACTIVITY:
            fields.update(activity=f"Simulated CPD activity, {day:%B %Y}.", hours=2.0, date=day.isoformat())
        return fields

    @staticmethod
    def observed_on(st: app.State, sample: str) -> date | None:
        """The day of the observation an audit sample drew."""
        obs = (st.subjects.get(sample) or {}).get("observation")
        found = [e for e in st.events if e["kind"] == "observation" and e["id"] == obs]
        return date.fromisoformat(found[0]["at"][:10]) if found else None

    # --- the people sign their pages

    def signoffs(self, st: app.State, at: datetime) -> list[tuple[dict[str, Any], str]]:
        today = at.date()
        due = {(d.step, d.subject) for d in app.due_steps(st, today) if d.type == "human"}
        stems = {app.page_stem(s, subj, "tm:person/x")[:-1]: (s, subj) for s, subj in due
                 if s not in OPTIONAL or (s, subj) in self.wanted}
        signed = devsign._signed(st)
        seen = devsign._seen_ids(st)
        taken: set[tuple[str, str]] = set()
        out = []
        for path in sorted((self.store / "pages").glob("*.html")):
            if path.stem.startswith(app.REVOKE_PREFIX):
                continue
            key = next((v for stem, v in stems.items() if path.stem.startswith(stem)), None)
            if key is None or key in taken:
                continue
            data = devsign._page_data(path)
            if (data["step"], data["subject_uri"]) != key or not self.current(st, data):
                continue
            if (data["step"], data["subject_uri"], data["signer"], data["input_sha256"]) in signed:
                continue
            if not self.ready(key, data["input_sha256"], today):
                continue
            turn = sum(1 for (s, subj, *_r) in signed if (s, subj) == key)
            fields = self.answers(st, data, at, turn)
            sid = devsign.input_sha256([data["step"], data["subject_uri"], data["signer"], data["input_sha256"], fields,
                                        at.isoformat()])[:32]
            if sid in seen:
                continue
            taken.add(key)
            doc = {"schema": app.SIGNOFF_SCHEMA, "id": sid, "step": data["step"], "subject_uri": data["subject_uri"],
                   "input_sha256": data["input_sha256"], "decision": "approve", "fields": fields,
                   "signer": data["signer"], "signed_at": (at + timedelta(seconds=30)).isoformat(timespec="seconds"),
                   "page_template_sha256": data["page_template_sha256"]}
            out.append((doc, self.email_of(st, data["signer"], st.step_defs[data["step"]]["role"])))
        return out

    def current(self, st: app.State, data: dict[str, Any]) -> bool:
        """The page is one the state builds now (pages are never pruned, so an old file can name a signer who left the
        pool or show inputs that changed): its signer is in the current page set and its inputs are current."""
        try:
            specs = app._page_specs(st, data["step"], data["subject_uri"]) or []
        except app.PageProblem:
            return False
        reader = self._readers.get(id(st)) or self._readers.setdefault(id(st), app._current_input_reader(st))
        return data["signer"] in {sp["signer"] for sp in specs} and reader(data["step"], data["subject_uri"]) == \
            data["input_sha256"]

    def ready(self, key: tuple[str, str], input_sha: str, today: date) -> bool:
        """Whether the person acts on this version of the page today: its delay has passed since it was first seen, and
        it is their weekday for a step they batch. An optional page an initiative asked for is acted on at once."""
        seen = self.first_seen.setdefault((*key, input_sha), today)
        if key in self.wanted:
            return True
        step = key[0]
        if step in WEEKLY and today.weekday() != WEEKLY[step]:
            return False
        lo, hi = DELAYS.get(step, DEFAULT_DELAY)
        return (today - seen).days >= lo + _h("delay", *key, input_sha) % (hi - lo + 1)

    # --- the mailbox answers the plan

    def receipt(self, st: app.State, at: datetime, signoffs: list[tuple[dict[str, Any], str]]) -> dict[str, Any]:
        plan = json.loads((self.store / "plans" / "latest.json").read_text(encoding="utf-8"))
        owner = next(p["email"] for p in st.people if "programme-owner" in p["roles"])
        sent_at = (at + timedelta(seconds=45)).isoformat(timespec="seconds")
        drafted = {p.stem for p in (self.store / "generated" / "notice-drafts").glob("*.eml")}
        by_email = {row["identity"]["email"].lower(): row["instructor"] for row in (st.roster or {}).get("instructors", [])}
        results = []
        for op in plan["ops"]:
            if op["op"] == "site.library":
                data: dict[str, Any] = {"exists": True}
            elif op["op"] == "mail.sent":
                to = op["args"]["to"]
                inst = by_email.get(to.lower())
                sent = inst is not None and app._slug(inst) in drafted
                data = {"messages": [{"sender": owner, "to": [to], "subject": f"Privacy notice {op['args']['tag']}",
                                      "sentDateTime": sent_at}] if sent else []}
            elif op["op"] == "mail.tagged":
                data = {"messages": [{"sender": sender, "subject": f"[tm-signoff {doc['id']}]", "received": sent_at,
                                      "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
                                     for doc, sender in signoffs]}
            else:
                results.append({"op_id": op["op_id"], "status": "error", "data": {}})
                continue
            results.append({"op_id": op["op_id"], "status": "ok", "data": data})
        return {"schema": "tm:contract/receipt@1",
                "plan_sha256": (self.store / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
                "driver": "fixture", "run_at": (at + timedelta(minutes=1)).isoformat(timespec="seconds"),
                "results": results}

    def round(self, at: datetime) -> int:
        app.do_tick(self.store, now=at, root=self.root)
        st = self.state()
        docs = self.signoffs(st, at)
        receipt = self.receipt(st, at, docs)
        path = self.store / "receipts" / f"sim-{at:%Y%m%dT%H%M%SZ}.json"
        path.write_text(json.dumps(receipt, indent=1), encoding="utf-8", newline="\n")
        rep = app.do_ingest(self.store, path, now=at + timedelta(minutes=2), allowed_drivers=("fixture",), root=self.root)
        if not rep.ok:
            raise SimulationError(f"{at:%Y-%m-%d %H:%M}: ingest failed: " + "; ".join(rep.all_lines()))
        # A refusal is real behaviour (evidence that lapsed before signing): logged and counted, and the person acts on the
        # page again in a later round. The report lists every reason, so a simulator defect still shows.
        for line in rep.lines:
            if line.startswith("rejected: "):
                reason = line.split(": ", 2)[-1]
                self.rejections[reason] += 1
                self.notes.append(f"rejected ({reason})")
        self.wanted.clear()
        for doc, _ in docs:
            self.counts[doc["step"]] += 1
        return len(docs)

    # --- what the organisation does on its own initiative

    def _clearers(self, st: app.State) -> list[str]:
        """The clearers by their latest level (a level change moves them, the registration only starts them)."""
        return clearer_instructors(st.registrations, st.events, st.people)

    def _first_clearer(self, st: app.State) -> str | None:
        found = self._clearers(st)
        return found[0] if found else None

    def initiatives(self, at: datetime) -> list[str]:
        out: list[str] = []
        st = self.state()
        today = at.date()
        due = {d.step for d in app.due_steps(st, today)}
        if STEP_ROSTER_IMPORT in due:
            out.append(app.do_import_roster(self.store, self.store / "inputs" / "roster.yaml", now=at, root=self.root).summary)
            st = self.state()
        out += self._calibration(st, at)
        out += self._outcomes(st, at)
        self._cpd(st, today)
        self._course(st, today)
        self._adhoc(st, today)
        out += self._bench(st, at)
        out += self._override(st, at)
        return out

    def _bench(self, st: app.State, at: datetime) -> list[str]:
        """The head asks for a bench review of a struggling instructor after two quality triggers despite triggered
        coaching, as a teaching-quality concern, when no review of theirs is open or decided."""
        out = []
        reviewed = {b["instructor"] for b in records.bench(st.events)}
        triggered = Counter(e["subject_uri"] for e in st.events if e["kind"] == "check"
                            and e["payload"].get("step") == "tm:step/quality-review" and e["payload"].get("result") == "trigger")
        for inst, n in sorted(triggered.items()):
            if n >= 2 and PERSONA.get(inst) == "struggling" and inst not in reviewed:
                opened = request_bench(self.store, instructor=inst, concern="teaching-quality", now=at, root=self.root)
                out.append(f"request-bench: {opened.bench}")
        return out

    def _calibration(self, st: app.State, at: datetime) -> list[str]:
        """Phase 2 rehearsal: the founding clearers score three pre-scored recordings in the first weeks. After that a
        renewal or a lapse goes through the head's recalibration page like any other page (decision 0024)."""
        clearers = self._clearers(st)
        if len(clearers) < 2 or at.date() >= self.start + timedelta(weeks=10) \
                or (self.exercises and (at.date() - self.exercises[-1]).days < 14):
            return []
        passes = records.calibrations(st.events)
        need = [c for c in clearers if len(passes.get(c, [])) < 3]
        if not need:
            return []
        group = need if len(need) >= 2 else sorted(set(need) | set(clearers[:2]))
        opened = open_exercise(self.store, unit=UNIT, recording_ref=f"recordings/sim-{at:%Y%m%d}.mp4", observers=group,
                               reference=self.store / "inputs" / "calibration-reference.yaml", now=at, root=self.root)
        self.exercises.append(at.date())
        if self.first_exercise is None:
            self.first_exercise = opened.exercise
        return [f"open-exercise: {opened.exercise} for {len(group)} clearer(s)"]

    def _outcomes(self, st: app.State, at: datetime) -> list[str]:
        """On the first weekday of a month, the export of last month's deliveries (two per delivering instructor)."""
        today = at.date()
        month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        if today.day > 3 or month in self.exported or today - timedelta(days=28) < self.start:
            return []
        self.exported.add(month)
        first = date.fromisoformat(f"{month}-01")
        deliveries = []
        rules_doc = load_standards(self.root)["rules"]
        for i in INSTRUCTORS:
            uri = _uri(i.slug)
            lo, hi = OUTCOME_DELTA[i.persona]
            for n in range(2):
                day = first + timedelta(days=7 + 9 * n)
                while day.weekday() > 4:
                    day += timedelta(days=1)
                mode = ("remote", "in-person")[n]
                # Scheduling runs the staffing check: a delivery it blocks went to someone else, so it has no outcome here.
                if staffing.check(st.events, {"instructor": uri, "unit": UNIT, "mode": mode, "date": day.isoformat()},
                                  rules_doc)["verdict"] == "block":
                    continue
                delta = lo + _h("outcome", uri, month, n) % (hi - lo + 1)
                learners = 16 + _h("learners", uri, month, n) % 5
                deliveries.append({"delivery_ref": f"sim-{month}-{i.slug}-{n + 1}", "instructor": uri, "unit": UNIT,
                                   "mode": mode, "delivered_on": day.isoformat(),
                                   "learners_assessed": learners, "score": BASELINE + delta, "baseline": BASELINE})
        if not deliveries:
            return []
        doc = {"schema": "tm:contract/outcome-import@1", "source": "Generated by teachermodel dev-simulate",
               "exported_at": at.isoformat(timespec="seconds"), "deliveries": deliveries}
        path = self.store / "inputs" / f"outcomes-{month}.yaml"
        path.write_text(_dump(doc), encoding="utf-8", newline="\n")
        res = import_outcomes(self.store, path, now=at, root=self.root)
        return [f"import-outcomes {month}: {res.appended} outcome event(s)"]

    def _cpd(self, st: app.State, today: date) -> None:
        """From the 10th of each month, one CPD activity per instructor whose log-activity page is open."""
        if today.day < 10:
            return
        month = today.strftime("%Y-%m")
        for d in app.due_steps(st, today):
            if d.step == LOG_ACTIVITY and (d.subject, month) not in self.cpd_months:
                self.cpd_months.add((d.subject, month))
                self.wanted.add((d.step, d.subject))

    def _course(self, st: app.State, today: date) -> None:
        """A participant whose train-the-trainer step is open has taken the course by then: every session is recorded,
        so the completion page exists (it is not built while a session is missing)."""
        for d in app.due_steps(st, today):
            if d.step == TRAIN_THE_TRAINER:
                course.record_generated(self.store, d.subject, today, st.registrations, self.root)

    def _adhoc(self, st: app.State, today: date) -> None:
        """Once a quarter, from its second month, one ad-hoc observer for the open candidate with the fewest observations."""
        quarter = f"{today.year}Q{(today.month - 1) // 3 + 1}"
        if quarter in self.adhoc_quarters or (today.month - 1) % 3 == 0:
            return
        open_ones = sorted(d.subject for d in app.due_steps(st, today) if d.step == ASSIGN_OBSERVER)
        if not open_ones:
            return
        observed = Counter(e["payload"].get("instructor") for e in st.events if e["kind"] == "observation")
        pick = min(open_ones, key=lambda c: (observed[self.instructor_of(st, c)], c))
        self.adhoc_quarters.add(quarter)
        self.wanted.add((ASSIGN_OBSERVER, pick))

    def _override(self, st: app.State, at: datetime) -> list[str]:
        """After a bench decision returns someone to co-teaching, one override for a delivery a week later, and the
        instructor appeals the decision once (decision 0021)."""
        out = []
        for e in st.events:
            if e["kind"] == "bench_decision" and e["payload"].get("decision") == "return-to-co-teaching":
                inst = e["payload"]["instructor"]
                if inst not in self.appeals:
                    self.appeals[inst] = e["id"]
                    self.wanted.add((REPLY, inst))
                    out.append(f"appeal: {inst} appeals {e['payload']['bench']}")
        for b in records.bench(st.events):
            decided = (b["decision"] or {}).get("decision")
            if decided == "return-to-co-teaching" and b["instructor"] not in self.overridden:
                self.overridden.add(b["instructor"])
                day = at.date() + timedelta(days=7)
                opened = request_override(self.store, instructor=b["instructor"], unit=UNIT, mode="remote",
                                          date=day.isoformat(), note="Simulated: the cleared lead is on leave.",
                                          now=at, root=self.root)
                out.append(f"request-override: {opened.override} for {day.isoformat()}")
        return out


def _weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def simulate(store: Path | str, *, weeks: int = 26, end: date | None = None, reset: bool = False, root: Path = ROOT,
             progress: Callable[[str], None] | None = None) -> app.Report:
    """Build the simulated store and run the calendar. Returns a report: event counts by kind and sign-offs by step."""
    if weeks < 1:
        raise SimulationError("--weeks must be at least 1")
    end = end or datetime.now(timezone.utc).date()
    start = end - timedelta(weeks=weeks)
    start -= timedelta(days=start.weekday())  # a Monday
    store = Path(store)
    init_store(store, start, end, reset=reset, root=root)
    run = _Run(store.resolve(), root, start)
    log = (store / LOG).open("w", encoding="utf-8", newline="\n")
    try:
        for day in _weekdays(start, end):
            morning = datetime.combine(day, ROUNDS[0], tzinfo=timezone.utc)
            run.notes = []
            n = run.round(morning)
            notes = run.initiatives(morning + timedelta(hours=2))
            n += run.round(datetime.combine(day, ROUNDS[1], tzinfo=timezone.utc))
            line = f"{day.isoformat()} {n} sign-off(s)" + "".join(f"; {x}" for x in [*notes, *run.notes])
            log.write(line + "\n")
            if progress:
                progress(line)
    finally:
        log.close()
    from . import views

    views.build(store, root=root)  # the index and the read views, as a developer would open them
    st = run.state()
    kinds = Counter(e["kind"] for e in st.events)
    rep = app.Report(lines=[f"events: {', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))}",
                            f"sign-offs by step: {', '.join(f'{util.slug(s)} {v}' for s, v in sorted(run.counts.items()))}",
                            *[f"rejected {v}x: {r}" for r, v in sorted(run.rejections.items())]])
    rep.summary = (f"dev-simulate: {start.isoformat()} to {end.isoformat()}, {sum(kinds.values())} event(s), "
                   f"{sum(run.counts.values())} sign-off(s) in {store}")
    return rep
