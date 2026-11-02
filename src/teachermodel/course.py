"""`teachermodel course`: the train-the-trainer course record (docs/train-the-trainer/DESIGN.md, W1 step 3).

    course intake <file> --instructor <tm:instructor/..> --session <id> --on DAY [--catalogue F] [--reference KEY]
    course record --instructor <tm:instructor/..> --session <id> --evidence-ref <private-store key> --on DAY
    course status --instructor <tm:instructor/..>
    check-questions <file>   (session 2's evidence, checked before it is recorded)
    check-failure-log <file> --catalogue <lab catalogue>   (session 3's evidence)
    compare-scores <file> --reference <file> [--out <file>]   (session 5's evidence: scores against the reference)

The sessions are in standards/train-the-trainer.yaml. The coordinator records each session a participant has
completed, with the private-store key of its evidence (the rubric forms, the question set, the failure log), in
training/<instructor slug>.yaml in the private store. A session is recorded once. The W1 train-the-trainer sign-off page
exists only once every session is recorded (`flows.onboarding`), and its inputs include the list, so the sign-off binds
to the record it was signed on. The record is not an event and holds no scores: the evidence stays under its key.

Intake (decision 0030) is the usual route: the session's `check` in the standards file picks the checker, a pass stores
the evidence under a generated key and records the session, and a refusal stores nothing and says what to fix. Every
intake is a line in training/intake/<instructor slug>.jsonl, a private document beside the record, never an event.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from . import units
from .standards import ROOT, domain_ids, load_yaml
from .util import slug

COURSE = Path("standards") / "train-the-trainer.yaml"
RECORDS = Path("training")
INTAKE = RECORDS / "intake"
EVIDENCE = Path("evidence") / "ttt"
CHECKS = ("scan", "question-set", "failure-log", "scores")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_INSTRUCTOR = re.compile(r"^tm:instructor/[a-z0-9][a-z0-9-]*$")


class CourseError(Exception):
    pass


def sessions(root: Path = ROOT) -> list[dict[str, Any]]:
    """The course's sessions, in order. Raises CourseError when the file is malformed or names an unknown domain."""
    doc = load_yaml(Path(root) / COURSE) or {}
    found = doc.get("sessions") or []
    domains = {d["id"] for d in (load_yaml(Path(root) / "standards" / "framework.yaml") or {}).get("domains", [])}
    ids = [s.get("id") for s in found]
    problems = [f"session {s.get('id')!r}: needs id, title, domains and evidence" for s in found
                if not all(s.get(k) for k in ("id", "title", "domains", "evidence"))]
    problems += [f"session {s.get('id')}: check {s.get('check')} is not one of {', '.join(CHECKS)}" for s in found
                 if s.get("check") not in CHECKS]
    problems += [f"session {s['id']}: unknown domain {d}" for s in found if s.get("id")
                 for d in s.get("domains") or [] if d not in domains]
    if len(set(ids)) != len(ids) or not found:
        problems.append("session ids must be unique, and there must be at least one session")
    if problems:
        raise CourseError("standards/train-the-trainer.yaml: " + "; ".join(problems))
    return found


def _path(private: Path, instructor: str) -> Path:
    return Path(private) / RECORDS / f"{slug(instructor)}.yaml"


def read(private: Path, instructor: str) -> dict[str, dict[str, str]]:
    """Session id -> {on, evidence_ref} for the sessions recorded so far."""
    path = _path(private, instructor)
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    return dict((doc or {}).get("sessions") or {})


def status(private: Path, instructor: str, root: Path = ROOT) -> list[dict[str, Any]]:
    """Every session in course order: recorded (its date) or missing. This list is the sign-off page's `course` input."""
    done = read(private, instructor)
    return [{"session": s["id"], "title": s["title"],
             "recorded": done[s["id"]]["on"] if s["id"] in done else "missing",
             "evidence": done[s["id"]]["evidence_ref"] if s["id"] in done else ""} for s in sessions(root)]


def missing(private: Path, instructor: str, root: Path = ROOT) -> list[str]:
    """The titles of the sessions not yet recorded, in course order."""
    return [r["title"] for r in status(private, instructor, root) if r["recorded"] == "missing"]


def record_generated(private: Path, instructor: str, on: date, registrations: dict[str, Any],
                     root: Path = ROOT) -> int:
    """For generated stores only (the simulator, dev-autosign, the end-to-end run): record every session a generated
    participant has not, on `on`, under a generated evidence key. Returns how many it recorded."""
    done = read(private, instructor)
    todo = [s["id"] for s in sessions(root) if s["id"] not in done]
    for session in todo:
        record(private, instructor, session, f"evidence/ttt/{slug(instructor)}-{session}.pdf", on, registrations, root)
    return len(todo)


def question_set_errors(doc: Any, root: Path = ROOT) -> list[str]:
    """Problems with a session 2 question set (the unit's `pre_check` shape, plus options whose wrong answers each name a
    misconception), or [] when it is well formed. See docs/train-the-trainer/02-prior-knowledge/LEARNER.md."""
    if not isinstance(doc, dict):
        return ["<root>: not a mapping"]
    try:
        unit = units.load(doc.get("unit"), root)
    except units.UnitError as exc:
        return [f"unit: {exc}"]
    known = {m["id"] for m in unit.get("misconceptions", [])}
    items = doc.get("pre_check") or []
    if not isinstance(items, list) or not items:
        return ["pre_check: needs at least one question"]
    errors: list[str] = []
    for n, item in enumerate(items):
        at = f"pre_check[{n}]"
        if not isinstance(item, dict):
            errors.append(f"{at}: not a mapping")
            continue
        options = [o for o in item.get("options") or [] if isinstance(o, dict)]
        if not all(item.get(k) for k in ("topic", "question", "options")):
            errors.append(f"{at}: needs topic, question and options")
        routes = item.get("routes")
        if not (isinstance(routes, dict) and routes.get("correct") and routes.get("incorrect")):
            errors.append(f"{at}: routes need correct and incorrect")
        if options and not 3 <= len(options) <= 5:
            errors.append(f"{at}: needs 3 to 5 options, has {len(options)}")
        correct = sum(o.get("correct") is True for o in options)
        if options and correct != 1:
            errors.append(f"{at}: needs exactly one correct option, has {correct}")
        wrong = [(i, o) for i, o in enumerate(options) if o.get("correct") is not True]
        for i, o in wrong:
            if o.get("misconception"):
                if o["misconception"] not in known:
                    errors.append(f"{at}.options[{i}]: misconception {o['misconception']} is not in {unit['id']}")
            elif not o.get("proposed_misconception"):
                errors.append(f"{at}.options[{i}]: a wrong option needs misconception (an id from the unit) "
                              "or proposed_misconception")
        if wrong and not any(o.get("misconception") in known for _, o in wrong):
            errors.append(f"{at}: at least one wrong option must use a misconception id from the unit")
    return errors


_LAB = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def failure_log_errors(doc: Any, catalogue: Any) -> list[str]:
    """Problems with a session 3 failure log against the lab's catalogue (a proving-ground `staff/catalogue.yaml`, or a
    unit: both hold `failure_catalogue`), or [] when it is well formed. See docs/train-the-trainer/03-lab-facilitation."""
    failures = [f.get("id") for f in (catalogue or {}).get("failure_catalogue") or [] if isinstance(f, dict)]
    if not failures:
        return ["catalogue: has no failure_catalogue"]
    if not isinstance(doc, dict):
        return ["<root>: not a mapping"]
    errors = []
    if not _LAB.match(str(doc.get("lab") or "")):
        errors.append("lab: a scenario slug (lower-case letters, digits and -)")
    if doc.get("failure") not in failures:
        errors.append(f"failure: {doc.get('failure')} is not in the catalogue ({', '.join(failures)})")
    if doc.get("against_expected") not in ("met", "partly", "missed"):
        errors.append("against_expected: met, partly or missed (the catalogue's expected_handling)")
    if not isinstance(doc.get("cohort_kept_moving"), bool):
        errors.append("cohort_kept_moving: true or false")
    done = str(doc.get("what_was_done") or "").strip()
    if not done:
        errors.append("what_was_done: say what was done")
    elif len(done) > 600:
        errors.append("what_was_done: at most 600 characters")
    return errors


def _recordings(doc: Any) -> list[dict[str, Any]]:
    found = (doc or {}).get("recordings") if isinstance(doc, dict) else None
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []


def _score_problems(label: str, scores: Any, domains: list[str]) -> list[str]:
    scores = scores if isinstance(scores, dict) else {}
    problems = [f"{label}: {d} must be a whole number 1-4" for d in domains
                if d in scores and not (type(scores[d]) is int and 1 <= scores[d] <= 4)]
    missing = [d for d in domains if d not in scores]
    return problems + ([f"{label}: missing {', '.join(missing)}"] if missing else [])


def compare_scores(scores: Any, reference: Any, root: Path = ROOT) -> tuple[list[dict[str, Any]], list[str]]:
    """Session 5: a participant's scores of the reference recordings against the reference, domain by domain. Returns
    (rows, problems); rows are empty when there are problems. Formative only: this is not a calibration (W5), writes no
    event and decides nothing. Both files are {recordings: [{recording: <label>, scores: {domain: 1-4}}]}."""
    domains = domain_ids(root)
    ref = {r.get("recording"): r.get("scores") for r in _recordings(reference)}
    problems = [p for label, s in ref.items() for p in _score_problems(f"reference {label}", s, domains)]
    if not ref or problems:
        return [], problems or ["reference: has no recordings"]
    mine = _recordings(scores)
    if len(mine) < 2:
        return [], ["recordings: score at least two reference recordings"]
    for r in mine:
        label = r.get("recording")
        bad = _score_problems(str(label), r.get("scores"), domains)
        problems += [p for p in bad if not p.startswith(f"{label}: missing")]
        if label not in ref:
            problems.append(f"{label}: not in the reference ({', '.join(str(k) for k in ref)})")
        problems += [p for p in bad if p.startswith(f"{label}: missing")]
    if problems:
        return [], problems
    rows = []
    for r in mine:
        theirs, want = r["scores"], ref[r["recording"]]
        rows.append({"recording": r["recording"],
                     "exact": round(sum(theirs[d] == want[d] for d in domains) / len(domains), 2),
                     "within_one": round(sum(abs(theirs[d] - want[d]) <= 1 for d in domains) / len(domains), 2),
                     "domains": [{"domain": d, "score": theirs[d], "reference": want[d],
                                  "difference": theirs[d] - want[d]} for d in domains]})
    return rows, []


def record(private: Path, instructor: str, session: str, evidence_ref: str, on: date,
           registrations: dict[str, Any], root: Path = ROOT) -> None:
    if not _INSTRUCTOR.match(instructor) or instructor not in registrations:
        raise CourseError(f"{instructor} is not a registered instructor")
    known = [s["id"] for s in sessions(root)]
    if session not in known:
        raise CourseError(f"no session {session!r}; the sessions are {', '.join(known)}")
    if not _KEY.match(evidence_ref) or ".." in evidence_ref:
        raise CourseError("--evidence-ref is a private-store key (letters, digits, . _ / -), never a link or a name")
    done = read(private, instructor)
    if session in done:
        raise CourseError(f"{session} is already recorded for {instructor} on {done[session]['on']}")
    done[session] = {"on": on.isoformat(), "evidence_ref": evidence_ref}
    path = _path(private, instructor)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"instructor": instructor, "sessions": done}, sort_keys=False), encoding="utf-8",
                    newline="\n")


# --- intake (decision 0030) -------------------------------------------------------------------------------------

_SCANS = {".pdf": ("PDF", (b"%PDF-",)), ".png": ("PNG", (b"\x89PNG\r\n\x1a\n",)),
          ".jpg": ("JPEG", (b"\xff\xd8\xff",)), ".jpeg": ("JPEG", (b"\xff\xd8\xff",))}
_QUESTION = re.compile(r"^pre_check\[(\d+)\](?:\.options\[(\d+)\])?: ")
_NO_MISCONCEPTION = "a wrong option needs misconception (an id from the unit) or proposed_misconception"


@dataclass(frozen=True)
class Intake:
    stored: bool
    key: str | None = None
    problems: list[str] = field(default_factory=list)


def scan_errors(name: str, data: bytes) -> list[str]:
    """Problems with a scanned form (sessions 1 and 4), or []: a non-empty PDF, PNG or JPEG whose content matches its
    name. The scan is not read beyond its first bytes."""
    if not data:
        return ["The file is empty."]
    ext = Path(name).suffix.lower()
    if ext not in _SCANS:
        return [f"A scan is a PDF, PNG or JPEG file; this one is {ext or 'without an extension'}."]
    kind, magic = _SCANS[ext]
    return [] if data.startswith(magic) else [f"The file is named {ext} but is not a {kind}."]


def plain(problems: list[str]) -> list[str]:
    """Checker output for people: "Question 2, option C" for `pre_check[1].options[2]`, a sentence per problem."""
    out = []
    for p in problems:
        m = _QUESTION.match(p)
        if m:
            where = f"Question {int(m[1]) + 1}" + (f", option {chr(ord('A') + int(m[2]))}" if m[2] else "")
            text = p[m.end():]
            if text == _NO_MISCONCEPTION:
                text = ("say which wrong idea this answer shows (a misconception id from the unit, "
                        "or proposed_misconception)")
            p = f"{where}: {text}"
        out.append(p if p.endswith(".") else p + ".")
    return out


def _check(session: dict[str, Any], path: Path, data: bytes, private: Path, catalogue: Path | None,
           reference: str | None, root: Path) -> tuple[list[str], bytes, str]:
    """(problems, the bytes to store, their extension). Problems are already in plain words."""
    kind = session["check"]
    if kind == "scan":
        return scan_errors(path.name, data), data, path.suffix.lower()
    if kind == "failure-log" and catalogue is None:
        raise CourseError(f"{session['id']} is checked against the lab's catalogue: give --catalogue <file>")
    if kind == "scores":
        if not reference:
            raise CourseError(f"{session['id']} is compared with the reference: give --reference <private-store key>")
        if not _KEY.match(reference) or ".." in reference or not (private / reference).is_file():
            raise CourseError(f"{reference} is not in the private store")
    try:
        doc = yaml.safe_load(data.decode("utf-8")) if data.strip() else None
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        return [f"The file cannot be read as YAML: {str(exc).splitlines()[0]}."], b"", ""
    if doc is None:
        return ["The file is empty."], b"", ""
    if kind == "question-set":
        return plain(question_set_errors(doc, root)), data, ".yaml"
    if kind == "failure-log":
        return plain(failure_log_errors(doc, load_yaml(catalogue))), data, ".yaml"
    rows, problems = compare_scores(doc, load_yaml(private / reference), root)
    comparison = yaml.safe_dump({"recordings": rows}, sort_keys=False).encode("utf-8")
    return plain(problems), comparison, ".yaml"


def _log(private: Path, instructor: str, entry: dict[str, Any]) -> None:
    path = Path(private) / INTAKE / f"{slug(instructor)}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry, sort_keys=False) + "\n")


def intake_log(private: Path, instructor: str) -> list[dict[str, Any]]:
    """Every intake for the participant, oldest first."""
    path = Path(private) / INTAKE / f"{slug(instructor)}.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def returned(private: Path, instructor: str) -> dict[str, int]:
    """Session id -> number of problems, for each session not yet recorded whose latest intake was refused."""
    latest = {e["session"]: e for e in intake_log(private, instructor)}
    done = read(private, instructor)
    return {s: len(e.get("problems") or []) for s, e in latest.items() if e["result"] == "refused" and s not in done}


def intake(private: Path, instructor: str, session: str, path: Path, on: date, registrations: dict[str, Any],
           now: datetime, catalogue: Path | None = None, reference: str | None = None, root: Path = ROOT) -> Intake:
    """Check one file of course evidence with its session's check. A pass stores it under a generated key
    (evidence/ttt/<slug>-<session>-<sha256[:8]><ext>) and records the session on `on`; a refusal stores and records
    nothing. Both are logged. Raises CourseError, logging nothing, for what the coordinator must put right first."""
    private, path = Path(private), Path(path)
    if not _INSTRUCTOR.match(instructor) or instructor not in registrations:
        raise CourseError(f"{instructor} is not a registered instructor")
    found = {s["id"]: s for s in sessions(root)}
    if session not in found:
        raise CourseError(f"no session {session!r}; the sessions are {', '.join(found)}")
    if on > now.date():
        raise CourseError(f"--on {on} is after today: give the day the session ran")
    done = read(private, instructor)
    if session in done:
        raise CourseError(f"{session} is already recorded for {instructor} on {done[session]['on']}")
    if not path.is_file():
        raise CourseError(f"no file {path}")
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    problems, evidence, ext = _check(found[session], path, data, private, catalogue, reference, root)
    entry: dict[str, Any] = {"at": now.isoformat(), "session": session, "sha256": sha}
    if problems:
        _log(private, instructor, {**entry, "result": "refused", "problems": problems})
        return Intake(stored=False, problems=problems)
    key = (EVIDENCE / f"{slug(instructor)}-{session}-{sha[:8]}{ext}").as_posix()
    (private / key).parent.mkdir(parents=True, exist_ok=True)
    (private / key).write_bytes(evidence)
    record(private, instructor, session, key, on, registrations, root)
    _log(private, instructor, {**entry, "result": "stored", "key": key, "on": on.isoformat()})
    return Intake(stored=True, key=key)
