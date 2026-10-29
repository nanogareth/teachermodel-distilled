"""`teachermodel dev-autosign`: walk a pilot store forward with generated sign-offs (owner, 2026-10-27).

There is no content to evaluate yet, so filling in every page by hand only costs time. In a pilot store only (settings
`pilot: true`, decision 0016) this repeats, until a round signs nothing new (or only another coaching cycle, `CYCLE_STEPS`):

1. tick;
2. import the generated roster and outcomes once the roster import is waiting for its command;
3. open a calibration exercise with the generated answer sheet when the roster has clearers and none is open. The
   clearers hold no clearance for the pilot unit: they decide each other's and everyone's clearance in founding rounds
   (decision 0017) until two of them hold it;
4. answer one page of each due human step and subject (`answers`; the next signer's page the next round, for a step
   every signer must sign), scoring calibration pages with the exercise's reference so the clearers pass, and submit
   them through the pilot path (`pilot.pilot_sign`), which checks them as ingest does. Optional records that reopen after
   every sign-off (`SKIP_STEPS`) are left alone.

The pilot owner's pages are signed too unless `generated_only`, which leaves them for the sign-off mailbox, the path the
pilot tests. Verify steps (the library check, sent notices) still need the connector. Each run's sign-off files are
kept under `dev-autosign/<run time>/round-NN/` in the store, so what was signed stays inspectable.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import app, pilot, setup
from .signoff import input_sha256
from .flows.calibration import STEP_SCORE, open_exercise
from .flows.quality import import_outcomes
from .standards import ROOT

STEP_ROSTER_IMPORT = "tm:step/roster-import"
# Optional records that open again after every sign-off (observation.yaml: an ad-hoc assignment; cpd.yaml: an activity
# log entry). Signing them only feeds them, and each ad-hoc observation reopens the candidate's clearance round.
SKIP_STEPS = frozenset({"tm:step/assign-observer", "tm:step/log-activity", "tm:step/reply-or-appeal"})
# The coaching cycle (coaching.yaml) opens the next cycle as one closes. Once every one of these steps has been signed, a round
# that signs only these again is the cycle turning over, and the run stops there.
CYCLE_STEPS = frozenset({"tm:step/coach-observe", "tm:step/coach-feedback", "tm:step/practice-task",
                         "tm:step/coach-reobserve"})
UNIT = pilot.UNIT
# The answer to pick where the first option would block the step (a DPO decision that a DPIA is needed).
PREFERRED = {"dpo-decision": "dpia-not-required"}
_DATA = re.compile(r'<script type="application/json" id="tm-data">(.*?)</script>', re.S)


class DevSignError(Exception):
    """dev-autosign refused to run; the message names why."""


def answers(data: dict[str, Any], today: date, *, note: str = "Generated evidence",
            scores: dict[str, int] | None = None, turn: int = 0) -> dict[str, Any]:
    """What a person fills in on a page: its pre-filled value, else a plain answer for each required field. A date is
    `today` (an observed session cannot precede the assignment it answers); `scores` replaces the score of an
    evidence_score field of that name (a calibration reference). The observer is the `turn`-th option, so successive
    assignments of one candidate rotate through the pool (clearance needs two distinct observers); an activity log
    ticks its first framework domain (at least one is required)."""
    out: dict[str, Any] = {}
    for f in data["fields"]:
        value = f.get("value")
        options = f.get("options") or [None]
        if value is None and f["kind"] == "enum" and PREFERRED.get(f["name"]) in options:
            value = PREFERRED[f["name"]]
        if value is None and f["name"] == "observer" and f["kind"] == "enum":
            value = options[turn % len(options)]
        if value is None and f.get("required"):
            value = {"enum": options[0], "score": 3, "bool": True, "date": today.isoformat(),
                     "number": f.get("min", 1),
                     "evidence_score": {"score": 3, "note": f"{note} for {f['name']}."},
                     "checklist": {i["id"]: {"result": "pass"} for i in f.get("items", [])},
                     }.get(f["kind"], f"example-{f['name']}")
        if f["kind"] == "evidence_score" and scores and f["name"] in scores and isinstance(value, dict):
            value = {**value, "score": scores[f["name"]]}
        if value is not None:
            out[f["name"]] = value
    domains = [f["name"] for f in data["fields"] if f["kind"] == "bool" and f["name"].startswith("domain-")]
    if domains and not any(out.get(name) for name in domains):
        out[domains[0]] = True
    if data["template"] == "batch_approve":
        out["rows"] = {r["key"]: "approve" for r in data["inputs"]["rows"]}
    return out


def _page_data(path: Path) -> dict[str, Any]:
    return json.loads(_DATA.search(path.read_text(encoding="utf-8")).group(1))


def _reference(private: Path, exercise: str) -> dict[str, int] | None:
    path = private / "calibration" / f"{exercise.split('/', 1)[1]}.reference.json"
    return json.loads(path.read_text(encoding="utf-8"))["scores"] if path.is_file() else None


def _signed(st: app.State) -> set[tuple[str, str, str, str]]:
    """(step, subject, signer, input hash) of every sign-off in the log."""
    return {(e["payload"]["step"], e["subject_uri"], e["actor"], e["payload"]["input_sha256"])
            for e in st.events if e["kind"] == "signoff"}


def _seen_ids(st: app.State) -> set[str]:
    """Every sign-off id the log knows, accepted or rejected: a rejected page is not submitted again."""
    return {e["payload"]["signoff_id"] for e in st.events
            if e["kind"] in ("signoff", "check") and isinstance(e["payload"].get("signoff_id"), str)}


def _sign_round(st: app.State, out_dir: Path, at: datetime, n: int, generated_only: bool) -> list[Path]:
    """Write a sign-off file for every page of a due human step not yet signed for its current inputs."""
    signed, seen, out, today = _signed(st), _seen_ids(st), [], at.date()
    private = st.private
    stems = {app.page_stem(d.step, d.subject, "tm:person/x")[:-1] for d in app.due_steps(st, today)
             if d.type == "human" and d.step not in SKIP_STEPS}
    taken: set[tuple[str, str]] = set()
    for path in sorted((private / "pages").glob("*.html")):
        if not any(path.stem.startswith(s) for s in stems):
            continue
        data = _page_data(path)
        if generated_only and data["signer"] == pilot.OWNER:
            continue
        if (data["step"], data["subject_uri"], data["signer"], data["input_sha256"]) in signed \
                or (data["step"], data["subject_uri"]) in taken:
            continue
        taken.add((data["step"], data["subject_uri"]))
        scores = _reference(private, data["subject_uri"]) if data["step"] == STEP_SCORE else None
        turn = sum(1 for (step, subject, *_rest) in signed if (step, subject) == (data["step"], data["subject_uri"]))
        fields = answers(data, today, scores=scores, turn=turn)
        sid = input_sha256([data["step"], data["subject_uri"], data["signer"], data["input_sha256"], fields])[:32]
        if sid in seen:  # the same answers were refused before: they would be refused again
            continue
        doc = {"schema": app.SIGNOFF_SCHEMA, "id": sid, "step": data["step"], "subject_uri": data["subject_uri"],
               "input_sha256": data["input_sha256"], "decision": "approve",
               "fields": fields, "signer": data["signer"],
               "signed_at": at.isoformat(timespec="seconds"),
               "page_template_sha256": data["page_template_sha256"]}
        target = out_dir / f"round-{n:02d}" / f"{path.stem}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
        out.append(target)
    return out


def _clearers(st: app.State) -> list[str]:
    return sorted(u for u, info in st.subjects.items() if info.get("kind") == "instructor" and info.get("level") == "clearer")


def autosign(private_dir: Path | str, *, rounds: int = 20, generated_only: bool = False, root: Path = ROOT,
             clock: Callable[[], datetime] | None = None) -> app.Report:
    """Run the rounds described in the module docstring. Raises DevSignError outside a pilot store."""
    private = Path(private_dir)
    try:
        settings = setup.load_settings(private)
    except setup.SetupError as exc:
        raise DevSignError(str(exc)) from exc
    if settings.get("pilot") is not True:
        raise DevSignError("dev-autosign works only in a pilot store (settings 'pilot: true', decision 0016)")
    clock = clock or (lambda: datetime.now(timezone.utc).replace(microsecond=0))
    last = datetime.min.replace(tzinfo=timezone.utc)

    def now() -> datetime:  # strictly increasing: each pilot receipt is named by its second
        nonlocal last
        last = max(clock(), last + timedelta(seconds=1))
        return last

    rep, done = app.Report(), Counter()
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    out_dir = private / "dev-autosign" / stamp
    for k in range(2, 100):  # never mix two runs' files
        if not out_dir.exists():
            break
        out_dir = private / "dev-autosign" / f"{stamp}-{k}"
    for n in range(1, rounds + 1):
        app.do_tick(private, now=now(), root=root)
        st = app.load_state(private, root)
        today = last.date()
        due = {d.step for d in app.due_steps(st, today)}
        acted = False
        if STEP_ROSTER_IMPORT in due and (private / "inputs" / "roster.yaml").is_file():
            rep.lines.append(app.do_import_roster(private, private / "inputs" / "roster.yaml", now=now(), root=root).summary)
            if (private / "inputs" / "outcomes.yaml").is_file():
                res = import_outcomes(private, private / "inputs" / "outcomes.yaml", now=now(), root=root)
                rep.lines.append(f"import-outcomes: {res.appended} outcome event(s) appended")
            acted = True
        st = app.load_state(private, root)
        clearers = _clearers(st)
        if len(clearers) >= 2 and not any(info.get("kind") == "exercise" for info in st.subjects.values()) \
                and (private / "inputs" / "calibration-reference.yaml").is_file():
            opened = open_exercise(private, unit=UNIT, recording_ref="recordings/pilot-001.mp4", observers=clearers,
                                reference=private / "inputs" / "calibration-reference.yaml", now=now(), root=root)
            rep.lines.append(f"open-exercise: {opened.exercise} for {len(clearers)} clearer(s)")
            acted = True
        if acted:
            app.do_tick(private, now=now(), root=root)
            st = app.load_state(private, root)
        files = _sign_round(st, out_dir, now(), n, generated_only)
        if files:
            signed = pilot.pilot_sign(private, files, now=now(), root=root, include_owner=not generated_only)
            rep.lines.extend(signed.lines)
            rep.lines.append(f"round {n}: {signed.summary}")
            steps = [json.loads(f.read_text(encoding="utf-8"))["step"] for f in files]
            turned_over = set(steps) <= CYCLE_STEPS and CYCLE_STEPS <= set(done)
            done.update(steps)
            if not signed.ok:
                rep.ok = False
                break
            if turned_over:
                rep.lines.append(f"round {n}: only the next coaching cycle is left; stopping")
                break
        elif not acted:
            break
    final = app.do_tick(private, now=now(), root=root)
    rep.lines.extend(r.summary for r in final[:3])
    signed_steps = ", ".join(f"{step.split('/', 1)[1]} {k}" for step, k in sorted(done.items())) or "none"
    rep.summary = f"dev-autosign: {sum(done.values())} sign-off(s) submitted ({signed_steps}); {final[-1].summary}"
    return rep
