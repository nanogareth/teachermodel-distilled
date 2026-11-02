"""`teachermodel audition`: a candidate teaches a 15-minute slice of a real lab, scored on the clearance rubric (decision 0025).

    audition new      --unit <sl:unit/..> --mode <mode> --slice <text> --candidate <name> [--on DAY]
                      opens auditions/<id>/ with the pack (the slice, the rubric's form) and a blank form.yaml
    audition assign   <id> --observer <tm:instructor/..> --observer <..> [--on DAY]   two observers from the observer pool
    audition replace  <id> --leaving <..> --joining <..> --reasons <text> [--on DAY]  an observer who has not scored yet
    audition score    <id> --observer <..> --form <filled form.yaml>                  the paper route: once per observer
    audition status   <id>                                                            who has scored (never what)
    audition result   <id>                       the evidence for the panel, once both forms are in (result.yaml, result.md)
    audition decide   <id> --decision hired|not-hired --reasons <text> --by <tm:person/..> [--on DAY]
    audition carry    <id> --instructor <tm:instructor/..>   after hire and registration: the starting plan, once per
                                                            audition and once per instructor

Each assigned observer also gets their own signed page (decision 0031): pages/audition-score--<id>--<observer slug>.html,
drawn on assign, replace and every tick until they have scored. The signed file comes back through the sign-off mailbox;
ingest hands it to `receive`, which keeps it with the audition and writes nothing to the event log. A domain may be marked
not observable in this slice, with a note; it is kept out of every average.

Kept apart from the instructor record: files under auditions/ in the private store, the candidate's name only in
identities/auditions.yaml, nothing in the event log. Evidence only: the result says where each domain stands against the
clearance bar and whether the observers agree within one point, and never recommends; the panel decides and records its
reasons. A store that is not simulated refuses to open an audition until standards/retention.yaml has an entry for the
`audition-records` category.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import date, datetime
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

from . import app, signoff, units
from . import pages as pagegen
from .bridge import AUDITION_STEP
from .flows import cpd
from .flows.common import observer_pool
from .standards import ROOT, load_yaml
from .util import slug

DIR = Path("auditions")
IDENTITIES = Path("identities") / "auditions.yaml"
PLANS = Path("generated") / "audition"
CATEGORY = "audition-records"
MODES = ("in-person", "remote", "hybrid")
DECISIONS = ("hired", "not-hired")
SLICE_MINUTES = 15
STEP = AUDITION_STEP
ROLE = "clearer"  # observers are calibrated clearers (common.observer_pool); their mailbox carries the role
TEMPLATE = "approve"
_ID = re.compile(r"^[a-z0-9-]+$")
_INSTRUCTOR = re.compile(r"^tm:instructor/[a-z0-9][a-z0-9-]*$")
_PERSON = re.compile(r"^tm:(person|instructor)/[a-z0-9][a-z0-9-]*$")


class AuditionError(Exception):
    pass


# --- files ---------------------------------------------------------------------------------------------------------


def _read(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None


def _write(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")


def _folder(private: Path, audition: str) -> Path:
    if not _ID.match(audition):
        raise AuditionError(f"{audition!r} is not an audition id")
    folder = private / DIR / audition
    if not (folder / "audition.yaml").is_file():
        raise AuditionError(f"no audition {audition}")
    return folder


def _scores(folder: Path) -> dict[str, dict[str, Any]]:
    """Observer -> their recorded form, for the forms recorded so far."""
    record = _read(folder / "audition.yaml")
    return {o: form for o in record.get("observers", []) if (form := _read(folder / f"score--{slug(o)}.yaml"))}


# --- the gate ------------------------------------------------------------------------------------------------------


def gate(settings: dict[str, Any], root: Path = ROOT) -> str | None:
    """Why an audition may not be opened in this store, or None. A simulated store may (decision 0020); any other needs a
    retention entry for the audition-records category, which needs legal review first (decision 0025)."""
    if settings.get("simulated") is True:
        return None
    retention = load_yaml(root / "standards" / "retention.yaml") or {}
    if any(e.get("category") == CATEGORY for e in retention.get("entries") or []):
        return None
    return (f"auditions hold candidates' data: standards/retention.yaml needs an entry for the {CATEGORY} category, "
            "with a lawful basis for hiring, before a real audition is opened (decision 0025)")


# --- pure: the evidence ----------------------------------------------------------------------------------------------


def evidence(forms: dict[str, dict[str, int]], order: list[str], rules: dict[str, Any]) -> dict[str, Any]:
    """The panel's evidence from two observers' scores: per domain each score, the average, whether the two are within one
    point, and whether the average meets the clearance bar; the overall mean against its bar. No recommendation."""
    bar, overall_bar = rules["clearance"]["min_domain_average"], rules["clearance"]["min_overall_mean"]
    observers = sorted(forms)
    domains = []
    for d in order:
        scores = [forms[o][d] for o in observers]
        if any(s is None for s in scores):  # not observable by one of them (decision 0031): no average, no flag
            domains.append({"domain": d, "scores": dict(zip(observers, scores)), "average": None, "within_one": None,
                            "meets_clearance_bar": None,
                            "not_observable_by": [o for o, s in zip(observers, scores) if s is None]})
            continue
        average = round(float(mean(scores)), 2)
        domains.append({"domain": d, "scores": dict(zip(observers, scores)), "average": average,
                        "within_one": max(scores) - min(scores) <= 1, "meets_clearance_bar": average >= bar})
    scored = [x for x in domains if x["average"] is not None]
    overall = round(float(mean(x["average"] for x in scored)), 2) if scored else None
    return {"observers": observers, "domains": domains,
            "overall_mean": overall, "overall_meets_clearance_bar": overall is not None and overall >= overall_bar,
            "clearance_bar": {"domain_average": bar, "overall_mean": overall_bar},
            "domains_scored": len(scored), "not_observable": [x["domain"] for x in domains if x["average"] is None],
            "agreement_within_one": round(sum(x["within_one"] for x in scored) / len(scored), 2) if scored else None,
            "domains_to_discuss": [x["domain"] for x in scored if not x["within_one"]]}


def starting_plan(result: dict[str, Any], order: list[str]) -> list[tuple[str, float]]:
    """The new instructor's first gaps, seeded as the CPD plan is: the two lowest domains below 3 (cpd.seed_gaps)."""
    averages = {x["domain"]: x["average"] for x in result["domains"] if x["average"] is not None}
    return cpd.seed_gaps(averages, [d for d in order if d in averages])


# --- commands ------------------------------------------------------------------------------------------------------


def _pack(record: dict[str, Any], unit: dict[str, Any], rubric: dict[str, Any], order: list[str]) -> str:
    lines = [f"# Audition {record['id']}", "",
             f"Unit: {unit['title']} ({record['unit']}), {record['mode']}. Opened {record['opened']}.", "",
             f"## The slice ({SLICE_MINUTES} minutes)", "", record["slice"], "",
             "The candidate teaches this slice as they would teach it to the cohort. Two observers score it "
             "independently on the clearance rubric and do not compare scores before both forms are recorded.", "",
             "## The form", "", "Score every domain from 1 to 4 with one note of what you saw. Fill in form.yaml.", ""]
    for d in order:
        lines += [f"### {d}", ""] + [f"- **{n} {rubric['scale'][n]}**: {rubric['anchors'][d][n]}"
                                     for n in sorted(rubric["anchors"][d])] + [""]
    lines += ["The result is evidence for the people deciding the hire, never a decision. An audition does not count toward "
              "clearance (decision 0025).", ""]
    return "\n".join(lines)


def open_audition(private: Path, unit_uri: str, mode: str, slice_text: str, candidate: str, on: date,
                  root: Path = ROOT, audition: str | None = None) -> str:
    st = app.load_state(private, root)
    if reason := gate(st.settings, root):
        raise AuditionError(reason)
    if mode not in MODES:
        raise AuditionError(f"mode must be one of {', '.join(MODES)}")
    if not slice_text.strip() or not candidate.strip():
        raise AuditionError("the slice and the candidate's name are required")
    try:
        unit = units.load(unit_uri, root)
    except units.UnitError as exc:
        raise AuditionError(str(exc)) from None
    audition = audition or f"a-{secrets.token_hex(3)}"
    folder = private / DIR / audition
    if folder.exists():
        raise AuditionError(f"audition {audition} exists")
    order = cpd.domain_order(st)
    record = {"id": audition, "uri": f"tm:audition/{audition}", "unit": unit_uri, "mode": mode,
              "slice": slice_text.strip(), "opened": on.isoformat(), "observers": [], "assigned": None}
    _write(folder / "audition.yaml", record)
    _write(folder / "form.yaml", {d: {"score": None, "note": ""} for d in order})
    (folder / "pack.md").write_text(_pack(record, unit, st.standards["rubric"], order), encoding="utf-8", newline="\n")
    names = _read(private / IDENTITIES) or {}
    names[audition] = {"candidate": candidate.strip()}
    _write(private / IDENTITIES, names)
    return audition


def assign(private: Path, audition: str, observers: list[str], on: date, root: Path = ROOT) -> None:
    folder = _folder(private, audition)
    record = _read(folder / "audition.yaml")
    if record["observers"]:
        raise AuditionError(f"audition {audition} already has its observers")
    if len(observers) != 2 or len(set(observers)) != 2:
        raise AuditionError("an audition needs two different observers")
    pool = observer_pool(app.load_state(private, root), on)
    if outside := [o for o in observers if o not in pool]:
        raise AuditionError(f"not in the observer pool on {on} (a calibrated clearer, not bench-blocked): "
                            + ", ".join(outside))
    record.update(observers=sorted(observers), assigned=on.isoformat())
    _write(folder / "audition.yaml", record)
    write_pages(private, audition, root=root)


def replace(private: Path, audition: str, leaving: str, joining: str, reasons: str, on: date,
            root: Path = ROOT) -> None:
    """Swap an observer who drops out, before they have scored: the newcomer comes from the pool, and the swap is kept
    with its reason. Once an observer's form is in they stay, since the form is recorded once."""
    folder = _folder(private, audition)
    record = _read(folder / "audition.yaml")
    if not record["observers"]:
        raise AuditionError(f"audition {audition} has no observers yet: assign two")
    if leaving not in record["observers"]:
        raise AuditionError(f"{leaving} is not an observer of audition {audition}")
    if (folder / f"score--{slug(leaving)}.yaml").exists():
        raise AuditionError(f"{leaving} has scored audition {audition}; an observer who has scored is not replaced")
    if joining in record["observers"]:
        raise AuditionError(f"{joining} is already an observer of audition {audition}")
    if len(reasons.strip()) < 10:
        raise AuditionError("the reason for the replacement is required (at least 10 characters)")
    if joining not in observer_pool(app.load_state(private, root), on):
        raise AuditionError(f"not in the observer pool on {on} (a calibrated clearer, not bench-blocked): {joining}")
    record["observers"] = sorted([o for o in record["observers"] if o != leaving] + [joining])
    record.setdefault("replaced", []).append({"leaving": leaving, "joining": joining, "reason": reasons.strip(),
                                              "on": on.isoformat()})
    _write(folder / "audition.yaml", record)
    write_pages(private, audition, root=root)


def score(private: Path, audition: str, observer: str, form: dict[str, Any], root: Path = ROOT) -> None:
    folder = _folder(private, audition)
    record = _read(folder / "audition.yaml")
    if observer not in record["observers"]:
        raise AuditionError(f"{observer} is not an observer of audition {audition}")
    target = folder / f"score--{slug(observer)}.yaml"
    if target.exists():
        raise AuditionError(f"{observer} has already scored audition {audition}; a form is recorded once")
    clean, problems = _clean(form, cpd.domain_order(app.load_state(private, root)))
    if problems:
        raise AuditionError("; ".join(problems))
    _write(target, clean)
    write_pages(private, audition, root=root)  # the observer's page is no longer needed


def _clean(form: Any, order: list[str]) -> tuple[dict[str, Any], list[str]]:
    """The form as stored, and its problems: every domain scored 1 to 4 or marked not observable (decision 0031), each
    with an evidence note."""
    if not isinstance(form, dict) or sorted(form) != sorted(order):
        return {}, [f"the form needs exactly the domains {', '.join(order)}"]
    clean, problems = {}, []
    for d in order:
        entry = form[d] if isinstance(form[d], dict) else {}
        note = entry.get("note").strip() if isinstance(entry.get("note"), str) else ""
        if entry.get("not_observable") is True and entry.get("score") is None:
            clean[d] = {"score": None, "not_observable": True, "note": note}
        elif type(entry.get("score")) is int and 1 <= entry["score"] <= 4 and "not_observable" not in entry:
            clean[d] = {"score": entry["score"], "note": note}
        else:
            problems.append(f"{d}: a score 1 to 4, or not observable, is required (the score must be a whole number "
                            "from 1 to 4)")
            continue
        if not note:
            problems.append(f"{d}: an evidence note is required")
    return clean, problems


def status(private: Path, audition: str) -> dict[str, Any]:
    folder = _folder(private, audition)
    record = _read(folder / "audition.yaml")
    scored = _scores(folder)
    return {"id": audition, "observers": record["observers"], "scored": sorted(scored),
            "waiting_for": [o for o in record["observers"] if o not in scored],
            "decided": (_read(folder / "decision.yaml") or {}).get("decision")}


def result(private: Path, audition: str, root: Path = ROOT) -> dict[str, Any]:
    folder = _folder(private, audition)
    record = _read(folder / "audition.yaml")
    forms = _scores(folder)
    if not record["observers"] or len(forms) < 2:
        raise AuditionError(f"audition {audition} has {len(forms)} of 2 forms; the scores stay hidden until both are in")
    st = app.load_state(private, root)
    order = cpd.domain_order(st)
    doc = {"id": audition, "unit": record["unit"], "mode": record["mode"],
           **evidence({o: {d: f[d]["score"] for d in order} for o, f in forms.items()}, order, st.standards["rules"])}
    _write(folder / "result.yaml", doc)
    (folder / "result.md").write_text(_result_page(doc, forms), encoding="utf-8", newline="\n")
    return doc


def _result_page(doc: dict[str, Any], forms: dict[str, dict[str, Any]]) -> str:
    obs = doc["observers"]
    bar = doc["clearance_bar"]
    lines = [f"# Audition {doc['id']}: evidence for the panel", "",
             f"{doc['unit']}, {doc['mode']}. Two observers scored a {SLICE_MINUTES}-minute slice on the clearance rubric. "
             "This is evidence, not a decision: the panel decides and records its reasons.", "",
             "| Domain | " + " | ".join(slug(o) for o in obs) + " | Average | Observers within one | "
             f"Meets the clearance bar ({bar['domain_average']}) |",
             "| --- |" + " --- |" * (len(obs) + 3)]
    for x in doc["domains"]:
        if x["average"] is None:
            lines.append(f"| {x['domain']} | " + " | ".join(
                "not observable" if x["scores"][o] is None else str(x["scores"][o]) for o in obs) + " | - | - | - |")
            continue
        lines.append(f"| {x['domain']} | " + " | ".join(str(x["scores"][o]) for o in obs)
                     + f" | {x['average']} | {'yes' if x['within_one'] else 'no'} | "
                       f"{'yes' if x['meets_clearance_bar'] else 'no'} |")
    total = len(doc["domains"])
    if doc["overall_mean"] is None:
        lines += ["", "No domain was scored by both observers, so there is no overall mean.", ""]
    else:
        lines += ["", f"Overall mean {doc['overall_mean']} over {doc.get('domains_scored', total)} of {total} domains, "
                      f"against the clearance bar of {bar['overall_mean']}: "
                      f"{'meets it' if doc['overall_meets_clearance_bar'] else 'below it'}.", ""]
    if doc.get("not_observable"):
        lines += ["Not observable in this slice, by at least one observer, and kept out of every average: "
                  + ", ".join(doc["not_observable"]) + ".", ""]
    if doc["domains_to_discuss"]:
        lines += ["The observers differ by two points or more on " + ", ".join(doc["domains_to_discuss"])
                  + ". Discuss what each saw before deciding.", ""]
    lines += ["## Observers' notes", ""]
    for x in doc["domains"]:
        lines += [f"### {x['domain']}", ""] + [f"- {slug(o)}: {forms[o][x['domain']]['note'] or '(no note)'}"
                                               for o in obs] + [""]
    lines += ["An audition is one short observation and does not count toward clearance (decision 0025).", ""]
    return "\n".join(lines)


def decide(private: Path, audition: str, decision: str, reasons: str, by: str, on: date) -> None:
    folder = _folder(private, audition)
    if not (folder / "result.yaml").exists():
        raise AuditionError("run `audition result` first: the panel decides on the evidence")
    if (folder / "decision.yaml").exists():
        raise AuditionError(f"audition {audition} is decided; a decision is recorded once")
    if decision not in DECISIONS:
        raise AuditionError(f"the decision is one of {', '.join(DECISIONS)}")
    if len(reasons.strip()) < 20:
        raise AuditionError("the panel's reasons are required (at least 20 characters)")
    if not _PERSON.match(by):
        raise AuditionError("--by is the panel chair's tm:person/ or tm:instructor/ id")
    _write(folder / "decision.yaml", {"decision": decision, "reasons": reasons.strip(), "by": by, "on": on.isoformat()})


def carry(private: Path, audition: str, instructor: str, root: Path = ROOT) -> Path:
    folder = _folder(private, audition)
    if (_read(folder / "decision.yaml") or {}).get("decision") != "hired":
        raise AuditionError(f"audition {audition} is not decided as hired")
    st = app.load_state(private, root)
    if not _INSTRUCTOR.match(instructor) or instructor not in st.registrations:
        raise AuditionError(f"{instructor} is not a registered instructor: import the roster first")
    names = _read(private / IDENTITIES) or {}
    if carried := (names.get(audition) or {}).get("instructor"):
        raise AuditionError(f"audition {audition} is already carried to {carried}")
    if other := next((a for a, n in sorted(names.items()) if (n or {}).get("instructor") == instructor), None):
        raise AuditionError(f"{instructor} already carried audition {other}: one starting plan per instructor")
    target = private / PLANS / f"{slug(instructor)}.md"
    if target.exists():
        raise AuditionError(f"{target.relative_to(private).as_posix()} exists: one starting plan per instructor")
    order = cpd.domain_order(st)
    doc = _read(folder / "result.yaml")
    forms = _scores(folder)
    gaps = starting_plan(doc, order)
    lines = [f"# Starting plan: {slug(instructor)}", "",
             f"From audition {audition} ({doc['unit']}, {doc['mode']}): the two lowest domains below {cpd.TARGET}, "
             "seeded the way the CPD plan is. The first W2 observations start the instructor's record; the audition "
             "does not count toward clearance.", ""]
    if not gaps:
        lines += [f"No domain averaged below {cpd.TARGET} at audition: the coach sets the first focus from the first "
                  "observations.", ""]
    for domain, average in gaps:
        lines += [f"## {domain} (audition average {average})", ""] + [
            f"- {slug(o)}: {forms[o][domain]['note'] or '(no note)'}" for o in sorted(forms)] + [""]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    names.setdefault(audition, {})["instructor"] = instructor
    _write(private / IDENTITIES, names)
    return target


# --- the observers' pages (decision 0031) -------------------------------------------------------------------------


def _subject(audition: str) -> str:
    return f"tm:audition/{audition}"


def _assigned_on(record: dict[str, Any], observer: str) -> date | None:
    """The day the observer was given the audition: the assignment, or the replacement that brought them in."""
    day = next((r["on"] for r in reversed(record.get("replaced") or []) if r.get("joining") == observer),
               record.get("assigned"))
    return date.fromisoformat(day) if day else None


def page_spec(st: app.State, record: dict[str, Any], observer: str) -> dict[str, Any]:
    """The observer's score page: the slice and the rubric's evidence-score field per domain, with not observable. It
    holds no name and nothing of the other observer's form."""
    unit = units.load(record["unit"], st.root)
    inputs = {"audition": record["id"], "unit": record["unit"], "unit_title": unit["title"], "mode": record["mode"],
              "slice": record["slice"], "minutes": SLICE_MINUTES, "observer": observer,
              "assigned": str(_assigned_on(record, observer))}
    fields = [{**f, "not_observable": True} for f in pagegen.evidence_score_fields(st.standards)]
    return {"template": TEMPLATE, "step": STEP, "subject_uri": _subject(record["id"]), "signer": observer, "role": ROLE,
            "inputs": inputs, "fields": fields, "title": f"Audition {record['id']}: your scores",
            "intro": (f"Score the candidate's {SLICE_MINUTES}-minute slice on each domain against the anchors, with the "
                      "evidence for the score. Where the slice did not show a domain, choose \"Not observable in this "
                      "slice\" and say why: it is kept out of every average.\n\nYou score alone: nobody sees your form, "
                      "and you never see the other observer's, until both are in. Save, then send the file to the "
                      "programme mailbox. This is evidence for the people deciding the hire; it does not count toward clearance "
                      "(decisions 0025 and 0031).")}


def _page_path(private: Path, audition: str, observer: str) -> Path:
    return private / "pages" / f"{app.page_stem(STEP, _subject(audition), observer)}.html"


def write_pages(private: Path, audition: str | None = None, st: app.State | None = None,
                root: Path = ROOT) -> tuple[int, int]:
    """Draw the page of every assigned observer who has not scored, for one audition or all of them, and remove the page
    of an observer who has scored or was replaced. Returns (written, removed)."""
    private = Path(private)
    folders = ([private / DIR / audition] if audition
               else sorted(p.parent for p in (private / DIR).glob("*/audition.yaml")))
    st = st or app.load_state(private, root)
    channel = {"kind": "mail", "to": st.settings["mailbox"]}
    written = removed = 0
    for folder in folders:
        record = _read(folder / "audition.yaml") or {}
        if not record.get("observers") or (folder / "decision.yaml").exists():
            continue
        scored = _scores(folder)
        due = [o for o in record["observers"] if o not in scored]
        for o in due:
            spec = page_spec(st, record, o)
            html, _ = pagegen.render(**spec, channel=channel, root=st.root)
            *_, changed = pagegen.write_page_if_changed(private / "pages", _page_path(private, record["id"], o).stem,
                                                        html, spec["inputs"])
            written += changed
        gone = set(scored) | {r["leaving"] for r in record.get("replaced") or []}
        for o in sorted(gone - set(due)):
            page = _page_path(private, record["id"], o)
            for path in (page, page.with_suffix(".input.json")):
                if path.exists():
                    path.unlink()
                    removed += path.suffix == ".html"
    return written, removed


def _refuse(folder: Path | None, doc: dict[str, Any], reasons: list[str], now: datetime) -> str:
    """Note a refusal once per (document, reasons) in the audition's refused.jsonl; returns the report line."""
    line = f"audition form refused ({doc.get('id') or '<no id>'}): {'; '.join(reasons)}"
    if folder is None:
        return line
    path = folder / "refused.jsonl"
    seen = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []
    if not any(e.get("signoff_id") == doc.get("id") and e.get("reasons") == reasons for e in seen):
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"at": now.isoformat(timespec="seconds"), "signoff_id": doc.get("id"),
                                "signer": doc.get("signer"), "reasons": reasons}) + "\n")
    return line


def receive(private: Path, items: list[tuple[dict[str, Any], str]], now: datetime,
            root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Take in observers' signed forms from a receipt (the bridge read the sender from the message). Accepted: the form
    becomes score--<observer>.yaml with the signed document beside it. Refused: noted in refused.jsonl. Nothing goes to
    the event log either way. Returns (stored lines, refused lines)."""
    private = Path(private)
    st = app.load_state(private, root)
    order = cpd.domain_order(st)
    stored: list[str] = []
    refused: list[str] = []
    for doc, sender in items:
        subject = doc.get("subject_uri") if isinstance(doc.get("subject_uri"), str) else ""
        aid = subject.removeprefix("tm:audition/")
        folder = private / DIR / aid
        if not (subject.startswith("tm:audition/") and _ID.match(aid) and (folder / "audition.yaml").is_file()):
            refused.append(_refuse(None, doc, [f"no audition {aid or subject}"], now))
            continue
        record = _read(folder / "audition.yaml")
        observer = doc.get("signer")
        if observer not in record.get("observers", []):
            refused.append(_refuse(folder, doc, [f"{observer} is not an observer of this audition"], now))
            continue
        kept = folder / f"signoff--{slug(observer)}.json"
        if kept.exists() and json.loads(kept.read_text(encoding="utf-8")).get("id") == doc.get("id"):
            continue  # the same message read again
        if (folder / f"score--{slug(observer)}.yaml").exists():
            refused.append(_refuse(folder, doc, [f"{observer} has already scored this audition; a form is recorded "
                                                 "once"], now))
            continue
        spec = page_spec(st, record, observer)
        res = signoff.accept(doc, current_input_sha256=signoff.input_sha256(spec["inputs"]), sender_email=sender,
                             identities=st.identities, step_role=ROLE, expected_signer=observer,
                             opened_on=_assigned_on(record, observer), now=now)
        if res.duplicate:
            continue
        reasons = list(res.reasons)
        clean: dict[str, Any] = {}
        if not reasons:
            if doc["step"] != STEP:
                reasons.append(f"not an audition form ({doc['step']})")
            if doc["page_template_sha256"] != pagegen.template_sha256(TEMPLATE):
                reasons.append("unknown page template")
            if doc["decision"] != "approve":
                reasons.append("an audition form is saved with the decision approve")
            clean, problems = _clean(doc["fields"], order)
            reasons += problems
        if reasons:
            refused.append(_refuse(folder, doc, reasons, now))
            continue
        _write(folder / f"score--{slug(observer)}.yaml", clean)
        kept.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        write_pages(private, aid, st=st, root=root)
        stored.append(f"audition {aid}: form from {observer} recorded")
    return stored, refused
