"""`teachermodel index`: the disposable SQLite index (spec v0.2, Architecture: "a build ... emits a SQLite index for the
views. The index is disposable and rebuilt from source"; increment 4 item 2).

`<store>/index/teachermodel.sqlite` is rebuilt from scratch on every call, from the event log and the registrations only:
deleting it loses nothing. It holds what the log holds (tm: URIs, keys, scores, dates), never a name or an address: the
identities stay in `identities/` (decision 0003, and the owner's 2026-10-27 rule that pages show ids only). A `meta` table
names the log it was built from (its sha256 and line count), so a view can tell when the index is stale.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

from . import app
from .standards import ROOT

INDEX = Path("index") / "teachermodel.sqlite"

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE events (id TEXT PRIMARY KEY, seq INTEGER NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
                     subject_uri TEXT NOT NULL, actor TEXT NOT NULL);
CREATE TABLE instructors (uri TEXT PRIMARY KEY, type TEXT, organisation TEXT, jurisdiction TEXT, regions TEXT,
                          registered_level TEXT, level TEXT, status TEXT, engagement_end TEXT, exited INTEGER NOT NULL);
CREATE TABLE level_changes (seq INTEGER PRIMARY KEY, at TEXT, instructor TEXT, from_level TEXT, to_level TEXT);
CREATE TABLE clearances (clearance TEXT PRIMARY KEY, candidate TEXT, instructor TEXT, unit TEXT, modes TEXT, outcome TEXT,
                         issued TEXT, expires TEXT, recheck TEXT, clearer_1 TEXT, clearer_2 TEXT, founding INTEGER,
                         framework_version TEXT, scope_partner TEXT, scope_regions TEXT, observations INTEGER);
CREATE TABLE observations (id TEXT PRIMARY KEY, at TEXT, instructor TEXT, observer TEXT, unit TEXT, mode TEXT, length TEXT,
                           lead INTEGER, delivery_ref TEXT, from_recording INTEGER, mean_score REAL);
CREATE TABLE observation_scores (observation TEXT, domain TEXT, score INTEGER, PRIMARY KEY (observation, domain));
CREATE TABLE dry_runs (id TEXT PRIMARY KEY, at TEXT, candidate TEXT, instructor TEXT, unit TEXT, mode TEXT, passed INTEGER);
CREATE TABLE calibrations (id TEXT PRIMARY KEY, at TEXT, observer TEXT, exercise TEXT, passed INTEGER,
                           within_one_share REAL, exact_share REAL);
CREATE TABLE cycles (cycle TEXT PRIMARY KEY, instructor TEXT, coach TEXT, number INTEGER, intensity TEXT, focus TEXT,
                     opened TEXT, feedback TEXT, practice TEXT, closed TEXT, change TEXT);
CREATE TABLE outcomes (delivery_ref TEXT PRIMARY KEY, instructor TEXT, unit TEXT, mode TEXT, delivered_on TEXT,
                       learners_assessed INTEGER, score REAL, baseline REAL);
CREATE TABLE triggers (id TEXT PRIMARY KEY, at TEXT, instructor TEXT, trigger TEXT);
CREATE TABLE audits (sample TEXT PRIMARY KEY, at TEXT, observation TEXT, observer TEXT, second_observer TEXT,
                     agreed INTEGER, within_one_share REAL, exact_share REAL, referred_to_calibration INTEGER);
CREATE TABLE cpd (id TEXT PRIMARY KEY, at TEXT, instructor TEXT, logged_on TEXT, hours REAL, domains TEXT);
CREATE TABLE bench (bench TEXT PRIMARY KEY, instructor TEXT, reason TEXT, opened TEXT, decision TEXT, decided TEXT);
CREATE TABLE overrides (override TEXT PRIMARY KEY, instructor TEXT, unit TEXT, mode TEXT, date TEXT, partner TEXT,
                        region TEXT, decision TEXT, decided TEXT, opened TEXT);
CREATE TABLE signoffs (signoff_id TEXT PRIMARY KEY, at TEXT, step TEXT, subject_uri TEXT, actor TEXT, decision TEXT);
CREATE TABLE replies (id TEXT PRIMARY KEY, at TEXT, instructor TEXT, decision TEXT, kind TEXT, appeal TEXT,
                      appeal_outcome TEXT, appeal_decided TEXT);
CREATE INDEX observations_by_instructor ON observations (instructor, at);
CREATE INDEX clearances_by_instructor ON clearances (instructor, unit);
CREATE INDEX outcomes_by_instructor ON outcomes (instructor, delivered_on);
"""


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"))


def _rows(st: app.State) -> dict[str, list[tuple]]:
    from . import records
    from .flows.common import current_level

    log = st.events
    out: dict[str, list[tuple]] = {k: [] for k in ("events", "instructors", "level_changes", "clearances", "observations",
                                                     "observation_scores", "dry_runs", "calibrations", "cycles", "outcomes",
                                                     "triggers", "audits", "cpd", "bench", "overrides", "signoffs",
                                                     "replies")}
    appeals: dict[str, str] = {}  # appeal URI -> the signoff id of the reply that opened it
    decided: dict[str, tuple[str, str]] = {}  # appeal URI -> (outcome, day)
    exited = {b["instructor"] for b in records.bench(log) if (b["decision"] or {}).get("decision") == "exit"}
    clearances: dict[str, dict[str, Any]] = {}
    cycles: dict[str, dict[str, Any]] = {}
    for seq, e in enumerate(log):
        p, at = e["payload"], e["at"]
        out["events"].append((e["id"], seq, at, e["kind"], e["subject_uri"], e["actor"]))
        kind = e["kind"]
        if kind == "level_change":
            out["level_changes"].append((seq, at, e["subject_uri"], p.get("from"), p.get("to")))
        elif kind == "clearance":
            clearances[p["clearance"]] = p  # the latest event of a clearance is its state (a lapse supersedes)
        elif kind == "observation":
            scores = p.get("scores") or {}
            mean = round(sum(scores.values()) / len(scores), 3) if scores else None
            out["observations"].append((e["id"], at, p.get("instructor"), p.get("observer"), p.get("unit"), p.get("mode"),
                                        p.get("length"), int(bool(p.get("lead"))), p.get("delivery_ref"),
                                        int(bool(p.get("recorded_at"))), mean))
            out["observation_scores"] += [(e["id"], d, s) for d, s in sorted(scores.items())]
        elif kind == "dry_run":
            out["dry_runs"].append((e["id"], at, p.get("candidate"), p.get("instructor"), p.get("unit"), p.get("mode"),
                                    int(bool(p.get("passed")))))
        elif kind == "calibration":
            out["calibrations"].append((e["id"], at, p.get("observer"), p.get("exercise"), int(bool(p.get("passed"))),
                                        p.get("within_one_share"), p.get("exact_share")))
        elif kind == "coaching_cycle":
            c = cycles.setdefault(p["cycle"], {"instructor": p["instructor"], "coach": p.get("coach"),
                                               "number": p.get("number"), "intensity": p.get("intensity"),
                                               "focus": p.get("focus")})
            c[p["phase"]] = at
            if p.get("change") is not None:
                c["change"] = p["change"]
        elif kind == "outcome":
            out["outcomes"].append((p["delivery_ref"], p.get("instructor"), p.get("unit"), p.get("mode"),
                                    p.get("delivered_on"), p.get("learners_assessed"), p.get("score"), p.get("baseline")))
        elif kind == "check" and p.get("step") == "tm:step/quality-review" and p.get("result") == "trigger":
            out["triggers"].append((e["id"], at, e["subject_uri"], p.get("trigger")))
        elif kind == "audit":
            out["audits"].append((p["sample"], at, p.get("observation"), p.get("observer"), p.get("second_observer"),
                                  int(bool(p.get("agreed"))), p.get("within_one_share"), p.get("exact_share"),
                                  int(bool(p.get("referred_to_calibration")))))
        elif kind == "cpd":
            out["cpd"].append((e["id"], at, p.get("instructor"), p.get("logged_on"), p.get("hours"), _j(p.get("domains"))))
        elif kind == "subject" and p.get("subject_kind") == "appeal":
            appeals[e["subject_uri"]] = p["attrs"]["request_ref"]
        elif kind == "check" and p.get("step") == "tm:step/appeal-decision" and p.get("result") in ("upheld", "varied"):
            decided[e["subject_uri"]] = (p["result"], at[:10])
        elif kind == "signoff":
            out["signoffs"].append((p.get("signoff_id"), at, p.get("step"), e["subject_uri"], e["actor"], p.get("decision")))
    by_key = {key: uri for uri, key in appeals.items()}
    for e in log:
        p = e["payload"]
        if e["kind"] == "step" and p.get("step") == "tm:step/reply-or-appeal":
            appeal = by_key.get(p.get("text_key"))
            outcome, day = decided.get(appeal, (None, None)) if appeal else (None, None)
            out["replies"].append((e["id"], e["at"], e["subject_uri"], p.get("decision"), p.get("kind"), appeal, outcome,
                                   day))
    for uri in sorted(st.registrations):
        reg = st.registrations[uri]
        eng = reg.get("engagement") or {}
        out["instructors"].append((uri, reg.get("type"), reg.get("organisation"), reg.get("jurisdiction"),
                                   _j(reg.get("regions")), reg.get("level"), current_level(st, uri), eng.get("status"),
                                   eng.get("end"), int(uri in exited)))
    for cid in sorted(clearances):
        p = clearances[cid]
        clearers = list(p.get("clearers") or []) + [None, None]
        scope = p.get("scope") or {}
        out["clearances"].append((cid, p.get("candidate"), p.get("instructor"), p.get("unit"), _j(p.get("modes")),
                                  p.get("outcome"), p.get("issued"), p.get("expires"), p.get("recheck"), clearers[0],
                                  clearers[1], int(bool(p.get("founding"))), p.get("framework_version"),
                                  scope.get("partner"), _j(scope.get("regions")), len(p.get("observations") or [])))
    for cid in sorted(cycles):
        c = cycles[cid]
        out["cycles"].append((cid, c["instructor"], c["coach"], c["number"], c["intensity"], _j(c["focus"]),
                              c.get("opened"), c.get("feedback"), c.get("practice"), c.get("closed"), _j(c.get("change"))))
    for b in records.bench(log):
        d = b["decision"] or {}
        out["bench"].append((b["bench"], b["instructor"], b.get("reason"), _iso(b.get("opened")), d.get("decision"),
                             _iso(d.get("at"))))
    for o in records.overrides(log):
        out["overrides"].append((o["override"], o["instructor"], o["unit"], o["mode"], _iso(o["date"]), o.get("partner"),
                                 o.get("region"), o["decision"], _iso(o["decided"]), _iso(o["opened"])))
    return out


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def _log_sha256(private: Path) -> str:
    log = private / app.EVENT_LOG
    return hashlib.sha256(log.read_bytes() if log.is_file() else b"").hexdigest()


def build(private_dir: Path | str, *, root: Path = ROOT) -> app.Report:
    """Rebuild the index from scratch (written beside, then moved into place, so a reader never sees half of it)."""
    private = Path(private_dir)
    st = app.load_state(private, root)
    rows = _rows(st)
    target = private / INDEX
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(SCHEMA)
        meta = {"events_sha256": _log_sha256(private), "events": str(len(st.events)),
                "built_from": app.EVENT_LOG}
        con.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))
        for table, data in rows.items():
            if data:
                marks = ",".join("?" * len(data[0]))
                con.executemany(f"INSERT INTO {table} VALUES ({marks})", data)  # noqa: S608 - fixed table names
        con.commit()
    finally:
        con.close()
    tmp.replace(target)
    counts = ", ".join(f"{t} {len(d)}" for t, d in rows.items() if t != "events")
    return app.Report(lines=[counts], summary=f"index: {len(st.events)} event(s) into {target.relative_to(private).as_posix()}")


def is_current(private_dir: Path | str) -> bool:
    """Whether the index was built from the event log as it is now."""
    private = Path(private_dir)
    path = private / INDEX
    if not path.is_file():
        return False
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        built = dict(con.execute("SELECT key, value FROM meta").fetchall())
    finally:
        con.close()
    return built.get("events_sha256") == _log_sha256(private)
