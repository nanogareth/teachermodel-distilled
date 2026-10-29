"""`teachermodel gates`: the spec's phase gates and acceptance criteria, computed from a store (increment 4, item 1).

Each criterion is one of:
- `met` / `unmet`: computed from the event log, the registrations and the standards, with the evidence or the shortfall;
- `attested`: a property no store can show (the test suite, a person's agreement); the line says how it is checked;
- `not-built`: the feature the criterion needs does not exist yet; the line names the increment item.

Read only: nothing is written. Spec v0.2, Build phases and Acceptance criteria. Run it on a simulated store
(`dev-simulate`) to rehearse the gates; real gates are passed on live data only.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import app, records, rules, staffing
from .flows.common import clearer_instructors
from .standards import ROOT, load_yaml

MET, UNMET, ATTESTED, NOT_BUILT = "met", "unmet", "attested", "not-built"
BELOW_CLEARED = ("shadow", "co-deliver", "lead-observed")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ALLOWED_DOMAINS = ("example.com", "example.org", "example.net", "anthropic.com", "users.noreply.github.com")
RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost")  # RFC 2606: never a real mailbox
FICTIONAL_DIRS = ("tests/",)  # fixtures are fictional by rule (CLAUDE.md), including addresses on real-looking domains


@dataclass(frozen=True)
class Criterion:
    id: str
    title: str
    status: str
    detail: str


def _day(stamp: str) -> date:
    return date.fromisoformat(stamp[:10])


def _quarter_end(q: str) -> date:
    year, n = int(q[:4]), int(q[-1])
    first_next = date(year + (n == 4), 1 if n == 4 else 3 * n + 1, 1)
    return first_next - timedelta(days=1)


class _Facts:
    """What the criteria read, computed once."""

    def __init__(self, st: app.State, on: date) -> None:
        self.st, self.on = st, on
        self.log = st.events
        self.rules = st.standards["rules"]
        self.passes, self.lapses = records.calibrations(self.log), records.lapses(self.log)
        self.exited = {b["instructor"] for b in records.bench(self.log)
                       if (b["decision"] or {}).get("decision") == "exit"}
        self.active = sorted(u for u, reg in st.registrations.items()
                             if (reg.get("engagement") or {}).get("status", "active") == "active" and u not in self.exited)
        self.clearers = [c for c in clearer_instructors(st.registrations, self.log, st.people) if c in self.active]
        self.by_id = {e["id"]: e for e in self.log}
        self.clearances = [e for e in self.log if e["kind"] == "clearance"]
        self.rounds = {e["payload"]["round"]: e for e in self.log if e["kind"] == "step"
                       and e["payload"].get("step") == "tm:step/evidence-ready" and isinstance(e["payload"].get("round"), str)}
        self.cycles = [e for e in self.log if e["kind"] == "coaching_cycle"]
        self.triggers = [e for e in self.log if e["kind"] == "check" and e["payload"].get("step") == "tm:step/quality-review"
                         and e["payload"].get("result") == "trigger"]
        voided = {e["subject_uri"] for e in self.log if e["kind"] == "step" and (e["payload"].get("void") is True
                                                                                or e["payload"].get("result") == "void")}
        self.samples = {u: info for u, info in st.subjects.items() if info.get("kind") == "sample" and u not in voided}
        self.audits = {e["payload"]["sample"]: e for e in self.log if e["kind"] == "audit"}

    def calibrated(self, who: str, on: date) -> bool:
        return rules.is_calibrated(who, on, self.passes, self.rules, self.lapses.get(who))


# --- acceptance criteria ---------------------------------------------------------------------------------------------


def _staffed(f: _Facts) -> Criterion:
    """Every delivery on record (the outcome imports) was staffed by an instructor cleared for its unit and mode on its
    day, or carries an override."""
    title = "Every delivery staffed by a cleared instructor or an override"
    outcomes = [e["payload"] for e in f.log if e["kind"] == "outcome"]
    if not outcomes:
        return Criterion("A1", title, UNMET, "no deliveries on record yet (outcome imports)")
    bad = [o["delivery_ref"] for o in outcomes
           if staffing.check(f.log, {"instructor": o["instructor"], "unit": o["unit"], "mode": o["mode"],
                                     "date": o["delivered_on"]}, f.rules)["verdict"] == "block"]
    return Criterion("A1", title, UNMET if bad else MET,
                     f"{len(outcomes) - len(bad)} of {len(outcomes)} deliveries cleared or overridden"
                     + (f"; blocked: {', '.join(sorted(bad)[:5])}{' ...' if len(bad) > 5 else ''}" if bad else ""))


def _clearance_links(f: _Facts) -> Criterion:
    """Every clearance links to 2+ observations by 2+ observers calibrated on the day, a dry run, both clearers and the
    framework version (the round it was issued on holds the observations and dry runs)."""
    short = []
    for e in f.clearances:
        p = e["payload"]
        rnd = f.rounds.get(p["clearance"].split("/", 1)[1])
        obs = [f.by_id.get(o) for o in p.get("observations", [])]
        observers = {o["payload"]["observer"] for o in obs if o and f.calibrated(o["payload"]["observer"], _day(o["at"]))}
        problems = []
        if len([o for o in obs if o]) < 2:
            problems.append("fewer than 2 observations in the log")
        if len(observers) < 2:
            problems.append("fewer than 2 calibrated observers")
        if not rnd or not rnd["payload"].get("dry_runs"):
            problems.append("no dry run on its round")
        if len(set(p.get("clearers", []))) < 2:
            problems.append("fewer than 2 clearers")
        if not p.get("framework_version"):
            problems.append("no framework version")
        if problems:
            short.append(f"{p['clearance']} ({'; '.join(problems)})")
    status = MET if f.clearances and not short else UNMET
    detail = (f"{len(f.clearances) - len(short)} of {len(f.clearances)} clearances fully linked" if f.clearances
              else "no clearances yet") + (f"; {short[0]}" + (f" and {len(short) - 1} more" if len(short) > 1 else "")
                                           if short else "")
    return Criterion("A2", "Every clearance links its observations, observers, dry run, clearers and framework", status, detail)


def _clearers_calibrated(f: _Facts) -> Criterion:
    lapsed = [c for c in f.clearers if not f.calibrated(c, f.on)]
    return Criterion("A3", "Every active clearer calibrated within the renewal period",
                     MET if f.clearers and not lapsed else UNMET,
                     f"{len(f.clearers) - len(lapsed)} of {len(f.clearers)} clearers calibrated on {f.on}"
                     + (f"; lapsed: {', '.join(lapsed)}" if lapsed else ""))


def _closed_quarters(f: _Facts) -> list[str]:
    quarters = sorted({str(info.get("quarter", "")).replace("-", "") for info in f.samples.values()})
    return [q for q in quarters if q and _quarter_end(q) < f.on]


def _audits(f: _Facts) -> Criterion:
    title = "Each quarter's audit sample drawn, double-scored, agreed or referred"
    quarters = _closed_quarters(f)
    if not quarters:
        return Criterion("A4", title, UNMET, "no closed quarter with a drawn sample yet")
    parts, ok = [], True
    for q in quarters:
        mine = [u for u, info in f.samples.items() if str(info.get("quarter", "")).replace("-", "") == q]
        scored = [u for u in mine if u in f.audits]
        settled = [u for u in scored if f.audits[u]["payload"].get("agreed")
                   or f.audits[u]["payload"].get("referred_to_calibration")]
        ok &= len(settled) == len(mine)
        parts.append(f"{q}: {len(settled)} of {len(mine)} samples scored and agreed or referred")
    return Criterion("A4", title, MET if ok else UNMET, "; ".join(parts))


def _last_closed(f: _Facts) -> dict[str, date]:
    out: dict[str, date] = {}
    for e in f.cycles:
        if e["payload"].get("phase") == "closed":
            out[e["payload"]["instructor"]] = max(out.get(e["payload"]["instructor"], date.min), _day(e["at"]))
    return out


def _coaching_cadence(f: _Facts) -> Criterion:
    days = f.rules["coaching"]["standard_cycle_days"]
    closed = _last_closed(f)
    first = min((_day(e["at"]) for e in f.log), default=f.on)
    new = f.on - first < timedelta(days=days)  # a store younger than one cadence cannot show it yet
    behind = [u for u in f.active if not (u in closed and (f.on - closed[u]).days <= days)]
    status = MET if not behind else UNMET
    detail = f"{len(f.active) - len(behind)} of {len(f.active)} active instructors closed a cycle in the last {days} days"
    if behind:
        detail += f"; behind: {', '.join(b.split('/', 1)[1] for b in behind)}" + (" (the store is younger than one cadence)"
                                                                                 if new else "")
    return Criterion("A5", "Every active instructor completed a coaching cycle within the cadence", status, detail)


def _triggers(f: _Facts) -> Criterion:
    """Every quality trigger is followed by triggered coaching: a triggered cycle opened for that instructor after it, or
    one already open on its day (one cycle at a time); or a recorded closure."""
    opened = defaultdict(list)
    spans: dict[str, list[tuple[date, date]]] = defaultdict(list)
    starts: dict[str, tuple[date, str]] = {}
    for e in f.cycles:
        inst, phase = e["payload"]["instructor"], e["payload"].get("phase")
        if phase == "opened":
            starts[e["payload"]["cycle"]] = (_day(e["at"]), e["payload"].get("intensity"))
            if e["payload"].get("intensity") == "triggered":
                opened[inst].append(_day(e["at"]))
        elif phase == "closed" and e["payload"]["cycle"] in starts:
            begun, intensity = starts.pop(e["payload"]["cycle"])
            if intensity == "triggered":
                spans[inst].append((begun, _day(e["at"])))
    for cycle, (begun, intensity) in starts.items():  # still open
        if intensity == "triggered":
            inst = next(e["payload"]["instructor"] for e in f.cycles if e["payload"]["cycle"] == cycle)
            spans[inst].append((begun, f.on))
    closures = {e["payload"].get("trigger") for e in f.log if e["kind"] == "check"
                and e["payload"].get("step") == "tm:step/quality-review" and e["payload"].get("result") == "closed"}
    open_ones = []
    for t in f.triggers:
        inst, day = t["subject_uri"], _day(t["at"])
        escalated = any(e["payload"].get("instructor") == inst and e["payload"].get("intensity") == "triggered"
                        and _day(e["at"]) >= day for e in f.cycles)  # a running cycle raised to triggered intensity
        if not any(d >= day for d in opened[inst]) and t["id"] not in closures and not escalated \
                and not any(a <= day <= b for a, b in spans[inst]):
            open_ones.append(f"{inst.split('/', 1)[1]} {day}")
    title = "Every quality trigger actioned by triggered coaching or a closure"
    if not f.triggers:
        return Criterion("A7", title, MET, "no quality triggers on record")
    return Criterion("A7", title, MET if not open_ones else UNMET,
                     f"{len(f.triggers) - len(open_ones)} of {len(f.triggers)} triggers actioned"
                     + (f"; open: {', '.join(open_ones[:5])}" if open_ones else ""))


def _bench(f: _Facts) -> Criterion:
    decided = [e for e in f.log if e["kind"] == "bench_decision"]
    packs = {e["payload"].get("evidence_pack_sha256"): e for e in f.log if e["kind"] == "step"
             and e["payload"].get("step") == "tm:step/evidence-pack"}
    short = []
    for d in decided:
        pack = packs.get(d["payload"].get("evidence_pack_sha256"))
        if pack is None or len(pack["payload"].get("observers", [])) < 2 or not d["payload"].get("rationale_key"):
            short.append(d["payload"]["bench"])
    title = "Every bench decision has a pack with 2+ observers and a rationale"
    if not decided:
        return Criterion("A8", title, MET, "no bench decisions on record")
    return Criterion("A8", title, MET if not short else UNMET,
                     f"{len(decided) - len(short)} of {len(decided)} bench decisions" + (f"; short: {', '.join(short)}"
                                                                                          if short else ""))


def _record(f: _Facts, private: Path) -> Criterion:
    """Every active instructor has a record view (teachermodel views) and the reply page (decision 0021)."""
    from .flows import PAGE_SPECS

    views = private / "views" / "instructors"
    have = [u for u in f.active if (views / f"{u.split('/', 1)[1]}.html").is_file()]
    replies = sum(1 for e in f.log if e["kind"] == "step" and e["payload"].get("step") == "tm:step/reply-or-appeal")
    ok = len(have) == len(f.active) and "tm:step/reply-or-appeal" in PAGE_SPECS
    return Criterion("A9", "An instructor can see their whole record and reply to any decision", MET if ok else UNMET,
                     f"record views for {len(have)} of {len(f.active)} active instructors"
                     + ("" if len(have) == len(f.active) else " (run teachermodel views)")
                     + f"; {replies} reply(ies) or appeal(s) on record")


def _history(f: _Facts) -> Criterion:
    """Each clearance's history is in the log: its round, the observations and dry runs the round counted."""
    missing = []
    for e in f.clearances:
        rnd = f.rounds.get(e["payload"]["clearance"].split("/", 1)[1])
        if rnd is None or any(o not in f.by_id for o in e["payload"].get("observations", [])):
            missing.append(e["payload"]["clearance"])
    return Criterion("A10", "The event log reproduces the history of any clearance", MET if not missing else UNMET,
                     f"{len(f.clearances) - len(missing)} of {len(f.clearances)} clearances trace to their round and "
                     "observations in the log" + (f"; broken: {', '.join(missing[:3])}" if missing else ""))


def personal_data_in_git(root: Path = ROOT) -> list[str]:
    """Tracked files holding an email address outside the reserved and functional domains (decision 0003)."""
    try:
        files = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, check=True,
                               timeout=60).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return ["git ls-files failed"]
    hits = []
    for rel in files:
        if rel.startswith(FICTIONAL_DIRS):
            continue
        path = root / rel
        if path.suffix.lower() in (".png", ".jpg", ".pdf", ".pptx", ".docx", ".xlsx", ".ico"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found = set()
        for m in _EMAIL.finditer(text):
            domain = m.group(0).lower().split("@", 1)[1]
            if domain[0].isdigit() or domain.endswith(ALLOWED_DOMAINS) or domain.endswith(RESERVED_TLDS):
                continue  # a unit file name (example-agent-loop@1.yaml), a reserved or functional domain
            found.add(m.group(0))
        if found:
            hits.append(f"{rel} ({len(found)} address(es))")
    return hits


def _no_personal_data(root: Path) -> Criterion:
    hits = personal_data_in_git(root)
    return Criterion("A11", "No personal data in the git repository", MET if not hits else UNMET,
                     "no email address outside reserved domains in tracked files" if not hits
                     else f"addresses outside reserved domains in: {', '.join(hits[:5])}")


# --- phase gates --------------------------------------------------------------------------------------------------


def _gate1(f: _Facts) -> Criterion:
    due = {d.step for d in app.due_steps(f.st, f.on)}
    agreed = any(e["kind"] == "signoff" and e["payload"].get("step") == "tm:step/gap-list-approved" for e in f.log) \
        and "tm:step/gap-list-approved" not in due
    return Criterion("G1", "Baseline: roster and gap list agreed", MET if f.st.registrations and agreed else UNMET,
                     f"{len(f.st.registrations)} instructors registered; gap list "
                     + ("approved as it stands" if agreed else "not approved as it stands"))


def _gate2(f: _Facts) -> Criterion:
    """Two clearers each passed three calibration exercises (pre-scored recordings)."""
    per = Counter(e["payload"]["observer"] for e in f.log if e["kind"] == "calibration" and e["payload"].get("passed"))
    three = sorted(o for o, n in per.items() if n >= 3)
    return Criterion("G2", "Standard: two clearers meet calibration on three pre-scored recordings",
                     MET if len(three) >= 2 else UNMET,
                     f"{len(three)} clearer(s) passed 3+ exercises" + (f": {', '.join(t.split('/', 1)[1] for t in three)}"
                                                                       if three else "")
                     + f"; most passes by one clearer: {max(per.values(), default=0)}")


def _gate3(f: _Facts) -> Criterion:
    rows, gaps = 0, 0
    for u in f.active:
        for d in f.st.registrations[u].get("delivers") or []:
            for mode in d.get("modes", []):
                rows += 1
                res = staffing.check(f.log, {"instructor": u, "unit": d["unit"], "mode": mode, "date": f.on.isoformat()},
                                     f.rules)
                gaps += res["verdict"] == "block"
    g1 = _gate1(f)
    flagged = g1.status == MET
    return Criterion("G3", "Records: every instructor has a record; every delivery maps to a clearance or a flagged gap",
                     MET if f.active and (gaps == 0 or flagged) else UNMET,
                     f"{len(f.active)} active instructors registered; {rows - gaps} of {rows} delivery rows cleared, "
                     f"{gaps} gap(s) " + ("flagged on the approved gap list" if flagged else "not flagged"))


def _gate4(f: _Facts) -> Criterion:
    calibrated = [c for c in f.clearers if f.calibrated(c, f.on)]
    issued = {e["payload"]["instructor"] for e in f.clearances}
    types: dict[str, list[str]] = defaultdict(list)
    for u in f.active:
        reg = f.st.registrations[u]
        if reg.get("level") in BELOW_CLEARED and u in issued:
            types[reg.get("type", "?")].append(u)
    all_types = sorted({f.st.registrations[u].get("type", "?") for u in f.active})
    missing = [t for t in all_types if not types.get(t)]
    open_or_recent = set(_last_closed(f)) | {e["payload"]["instructor"] for e in f.cycles
                                             if e["payload"].get("phase") == "opened"}
    not_in_cycle = [u for u in f.active if u not in open_or_recent]
    ok = len(calibrated) >= 4 and not missing and not not_in_cycle
    return Criterion("G4", "Pathway: 4+ calibrated clearers, one of each type through the pathway, all in coaching",
                     MET if ok else UNMET,
                     f"{len(calibrated)} calibrated clearers; types through the pathway: "
                     f"{', '.join(sorted(types)) or 'none'}" + (f" (missing: {', '.join(missing)})" if missing else "")
                     + f"; {len(f.active) - len(not_in_cycle)} of {len(f.active)} instructors in a coaching cycle")


def _gate5(f: _Facts, a4: Criterion, a7: Criterion) -> Criterion:
    quarters = _closed_quarters(f)
    return Criterion("G5", "Quality loop: one quarter end to end, audit scored, every trigger actioned",
                     MET if quarters and a4.status == MET and a7.status == MET else UNMET,
                     f"closed quarters with a sample: {', '.join(quarters) or 'none'}; audits {a4.status}; triggers "
                     f"{a7.status}")


def attestations(root: Path = ROOT) -> dict[str, dict[str, Any]]:
    """standards/attestations.yaml by criterion (decision 0023): what a role states that no store can show."""
    path = root / "standards" / "attestations.yaml"
    doc = (load_yaml(path) or {}) if path.is_file() else {}
    return {a["criterion"]: a for a in doc.get("attestations", []) if isinstance(a, dict) and a.get("criterion")}


def _version_at_least(version: str, want: tuple[int, int]) -> bool:
    try:
        parts = tuple(int(x) for x in version.split(".")[:2])
    except ValueError:
        return False
    return parts >= want


def _gate6(f: _Facts, root: Path) -> Criterion:
    partners = {u for u in f.active if f.st.registrations[u].get("type") == "partner"}
    remote = [e for e in f.clearances if e["payload"]["instructor"] in partners
              and any((f.by_id.get(o) or {}).get("payload", {}).get("recorded_at") for o in e["payload"]["observations"])]
    version = str((load_yaml(root / "standards" / "framework.yaml") or {}).get("version", ""))
    revised = _version_at_least(version, (1, 1))
    sme = attestations(root).get("G6-sme-module-delivered")
    ok = bool(remote) and revised and sme is not None
    return Criterion("G6", "Scale: a partner cleared remotely, an SME module delivered, standard v1.1",
                     MET if ok else UNMET,
                     f"partner clearances from recordings: {len(remote)}; framework version {version or '?'}"
                     + ("" if revised else " (v1.1 needed)") + "; SME module to delivery: "
                     + (f"attested by the {sme['role']} on {sme['date']} (decision {sme['decision']})" if sme
                        else "not attested (standards/attestations.yaml)"))


def report(private_dir: Path | str, *, on: date | None = None, root: Path = ROOT) -> list[Criterion]:
    st = app.load_state(private_dir, root)
    on = on or max((_day(e["at"]) for e in st.events), default=date.today())
    f = _Facts(st, on)
    a4, a7 = _audits(f), _triggers(f)
    return [
        _gate1(f), _gate2(f), _gate3(f), _gate4(f), _gate5(f, a4, a7), _gate6(f, root),
        _staffed(f), _clearance_links(f), _clearers_calibrated(f), a4, _coaching_cadence(f),
        Criterion("A6", "Outcomes shown against the cohort baseline, hidden below the minimum learner count", ATTESTED,
                  "the quality review view and the evidence pack hide them (tests/test_views.py, tests/test_bench.py)"),
        a7, _bench(f),
        _record(f, Path(private_dir)),
        _history(f), _no_personal_data(root),
        Criterion("A12", "A session runs from paper with the system down and is entered afterwards", ATTESTED,
                  "built: teachermodel paper (run sheet, rubric) and held_on on the ad-hoc assignment (decision 0022); "
                  "that a session ran from paper is attested by the head of training"),
        Criterion("A13", "Every rule unit-tested; observer form and staffing check browser-tested", ATTESTED,
                  "py -m pytest (tests/browser holds the browser tests)"),
    ]


def do_gates(private_dir: Path | str, *, on: date | None = None, root: Path = ROOT) -> app.Report:
    found = report(private_dir, on=on, root=root)
    rep = app.Report(lines=[f"{c.status.upper():<9} {c.id:<4} {c.title}: {c.detail}" for c in found])
    n = Counter(c.status for c in found)
    rep.summary = (f"gates: {n[MET]} met, {n[UNMET]} unmet, {n[ATTESTED]} attested, {n[NOT_BUILT]} not built "
                   f"(of {len(found)})")
    return rep
