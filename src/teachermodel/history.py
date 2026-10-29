"""`teachermodel history --clearance <uri>` and `teachermodel audit-export --quarter <YYYYQn>` (increment 4 item 5).

Spec v0.2, Acceptance: "The event log reproduces the history of any clearance on its own"; Interfaces: the command line
covers the audit export. Both read the event log only: no index, no private document, no name.

history: every event that led to the clearance, in log order: the candidate opened, the assignments and observations its
round counted, the dry runs, the round, the clearers' and the head's sign-offs, the clearance itself and anything later on
it (a lapse, a recheck). Each line names the event's id, day, kind and the facts it carries.

audit-export: the quarter's samples as JSON (`exports/audit-<quarter>.json` in the store): for each, the observation
drawn, the first and second observer, the agreement shares and whether the observer was referred back to calibration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import app
from .standards import ROOT
from .util import slug, write_if_changed

_QUARTER = re.compile(r"^\d{4}-?Q[1-4]\Z")


def _facts(e: dict[str, Any]) -> str:
    p, kind = e["payload"], e["kind"]
    if kind == "subject":
        return f"opened {p.get('subject_kind')} " + json.dumps(p.get("attrs", {}), sort_keys=True)
    if kind == "observation":
        scores = p.get("scores") or {}
        return (f"observer {p.get('observer')}, {p.get('mode')}, {p.get('length')}, lead {p.get('lead')}, "
                f"scores {json.dumps(scores, sort_keys=True)}")
    if kind == "dry_run":
        return f"{p.get('mode')}, passed {p.get('passed')}"
    if kind == "signoff":
        return f"{p.get('step')} {p.get('decision')} by {e['actor']}"
    if kind == "step":
        keep = {k: p[k] for k in ("step", "round", "reason", "observations", "observers", "dry_runs", "result", "clearance")
                if k in p}
        return json.dumps(keep, sort_keys=True)
    if kind == "clearance":
        return (f"{p.get('outcome')}, issued {p.get('issued')}, expires {p.get('expires')}, clearers "
                f"{', '.join(p.get('clearers', []))}, framework {p.get('framework_version')}"
                + (f", recheck {p['recheck']}" if p.get("recheck") else "") + (", founding" if p.get("founding") else ""))
    if kind == "check":
        return f"{p.get('step')} {p.get('result')}" + (f": {'; '.join(p['reasons'])}" if p.get("reasons") else "")
    return json.dumps(p, sort_keys=True)[:200]


def clearance_history(private_dir: Path | str, clearance: str, *, root: Path = ROOT) -> app.Report:
    log = app.read_events(private_dir)
    issued = [e for e in log if e["kind"] == "clearance" and e["payload"].get("clearance") == clearance]
    if not issued:
        raise app.AppError(f"{clearance} is not a clearance on record")
    candidate = issued[0]["payload"]["candidate"]
    round_id = slug(clearance)
    rnd = next((e for e in log if e["kind"] == "step" and e["subject_uri"] == candidate
                and e["payload"].get("round") == round_id), None)
    observations = set(issued[0]["payload"].get("observations") or []) | set((rnd or {}).get("payload", {})
                                                                            .get("observations") or [])
    assignments = {e["payload"].get("assignment") for e in log if e["id"] in observations}
    related = []
    for e in log:
        p = e["payload"]
        if (e["subject_uri"] == candidate and e["kind"] in ("subject", "dry_run", "signoff", "step", "check")) \
                or e["id"] in observations \
                or (e["kind"] == "subject" and e["subject_uri"] in assignments) \
                or (e["kind"] == "clearance" and p.get("clearance") == clearance):
            related.append(e)
    rep = app.Report(lines=[f"{e['at'][:10]}  {e['id'][:12]}  {e['kind']:<11} {_facts(e)}" for e in related])
    missing = observations - {e["id"] for e in log}
    if missing:
        rep.ok = False
        rep.lines.append(f"missing from the log: {', '.join(sorted(missing))}")
    rep.summary = (f"history: {clearance} for {candidate}, {len(related)} event(s); round {round_id}"
                   f"{' on record' if rnd else ' NOT on record'}; {len(observations)} observation(s)")
    return rep


def audit_export(private_dir: Path | str, quarter: str, *, root: Path = ROOT) -> app.Report:
    if not _QUARTER.match(quarter):
        raise app.AppError(f"quarter: {quarter!r} is not a quarter (YYYYQn)")
    want = quarter.replace("-", "")
    private = Path(private_dir)
    st = app.load_state(private, root)
    voided = {e["subject_uri"] for e in st.events if e["kind"] == "step"
              and (e["payload"].get("void") is True or e["payload"].get("result") == "void")}
    audits = {e["payload"]["sample"]: e for e in st.events if e["kind"] == "audit"}
    rows = []
    for uri in sorted(u for u, info in st.subjects.items() if info.get("kind") == "sample"
                      and str(info.get("quarter", "")).replace("-", "") == want):
        info = st.subjects[uri]
        a = (audits.get(uri) or {}).get("payload", {})
        rows.append({"sample": uri, "observation": info.get("observation"), "instructor": info.get("instructor"),
                     "observer": info.get("observer"), "second_observer": info.get("second_observer"),
                     "void": uri in voided, "scored": bool(a), "within_one_share": a.get("within_one_share"),
                     "exact_share": a.get("exact_share"), "agreed": a.get("agreed"),
                     "referred_to_calibration": a.get("referred_to_calibration")})
    doc = {"quarter": want, "samples": rows,
           "summary": {"drawn": len(rows), "void": sum(r["void"] for r in rows),
                       "scored": sum(r["scored"] for r in rows), "agreed": sum(bool(r["agreed"]) for r in rows),
                       "referred": sum(bool(r["referred_to_calibration"]) for r in rows)}}
    target = private / "exports" / f"audit-{want}.json"
    write_if_changed(target, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    s = doc["summary"]
    return app.Report(lines=[f"file: {target.relative_to(private).as_posix()}"],
                      summary=f"audit-export {want}: {s['drawn']} drawn, {s['void']} void, {s['scored']} scored, "
                              f"{s['agreed']} agreed, {s['referred']} referred")
