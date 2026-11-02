"""`teachermodel views`: the spec's read views as static HTML in the store (spec v0.2, Interfaces; increment 4 item 3).

Built from the SQLite index (index.py), which is rebuilt first, into `<store>/views/`:

    clearance-matrix.html          instructors by unit and mode: outcome, scope, expiry, the two clearers; filters by type,
                                   organisation, region and mode; expiries within staffing.warn_expiry_days flagged
    coaching-log.html              every cycle (head of training); coaching-log--<coach>.html, each coach's own cycles;
                                   a cycle open longer than its cadence (coaching.*_cycle_days) is flagged overdue
    quality-review.html            per instructor and unit: outcome summaries against the cohort baseline (below
                                   quality.min_learners_for_metric: "insufficient data"), the monthly rubric average, the
                                   observer count and open triggers
    monthly-outcomes.html          per month and instructor, newest month first: deliveries measured, learners assessed, the
                                   learner-weighted score and baseline and the gap; deliveries below
                                   quality.min_learners_for_metric are counted with their learners as "too small to
                                   read" and add no figures.
                                   From a lab grader export (outcome-import@1) the score is the pass rate in percent
    instructors/<slug>.html        the instructor's own record: clearances, observations (scores), coaching cycles, dry runs,
                                   CPD, level changes and bench decisions

Ids only, never names (owner, 2026-10-27). Each file is one role's slice; the store's access rules (decision 0006) decide who
opens which. Every value is escaped and no file loads anything from outside. Deterministic: the same log writes the same
files, and a file is rewritten only when its bytes change.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import app, index
from .standards import ROOT, load_standards
from .util import esc as _e
from .util import write_if_changed

VIEWS = Path("views")
STYLE = (
    "body{font-family:Arial,Helvetica,sans-serif;margin:1.5rem;color:#262838;line-height:1.4}"
    "h1{color:#12193E;font-size:1.5rem}h2{color:#434D9E;border-bottom:1px solid #ccc;padding-bottom:.2rem;margin-top:2rem}"
    "table{border-collapse:collapse;font-size:.85rem;margin:.5rem 0}th,td{border:1px solid #ccc;padding:.25rem .45rem;"
    "text-align:left;vertical-align:top}th{background:#f0f1f8}.flag{background:#fff3cd}.bad{background:#fde2e1}"
    ".ok{background:#e6f4ea}.muted{color:#777}.filters{margin:.5rem 0}.filters label{margin-right:1rem}"
    "footer{margin-top:2rem;font-size:.8rem;color:#555}"
    # On a phone a table's rows stack as label and value, so the page never runs off the screen.
    "@media (max-width:640px){body{margin:1rem}table.stack,table.stack tbody,table.stack tr{display:block}"
    "table.stack thead{display:none}table.stack tr{border:1px solid #ccc;margin:.5rem 0;padding:.25rem .45rem}"
    "table.stack td{display:block;border:0;padding:.15rem 0;text-align:right;overflow-wrap:anywhere}"
    "table.stack td:empty{display:none}table.stack td::before{content:attr(data-label);float:left;max-width:50%;"
    'font-weight:600;text-align:left}table.stack td::after{content:"";display:block;clear:both}'
    "table.stack td[data-mode]{text-align:left;padding:.3rem .45rem;margin:.25rem 0}"
    "table.stack td[data-mode]::before{float:none;display:block;max-width:none}}"
)
FOOTER = ("A record of the technical training function (decision 0005): used to coach and to decide clearances and bench "
          "reviews, never for performance review. Ids only; names stay in the private store.")


def _slug(uri: str | None) -> str:
    return "" if uri is None else uri.split("/", 1)[-1]


def _page(title: str, body: str, as_of: str, script: str = "") -> str:
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{_e(title)}</title>'
            f"<style>{STYLE}</style></head><body><h1>{_e(title)}</h1><p class=\"muted\">As of {_e(as_of)}, from the "
            f"event log through the index.</p>{body}<footer>{_e(FOOTER)}</footer>"
            + (f"<script>{script}</script>" if script else "") + "</body></html>\n")


def _table(headers: list[str], rows: list[list[Any]], classes: list[str] | None = None,
           attrs: list[str] | None = None) -> str:
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = []
    for i, row in enumerate(rows):
        cls = f' class="{classes[i]}"' if classes and classes[i] else ""
        extra = f" {attrs[i]}" if attrs and attrs[i] else ""
        body.append(f"<tr{cls}{extra}>" + "".join(f'<td data-label="{_e(h)}">{c}</td>'
                                                  for h, c in zip(headers, row)) + "</tr>")
    return f'<table class="stack"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def _rows(con: sqlite3.Connection, sql: str, *args: Any) -> list[sqlite3.Row]:
    return con.execute(sql, args).fetchall()


# --- clearance matrix ---------------------------------------------------------------------------------------------


MATRIX_SCRIPT = """
function f(){var t=document.getElementById('f-type').value,o=document.getElementById('f-org').value,
r=document.getElementById('f-region').value,m=document.getElementById('f-mode').value;
document.querySelectorAll('tr[data-type]').forEach(function(tr){
var show=(!t||tr.dataset.type===t)&&(!o||tr.dataset.org===o)&&(!r||(' '+tr.dataset.regions+' ').indexOf(' '+r+' ')>=0);
tr.style.display=show?'':'none';});
document.querySelectorAll('[data-mode]').forEach(function(c){c.style.display=(!m||c.dataset.mode===m)?'':'none';});}
document.querySelectorAll('.filters select').forEach(function(s){s.addEventListener('change',f);});
"""


def clearance_matrix(con: sqlite3.Connection, on: date, rules: dict[str, Any]) -> str:
    warn = rules["staffing"]["warn_expiry_days"]
    instructors = _rows(con, "SELECT * FROM instructors ORDER BY uri")
    clearances = _rows(con, "SELECT * FROM clearances ORDER BY issued, clearance")
    cells: dict[tuple[str, str, str], sqlite3.Row] = {}
    units, modes = set(), set()
    for c in clearances:
        for mode in json.loads(c["modes"] or "[]"):
            cells[(c["instructor"], c["unit"], mode)] = c  # issued order: the latest clearance of a cell wins
            units.add(c["unit"])
            modes.add(mode)
    columns = [(u, m) for u in sorted(units) for m in sorted(modes)]

    def cell(c: sqlite3.Row | None, unit: str, mode: str) -> str:
        label = f'data-label="{_e(_slug(unit))}, {_e(mode)}"'
        if c is None:
            return f'<td data-mode="{_e(mode)}" class="muted" {label}>no clearance</td>'
        expires = date.fromisoformat(c["expires"]) if c["expires"] else None
        cls = "bad" if c["outcome"] not in ("cleared", "cleared_with_conditions") or (expires and expires < on) else \
            "flag" if expires and (expires - on).days <= warn else "ok"
        scope = []
        if c["scope_partner"]:
            scope.append(f"partner {c['scope_partner']}")
        if c["scope_regions"]:
            scope.append("regions " + ", ".join(json.loads(c["scope_regions"])))
        text = (f"{_e(c['outcome'])}<br>expires {_e(c['expires'])}"
                + (f"<br>recheck {_e(c['recheck'])}" if c["recheck"] else "")
                + f"<br>scope: {_e('; '.join(scope) or 'any')}<br>clearers: {_e(_slug(c['clearer_1']))}, "
                  f"{_e(_slug(c['clearer_2']))}" + ("<br>founding" if c["founding"] else ""))
        return f'<td data-mode="{_e(mode)}" class="{cls}" {label}>{text}</td>'

    head = "".join(f'<th data-mode="{_e(m)}">{_e(_slug(u))}<br>{_e(m)}</th>' for u, m in columns)
    body = []
    for i in instructors:
        regions = " ".join(json.loads(i["regions"] or "[]"))
        row = "".join(cell(cells.get((i["uri"], u, m)), u, m) for u, m in columns)
        body.append(f'<tr data-type="{_e(i["type"])}" data-org="{_e(i["organisation"])}" data-regions="{_e(regions)}">'
                    f"<td data-label=\"Instructor\">{_e(_slug(i['uri']))}<br><span class=\"muted\">{_e(i['type'])}, {_e(i['level'])}"
                    f"{', exited' if i['exited'] else ''}</span></td>{row}</tr>")

    def select(name: str, label: str, values: list[str]) -> str:
        opts = "".join(f'<option value="{_e(v)}">{_e(v)}</option>' for v in values)
        return f'<label>{_e(label)} <select id="f-{name}"><option value="">all</option>{opts}</select></label>'

    filters = ('<div class="filters">'
               + select("type", "Type", sorted({i["type"] for i in instructors if i["type"]}))
               + select("org", "Organisation", sorted({i["organisation"] for i in instructors if i["organisation"]}))
               + select("region", "Region", sorted({r for i in instructors for r in json.loads(i["regions"] or "[]")}))
               + select("mode", "Mode", sorted(modes)) + "</div>")
    legend = (f'<p><span class="ok">cleared</span> <span class="flag">expires within {warn} days</span> '
              '<span class="bad">expired or not cleared</span></p>')
    table = f'<table class="stack"><thead><tr><th>Instructor</th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
    return _page("Clearance matrix", filters + legend + table, on.isoformat(), MATRIX_SCRIPT)


# --- coaching log -------------------------------------------------------------------------------------------------


def coaching_log(con: sqlite3.Connection, on: date, rules: dict[str, Any], coach: str | None = None) -> str:
    days = {"standard": rules["coaching"]["standard_cycle_days"], "triggered": rules["coaching"]["triggered_cycle_days"]}
    sql = "SELECT * FROM cycles" + (" WHERE coach = ?" if coach else "") + " ORDER BY opened, cycle"
    cycles = _rows(con, sql, *([coach] if coach else []))
    rows, classes = [], []
    for c in cycles:
        opened = date.fromisoformat(c["opened"][:10]) if c["opened"] else None
        due = opened + timedelta(days=days.get(c["intensity"], days["standard"])) if opened else None
        overdue = c["closed"] is None and due is not None and due < on
        change = json.loads(c["change"]) if c["change"] else {}
        rows.append([_e(_slug(c["instructor"])), _e(_slug(c["coach"])), _e(c["number"]), _e(c["intensity"]),
                     _e(", ".join(json.loads(c["focus"] or "[]"))), _e((c["opened"] or "")[:10]),
                     _e((c["feedback"] or "")[:10]), _e((c["practice"] or "")[:10]), _e((c["closed"] or "")[:10] or "open"),
                     _e(", ".join(f"{d} {v:+d}" if isinstance(v, int) else f"{d} {v}" for d, v in sorted(change.items()))),
                     "overdue" if overdue else (f"due {due}" if c["closed"] is None and due else "")])
        classes.append("bad" if overdue else "")
    title = f"Coaching log: {_slug(coach)}" if coach else "Coaching log"
    body = (f"<p>{len(cycles)} cycle(s); a cycle open longer than {days['standard']} days (standard) or "
            f"{days['triggered']} days (triggered) is overdue.</p>"
            + _table(["Instructor", "Coach", "No.", "Intensity", "Focus", "Opened", "Feedback", "Practice", "Closed",
                      "Change", "Status"], rows, classes))
    return _page(title, body, on.isoformat())


# --- quality review -----------------------------------------------------------------------------------------------


def quality_review(con: sqlite3.Connection, on: date, rules: dict[str, Any]) -> str:
    minimum = rules["quality"]["min_learners_for_metric"]
    sections = []
    for i in _rows(con, "SELECT uri FROM instructors ORDER BY uri"):
        uri = i["uri"]
        outcomes = _rows(con, "SELECT * FROM outcomes WHERE instructor = ? ORDER BY delivered_on, delivery_ref", uri)
        obs = _rows(con, "SELECT substr(at, 1, 7) AS month, avg(mean_score) AS avg, count(*) AS n, "
                         "count(DISTINCT observer) AS observers FROM observations WHERE instructor = ? GROUP BY month "
                         "ORDER BY month", uri)
        observers = _rows(con, "SELECT count(DISTINCT observer) AS n FROM observations WHERE instructor = ?", uri)[0]["n"]
        triggers = _rows(con, "SELECT at, trigger FROM triggers WHERE instructor = ? ORDER BY at", uri)
        if not outcomes and not obs:
            continue
        orows, ocls = [], []
        for o in outcomes:
            enough = (o["learners_assessed"] or 0) >= minimum
            delta = (o["score"] - o["baseline"]) if enough and o["score"] is not None and o["baseline"] is not None else None
            orows.append([_e(o["delivery_ref"]), _e(_slug(o["unit"])), _e(o["mode"]), _e(o["delivered_on"]),
                          _e(o["learners_assessed"]),
                          _e(o["score"]) if enough else '<span class="muted">insufficient data</span>',
                          _e(o["baseline"]) if enough else "", _e(f"{delta:+.1f}") if delta is not None else ""])
            ocls.append("bad" if delta is not None and delta <= -rules["quality"]["score_drop_points"] else "")
        trend = _table(["Month", "Rubric average", "Observations", "Observers"],
                       [[_e(r["month"]), _e(f"{r['avg']:.2f}" if r["avg"] is not None else ""), _e(r["n"]),
                         _e(r["observers"])] for r in obs]) if obs else "<p class=\"muted\">No observations.</p>"
        sections.append(
            f"<section><h2>{_e(_slug(uri))}</h2><p>{observers} distinct observer(s); {len(triggers)} quality trigger(s)"
            + (": " + _e(", ".join(f"{t['at'][:10]} {t['trigger']}" for t in triggers)) if triggers else "") + ".</p>"
            + (_table(["Delivery", "Unit", "Mode", "Delivered", "Learners", "Score", "Baseline", "Against baseline"],
                      orows, ocls) if outcomes else "<p class=\"muted\">No outcome summaries.</p>")
            + trend + "</section>")
    intro = (f"<p>Outcomes are read against the cohort baseline and hidden below {minimum} learners assessed; they never "
             "decide a bench review alone (spec, Fair reading of outcomes).</p>")
    return _page("Quality review", intro + "".join(sections), on.isoformat())


# --- monthly outcomes ---------------------------------------------------------------------------------------------


def monthly_outcomes(con: sqlite3.Connection, on: date, rules: dict[str, Any]) -> str:
    q = rules["quality"]
    minimum, drop = q["min_learners_for_metric"], q["score_drop_points"]
    months: dict[tuple[str, str], dict[str, Any]] = {}
    for o in _rows(con, "SELECT * FROM outcomes WHERE delivered_on IS NOT NULL"):
        m = months.setdefault((o["delivered_on"][:7], o["instructor"]),
                              {"n": 0, "learners": 0, "score": 0.0, "baseline": 0.0, "few": 0, "few_learners": 0,
                               "units": set()})
        m["units"].add(_slug(o["unit"]))
        learners = o["learners_assessed"] or 0
        if learners < minimum or o["score"] is None or o["baseline"] is None:
            m["few"] += 1
            m["few_learners"] += learners
            continue
        m["n"] += 1
        m["learners"] += learners
        m["score"] += o["score"] * learners
        m["baseline"] += o["baseline"] * learners
    rows, classes = [], []
    by_instructor = sorted(months.items(), key=lambda kv: kv[0][1])
    for (month, uri), m in sorted(by_instructor, key=lambda kv: kv[0][0], reverse=True):  # stable: newest month first
        if m["learners"]:
            score, baseline = m["score"] / m["learners"], m["baseline"] / m["learners"]
            gap = round(score, 1) - round(baseline, 1)
            numbers = [_e(f"{score:.1f}"), _e(f"{baseline:.1f}"), _e(f"{gap:+.1f}")]
        else:
            gap = None
            numbers = ['<span class="muted">insufficient data</span>', "", ""]
        few = (f"{m['few']} deliver{'y' if m['few'] == 1 else 'ies'}, {m['few_learners']} learners" if m["few"]
               else "none")
        rows.append([_e(month), _e(_slug(uri)), _e(", ".join(sorted(m["units"]))), _e(m["n"]), _e(m["learners"]),
                     *numbers, _e(few)])
        classes.append("bad" if gap is not None and gap <= -drop else "")
    intro = (f"<p>Per month and instructor, newest month first. The score and baseline are weighted by learners assessed "
             f"and read only deliveries with at least {minimum} learners; smaller deliveries are counted, with their "
             "learners, under Too small to read, and never measured. "
             f"A month {drop} or more points below baseline is marked. When the outcomes come from a lab grader the score "
             "is the pass rate in percent. A month is a summary for the quality review, which decides what it means.</p>")
    table = _table(["Month", "Instructor", "Units", "Deliveries measured", "Learners measured", "Score", "Baseline",
                    "Against baseline", "Too small to read"], rows, classes) if rows else         '<p class="muted">No outcome summaries.</p>'
    return _page("Monthly outcomes", intro + table, on.isoformat())


# --- instructor record --------------------------------------------------------------------------------------------


def instructor_record(con: sqlite3.Connection, on: date, uri: str) -> str:
    i = _rows(con, "SELECT * FROM instructors WHERE uri = ?", uri)[0]
    parts = [f"<p>{_e(i['type'])}, {_e(i['organisation'])}, {_e(i['jurisdiction'])}; level {_e(i['level'])} "
             f"(registered {_e(i['registered_level'])}){'; exited' if i['exited'] else ''}.</p>"]

    def section(title: str, headers: list[str], rows: list[list[Any]]) -> None:
        parts.append(f"<section><h2>{_e(title)}</h2>"
                     + (_table(headers, rows) if rows else '<p class="muted">None on record.</p>') + "</section>")

    section("Clearances", ["Clearance", "Unit", "Modes", "Outcome", "Issued", "Expires", "Recheck", "Clearers"],
            [[_e(_slug(c["clearance"])), _e(_slug(c["unit"])), _e(", ".join(json.loads(c["modes"] or "[]"))),
              _e(c["outcome"]), _e(c["issued"]), _e(c["expires"]), _e(c["recheck"]),
              _e(f"{_slug(c['clearer_1'])}, {_slug(c['clearer_2'])}")]
             for c in _rows(con, "SELECT * FROM clearances WHERE instructor = ? ORDER BY issued", uri)])
    domains = [r["domain"] for r in _rows(con, "SELECT DISTINCT domain FROM observation_scores ORDER BY domain")]
    obs = _rows(con, "SELECT * FROM observations WHERE instructor = ? ORDER BY at", uri)
    scores = defaultdict(dict)
    for s in _rows(con, "SELECT s.* FROM observation_scores s JOIN observations o ON o.id = s.observation "
                        "WHERE o.instructor = ?", uri):
        scores[s["observation"]][s["domain"]] = s["score"]
    section("Observations", ["Date", "Observer", "Unit", "Mode", "Length", "Lead", "From recording", *domains],
            [[_e(o["at"][:10]), _e(_slug(o["observer"])), _e(_slug(o["unit"])), _e(o["mode"]), _e(o["length"]),
              "yes" if o["lead"] else "no", "yes" if o["from_recording"] else "no",
              *[_e(scores[o["id"]].get(d, "")) for d in domains]] for o in obs])
    section("Coaching cycles", ["No.", "Coach", "Intensity", "Focus", "Opened", "Closed", "Change"],
            [[_e(c["number"]), _e(_slug(c["coach"])), _e(c["intensity"]), _e(", ".join(json.loads(c["focus"] or "[]"))),
              _e((c["opened"] or "")[:10]), _e((c["closed"] or "")[:10] or "open"),
              _e(", ".join(f"{d} {v}" for d, v in sorted(json.loads(c["change"]).items())) if c["change"] else "")]
             for c in _rows(con, "SELECT * FROM cycles WHERE instructor = ? ORDER BY opened", uri)])
    section("Dry runs", ["Date", "Unit", "Mode", "Passed"],
            [[_e(d["at"][:10]), _e(_slug(d["unit"])), _e(d["mode"]), "yes" if d["passed"] else "no"]
             for d in _rows(con, "SELECT * FROM dry_runs WHERE instructor = ? ORDER BY at", uri)])
    section("CPD", ["Logged", "Hours", "Domains"],
            [[_e(c["logged_on"]), _e(c["hours"]), _e(", ".join(json.loads(c["domains"] or "[]")))]
             for c in _rows(con, "SELECT * FROM cpd WHERE instructor = ? ORDER BY at", uri)])
    section("Level changes", ["Date", "From", "To"],
            [[_e(lc["at"][:10]), _e(lc["from_level"]), _e(lc["to_level"])]
             for lc in _rows(con, "SELECT * FROM level_changes WHERE instructor = ? ORDER BY seq", uri)])
    section("Replies and appeals", ["Date", "Decision (event id)", "Kind", "Appeal", "Outcome", "Decided"],
            [[_e(r["at"][:10]), _e(r["decision"][:12]), _e(r["kind"]), _e(_slug(r["appeal"])),
              _e(r["appeal_outcome"] or ("awaiting the head" if r["appeal"] else "")), _e(r["appeal_decided"])]
             for r in _rows(con, "SELECT * FROM replies WHERE instructor = ? ORDER BY at", uri)])
    section("Bench reviews", ["Review", "Reason", "Opened", "Decision", "Decided"],
            [[_e(_slug(b["bench"])), _e(b["reason"]), _e(b["opened"]), _e(b["decision"] or "open"), _e(b["decided"])]
             for b in _rows(con, "SELECT * FROM bench WHERE instructor = ? ORDER BY opened", uri)])
    return _page(f"Instructor record: {_slug(uri)}", "".join(parts), on.isoformat())


# --- build ---------------------------------------------------------------------------------------------------------


def build(private_dir: Path | str, *, root: Path = ROOT) -> app.Report:
    """Rebuild the index, then write every view. Returns how many files changed."""
    private = Path(private_dir)
    index.build(private, root=root)
    rules = load_standards(root)["rules"]
    con = sqlite3.connect(f"file:{(private / index.INDEX).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        last = con.execute("SELECT max(at) FROM events").fetchone()[0]
        on = date.fromisoformat(last[:10]) if last else date.today()
        out = private / VIEWS
        files = {out / "clearance-matrix.html": clearance_matrix(con, on, rules),
                 out / "coaching-log.html": coaching_log(con, on, rules),
                 out / "quality-review.html": quality_review(con, on, rules),
                 out / "monthly-outcomes.html": monthly_outcomes(con, on, rules)}
        for (coach,) in con.execute("SELECT DISTINCT coach FROM cycles WHERE coach IS NOT NULL ORDER BY coach"):
            files[out / f"coaching-log--{_slug(coach)}.html"] = coaching_log(con, on, rules, coach)
        for (uri,) in con.execute("SELECT uri FROM instructors ORDER BY uri"):
            files[out / "instructors" / f"{_slug(uri)}.html"] = instructor_record(con, on, uri)
    finally:
        con.close()
    changed = sum(write_if_changed(path, text.encode("utf-8")) for path, text in files.items())
    return app.Report(lines=[f"{len(files)} view(s) in {VIEWS.as_posix()}/"],
                      summary=f"views: {changed} written, {len(files) - changed} unchanged")
