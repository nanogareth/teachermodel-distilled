"""End-to-end run of the workflow tooling on fictional data (plan 2026-10-24, Task 12).

    py scripts/e2e_fictional.py [--keep] [--work-dir DIR]

Builds a private store in a fresh temp directory outside the repo (fictional settings, fictional people
at example.com, the example roster) and drives the real app functions with a fixture driver: tick,
fixture receipts that carry sign-offs built from each due page's embedded `tm-data`, legal's verification of
the fictional base privacy profile, the DPIA, retention entries and their approval, roster import (refused until all
of those are done), the privacy
notice, a negative stage (editing the profile after verification reopens the verification and blocks retention
and the notice until it is re-verified), a strict `mail.sent` check per instructor, the gap list, and the
W1 onboarding chain through to the level change. The roster has Irish instructors (the base profile covers IE), a
Californian contractor (a fictional overlay coded US-CA) and a German partner (no profile): the Irish proceed on the
base notice, the Californian waits for the overlay's profile verification, DPIA delta, retention check and notice
variant (`2026-11-us-ca`) and for a `mail.sent` hit on the variant tag, and the German stays blocked ("no profile
for DE"), so their W1 never opens. Then increment 2, through the same real ingest. Bootstrap (decision 0017): the
professional and the contractor are the programme's founding clearers, entered at the roster's baseline level clearer
with no clearance, and the levels workflow proposes no move for them. W5 (`open-exercise` for the two, both score, a
`calibration` event each); W3 (a clearer dry-runs the lead-observed SME's candidate) and W2 (observers proposed, the coordinator approves the batch, two observers observe blind,
the instructor self-assesses, release writes the `observation` events); the `records` adapters return the rules.py
dataclasses for all three. W4: evidence-ready opens a round for the SME's in-person candidate, a founding round since
nobody holds the unit yet, two different calibrated clearers decide cleared, the head's step is skipped, issue writes the `clearance` event marked founding, the staffing check flips from
block to ok for that unit and mode, the gap list drops that delivery, and the head approves the proposed level change to
cleared; on the SME's hybrid candidate the clearers disagree and the head resolves it with a conditional clearance (the
staffing check warns, exit 3, within 30 days of the recheck). Then the SME's own path on: W5 with the professional, the
levels workflow proposes the SME for clearer and the head approves, and the SME, now a clearer, is proposed to observe the
professional's candidate and observes it.
Then increment 3: two outcome summaries 10+ points below baseline (at least 15 learners each) are imported and the quality
review writes a score-drop trigger for the SME; once the professional is named the SME's coach (people.yaml `coaches`), the
next coaching cycle opens triggered, and the coach observes, gives feedback, sets a practice task and re-observes through
ingest, and the cycle closes with the change in the focus domains, closing the CPD gaps the SME's W2 observations seeded;
the SME logs one CPD activity, and the cycle's close opens the next one (standard: the trigger was used). Nothing is
sampled while 2026Q4 is open; on the first run after it closed the quarter's audit sample is drawn once, over all its live
observations; the second observer of one sampled observation scores it from the recording and the result agrees. Finally the head requests a bench review of the SME: the evidence pack
is written with the real records of the quality loop, bench-ready holds, and the head decides return-to-co-teaching, which
drops the SME's level to co-deliver and, from the day of the decision, blocks the staffing check ("bench decision: returned
to co-teaching"). The head then overrides that block for one delivery: `request-override` for a future date, the head's
`override-decision` approves, and the staffing check is ok for exactly that date ("override <id>" in the reasons) and blocks the
day after; the reason and the requester's note stay out of the log. A second bench review ends in an exit, which blocks staffing
the same way ("bench decision: exit"), closes the SME's candidates and changes no level. W11 (partners) and W12 (unit
authors) are covered by the unit tests.
After every stage it asserts the expected step is no longer due. Nothing in the repo is written: the standards, contracts and decisions are copied to a temp
root (so the privacy files, the retention entries and decision 0005 can be edited there), and the script checks
at the end that the real files are unchanged. The privacy files in the temp root are the fictional fixtures of
tests/fixtures/privacy, never the AI-drafted profiles.

The fixture driver is allowed only here, through the `allowed_drivers` keyword of `app.do_ingest`; the
CLI never accepts it. Exit status 0 when every stage passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
try:
    import teachermodel  # noqa: F401
except ImportError:  # run straight from a checkout without `pip install -e .`
    sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from teachermodel import app, config, course, devsign, events, records, rules, setup, staffing, workflow  # noqa: E402
from teachermodel.flows import audit, bench, calibration, clearance, cpd, dry_run, override, quality  # noqa: E402
from teachermodel.standards import check_standards, domain_ids, load_standards  # noqa: E402

PROGRAMME = "tm:programme/teachermodel"
SME = "tm:instructor/k7m2q"
PROFESSIONAL = "tm:instructor/p3x9d"
CONTRACTOR = "tm:instructor/c5w1t"
PARTNER = "tm:instructor/r8n4h"
FOUNDERS = (PROFESSIONAL, CONTRACTOR)  # the programme's founding clearers: roster level clearer, no clearance (decision 0017)
FIXTURE_DRIVERS = ("connector", "graph", "fixture")
VERIFIED = "tm:step/base-profile-verified"
ROPA_APPROVED = "tm:step/ropa-approved"
DPIA = "tm:step/dpia-screening"
RETENTION = "tm:step/retention-approved"
NOTICE_APPROVED = "tm:step/notice-approved"
US_CA = "tm:jurisdiction/us-ca"
DE = "tm:jurisdiction/de"
PROFILE_PRESENT = "tm:step/profile-present"
PROFILE_VERIFIED = "tm:step/profile-verified"
RETENTION_CHECK = "tm:step/retention-check"
DELTA_CHECK = "tm:step/dpia-delta-check"
DELTA = "tm:step/dpia-delta"
VARIANT = "tm:step/notice-variant"
VARIANT_APPROVED = "tm:step/variant-approved"
VARIANT_ID = "2026-11-us-ca"
UNIT = "sl:unit/example-agent-loop@1"
SME_CANDIDATE = "tm:candidate/k7m2q--example-agent-loop-1--in-person"  # the lead-observed SME engineer's candidate
CLEARER_PERSON = "tm:person/clearer-1"  # a clearer who is not an instructor: dry-runs only
STEP_SCORE = "tm:step/calibration-score"
STEP_APPROVED = "tm:step/assignments-approved"
STEP_OBSERVE = "tm:step/observe"
STEP_SELF = "tm:step/self-assessment"
STEP_DRY_RUN = "tm:step/dry-run"
EVIDENCE, D1, D2, HEAD, ISSUE = (f"tm:step/{s}" for s in (
    "evidence-ready", "clearer-decision-1", "clearer-decision-2", "head-resolves", "issue"))
LEVELS = "tm:step/levels-decided"
HOT = "tm:person/hot-1"
SME_HYBRID = "tm:candidate/k7m2q--example-agent-loop-1--hybrid"
PROFESSIONAL_CANDIDATE = "tm:candidate/p3x9d--example-agent-loop-1--in-person"
QUALITY_REVIEW = "tm:step/quality-review"
COACH_OBSERVE, COACH_FEEDBACK, PRACTICE, COACH_REOBSERVE, CYCLE_CLOSE = (f"tm:step/{s}" for s in (
    "coach-observe", "coach-feedback", "practice-task", "coach-reobserve", "cycle-close"))
CPD_PLAN, LOG_ACTIVITY = "tm:step/cpd-plan", "tm:step/log-activity"
DRAW_SAMPLE, SECOND_SCORE, AUDIT_RESULT = "tm:step/draw-sample", "tm:step/second-score", "tm:step/audit-result"
BENCH_PACK, BENCH_READY, BENCH_DECISION = "tm:step/evidence-pack", "tm:step/bench-ready", "tm:step/bench-decision"
OVERRIDE_DECISION = "tm:step/override-decision"
GAP_LIST_APPROVED = "tm:step/gap-list-approved"
# The professional coaches the SME from the coaching stage on (people.yaml `coaches`, decision 0014); added then, so that no
# cycle opens during the earlier stages.
COACH_ROW = {"person": "tm:person/coach-1", "name": "Coby Coach", "email": "coby.coach@example.com", "roles": ["coach"],
             "instructor": PROFESSIONAL, "coaches": [SME]}
T0 =datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
AUDIT_DAY = datetime(2027, 1, 4, 7, 0, tzinfo=timezone.utc)  # the first run after 2026Q4 closed (tick() moves on an hour)
EXAMPLE_ROSTER = REPO / "standards" / "templates" / "roster.example.yaml"

SETTINGS = {
    "schema": "tm:contract/settings@1",
    "library": "TeacherModel Private",
    "mailbox": "signoffs@example.com",
    "it_email": "it.requests@example.com",
    "dpo_email": "dpo@example.com",
    "notice_version": "2026-11",
}
# One fictional person per role the workflows need, two coordinators.
PEOPLE = [
    {"person": "tm:person/it-1", "name": "Pat Itperson", "email": "pat.it@example.com", "roles": ["it"]},
    {"person": "tm:person/dpo-1", "name": "Dana Dataofficer", "email": "dana.dpo@example.com", "roles": ["dpo"]},
    {"person": "tm:person/legal-1", "name": "Lena Legalcounsel", "email": "legal.lena@example.com",
     "roles": ["legal"]},
    {"person": "tm:person/owner-1", "name": "Olive Owner", "email": "olive.owner@example.com",
     "roles": ["programme-owner"]},
    {"person": "tm:person/hot-1", "name": "Hal Headtraining", "email": "hal.head@example.com",
     "roles": ["head-of-training"]},
    {"person": "tm:person/eng-manager-1", "name": "Maxine Manager", "email": "maxine.mgr@example.com",
     "roles": ["manager"]},
    {"person": "tm:person/partner-lead-1", "name": "Lee Partnerlead", "email": "lee.pl@example.com",
     "roles": ["partner-lead"]},
    {"person": "tm:person/coord-1", "name": "Cora Coordinator", "email": "cora.coord@example.com",
     "roles": ["coordinator"]},
    {"person": "tm:person/coord-2", "name": "Kit Coordinator", "email": "kit.coord@example.com",
     "roles": ["coordinator"]},
    # A dry-run clearer is mapped to an instructor who is a clearer by level and calibrated (decision 0012, amended): the role
    # alone is not clearer status. Cleo signs as herself; the mapping to the contractor is what makes her one.
    {"person": CLEARER_PERSON, "name": "Cleo Clearer", "email": "cleo.clearer@example.com", "roles": ["clearer"],
     "instructor": CONTRACTOR},
]
# Fictional placeholders for the temp retention file, not advice and not proposals: each fictional purpose
# keeps its data categories (ids from setup.data_categories) for these months.
RETENTION_PURPOSES = {
    "tm:purpose/e2e-clearance": {
        "identity-data": 6, "pseudonymous-identifier": 84, "employment-and-training-data": 24,
        "delivery-data": 12, "performance-data": 24, "record-of-actions": 84,
    },
    "tm:purpose/e2e-quality-review": {"performance-data": 36},
}
FIXTURES = REPO / "tests" / "fixtures" / "privacy"
BASE_URI = "tm:jurisdiction/xx"
PURPOSES = [
    {"id": "tm:purpose/e2e-clearance", "name": "Clearance decisions (fictional)",
     "description": "Deciding whether an instructor may teach a unit, from observations of their teaching.",
     "workflows": ["tm:workflow/onboarding"], "categories": list(RETENTION_PURPOSES["tm:purpose/e2e-clearance"]),
     "proposed_basis": {BASE_URI: {"basis": "legitimate-interests",
                                   "reason": "The training function must show that instructors were assessed.",
                                   "notice_text": "Fictional notice sentence: we use observations to clear you to teach."}}},
    {"id": "tm:purpose/e2e-quality-review", "name": "Quality review (fictional)",
     "description": "Comparing delivery outcomes with the cohort baseline to decide where coaching should focus.",
     "workflows": ["tm:workflow/setup"], "categories": list(RETENTION_PURPOSES["tm:purpose/e2e-quality-review"]),
     "proposed_basis": {BASE_URI: {"basis": "legitimate-interests",
                                   "reason": "Finding where coaching should focus; never a bench trigger alone.",
                                   "notice_text": "Fictional notice sentence: we use totals to decide where coaching helps."}}},
]
for _purpose in PURPOSES:
    _purpose["proposed_basis"][US_CA] = {
        "basis": "disclosed-purpose", "reason": "Fictional: disclosed at collection and kept to that purpose.",
        "notice_text": "Fictional notice sentence: we use this for the purpose above only."}
OVERLAY_TEMPLATE = """## For residents of Fictional State

### What we collect

<!-- element: categories-collected -->
The categories of personal information we collect about you are:

$held

### How long we keep them

$retention

### Why

$overlay_purposes
"""
DECISION_0005 = "Option 1: training-function use only. Fictional acceptance for the end-to-end script."


class StageFailed(AssertionError):
    """A stage's expectation did not hold."""


def expect(cond: object, message: str) -> None:
    if not cond:
        raise StageFailed(message)


def _slug(uri: str) -> str:
    return uri.split("/", 1)[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Want:
    """A sign-off to produce from the page for (step, subject)."""

    step: str
    subject: str = PROGRAMME
    person: str | None = None  # pick this signer's page when there is one page per signer
    decision: str = "approve"
    fields: dict[str, Any] = field(default_factory=dict)  # overrides the generated answers
    sender: str | None = None  # the mailbox that sends it, when not the signer's own (a coach signs from the coach row's)


class Harness:
    def __init__(self, work: Path) -> None:
        self.work = work
        self.private = work / "private"
        self.root = work / "root"
        self.t = T0
        self.stage = 0
        self.lines: list[str] = []
        self.signoff_ids: list[str] = []
        self.rounds = 0

    # --- setup ---------------------------------------------------------------------------------

    def build(self) -> None:
        config.assert_outside_repo(self.work)
        (self.private / "identities").mkdir(parents=True)
        (self.private / "settings.yaml").write_text(yaml.safe_dump(SETTINGS), encoding="utf-8")
        (self.private / "identities" / "people.yaml").write_text(
            yaml.safe_dump({"schema": "tm:contract/people@1", "people": PEOPLE}), encoding="utf-8")
        for sub in ("standards", "contracts", "docs/decisions", "docs/specs"):  # the ROPA cites both
            shutil.copytree(REPO / sub, self.root / sub)
        roster = yaml.safe_load(EXAMPLE_ROSTER.read_text(encoding="utf-8"))
        for row in roster["instructors"]:
            if row["instructor"] in FOUNDERS:  # the founding clearers enter at the roster's baseline level (decision 0017)
                row["level"] = "clearer"
        (self.work / "roster-in.yaml").write_text(yaml.safe_dump(roster, sort_keys=False), encoding="utf-8")
        privacy_dir = self.root / "standards" / "privacy"
        shutil.rmtree(privacy_dir)
        (privacy_dir / "jurisdictions").mkdir(parents=True)
        profile = yaml.safe_load((FIXTURES / "jurisdiction-base.yaml").read_text(encoding="utf-8"))
        profile["lawful_bases"] = {p["id"]: ["legitimate-interests"] for p in PURPOSES}
        profile["codes"] = ["IE"]  # the base covers Ireland; the roster's US-CA and DE instructors need overlays
        self.profile = privacy_dir / "jurisdictions" / "xx.yaml"
        self.profile.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
        overlay = yaml.safe_load((FIXTURES / "jurisdiction-overlay.yaml").read_text(encoding="utf-8"))
        overlay.update(
            id=US_CA, name="Fictional State (test overlay coded US-CA)", codes=["US-CA"],
            lawful_bases={p["id"]: ["disclosed-purpose"] for p in PURPOSES},
            retention_limits=[{"category": "performance-data", "max_months": 36, "citation": "Fictional Privacy Rights Act s.10"}],
            dpia_triggers=[{"criterion": "ca-sell-or-share", "citation": "Fictional Privacy Rights Act s.21"}])
        self.overlay = privacy_dir / "jurisdictions" / "us-ca.yaml"
        self.overlay.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
        (self.root / "standards" / "templates" / "privacy-notice-us-ca.md").write_text(
            OVERLAY_TEMPLATE, encoding="utf-8", newline="\n")
        # The real templates are drafts and cannot be rendered; the fictional base profile gets a finished one.
        shutil.copy2(FIXTURES / "privacy-notice.md", self.root / "standards" / "templates" / "privacy-notice.md")
        (privacy_dir / "purposes.yaml").write_text(
            yaml.safe_dump({"schema_version": 1, "status": "draft", "purposes": PURPOSES}, sort_keys=False),
            encoding="utf-8")
        errors = check_standards(self.root)
        expect(not errors, f"the fictional privacy files do not validate: {errors}")

    # --- reporting -----------------------------------------------------------------------------

    def done(self, label: str, detail: str = "") -> None:
        self.stage += 1
        line = f"ok  {self.stage:02d} {label}" + (f": {detail}" if detail else "")
        self.lines.append(line)
        print(line)

    # --- state ---------------------------------------------------------------------------------

    def state(self) -> app.State:
        return app.load_state(self.private, self.root)

    def log(self) -> list[dict[str, Any]]:
        return app.read_events(self.private)

    def due(self) -> set[tuple[str, str]]:
        return {(d.step, d.subject) for d in app.due_steps(self.state(), self.t.date())}

    def expect_due(self, step: str, subject: str = PROGRAMME) -> None:
        expect((step, subject) in self.due(), f"{step} for {subject} should be due")

    def expect_not_due(self, step: str, subject: str = PROGRAMME) -> None:
        expect((step, subject) not in self.due(), f"{step} for {subject} is still due")

    def steps_done(self, step: str) -> list[dict[str, Any]]:
        return [e for e in self.log() if e["kind"] == "step" and e["payload"].get("step") == step]

    # --- driving the app -----------------------------------------------------------------------

    def advance(self) -> datetime:
        self.t += timedelta(hours=1)
        return self.t

    def tick(self) -> datetime:
        now = self.advance()
        app.do_tick(self.private, now=now, root=self.root)
        return now

    def email_of(self, uri: str) -> str:
        st = self.state()
        for row in (st.roster or {}).get("instructors", []):  # an instructor's own mailbox, not a mapped person's
            if row["instructor"] == uri:
                return row["identity"]["email"]
        for email, entries in st.identities.items():
            if any(ident["uri"] == uri for ident in entries):
                return email
        raise StageFailed(f"no identity for {uri}")

    def owner_email(self) -> str:
        return next(p["email"] for p in PEOPLE if "programme-owner" in p["roles"])

    def signoff_doc(self, want: Want, now: datetime) -> tuple[dict[str, Any], str]:
        """The sign-off a person would return from the generated page, and the sender's address."""
        pattern = f"{_slug(want.step)}--{_slug(want.subject)}--*.html".lower()  # page stems are lowercase (app.page_stem)
        found = sorted(p for p in (self.private / "pages").glob(pattern) if p.name.startswith(pattern[:-6]))
        if want.person:
            found = [p for p in found if p.name.endswith(f"--{_slug(want.person)}.html".lower())]
        expect(found, f"no page for {want.step} {want.subject} {want.person or ''}".strip())
        page = found[0].read_text(encoding="utf-8")
        m = re.search(r'<script type="application/json" id="tm-data">(.*?)</script>', page, re.S)
        expect(m, f"{found[0].name} has no tm-data block")
        data = json.loads(m.group(1))
        self.rounds += 1
        sid = hashlib.sha256(f"{data['step']}|{data['subject_uri']}|{data['signer']}|{self.rounds}".encode()
                             ).hexdigest()[:16]
        doc = {
            "schema": "tm:contract/signoff@1", "id": sid, "step": data["step"], "subject_uri": data["subject_uri"],
            "input_sha256": data["input_sha256"], "decision": want.decision,
            "fields": self.answers(data, now.date()) | want.fields, "signer": data["signer"],
            "signed_at": (now + timedelta(seconds=30)).isoformat(timespec="seconds"),
            "page_template_sha256": data["page_template_sha256"],
        }
        return doc, want.sender or self.email_of(data["signer"])

    @staticmethod
    def answers(data: dict[str, Any], today: Any) -> dict[str, Any]:
        """What a person fills in (devsign.answers, shared with `teachermodel dev-autosign`)."""
        return devsign.answers(data, today, note="Fictional evidence")

    def receipt(self, plan: dict[str, Any], now: datetime, signoffs: list[tuple[dict[str, Any], str]],
                library_ok: bool, sent_by: dict[str, str], tags: dict[str, str] | None = None) -> dict[str, Any]:
        """A fixture driver's answer to every op of the plan."""
        sent_at = (now + timedelta(seconds=45)).isoformat(timespec="seconds")
        results = []
        for op in plan["ops"]:
            if op["op"] == "site.library":
                data: dict[str, Any] = {"exists": library_ok}
            elif op["op"] == "mail.sent":
                to = op["args"]["to"]
                sender = sent_by.get(to.lower())
                tag = (tags or {}).get(to.lower(), op["args"]["tag"])
                msgs = [] if sender is None else [{
                    "sender": sender, "to": [to], "subject": f"Privacy notice: instructor development {tag}",
                    "sentDateTime": sent_at}]
                data = {"messages": msgs}
            elif op["op"] == "mail.tagged":
                data = {"messages": [{
                    "sender": sender, "subject": f"[tm-signoff {doc['id']}]", "received": sent_at,
                    "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
                    for doc, sender in signoffs]}
            else:
                raise StageFailed(f"the fixture driver has no answer for op {op['op']}")
            results.append({"op_id": op["op_id"], "status": "ok", "data": data})
        return {
            "schema": "tm:contract/receipt@1",
            "plan_sha256": (self.private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
            "driver": "fixture", "run_at": (now + timedelta(minutes=1)).isoformat(timespec="seconds"),
            "results": results,
        }

    def round(self, wants: list[Want] = (), *, library_ok: bool = False,
              sent_by: dict[str, str] | None = None, tags: dict[str, str] | None = None) -> app.Report:
        """tick, then one fixture receipt answering the plan (with the wanted sign-offs), then ingest."""
        now = self.tick()
        plan = json.loads((self.private / "plans" / "latest.json").read_text(encoding="utf-8"))
        signoffs = [self.signoff_doc(w, now) for w in wants]
        doc = self.receipt(plan, now, signoffs, library_ok, sent_by or {}, tags)
        path = self.private / "receipts" / f"stage-{self.stage + 1:02d}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.t = now + timedelta(minutes=2)
        rep = app.do_ingest(self.private, path, now=self.t, allowed_drivers=FIXTURE_DRIVERS, root=self.root)
        expect(rep.ok, f"ingest failed: {rep.summary}")
        expect("0 rejected" in rep.summary, f"ingest rejected something: {rep.all_lines()}")
        have = {e["payload"].get("signoff_id") for e in self.log() if e["kind"] == "signoff"}
        for d, _ in signoffs:
            expect(d["id"] in have, f"sign-off {d['id']} ({d['step']}) is not a signoff event")
            self.signoff_ids.append(d["id"])
        return rep

    def refused_round(self, wants: list[Want], reason: str) -> app.Report:
        """Like `round`, but every sign-off must be rejected at ingest for `reason` and none may become an event."""
        now = self.tick()
        plan = json.loads((self.private / "plans" / "latest.json").read_text(encoding="utf-8"))
        signoffs = [self.signoff_doc(w, now) for w in wants]
        doc = self.receipt(plan, now, signoffs, False, {})
        path = self.private / "receipts" / f"stage-{self.stage + 1:02d}-refused.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.t = now + timedelta(minutes=2)
        rep = app.do_ingest(self.private, path, now=self.t, allowed_drivers=FIXTURE_DRIVERS, root=self.root)
        expect(f"{len(wants)} rejected" in rep.summary, f"expected {len(wants)} rejection(s): {rep.all_lines()}")
        expect(any(reason in line for line in rep.lines), f"no rejection says {reason!r}: {rep.all_lines()}")
        have = {e["payload"].get("signoff_id") for e in self.log() if e["kind"] == "signoff"}
        expect(not any(d["id"] in have for d, _ in signoffs), "a rejected sign-off became a signoff event")
        expect(not any((self.private / "signoffs" / f"{d['id']}.json").exists() for d, _ in signoffs),
               "a rejected sign-off was stored")
        return rep


# --- stages ---------------------------------------------------------------------------------------


def stage_setup_steps(h: Harness) -> None:
    h.tick()
    expect(h.steps_done("tm:step/it-request") and h.steps_done("tm:step/ropa"), "it-request and ropa did not run")
    expect((h.private / "generated" / "it-request.eml").is_file(), "no IT request draft")
    for step in ("tm:step/it-done", VERIFIED, ROPA_APPROVED):
        h.expect_due(step)
    for step in ("tm:step/it-request", "tm:step/ropa", DPIA):
        h.expect_not_due(step)
    h.done("tick", "it-request and ropa generated; it-done, the profile verification and the ROPA approval await "
                   "sign-off, the DPIA waits")


def stage_it_done(h: Harness) -> None:
    h.round([Want("tm:step/it-done")])
    h.expect_not_due("tm:step/it-done")
    h.expect_due("tm:step/library-exists")
    h.done("it-done signed", "library-exists is now a verify step")


def stage_library(h: Harness) -> None:
    h.round(library_ok=False)  # a driver that finds no library does not complete the step
    h.expect_due("tm:step/library-exists")
    h.round(library_ok=True)
    h.expect_not_due("tm:step/library-exists")
    h.done("site.library", "a negative result leaves it open, an ok result completes it")


def stage_profile_verified(h: Harness) -> None:
    page = (h.private / "pages" / f"{_slug(VERIFIED)}--teachermodel--legal-1.html").read_text(encoding="utf-8")
    expect("first verification" in page, "the verification page should say it is the first")
    h.round([Want(VERIFIED)])
    h.expect_not_due(VERIFIED)
    h.expect_not_due(DPIA)  # the DPO has not approved the ROPA yet
    kept = sorted((h.private / "signoffs").glob("*.inputs.json"))
    expect(len(kept) == 1 and json.loads(kept[0].read_text(encoding="utf-8"))["step"] == VERIFIED,
           "the inputs of the verification were not kept for the next review")
    h.done("base-profile-verified signed", "legal signed the profile bytes; the DPIA still waits for the ROPA approval")


def stage_ropa_approved(h: Harness) -> None:
    h.expect_not_due(DPIA)
    page = (h.private / "pages" / f"{_slug(ROPA_APPROVED)}--teachermodel--dpo-1.html").read_text(encoding="utf-8")
    ropa = (h.private / "generated" / "ropa.md").read_text(encoding="utf-8")
    expect("exact record of processing" in page and ropa.splitlines()[0] in page,
           "the ROPA approval page should show the generated text")
    h.round([Want(ROPA_APPROVED)])
    h.expect_not_due(ROPA_APPROVED)
    h.expect_due(DPIA)
    h.done("ropa-approved signed", "the DPO approved the ROPA as written; the DPIA screening is now due")


def stage_dpia(h: Harness) -> None:
    dpia = "tm:step/dpia-screening"
    # a DPIA that is required or undecided must not unlock roster-import, however the document is labelled
    for answer in ("dpia-required", "needs-more-information"):
        h.refused_round([Want(dpia, fields={"dpo-decision": answer})], "DPIA required or undecided")
        h.expect_due(dpia)
        h.expect_not_due("tm:step/roster-import")
    # what the page itself produces for "DPIA required" is a request for changes: recorded, step still open
    h.round([Want(dpia, decision="changes", fields={"dpo-decision": "dpia-required"})])
    h.expect_due(dpia)
    h.expect_not_due("tm:step/roster-import")
    h.done("dpia-screening not cleared", "required or undecided answers are refused or leave the step open")

    h.round([Want(dpia, fields={"dpo-decision": "dpia-not-required"})])
    h.expect_not_due("tm:step/dpia-screening")
    h.expect_not_due("tm:step/roster-import")  # the retention approval is still missing
    h.done("dpia-screening signed", "roster-import still waits for the retention approval")


def stage_roster(h: Harness) -> None:
    h.tick()
    h.expect_due("tm:step/roster-import")  # the run only reports it; the roster file is a human input
    h.t += timedelta(hours=1)
    rep = app.do_import_roster(h.private, h.work / "roster-in.yaml", now=h.t, root=h.root)
    st = h.state()
    expect({SME, PROFESSIONAL, CONTRACTOR, PARTNER} <= set(st.subjects), "instructors not registered")
    h.expect_not_due("tm:step/roster-import")
    h.done("import-roster", rep.summary)


def stage_retention(h: Harness) -> None:
    """Retention entries live in the temp root; the repo's own file is never edited."""
    retention = h.root / "standards" / "retention.yaml"
    doc = yaml.safe_load(retention.read_text(encoding="utf-8"))
    expect(doc["entries"] == [], "the copied retention file should start with no entries")
    known = {c["id"] for c in setup.data_categories(h.root)}
    expect(known >= {c for cats in RETENTION_PURPOSES.values() for c in cats}, "a fictional category id is unknown")
    # Exercise the 0005 block: reopen it in the temp copy (the repo's record is accepted since 2026-10-24);
    # notice-text first falls due after the retention approval below.
    d0005 = next((h.root / "docs" / "decisions").glob("0005-*.md"))
    d0005.write_text(d0005.read_text(encoding="utf-8").replace("status: accepted", "status: proposed", 1),
                     encoding="utf-8", newline="\n")
    h.tick()
    expect(any("retention entries still empty" in line for line in app.do_pages(h.private, now=h.t, root=h.root).lines),
           "an empty retention table should refuse its page")
    h.expect_due(RETENTION)
    doc.update(status="approved", basis="fictional values for the end-to-end script")
    doc["entries"] = [
        {"category": category, "purpose": purpose, "period_months": months, "starts": "The engagement ends.",
         "reason": f"Fictional reason for keeping {category} for this purpose.", "basis": "legitimate-interests"}
        for purpose, cats in RETENTION_PURPOSES.items() for category, months in cats.items()
    ]
    retention.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    expect(not check_standards(h.root), "an approved retention table should cover every category and purpose")
    h.round([Want(RETENTION)])
    h.expect_not_due(RETENTION)
    h.expect_due("tm:step/roster-import")
    h.done("retention-approved signed", f"{len(doc['entries'])} entries taken from the temp retention file; "
                                       "roster-import is now due")


def stage_notice(h: Harness) -> None:
    h.tick()  # notice-text is due (retention is approved), and 0005 is only proposed in the temp decisions dir
    blocked = [e for e in h.log() if e["kind"] == "check" and e["payload"].get("step") == "tm:step/notice-text"
               and e["payload"].get("result") == "blocked"]
    expect(blocked and any("0005" in r for r in blocked[-1]["payload"]["reasons"]), "notice-text should be blocked on 0005")
    expect(not h.steps_done("tm:step/notice-text"), "notice-text rendered while 0005 is open")
    h.expect_due("tm:step/notice-text")
    d0005 = next((h.root / "docs" / "decisions").glob("0005-*.md"))
    text = d0005.read_text(encoding="utf-8")
    text = text.replace("status: proposed", "status: accepted", 1)
    text = re.sub(r"(^## Decision[ \t]*\n).*?(?=^## |\Z)", lambda m: m.group(1) + DECISION_0005 + "\n\n", text,
                  count=1, flags=re.S | re.M)
    d0005.write_text(text, encoding="utf-8", newline="\n")
    h.tick()
    out = h.steps_done("tm:step/notice-text")
    expect(out, "notice-text did not render once 0005 was accepted")
    notice = (h.private / out[-1]["payload"]["output"]).read_text(encoding="utf-8")
    expect("training-function use only" in notice.lower(), "the notice does not state the 0005 decision")
    expect("not set" not in notice and "No retention entries" not in notice, "the notice carries an unset retention")
    expect("Fictional reason for keeping performance-data" in notice, "the notice does not carry the entry reasons")
    expect("Clearance decisions (fictional)" in notice and "<!--" not in notice, "the notice lacks the purposes")
    h.expect_not_due("tm:step/notice-text")
    h.done("notice-text", "blocked while 0005 was open, rendered after it was accepted and periods were approved")

    h.round([Want(NOTICE_APPROVED)])
    h.expect_not_due(NOTICE_APPROVED)
    h.done("notice-approved signed", "the owner approved the exact text hash against the verified profile")


def stage_profile_edited(h: Harness) -> None:
    """Negative: an edit after verification reopens the verification and blocks retention and the notice."""
    h.profile.write_bytes(h.profile.read_bytes() + b"# edited after verification\n")
    h.tick()
    h.expect_due(VERIFIED)
    h.expect_not_due(RETENTION)
    h.expect_not_due(NOTICE_APPROVED)
    expect(not h.steps_done("tm:step/notice-drafts"), "notice drafts were made against an unverified profile")
    expect(not any(d.step == "tm:step/notice-drafts" for d in app.due_steps(h.state(), h.t.date())),
           "notice-drafts should wait for the notice approval")
    page = (h.private / "pages" / f"{_slug(VERIFIED)}--teachermodel--legal-1.html").read_text(encoding="utf-8")
    expect("first verification" not in page and "only comments or layout differ" in page,
           "the re-verification page should compare with the last verified version")
    h.done("profile edited after verification", "verification reopened; retention-approved and the notice are blocked")

    h.round([Want(VERIFIED)])
    h.expect_not_due(VERIFIED)
    h.expect_due(RETENTION)  # its approval covered the old profile
    h.expect_not_due(NOTICE_APPROVED)  # and the notice waits for retention in turn
    h.round([Want(RETENTION)])
    h.expect_not_due(RETENTION)
    h.expect_due(NOTICE_APPROVED)
    h.round([Want(NOTICE_APPROVED)])
    h.expect_not_due(NOTICE_APPROVED)
    h.done("re-verified", "verification, retention and the notice were approved again, in that order")


def draft_tag(h: Harness, uri: str) -> str | None:
    """The `[tm-notice ...]` tag in the subject of an instructor's draft, or None when there is no draft."""
    eml = h.private / "generated" / "notice-drafts" / f"{_slug(uri)}.eml"
    if not eml.is_file():
        return None
    m = re.search(rb"Subject: .*?(\[tm-notice [^\]]+\])", eml.read_bytes())
    return m.group(1).decode() if m else None


def stage_notice_sent(h: Harness) -> None:
    """The Irish instructors (the base profile covers IE) get the base notice; the others wait."""
    h.tick()
    drafts = {e["subject_uri"] for e in h.steps_done("tm:step/notice-drafts")}
    expect(drafts == {SME, PROFESSIONAL}, f"notice drafts for {sorted(drafts)}")
    for uri in drafts:
        eml = h.private / "generated" / "notice-drafts" / f"{_slug(uri)}.eml"
        expect(eml.is_file() and b"X-Unsent: 1" in eml.read_bytes(), f"{eml.name} is not an unsent draft")
        expect(draft_tag(h, uri) == "[tm-notice 2026-11]", f"{uri} is not tagged with the base notice")
        h.expect_not_due("tm:step/notice-drafts", uri)
        h.expect_due("tm:step/notice-sent", uri)
    for uri in (CONTRACTOR, PARTNER):  # waiting for an overlay variant that is not approved (CA) or has no profile (DE)
        h.expect_not_due("tm:step/notice-drafts", uri)
        expect(draft_tag(h, uri) is None, f"{uri} has a draft before their variant is approved")
    h.done("notice-drafts", "unsent .eml for the two Irish instructors on the base notice; US-CA and DE wait")

    owner = h.owner_email()
    emails = {u: h.email_of(u) for u in (SME, PROFESSIONAL)}
    sent = {emails[SME]: owner, emails[PROFESSIONAL]: "dana.dpo@example.com"}  # sent by someone other than the owner
    h.round(sent_by=sent)
    h.expect_not_due("tm:step/notice-sent", SME)
    h.expect_due("tm:step/notice-sent", PROFESSIONAL)
    h.done("mail.sent (strict)", "an owner-sent notice counts; a notice sent by someone else does not")
    h.round(sent_by={emails[PROFESSIONAL]: owner})
    h.expect_not_due("tm:step/notice-sent", PROFESSIONAL)
    notices = [e for e in h.log() if e["kind"] == "notice"]
    expect(len(notices) == 2 and {e["subject_uri"] for e in notices} == {SME, PROFESSIONAL}, "expected one notice each")
    expect({e["payload"]["notice_variant"] for e in notices} == {"2026-11"}, "the Irish notices carry the base variant")
    h.done("mail.sent (Irish)", "both Irish instructors have a notice event for the base notice")


def stage_gap_list(h: Harness) -> None:
    h.tick()
    out = h.steps_done("tm:step/gap-list")
    expect(out, "gap-list did not run")
    rows = json.loads((h.private / out[-1]["payload"]["output"]).read_text(encoding="utf-8"))["rows"]
    expect(rows, "the example roster delivers units with no clearance, so the gap list needs rows")
    h.expect_due("tm:step/gap-list-approved")
    keys = [r["key"] for r in rows]
    expect(len(keys) >= 2, "the negative stage needs at least two gap rows")
    for bad in ("reject", "unreviewed"):  # an approval whose rows are not all approved is refused
        mixed = {k: "approve" for k in keys} | {keys[0]: bad}
        h.refused_round([Want("tm:step/gap-list-approved", fields={"rows": mixed})], "batch rows not all approved")
        h.expect_due("tm:step/gap-list-approved")
    h.done("gap-list approval with a row not approved", "refused; the step stays open")
    h.round([Want("tm:step/gap-list-approved")])
    h.expect_not_due("tm:step/gap-list-approved")
    approvals = [e for e in h.log() if e["kind"] == "signoff"
                 and e["payload"]["step"] == "tm:step/gap-list-approved"]
    expect(len(approvals) == 1 and approvals[0]["payload"]["decision"] == "approve", "gap-list approval is not a signoff event")
    h.done("gap-list-approved signed", f"{len(rows)} gap row(s) agreed; phase 1 gate")


def stage_w1(h: Harness) -> None:
    """W1 of the Irish SME engineer, on the base notice. The Californian and the German have not started."""
    h.expect_due("tm:step/commitment-manager", SME)
    for uri in (CONTRACTOR, PARTNER):
        h.expect_not_due("tm:step/baseline-self-assessment", uri)
    h.expect_not_due("tm:step/commitment-partner-lead", PARTNER)
    h.round([Want("tm:step/commitment-manager", SME)])
    h.expect_not_due("tm:step/commitment-manager", SME)
    h.done("commitment signed", "the manager for the SME engineer, on the base notice (the Californian and German wait)")

    h.expect_due("tm:step/baseline-self-assessment", SME)
    h.round([Want("tm:step/baseline-self-assessment", SME)])
    h.expect_not_due("tm:step/baseline-self-assessment", SME)
    stored = [json.loads(p.read_text(encoding="utf-8")) for p in (h.private / "signoffs").glob("*.json")
              if not p.name.endswith(".inputs.json")]
    mine = [d for d in stored if d["step"] == "tm:step/baseline-self-assessment"]
    expect(len(mine) == 1 and mine[0]["signer"] == SME and mine[0]["fields"], "self-assessment not stored in signoffs/")
    h.done("baseline-self-assessment signed", "the instructor signed their own, scores kept in the private store")

    for step in ("tm:step/train-the-trainer", "tm:step/shadow-delivery", "tm:step/co-delivery"):
        h.expect_due(step, SME)
        if step == "tm:step/train-the-trainer":  # no completion page until every session is recorded
            expect(not app.PAGE_SPECS[step](h.state(), SME), "a completion page with sessions missing")
            course.record_generated(h.private, SME, h.t.date(), h.state().registrations, h.root)
        h.round([Want(step, SME, person="tm:person/coord-1")])
        h.expect_not_due(step, SME)
    h.done("coordinator steps signed", "train-the-trainer, shadow delivery and co-delivery recorded")

    st = h.state()
    expect(app.current_level(st, SME) == "co-deliver", "the level should still be co-deliver")
    h.expect_due("tm:step/lead-observed-level", SME)
    h.round([Want("tm:step/lead-observed-level", SME)])
    h.expect_not_due("tm:step/lead-observed-level", SME)
    st = h.state()
    changes = [e for e in h.log() if e["kind"] == "level_change" and e["subject_uri"] == SME]
    expect(app.current_level(st, SME) == "lead-observed", "the level did not move to lead-observed")
    last = changes[-1]
    expect(last["actor"] == "tm:person/hot-1" and last["payload"]["from"] == "co-deliver"
           and last["payload"]["basis"].startswith("signoff "), "level_change has the wrong shape")
    h.done("lead-observed-level signed", "level_change co-deliver to lead-observed, actor the signer")


def stage_candidates(h: Harness) -> None:
    """open-candidates: one candidate per unit x mode for instructors at lead-observed or higher. The professional (a founding
    clearer) had theirs from the first run after the roster import; the SME's open only after the level change."""
    h.tick()
    unit = "example-agent-loop-1"
    subjects = [e for e in h.log() if e["kind"] == "subject" and e["payload"]["subject_kind"] == "candidate"]
    opened = {e["subject_uri"] for e in subjects}  # the founding clearers' recalibrations (decision 0024) are not candidates
    want = {f"tm:candidate/p3x9d--{unit}--{m}" for m in ("in-person", "remote", "hybrid")} | {
        f"tm:candidate/k7m2q--{unit}--{m}" for m in ("in-person", "hybrid")}
    expect(opened == want, f"candidates opened: {sorted(opened)}")
    expect(len(subjects) == len(opened), "a candidate was opened twice")
    level_at = next(n for n, e in enumerate(h.log()) if e["kind"] == "level_change" and e["subject_uri"] == SME
                    and e["payload"]["to"] == "lead-observed")
    for n, e in enumerate(h.log()):
        if e["kind"] == "subject" and "k7m2q" in e["subject_uri"]:
            expect(n > level_at, "an SME candidate was opened before the level change")
    h.expect_not_due("tm:step/open-candidates")
    h.done("open-candidates", "5 candidates: the founding professional's three, the SME's two after lead-observed")


def log_index(h: Harness, kind: str, step: str, subject: str) -> int:
    for n, e in enumerate(h.log()):
        if e["kind"] == kind and e["subject_uri"] == subject and e["payload"].get("step") == step:
            return n
    raise StageFailed(f"no {kind} event for {step} {subject}")


def stage_overlay_us_ca(h: Harness) -> None:
    """The overlay for US-CA: profile present and verified, retention checked, the DPIA delta decided, the variant approved."""
    h.tick()
    expect(h.steps_done(PROFILE_PRESENT) and all(e["subject_uri"] == US_CA for e in h.steps_done(PROFILE_PRESENT)),
           "profile-present should be done for US-CA only")
    h.expect_due(PROFILE_VERIFIED, US_CA)
    h.expect_not_due(PROFILE_VERIFIED, DE)
    page = (h.private / "pages" / f"{_slug(PROFILE_VERIFIED)}--us-ca--legal-1.html").read_text(encoding="utf-8")
    expect("first verification" in page, "the overlay verification page should say it is the first")
    h.round([Want(PROFILE_VERIFIED, US_CA)])
    h.expect_not_due(PROFILE_VERIFIED, US_CA)
    h.tick()
    expect(h.steps_done(RETENTION_CHECK), "retention-check did not pass for the fictional overlay")
    expect(h.steps_done(DELTA_CHECK)[-1]["payload"]["delta"] == ["ca-sell-or-share"], "the delta should name the overlay trigger")
    h.expect_due(DELTA, US_CA)  # the overlay adds a trigger the base screening does not cover
    expect(not h.steps_done(VARIANT), "the variant rendered before the DPIA delta was decided")
    h.done("overlay profile verified", "legal signed the US-CA bytes; retention-check passed; the DPO is asked about the delta")

    h.refused_round([Want(DELTA, US_CA, fields={"dpo-decision": "dpia-required"})], "DPIA required or undecided")
    h.expect_due(DELTA, US_CA)
    h.round([Want(DELTA, US_CA, fields={"dpo-decision": "dpia-not-required"})])
    h.expect_not_due(DELTA, US_CA)
    h.tick()
    out = h.steps_done(VARIANT)
    expect(out and out[-1]["payload"]["notice_variant"] == VARIANT_ID, "the variant was not rendered")
    text = (h.private / out[-1]["payload"]["output"]).read_text(encoding="utf-8")
    expect(f"Version {VARIANT_ID}" in text and "For residents of Fictional State" in text and "<!--" not in text,
           "the variant lacks its version or the overlay section")
    h.expect_due(VARIANT_APPROVED, US_CA)
    h.done("dpia-delta decided, variant rendered", "a required DPIA is refused; 'not required' releases the variant text")

    h.round([Want(VARIANT_APPROVED, US_CA)])
    h.expect_not_due(VARIANT_APPROVED, US_CA)
    h.tick()
    expect(draft_tag(h, CONTRACTOR) == f"[tm-notice {VARIANT_ID}]", "the Californian draft should carry the variant tag")
    expect(draft_tag(h, SME) == "[tm-notice 2026-11]", "an Irish draft changed")
    h.expect_due("tm:step/notice-sent", CONTRACTOR)
    h.expect_not_due("tm:step/baseline-self-assessment", CONTRACTOR)  # W1 waits for the variant to be sent
    h.done("variant approved", f"the owner approved {VARIANT_ID}; the Californian draft carries its tag")

    owner, email = h.owner_email(), h.email_of(CONTRACTOR)
    h.round(sent_by={email: owner}, tags={email: "[tm-notice 2026-11]"})  # the base notice is not the variant
    h.expect_due("tm:step/notice-sent", CONTRACTOR)
    h.round(sent_by={email: owner})
    h.expect_not_due("tm:step/notice-sent", CONTRACTOR)
    (notice,) = [e for e in h.log() if e["kind"] == "notice" and e["subject_uri"] == CONTRACTOR]
    expect(notice["payload"]["notice_variant"] == VARIANT_ID, "the Californian notice event lacks the variant")
    h.done("mail.sent (variant)", "a mail with the base tag does not close notice-sent; the variant tag does")

    h.expect_due("tm:step/baseline-self-assessment", CONTRACTOR)
    h.round([Want("tm:step/baseline-self-assessment", CONTRACTOR)])
    h.expect_not_due("tm:step/baseline-self-assessment", CONTRACTOR)
    order = [log_index(h, "signoff", "tm:step/commitment-manager", SME), log_index(h, "signoff", VARIANT_APPROVED, US_CA),
             log_index(h, "notice", "tm:step/notice-sent", CONTRACTOR),
             log_index(h, "signoff", "tm:step/baseline-self-assessment", CONTRACTOR)]
    expect(order == sorted(order), f"the Californian W1 did not open after the variant was approved and sent: {order}")
    h.done("Californian W1", "opened only after the variant was approved and sent; the Irish SME engineer started earlier")


def stage_german_blocked(h: Harness) -> None:
    """DE has no profile: no overlay step passes profile-present, so the partner gets no draft and no W1."""
    h.tick()
    blocked = [e for e in h.log() if e["kind"] == "check" and e["subject_uri"] == DE
               and e["payload"].get("step") == PROFILE_PRESENT]
    expect(blocked and blocked[-1]["payload"]["reasons"] == ["no profile for DE"], "profile-present for DE should be blocked")
    h.expect_due(PROFILE_PRESENT, DE)
    for step in (PROFILE_VERIFIED, RETENTION_CHECK, DELTA, VARIANT, VARIANT_APPROVED):
        h.expect_not_due(step, DE)
    for step in ("tm:step/notice-drafts", "tm:step/notice-sent", "tm:step/commitment-partner-lead",
                 "tm:step/baseline-self-assessment"):
        h.expect_not_due(step, PARTNER)
    expect(draft_tag(h, PARTNER) is None, "the German partner has a notice draft")
    expect(not [e for e in h.log() if e["subject_uri"] == PARTNER and e["kind"] in ("signoff", "notice", "step")],
           "the German partner has a W1 or notice event")
    h.done("German partner blocked", "no profile for DE, so no variant, no draft and no W1")


def log_of(h: Harness, kind: str, subject: str | None = None) -> list[dict[str, Any]]:
    return [e for e in h.log() if e["kind"] == kind and (subject is None or e["subject_uri"] == subject)]


def seed_clearer(h: Harness, who: str) -> None:
    """`who` at level clearer with a passed calibration dated today (fictional seed data: the levels and calibration workflows
    would take weeks of the programme's time)."""
    stamp = h.t.isoformat(timespec="seconds")
    events.append(h.private / app.EVENT_LOG, events.make_event(
        "level_change", who, HOT, {"from": "lead-observed", "to": "clearer", "basis": "e2e seed"}, at=stamp))
    sid = hashlib.sha256(f"e2e seed calibration {who}".encode()).hexdigest()[:16]
    events.append(h.private / app.EVENT_LOG, events.make_event(
        "calibration", who, "tm:system/teachermodel",
        {"exercise": "tm:exercise/" + sid, "observer": who, "unit": UNIT, "rubric_version": "0.2.0", "within_one_share": 1.0,
         "exact_share": 1.0, "passed": True, "signoff_id": sid}, at=stamp))


def stage_founders(h: Harness) -> None:
    """The founding clearers (decision 0017): the professional and the contractor entered at the roster's baseline level,
    clearer, and hold no clearance. Nothing seeds one: W4 lets them decide in founding rounds while nobody else holds the
    unit. The levels workflow proposes no move for them (no clearance was ever held, no calibration has lapsed)."""
    h.tick()
    st = h.state()
    for who in FOUNDERS:
        expect(app.current_level(st, who) == "clearer", f"{who} is not at level clearer")
        changes = [e["payload"] for e in h.log() if e["kind"] == "level_change" and e["subject_uri"] == who]
        expect([(c["to"], c["basis"]) for c in changes] == [("clearer", "roster baseline")],
               f"{who}: the roster import should be their only level change: {changes}")
        expect(all("clearer" in i["roles"] for i in st.identities[h.email_of(who)] if i["uri"] == who),
               "a roster instructor at level clearer should hold the clearer role")
    expect(not log_of(h, "clearance"), "no clearance should be on record before W4")
    expect(level_rows(h) == [], f"level proposals: {level_rows(h)}")
    h.expect_not_due(LEVELS)
    h.done("founding clearers", "two roster clearers with no clearance; no level move proposed; nothing seeded")


def stage_founders_calibrated(h: Harness) -> None:
    """After W5 the founders are calibrated clearers holding no clearance: the observer pool, and still no level move."""
    h.tick()
    expect(level_rows(h) == [], f"level proposals: {level_rows(h)}")
    h.expect_not_due(LEVELS)
    h.done("founders calibrated", "both calibrated; still no clearance and no level move")


def level_rows(h: Harness) -> list[dict[str, Any]]:
    return json.loads((h.private / "generated" / "levels.json").read_text(encoding="utf-8"))["rows"]


def stage_w5_calibration(h: Harness) -> None:
    """Open an exercise for the two clearers (the CLI function), both score it through ingest, the result step writes a
    `calibration` event for each against the private reference."""
    reference = h.work / "reference.yaml"
    reference.write_text(yaml.safe_dump({d: 3 for d in domain_ids(h.root)}), encoding="utf-8")
    h.advance()
    opened = calibration.open_exercise(
        h.private, unit=UNIT, recording_ref="recordings/fictional-delivery-1.mp4", observers=[PROFESSIONAL, CONTRACTOR],
        reference=reference, now=h.t, root=h.root)
    expect(opened.created, "the exercise was not opened")
    exercise = opened.exercise
    h.round([Want(STEP_SCORE, exercise, person=PROFESSIONAL), Want(STEP_SCORE, exercise, person=CONTRACTOR)])
    expect(not log_of(h, "calibration"), "a calibration was written before the result step ran")
    h.tick()  # the result step: both observers have submitted
    found = {e["subject_uri"]: e["payload"] for e in log_of(h, "calibration")}
    expect(set(found) == {PROFESSIONAL, CONTRACTOR} and all(p["passed"] for p in found.values()),
           f"calibration events: {found}")
    expect(len(h.steps_done("tm:step/calibration-result")) == 1, "the result step should be done once")
    expect((STEP_SCORE, exercise) not in h.due(), "the scoring step is still due after the result")
    (opening,) = [e for e in log_of(h, "subject", exercise)]
    expect("scores" not in json.dumps(opening) and opening["payload"]["attrs"]["reference_key"].endswith(".reference.json"),
           "the exercise event should hold the reference key only")
    h.done("W5 calibration", "open-exercise for two clearers; both scored through ingest; two calibration events")


def stage_w3_dry_run(h: Harness) -> None:
    """A clearer who is not the instructor dry-runs the SME's candidate: a passed `dry_run` event."""
    h.round([Want(STEP_DRY_RUN, SME_CANDIDATE, person=CLEARER_PERSON)])
    (event,) = log_of(h, "dry_run", SME_CANDIDATE)
    p = event["payload"]
    expect(p["passed"] is True and p["instructor"] == SME and p["fallback_exercised"] and p["failure_injected"],
           f"the dry run did not pass: {p}")
    expect(event["actor"] == CLEARER_PERSON, "the dry run is not attributed to the clearer")
    h.expect_not_due(STEP_DRY_RUN, SME_CANDIDATE)
    h.done("W3 dry-run", "a passed dry_run event for the SME's candidate, with the unit's environment hash")


def sme_scores(h: Harness) -> dict[str, Any]:
    """The W2 observers' scores of the SME: the first two framework domains at 2, the rest at 4 (overall mean 3.2, every
    domain at least 2, so W4 still clears; the two low domains seed the CPD plan's gaps and set the coaching focus)."""
    ids = domain_ids(h.root)
    return {d: {"score": 2 if n < 2 else 4, "note": f"Fictional evidence for {d}."} for n, d in enumerate(ids)}


def stage_w2_observation(h: Harness) -> None:
    """propose-observations -> the coordinator approves the batch -> two observers observe (blind) -> release."""
    h.tick()
    proposal = h.private / "generated" / "observations" / f"{_slug(SME_CANDIDATE)}.json"
    expect(proposal.is_file() and h.steps_done("tm:step/propose-observations"), "no observation proposal for the SME")
    rows = json.loads(proposal.read_text(encoding="utf-8"))["rows"]
    observers = {r["attrs"]["observer"] for r in rows}
    expect(observers == {PROFESSIONAL, CONTRACTOR}, f"the proposed observers are {sorted(observers)}")
    h.expect_due(STEP_APPROVED, SME_CANDIDATE)
    h.done("propose-observations", "two clearers other than the instructor are proposed for the SME's candidate")

    h.round([Want(STEP_APPROVED, SME_CANDIDATE, person="tm:person/coord-1")])
    h.expect_not_due(STEP_APPROVED, SME_CANDIDATE)
    found = [e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "assignment"
             and e["payload"]["attrs"]["candidate"] == SME_CANDIDATE]
    expect(len(found) == 2, "approving the batch should open two assignments")
    first, second = sorted(found, key=lambda e: e["subject_uri"])
    h.tick()
    for e in found:
        h.expect_due(STEP_OBSERVE, e["subject_uri"])
        h.expect_due(STEP_SELF, e["subject_uri"])
    h.done("assignments-approved", "the coordinator approved the batch; two assignments are open")

    # The session is dated the day it is signed, after the observers' calibration (W4 counts an observation only if its
    # observer was calibrated on the observation date).
    h.round([Want(STEP_OBSERVE, first["subject_uri"], person=first["payload"]["attrs"]["observer"],
                  fields={"date": h.t.date().isoformat(), **sme_scores(h)})])
    h.tick()  # release waits for the second observer
    expect(not log_of(h, "observation"), "blind: an observation was released after the first observer only")
    h.expect_not_due(STEP_OBSERVE, first["subject_uri"])
    h.expect_due(STEP_OBSERVE, second["subject_uri"])
    h.done("observe (first observer)", "signed through ingest as the assigned observer; nothing released (blind)")

    h.round([Want(STEP_OBSERVE, second["subject_uri"], person=second["payload"]["attrs"]["observer"],
                  fields={"date": h.t.date().isoformat(), **sme_scores(h)}),
             Want(STEP_SELF, first["subject_uri"], person=SME)])
    h.tick()
    released = log_of(h, "observation", SME)
    expect(len(released) == 2, f"expected two observations after the second observer, found {len(released)}")
    expect({e["payload"]["observer"] for e in released} == observers, "the observations name the wrong observers")
    h.expect_not_due(STEP_SELF, first["subject_uri"])
    h.done("observe (second observer) and release", "the instructor self-assessed; both observations released together")


def stage_records(h: Harness) -> None:
    """The record adapters return the rules.py dataclasses for what the stages above wrote."""
    log = h.log()
    observed = records.observations(log)
    expect(len(observed) == 2 and all(isinstance(o, rules.Observation) for o in observed), f"observations: {observed}")
    expect({o.instructor for o in observed} == {SME} and all(o.unit == UNIT and o.lead for o in observed),
           "the observations are not the SME's lead observations")
    runs = records.dry_runs(log, dry_run.current_environment_hashes([UNIT], h.root))
    expect(len(runs) == 1 and isinstance(runs[0], rules.DryRun) and runs[0].passed and runs[0].instructor == SME
           and runs[0].mode == "in-person", f"dry runs: {runs}")
    expect(records.dry_runs(log, {}) == [], "a dry run should not count when the unit's hash is unknown")
    passed = records.calibrations(log)
    expect(set(passed) == {PROFESSIONAL, CONTRACTOR} and all(len(v) == 1 for v in passed.values()),
           f"calibrations: {passed}")
    rules_doc = load_standards(h.root)["rules"]
    referred = records.lapses(log)
    expect(all(rules.is_calibrated(o, h.t.date(), passed, rules_doc, referred.get(o)) for o in (PROFESSIONAL, CONTRACTOR)),
           "the clearers should be calibrated")
    h.done("records", "observations, dry_runs and calibrations return rules.Observation, rules.DryRun and passed dates")


def staffing_verdict(h: Harness, mode: str = "in-person", on: str | None = None) -> tuple[str, int]:
    """(verdict, the command's exit status) of the staffing check for the SME, the example unit and `mode` today (or on)."""
    res = app.do_staffing_check(h.private, {"instructor": SME, "unit": UNIT, "mode": mode,
                                            "date": on or h.t.date().isoformat()}, root=h.root)
    return res["verdict"], staffing.EXIT_CODES[res["verdict"]]


def staffing_response(h: Harness, mode: str = "in-person", on: str | None = None, detail: bool = True) -> dict[str, Any]:
    """The whole staffing-check response for the SME, the example unit and `mode` today (or on), with the detailed reasons
    the head of training sees (`--detail`) unless `detail` is False (what delivery scheduling receives, decision 0005)."""
    return app.do_staffing_check(h.private, {"instructor": SME, "unit": UNIT, "mode": mode,
                                             "date": on or h.t.date().isoformat()}, root=h.root, detail=detail)


def gap_keys(h: Harness) -> set[str]:
    return {r["key"] for r in json.loads((h.private / "generated" / "gap-list.json").read_text(encoding="utf-8"))["rows"]}


def stage_w4_evidence(h: Harness) -> None:
    """evidence-ready: the two released observations, by two calibrated clearers, and the passed dry run meet
    rules.clearance_check, so a round opens for the SME's in-person candidate; the hybrid one has no dry run yet."""
    expect(staffing_verdict(h) == ("block", 2), "the staffing check should block before any clearance")
    expect(f"{SME} {UNIT} in-person" in gap_keys(h), "the gap list should list the SME's in-person delivery")
    h.tick()
    found = [e for e in h.steps_done(EVIDENCE) if e["subject_uri"] == SME_CANDIDATE]
    why = [e["payload"]["reasons"] for e in log_of(h, "check", SME_CANDIDATE) if e["payload"].get("step") == EVIDENCE]
    expect(len(found) == 1, f"no evidence round for the SME's in-person candidate: {why[-1:] }")
    p = found[0]["payload"]
    expect(p["observers"] == sorted([PROFESSIONAL, CONTRACTOR]) and len(p["observations"]) == 2,
           f"the round rests on the wrong evidence: {p}")
    hybrid = [e for e in log_of(h, "check", SME_HYBRID) if e["payload"].get("step") == EVIDENCE]
    expect(hybrid and any("dry-run" in r for r in hybrid[-1]["payload"]["reasons"]), "the hybrid candidate should wait")
    h.expect_due(D1, SME_CANDIDATE)
    pages = sorted(p.name for p in (h.private / "pages").glob(f"clearer-decision-1--{_slug(SME_CANDIDATE)}--*.html"))
    expect(pages == [f"clearer-decision-1--{_slug(SME_CANDIDATE)}--{_slug(u)}.html" for u in sorted([CONTRACTOR, PROFESSIONAL])],
           f"decision pages: {pages}")
    st = h.state()
    expect(clearance.founding(st, st.subjects[SME_CANDIDATE], h.t.date()), "nobody holds the unit: the round is founding")
    h.done("W4 evidence-ready", "a founding round for the SME's in-person candidate; pages for the two calibrated clearers, "
                                "who hold no clearance (decision 0017)")


def stage_w4_decisions(h: Harness) -> None:
    """Two different clearers decide cleared (decision 2 is not offered to the first clearer), the head's step is skipped,
    issue writes the clearance, and the staffing check flips from block to ok for that unit and mode only."""
    h.round([Want(D1, SME_CANDIDATE, person=PROFESSIONAL, fields={"outcome": "cleared"})])
    h.expect_not_due(D1, SME_CANDIDATE)
    h.expect_due(D2, SME_CANDIDATE)
    expect(not list((h.private / "pages").glob(f"clearer-decision-2--{_slug(SME_CANDIDATE)}--{_slug(PROFESSIONAL)}.html")),
           "decision 2 should not be offered to the first clearer")
    h.round([Want(D2, SME_CANDIDATE, person=CONTRACTOR, fields={"outcome": "cleared"})])
    h.tick()  # head-resolves was skipped by the second decision's hook; issue runs
    h.expect_not_due(HEAD, SME_CANDIDATE)
    (cleared,) = log_of(h, "clearance", SME_CANDIDATE)
    p = cleared["payload"]
    expect(p["outcome"] == "cleared" and p["clearers"] == [PROFESSIONAL, CONTRACTOR] and p["modes"] == ["in-person"]
           and len(p["observations"]) == 2 and p.get("founding") is True, f"clearance: {p}")
    expect(staffing_verdict(h) == ("ok", 0), "the staffing check should be ok once cleared")
    expect(staffing_verdict(h, "hybrid") == ("block", 2), "the hybrid mode is not cleared")
    keys = gap_keys(h)
    expect(f"{SME} {UNIT} in-person" not in keys and f"{SME} {UNIT} hybrid" in keys,
           "the gap list should drop only the cleared delivery")
    h.done("W4 decisions and issue", "two clearers decided cleared; the clearance is issued; staffing block -> ok; "
                                     "the gap list drops that delivery")


def stage_w4_level(h: Harness) -> None:
    """The levels workflow proposes cleared for the lead-observed SME who now holds a valid clearance; the head approves."""
    rows = level_rows(h)
    expect([(r["key"], r["from"], r["to"]) for r in rows] == [(SME, "lead-observed", "cleared")], f"rows: {rows}")
    h.round([Want(LEVELS, person=HOT)])
    expect(app.current_level(h.state(), SME) == "cleared", "the SME is not at level cleared")
    h.done("levels: SME to cleared", "proposed from the issued clearance; the head approved it")


def stage_w4_disagreement(h: Harness) -> None:
    """The SME's hybrid candidate: a dry run, then one clearer decides cleared and the other not yet; the head of training
    resolves it with a conditional clearance, which the staffing check accepts until the recheck."""
    h.round([Want(STEP_DRY_RUN, SME_HYBRID, person=CLEARER_PERSON)])
    h.tick()
    h.expect_due(D1, SME_HYBRID)
    h.round([Want(D1, SME_HYBRID, person=CONTRACTOR, fields={"outcome": "cleared"})])
    h.round([Want(D2, SME_HYBRID, person=PROFESSIONAL,
                  fields={"outcome": "not_yet", "actions": "Fictional: two more remote sessions observed"})])
    h.expect_due(HEAD, SME_HYBRID)
    expect(not log_of(h, "clearance", SME_HYBRID), "issued before the head resolved the disagreement")
    h.round([Want(HEAD, SME_HYBRID, person=HOT, fields={
        "outcome": "cleared_with_conditions", "conditions": "Fictional: pace the remote room", "recheck": "2027-03-15"})])
    h.tick()
    (event,) = log_of(h, "clearance", SME_HYBRID)
    p = event["payload"]
    expect(p["outcome"] == "cleared_with_conditions" and p["recheck"] == "2027-03-15"
           and p["clearers"] == [CONTRACTOR, PROFESSIONAL] and len(p["conditions"]) == 1, f"clearance: {p}")
    expect("pace the remote room" not in (h.private / app.EVENT_LOG).read_text(encoding="utf-8"),
           "the condition text reached the log")
    expect(staffing_verdict(h, "hybrid") == ("ok", 0), "a conditional clearance is valid until its recheck")
    expect(staffing_verdict(h, "hybrid", "2027-02-13") == ("warn", 3), "the check warns 30 days before the recheck")
    expect(staffing_verdict(h, "hybrid", "2027-03-16") == ("block", 2), "a missed recheck no longer covers the delivery")
    h.done("W4 disagreement", "cleared vs not yet went to the head, who cleared with conditions; staffing ok, warn (exit 3) "
                              "30 days before the recheck, block after it")


def stage_sme_clearer(h: Harness) -> None:
    """The SME, cleared by W4, takes a W5 exercise with the professional (two observers score one recording); the levels
    workflow proposes the SME for clearer (a valid clearance and a current calibration) and the head approves the row."""
    reference = h.work / "reference-2.yaml"
    reference.write_text(yaml.safe_dump({d: 3 for d in domain_ids(h.root)}), encoding="utf-8")
    h.advance()
    opened = calibration.open_exercise(
        h.private, unit=UNIT, recording_ref="recordings/fictional-delivery-2.mp4", observers=[SME, PROFESSIONAL],
        reference=reference, now=h.t, root=h.root)
    h.round([Want(STEP_SCORE, opened.exercise, person=SME), Want(STEP_SCORE, opened.exercise, person=PROFESSIONAL)])
    h.tick()
    found = {e["subject_uri"]: e["payload"] for e in log_of(h, "calibration") if e["payload"]["exercise"] == opened.exercise}
    expect(set(found) == {SME, PROFESSIONAL} and all(p["passed"] for p in found.values())
           and all(p["inter_observer"] == {"within_one_share": 1.0, "exact_share": 1.0} for p in found.values()),
           f"calibration events: {found}")
    h.tick()
    rows = level_rows(h)
    expect([(r["key"], r["from"], r["to"]) for r in rows] == [(SME, "cleared", "clearer")], f"level proposals: {rows}")
    h.round([Want(LEVELS, person=HOT)])
    st = h.state()
    expect(app.current_level(st, SME) == "clearer", "the SME is not at level clearer")
    expect(all("clearer" in i["roles"] for i in st.identities[h.email_of(SME)] if i["uri"] == SME),
           "the SME at level clearer should hold the clearer role")
    h.done("SME to clearer", "lead-observed -> cleared (W4) -> calibrated (W5) -> clearer (the head approved the row)")


def stage_sme_observes(h: Harness) -> None:
    """The SME, now a clearer, completes the observer pool of the professional's candidate (a clearer never observes
    themself, so it had one observer until now): the coordinator approves the batch and the SME observes, blind, with the
    contractor; release writes the SME's observation of the professional."""
    h.tick()
    proposal = h.private / "generated" / "observations" / f"{_slug(PROFESSIONAL_CANDIDATE)}.json"
    expect(proposal.is_file(), "no observation proposal for the professional's candidate")
    rows = json.loads(proposal.read_text(encoding="utf-8"))["rows"]
    observers = {r["attrs"]["observer"] for r in rows}
    expect(observers == {SME, CONTRACTOR}, f"the proposed observers are {sorted(observers)}")
    h.round([Want(STEP_APPROVED, PROFESSIONAL_CANDIDATE, person="tm:person/coord-1")])
    found = sorted((e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "assignment"
                    and e["payload"]["attrs"]["candidate"] == PROFESSIONAL_CANDIDATE), key=lambda e: e["subject_uri"])
    expect(len(found) == 2, "approving the batch should open two assignments")
    h.tick()
    h.round([Want(STEP_OBSERVE, e["subject_uri"], person=e["payload"]["attrs"]["observer"],
                  fields={"date": h.t.date().isoformat()}) for e in found])
    h.tick()
    released = log_of(h, "observation", PROFESSIONAL)
    expect({e["payload"]["observer"] for e in released} == {SME, CONTRACTOR}, f"released: {released}")
    h.done("SME observes", "the SME, a clearer now, was proposed for the professional's candidate and observed it")


# --- increment 3: the quality loop ------------------------------------------------------------------------------


def stage_outcomes(h: Harness) -> None:
    """W8: two deliveries of the SME 10+ points below the cohort baseline, each with at least the minimum learner count,
    imported through `import-outcomes`; the quality review writes one score-drop trigger and the summary hides nothing."""
    q = load_standards(h.root)["rules"]["quality"]
    minimum, drop = q["min_learners_for_metric"], q["score_drop_points"]
    rows = [{"delivery_ref": f"e2e-delivery-{n}", "instructor": SME, "unit": UNIT, "mode": "in-person",
             "delivered_on": day, "learners_assessed": minimum + n, "score": 72.0 - drop - 2, "baseline": 72.0}
            for n, day in ((1, "2026-10-19"), (2, "2026-10-23"))]
    src = h.work / "outcomes.json"
    src.write_text(json.dumps({"schema": "tm:contract/outcome-import@1", "source": "fictional-lms",
                               "exported_at": h.advance().isoformat(timespec="seconds"), "deliveries": rows}),
                   encoding="utf-8")
    imported = quality.import_outcomes(h.private, src, now=h.t, root=h.root)
    expect(imported.appended == 2, f"import-outcomes appended {imported.appended}")
    again = quality.import_outcomes(h.private, src, now=h.advance(), root=h.root)
    expect(again.appended == 0 and again.unchanged == 2, "a re-import of the same deliveries should append nothing")
    outcomes = log_of(h, "outcome", SME)
    expect(len(outcomes) == 2 and all(set(e["payload"]) >= {"delivery_ref", "learners_assessed", "score", "baseline"}
                                      for e in outcomes), f"outcome events: {outcomes}")
    h.tick()
    triggers = [e for e in log_of(h, "check", SME) if e["payload"].get("step") == QUALITY_REVIEW
                and e["payload"].get("result") == "trigger"]
    expect([e["payload"]["trigger"] for e in triggers] == ["score-drop"], f"quality triggers: {triggers}")
    expect(not [e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "bench"],
           "an outcome trigger alone must not open a bench review")
    h.done("W8 import-outcomes and quality-review", f"two deliveries {drop}+ below baseline with {minimum}+ learners; one "
                                                    "score-drop trigger on the SME; no bench review")


def sme_cycle(h: Harness) -> dict[str, Any]:
    opening = [e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "cycle"
               and e["payload"]["attrs"]["instructor"] == SME][0]  # cycle 1: the later ones open as each closes
    return {"uri": opening["subject_uri"], **opening["payload"]["attrs"]}


def stage_coaching(h: Harness) -> None:
    """W7: the professional is named the SME's coach; open-cycles opens the SME's next cycle at triggered intensity (the
    trigger came after any cycle of theirs) on the two lowest domains; the coach observes, gives feedback and sets a practice
    task through ingest, re-observes a day later, and cycle-close records the change and closes the CPD gaps."""
    path = h.private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["people"].append(COACH_ROW)
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    h.tick()
    c = sme_cycle(h)
    low = domain_ids(h.root)[:2]
    expect(c["coach"] == PROFESSIONAL and c["intensity"] == "triggered" and c["trigger"] == "score-drop"
           and c["focus"] == low and c["number"] == 1, f"the SME's cycle: {c}")
    h.expect_due(COACH_OBSERVE, c["uri"])
    h.done("W7 open-cycles (triggered)", f"{c['uri']}: coach {_slug(PROFESSIONAL)}, focus {', '.join(low)}, trigger score-drop")

    sender = COACH_ROW["email"]

    def marks(score: int) -> dict[str, Any]:
        return {d: {"score": score, "note": f"Fictional coaching evidence for {d}."} for d in c["focus"]}

    h.round([Want(COACH_OBSERVE, c["uri"], person=PROFESSIONAL, sender=sender,
                  fields={"date": h.t.date().isoformat(), "unit": UNIT, **marks(2)})])
    h.tick()
    h.expect_not_due(COACH_OBSERVE, c["uri"])
    h.round([Want(COACH_FEEDBACK, c["uri"], person=PROFESSIONAL, sender=sender)])
    h.tick()
    h.round([Want(PRACTICE, c["uri"], person=PROFESSIONAL, sender=sender)])
    h.tick()
    phases = [e["payload"]["phase"] for e in log_of(h, "coaching_cycle", c["uri"])]
    expect(phases == ["opened", "feedback", "practice"], f"cycle phases: {phases}")
    expect("example-task" not in (h.private / app.EVENT_LOG).read_text(encoding="utf-8"), "the practice task reached the log")
    h.done("W7 coach-observe, coach-feedback, practice-task", "signed through ingest by the coach; the words stay private")

    h.t += timedelta(days=1)  # the re-observation is a later session: its day is the latest the CPD review reads
    h.round([Want(COACH_REOBSERVE, c["uri"], person=PROFESSIONAL, sender=sender,
                  fields={"date": h.t.date().isoformat(), "unit": UNIT, **marks(3)})])
    h.tick()
    (closed,) = [e for e in log_of(h, "coaching_cycle", c["uri"]) if e["payload"]["phase"] == "closed"]
    expect(closed["payload"]["change"] == {d: 1 for d in c["focus"]}, f"the recorded change: {closed['payload']}")
    (done,) = [e for e in h.steps_done(CYCLE_CLOSE) if e["subject_uri"] == c["uri"]]
    expect(done["payload"].get("cpd_review") == {"closed": c["focus"], "kept": []}, f"the CPD review at close: {done['payload']}")
    h.expect_not_due(CYCLE_CLOSE, c["uri"])
    # a cycle is always open: the next opened with this close, standard (the one trigger was used by the first cycle)
    (nxt,) = [e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "cycle" and e["subject_uri"] != c["uri"]
              and e["payload"]["attrs"]["instructor"] == SME]
    expect(nxt["payload"]["attrs"]["number"] == 2 and nxt["payload"]["attrs"]["intensity"] == "standard"
           and nxt["at"][:10] == closed["at"][:10], f"the next cycle: {nxt['payload']['attrs']}")
    h.expect_due(COACH_OBSERVE, nxt["subject_uri"])
    coached = [e for e in log_of(h, "observation", SME) if e["payload"]["observer"] == PROFESSIONAL
               and str(e["payload"].get("delivery_ref", "")).startswith(_slug(c["uri"]))]
    expect(len(coached) == 2, f"the coach's observations: {coached}")
    h.done("W7 coach-reobserve and cycle-close", f"change {closed['payload']['change']}; the CPD gaps "
                                                 f"{', '.join(c['focus'])} closed by the cycle; cycle 2 opened with the close")


def stage_cpd(h: Harness) -> None:
    """W9: the SME's plan was seeded from the lowest-scoring domains of their observations (the two W2 domains at 2); the
    SME logs one activity against a gap, which becomes a `cpd` event with the text in the private store."""
    plan = json.loads((h.private / cpd.plan_path(SME)).read_text(encoding="utf-8"))
    low = domain_ids(h.root)[:2]
    expect([g["domain"] for g in plan["gaps"]] == low and all(g["seed_average"] == 2 for g in plan["gaps"]),
           f"the SME's CPD plan: {plan['gaps']}")
    expect([s for s in h.steps_done(CPD_PLAN) if s["subject_uri"] == SME], "no cpd-plan step for the SME")
    h.tick()
    h.expect_due(LOG_ACTIVITY, SME)
    h.round([Want(LOG_ACTIVITY, SME, person=SME, fields={
        "activity": "Fictional: rehearsed the lab pre-check with a peer", "hours": 2.5,
        "date": h.t.date().isoformat(), f"domain-{low[0]}": True})])
    (logged,) = log_of(h, "cpd", SME)
    p = logged["payload"]
    expect(p["domains"] == [low[0]] and p["hours"] == 2.5 and (h.private / p["activity_key"]).is_file(),
           f"the cpd event: {p}")
    expect("rehearsed the lab pre-check" not in (h.private / app.EVENT_LOG).read_text(encoding="utf-8"),
           "the activity text reached the log")
    # bind: input with the count of activities logged: the step opens again at once, due 91 days after this activity
    (again,) = [d for d in app.due_steps(h.state(), h.t.date()) if (d.step, d.subject) == (LOG_ACTIVITY, SME)]
    expect(again.due == date.fromisoformat(p["logged_on"]) + timedelta(days=cpd.LOG_WINDOW_DAYS) and not again.overdue,
           f"the next activity should be due {cpd.LOG_WINDOW_DAYS} days after this one: {again}")
    h.done("W9 CPD plan and log-activity", f"plan gaps {', '.join(low)} seeded from the observations; one activity logged; "
                                           f"the next due in {cpd.LOG_WINDOW_DAYS} days")


def stage_audit(h: Harness) -> None:
    """W6: nothing is sampled while 2026Q4 is open. On the first run after it closed draw-sample draws the quarter once, over all
    its live observations (rules.audit_sample); a sample whose second observer then becomes the instructor's coach is voided
    and a replacement drawn (decision 0015); the second observer of one sampled observation of the SME scores it from the
    recording, blind, and audit-result records agreement."""
    h.tick()
    expect(not [e for e in log_of(h, "subject") if e["payload"]["subject_kind"] == "sample"],
           "a sample was drawn while the quarter was open")
    h.t = AUDIT_DAY  # the day after 2026Q4 closed; tick() moves on an hour
    # Only three clearers exist, and a second observer is none of the instructor, the first observer and the others who observed
    # the delivery: a fourth clearer (fictional seed data, as the first two were) lets the sample find second observers.
    seed_clearer(h, PARTNER)
    h.tick()
    samples = {e["subject_uri"]: e["payload"]["attrs"] for e in log_of(h, "subject")
               if e["payload"]["subject_kind"] == "sample"}
    quarter = audit.previous_quarter(h.t.date())
    expect(quarter == "2026Q4" and samples and all(a["quarter"] == quarter for a in samples.values()), f"samples: {samples}")
    st = h.state()
    live = [o for o in records.observations(h.log()) if audit.quarter_id(o.at) == quarter]
    picked = [o for o in live if o.id in set(rules.audit_sample(live, quarter, st.standards["rules"]))]
    expect({a["observation"] for a in samples.values()} == {o.id for o in picked},
           "the sample is not what rules.audit_sample picks over the quarter's observations")
    expect(len([e for e in h.steps_done(DRAW_SAMPLE) if e["payload"].get("drawn") is True]) == 1, "the quarter was drawn twice")
    # No second observer observed the sampled delivery, coached the instructor, or is the instructor or the first observer.
    for a in samples.values():
        expect(a["second_observer"] not in audit.delivery_observers(st, a["observation"]) | {a["instructor"]},
               f"the second observer of {a['observation']} observed the delivery")
    # A second observer becomes the coach of the instructor of one sample (other than the SME's, whose samples the rest of the
    # stage scores): draw-sample voids a sample whose second observer is no longer eligible (decision 0015), draws a
    # replacement, and nothing stays due for the voided one.
    victim = next(a for u, a in sorted(samples.items()) if a["instructor"] != SME)
    path = h.private / "identities" / "people.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows = [r for r in doc["people"] if r.get("instructor") == victim["second_observer"] and "coach" in r["roles"]]
    if rows:
        rows[0]["coaches"] = [*rows[0]["coaches"], victim["instructor"]]
    else:
        slug = _slug(victim["second_observer"])
        doc["people"].append({"person": f"tm:person/coach-{slug}", "name": f"Fictional Coach {slug}",
                              "email": f"coach.{slug}@example.com", "roles": ["coach"],
                              "instructor": victim["second_observer"], "coaches": [victim["instructor"]]})
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    h.tick()
    samples = {e["subject_uri"]: e["payload"]["attrs"] for e in log_of(h, "subject")
               if e["payload"]["subject_kind"] == "sample"}
    voided = sorted(e["subject_uri"] for e in log_of(h, "check") if e["payload"].get("step") == DRAW_SAMPLE
                    and e["payload"].get("result") == "void")
    expect(voided and all(samples[u]["second_observer"] == victim["second_observer"]
                          and samples[u]["instructor"] == victim["instructor"] for u in voided),
           f"the sample whose second observer became the instructor's coach was not voided: {voided}")
    for u in voided:
        expect(not {s for s, subject in h.due() if subject == u}, f"a voided sample {u} still has a step due")
    pick = sorted(u for u, a in samples.items() if a["instructor"] == SME and u not in voided)
    expect(pick, f"no sample of an observation of the SME left to second-score: {samples}")
    sample, attrs = pick[0], samples[pick[0]]
    second = attrs["second_observer"]
    expect(second not in (attrs["observer"], attrs["instructor"]), f"the second observer is not eligible: {attrs}")
    h.expect_due(SECOND_SCORE, sample)
    first = next(e for e in h.log() if e["kind"] == "observation" and e["id"] == attrs["observation"])
    blind = (h.private / "pages").glob(f"second-score--{_slug(sample)}--*.html".lower())
    expect(all(json.dumps(first["payload"]["scores"]) not in p.read_text(encoding="utf-8") for p in blind),
           "the second observer's page shows the first observer's scores")
    scores = {d: {"score": s, "note": f"Fictional second scoring of {d}."} for d, s in first["payload"]["scores"].items()}
    h.round([Want(SECOND_SCORE, sample, person=second, fields=scores)])
    h.tick()
    (result,) = log_of(h, "audit", sample)
    p = result["payload"]
    expect(p["agreed"] is True and p["referred_to_calibration"] is False and p["observer"] == attrs["observer"]
           and p["second_observer"] == second and p["within_one_share"] == 1.0, f"the audit: {p}")
    h.expect_not_due(AUDIT_RESULT, sample)
    expect(not records.lapses(h.log()), "an agreed audit should refer nobody to calibration")
    h.done("W6 audit", f"none while {quarter} was open; {len(samples)} sample(s) drawn once it closed, {len(voided)} voided (its "
                       f"second observer became the instructor's coach); {_slug(second)} second-scored one blind; agreed")


def stage_bench(h: Harness) -> None:
    """W10: the head requests a bench review of the SME (`request-bench`); evidence-pack writes the self-contained pack with
    the real records (clearances, observations, outcomes, the coaching cycle, CPD, the audit), bench-ready holds (the pack and
    two current observers), and the head decides return-to-co-teaching, which drops the SME's level to co-deliver."""
    opened = bench.request_bench(h.private, instructor=SME, now=h.advance(), root=h.root)
    expect(opened.created, "request-bench did not open a review")
    h.tick()
    (pack,) = [e for e in h.steps_done(BENCH_PACK) if e["subject_uri"] == opened.bench]
    path = h.private / pack["payload"]["output"]
    html = path.read_text(encoding="utf-8")
    expect(pack["payload"]["evidence_pack_sha256"] == _sha(path), "the pack's hash is not the file's")
    c = sme_cycle(h)["uri"]  # the first cycle, the one with the coaching on record
    (activity,) = log_of(h, "cpd", SME)
    (audited,) = log_of(h, "audit")
    for needle, what in (("e2e-delivery-1", "an outcome"), (c, "the coaching cycle"),
                         (activity["payload"]["activity_key"], "the CPD activity"), (audited["payload"]["observation"], "the audit")):
        expect(needle in html, f"the evidence pack does not show {what}")
    expect("not available" not in html and "Fictional evidence" not in html, "the pack is missing records or shows notes")
    expect([e for e in h.steps_done(BENCH_READY) if e["subject_uri"] == opened.bench], "bench-ready did not hold")
    h.expect_due(BENCH_DECISION, opened.bench)
    h.done("W10 request-bench, evidence-pack, bench-ready", f"{path.name}: outcomes, coaching, CPD and the audit from real "
                                                            "records; two current observers")
    h.round([Want(BENCH_DECISION, opened.bench, person=HOT, fields={
        "decision": "return-to-co-teaching", "rationale": "Fictional: the scores dropped; co-teach the next run"})])
    (decided,) = log_of(h, "bench_decision", opened.bench)
    expect(decided["payload"]["decision"] == "return-to-co-teaching"
           and decided["payload"]["evidence_pack_sha256"] == pack["payload"]["evidence_pack_sha256"],
           f"the bench decision: {decided['payload']}")
    expect("co-teach the next run" not in (h.private / app.EVENT_LOG).read_text(encoding="utf-8"),
           "the rationale reached the log")
    expect(app.current_level(h.state(), SME) == "co-deliver", "return-to-co-teaching should lower the SME to co-deliver")
    h.expect_not_due(BENCH_DECISION, opened.bench)
    h.done("W10 bench-decision", "the head decided return-to-co-teaching on the pack's hash; the SME's level is co-deliver")


def stage_bench_blocks_staffing(h: Harness) -> None:
    """A return to co-teaching stops staffing: the SME holds a valid clearance for the example unit in person, issued before the
    decision, and the staffing check now blocks it for the bench decision (exit status 2)."""
    res = staffing_response(h)
    expect(res["verdict"] == "block" and res["reasons"] == ["bench decision: returned to co-teaching"],
           f"the staffing check after the bench decision: {res}")
    expect(staffing_verdict(h) == ("block", 2), "the staffing check should exit 2 after the bench decision")
    outbound = staffing_response(h, detail=False)
    expect(outbound == {"verdict": "block", "reasons": ["not cleared"]},
           f"delivery scheduling should see clearance status only (decision 0005): {outbound}")
    h.done("staffing after the bench decision", "block: bench decision: returned to co-teaching (the clearance predates it); "
           "scheduling sees only 'not cleared'")


def stage_override(h: Harness) -> None:
    """The head overrides that block for one delivery. `request-override` for a date a week out opens an override subject (the
    requester's note goes to the private store); until it is decided the check still blocks; the head's `override-decision`
    approves with a reason; the check is then ok for exactly that date, with the override id in the reasons, and blocks the day
    after and in another mode. Neither the note nor the reason reaches the log."""
    day = h.t.date() + timedelta(days=7)
    opened = override.request_override(h.private, instructor=SME, unit=UNIT, mode="in-person", date=day.isoformat(),
                                       note="Fictional: the cleared lead is ill that week", now=h.advance(), root=h.root)
    expect(opened.created, "request-override did not open an override")
    again = override.request_override(h.private, instructor=SME, unit=UNIT, mode="in-person", date=day.isoformat(),
                                      now=h.advance(), root=h.root)
    expect(not again.created and again.override == opened.override, "a second request-override opened another override")
    expect(staffing_response(h, on=day.isoformat())["verdict"] == "block", "an undecided override changed the verdict")
    h.tick()
    h.expect_due(OVERRIDE_DECISION, opened.override)
    h.done("request-override", f"{opened.override} opened for {day.isoformat()}; the check still blocks")
    h.round([Want(OVERRIDE_DECISION, opened.override, person=HOT, fields={
        "decision": "approve", "reason": "Fictional: no other cleared lead is free; the learners are waiting"})])
    h.expect_not_due(OVERRIDE_DECISION, opened.override)
    (granted,) = [e for e in log_of(h, "check", opened.override) if e["payload"].get("result") == "granted"]
    expect(granted["payload"]["decided_by"] == HOT and events.check_event(granted) == [], f"the decision event: {granted}")
    res = staffing_response(h, on=day.isoformat())
    expect(res["verdict"] == "ok" and res["reasons"][0] == f"override {opened.override}"
           and "overridden: bench decision: returned to co-teaching" in res["reasons"], f"the overridden check: {res}")
    expect(staffing_response(h, on=(day + timedelta(days=1)).isoformat())["verdict"] == "block",
           "the override covered the day after")
    expect(staffing_response(h, on=(day - timedelta(days=1)).isoformat())["verdict"] == "block",
           "the override covered the day before")
    expect(staffing_response(h, mode="remote", on=day.isoformat())["verdict"] == "block", "the override covered another mode")
    raw = (h.private / app.EVENT_LOG).read_text(encoding="utf-8")
    expect("cleared lead is ill" not in raw and "learners are waiting" not in raw, "an override note or reason reached the log")
    expect("learners are waiting" in (h.private / granted["payload"]["reason_key"]).read_text(encoding="utf-8"),
           "the reason is not in the private store")
    h.done("override-decision", f"approved: ok on {day.isoformat()} only, with the override id in the reasons; reason private")


def stage_bench_exit(h: Harness) -> None:
    """A second review of the SME ends in an exit: the staffing check blocks for the bench decision ("bench decision: exit"),
    the SME's candidates are closed by a check each and no level changes."""
    level = app.current_level(h.state(), SME)
    opened = bench.request_bench(h.private, instructor=SME, now=h.advance(), root=h.root)
    expect(opened.created and opened.bench.endswith("--2"), f"the second review: {opened}")
    h.tick()
    h.expect_due(BENCH_DECISION, opened.bench)
    h.round([Want(BENCH_DECISION, opened.bench, person=HOT, fields={
        "decision": "exit", "rationale": "Fictional: the engagement is not renewed"})])
    expect([e for e in log_of(h, "bench_decision", opened.bench) if e["payload"]["decision"] == "exit"], "no exit decision")
    res = staffing_response(h)
    expect(res["verdict"] == "block" and res["reasons"] == ["bench decision: exit"], f"the staffing check after the exit: {res}")
    closed = [e for e in log_of(h, "check") if e["payload"].get("result") == "closed" and e["payload"].get("bench") == opened.bench]
    expect(closed, "the exit closed no candidate")
    expect(app.current_level(h.state(), SME) == level, "an exit changed the level")
    h.done("W10 exit blocks staffing", "block: bench decision: exit; the SME's candidates closed; no level change")


def final_checks(h: Harness, guarded: dict[Path, str]) -> None:
    log_path = h.private / app.EVENT_LOG
    problems = events.verify(log_path)
    expect(problems == [], f"events.verify: {problems}")
    have = [e["payload"]["signoff_id"] for e in h.log() if e["kind"] == "signoff"]
    expect(sorted(have) == sorted(h.signoff_ids), "accepted sign-offs and signoff events differ")
    expect(len(set(have)) == len(have), "a sign-off id appears twice")
    stored = sorted(p.stem for p in (h.private / "signoffs").glob("*.json") if not p.name.endswith(".inputs.json"))
    expect(stored == sorted(have), "signoffs/ does not hold one document per signoff event")
    bound = {e["payload"]["signoff_id"] for e in h.log() if e["kind"] == "signoff"
             and e["payload"]["decision"] in ("approve", "record")  # a request for changes covers nothing
             and e["payload"]["step"] in (VERIFIED, ROPA_APPROVED, DPIA, RETENTION, NOTICE_APPROVED, PROFILE_VERIFIED, DELTA,
                                          VARIANT_APPROVED, STEP_APPROVED, STEP_DRY_RUN, D1, D2, HEAD, LEVELS,
                                          LOG_ACTIVITY, BENCH_DECISION, GAP_LIST_APPROVED, SECOND_SCORE)}
    kept = {p.name[: -len(".inputs.json")] for p in (h.private / "signoffs").glob("*.inputs.json")}
    expect(kept == bound, "signoffs/ should keep the inputs of exactly the bound sign-offs")
    needles = [p["name"] for p in (*PEOPLE, COACH_ROW)] + [p["email"] for p in (*PEOPLE, COACH_ROW)]
    roster = yaml.safe_load(EXAMPLE_ROSTER.read_text(encoding="utf-8"))
    for row in roster["instructors"]:
        needles += [v for v in row["identity"].values()]
    raw = log_path.read_text(encoding="utf-8")
    leaked = [n for n in needles if n in raw]
    expect(not leaked, f"names or emails in events.jsonl: {leaked}")
    changed = [str(p) for p, digest in guarded.items() if _sha(p) != digest]
    expect(not changed, f"repo files were changed: {changed}")
    expect(wrote_outside_repo(h), "the run wrote inside the repo")
    h.done("final", f"{len(have)} sign-offs are signoff events; events.verify is []; no names or emails in the log; "
                    "repo files untouched")


def wrote_outside_repo(h: Harness) -> bool:
    """Nothing the run wrote is inside the repo."""
    return not any(REPO in p.parents for p in (h.private, h.root))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="e2e_fictional", description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep", action="store_true", help="keep the temp directory and print its path")
    ap.add_argument("--work-dir", type=Path, default=None, help="use this empty directory (outside the repo)")
    args = ap.parse_args(argv)
    real_files = [REPO / "standards" / "retention.yaml", *(REPO / "docs" / "decisions").glob("0005-*.md")]
    guarded = {p: _sha(p) for p in real_files}
    work = args.work_dir
    h: Harness | None = None
    try:
        if work is None:
            work = Path(tempfile.mkdtemp(prefix="tm-e2e-"))
        else:
            config.assert_outside_repo(work)
            work.mkdir(parents=True, exist_ok=True)
            expect(not any(work.iterdir()), f"{work} is not empty")
        h = Harness(work.resolve())
        h.build()
        stage_setup_steps(h)
        stage_it_done(h)
        stage_library(h)
        stage_profile_verified(h)
        stage_ropa_approved(h)
        stage_dpia(h)
        stage_retention(h)
        stage_roster(h)
        stage_notice(h)
        stage_profile_edited(h)
        stage_notice_sent(h)
        stage_gap_list(h)
        stage_w1(h)
        stage_candidates(h)
        stage_overlay_us_ca(h)
        stage_german_blocked(h)
        stage_founders(h)
        stage_w5_calibration(h)
        stage_founders_calibrated(h)
        stage_w3_dry_run(h)
        stage_w2_observation(h)
        stage_records(h)
        stage_w4_evidence(h)
        stage_w4_decisions(h)
        stage_w4_level(h)
        stage_w4_disagreement(h)
        stage_sme_clearer(h)
        stage_sme_observes(h)
        stage_outcomes(h)
        stage_coaching(h)
        stage_cpd(h)
        stage_audit(h)
        stage_bench(h)
        stage_bench_blocks_staffing(h)
        stage_override(h)
        stage_bench_exit(h)
        final_checks(h, guarded)
    except (StageFailed, app.AppError, config.ConfigError, setup.SetupError, quality.QualityError, bench.BenchError,
            override.OverrideError) as exc:
        print(f"FAIL after stage {h.stage if h else 0}: {exc}", file=sys.stderr)
        print(f"work dir kept: {work}", file=sys.stderr)
        return 1
    if args.keep:
        print(f"work dir kept: {work}")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
