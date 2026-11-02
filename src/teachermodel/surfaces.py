"""The read models behind the role surfaces, and the audience policy that filters them (decision 0027).

    ctx = surfaces.context(private, now)
    surfaces.this_week(ctx)            the head of training's decisions, risks ahead and sources not reporting
    surfaces.coordinator_board(ctx)    sessions delivered with learners expected and results received, as counts
    surfaces.my_record(ctx, uri)       one instructor's sessions ahead, clearances, observations, results, coaching
    surfaces.project(model, surface, role, viewer)   the model as `role` may see it (standards/audience.yaml)

Each read model is a plain dict built from the index, the schedule (decision 0027), the course records, the audition
folders, the freshness register and the lab feeds (decision 0028). Pages and emails are built from projections only, never from a model directly, so
standards/audience.yaml decides what reaches each person: anything it does not name is dropped, and a field whose name
holds one of a role's `never` words is refused outright. Ids only, never names.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from . import course as course_mod
from . import feeds, freshness, index, setup
from . import schedule as schedule_mod
from .standards import ROOT, load_standards, load_yaml

AUDIENCE = Path("standards") / "audience.yaml"
AHEAD_DAYS = 21  # how far ahead This week looks for risks (operational default, decision 0002)
DELIVERED_DAYS = 31  # how far back the coordinator board lists delivered sessions
COVERED = ("cleared", "cleared_with_conditions")


class AudienceError(Exception):
    pass


@dataclass
class Context:
    private: Path
    now: datetime
    on: date
    con: sqlite3.Connection
    sessions: tuple[schedule_mod.Session, ...]
    freshness: list[freshness.Status]
    rules: dict[str, Any]
    root: Path
    labs: dict[str, str]  # lab slug -> status in the latest release check (decision 0028)
    received: dict[str, dict[str, int]]  # delivery ref -> results received and unreadable (decision 0028)


def context(private: Path | str, now: datetime, root: Path = ROOT) -> Context:
    """Rebuild the index and gather what every read model needs, as of `now`."""
    private = Path(private)
    index.build(private, root=root)
    con = sqlite3.connect(f"file:{(private / index.INDEX).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    found = schedule_mod.load(private, setup.load_settings(private), root)
    release = feeds.load(private, feeds.RELEASE) or {}
    received = feeds.load(private, feeds.RECEIVED) or {}
    return Context(private, now, now.date(), con, found.sessions if found else (),
                   freshness.status(private, now, root), load_standards(root)["rules"], root,
                   {lab["lab"]: lab["status"] for lab in release.get("labs") or []},
                   {d["delivery_ref"]: d for d in received.get("deliveries") or []})


def _rows(ctx: Context, sql: str, *args: Any) -> list[sqlite3.Row]:
    return ctx.con.execute(sql, args).fetchall()


def _sources(ctx: Context, owner: str | None = None) -> list[dict[str, Any]]:
    return [{"source": s.source.id, "title": s.source.title, "owner": s.source.owner, "state": s.state,
             "last": s.last.isoformat() if s.last else None, "days_late": s.days_late}
            for s in ctx.freshness if (owner is None and s.state != "ok") or s.source.owner == owner]


def _auditions(ctx: Context) -> list[tuple[str, dict[str, Any], dict[str, Any] | None, int, bool]]:
    """(id, record, result or None, forms in, decided) per audition folder, in id order."""
    out = []
    for folder in sorted((ctx.private / "auditions").glob("*/audition.yaml")):
        record = load_yaml(folder) or {}
        result_path = folder.parent / "result.yaml"
        out.append((folder.parent.name, record, load_yaml(result_path) if result_path.exists() else None,
                    len(list(folder.parent.glob("score--*.yaml"))), (folder.parent / "decision.yaml").exists()))
    return out


def _clearance(ctx: Context, instructor: str, unit: str, mode: str) -> sqlite3.Row | None:
    best = None
    for row in _rows(ctx, "SELECT * FROM clearances WHERE instructor = ? AND unit = ? ORDER BY issued", instructor, unit):
        if row["outcome"] in COVERED and mode in json.loads(row["modes"] or "[]"):
            best = row
    return best


# --- the head of training ----------------------------------------------------------------------------------------


def this_week(ctx: Context) -> dict[str, Any]:
    triggers = []
    for t in _rows(ctx, "SELECT * FROM triggers ORDER BY at"):
        answered = _rows(ctx, "SELECT 1 FROM cycles WHERE instructor = ? AND intensity = 'triggered' AND opened >= ?",
                         t["instructor"], t["at"])
        if not answered:
            recent = _rows(ctx, "SELECT * FROM outcomes WHERE instructor = ? ORDER BY delivered_on DESC LIMIT 5",
                           t["instructor"])
            triggers.append({"instructor": t["instructor"], "trigger": t["trigger"], "raised": t["at"][:10],
                             "deliveries": [{"delivered_on": o["delivered_on"], "learners": o["learners_assessed"],
                                             "score": o["score"], "baseline": o["baseline"]} for o in reversed(recent)]})
    auditions = [{"audition": aid, "unit": rec.get("unit"), "mode": rec.get("mode"),
                  "overall_mean": res.get("overall_mean"), "meets_bar": res.get("overall_meets_clearance_bar"),
                  "domains_to_discuss": res.get("domains_to_discuss") or []}
                 for aid, rec, res, _, decided in _auditions(ctx) if res and not decided]
    lab_state = next((s.state for s in ctx.freshness if s.source.id == "release-check"), "not-connected")
    horizon = ctx.on + timedelta(days=AHEAD_DAYS)
    risks = []
    for s in ctx.sessions:
        if s.status == "cancelled" or not (ctx.on <= s.start <= horizon):
            continue
        held = _clearance(ctx, s.lead, s.unit, s.mode)
        if held is None:
            risks.append({"kind": "not-cleared", "session": s.ref, "instructor": s.lead, "on": s.start.isoformat()})
        elif held["expires"] and date.fromisoformat(held["expires"]) < s.end:
            risks.append({"kind": "clearance-expires", "session": s.ref, "instructor": s.lead, "on": held["expires"]})
        elif held["recheck"] and s.start <= date.fromisoformat(held["recheck"]) <= s.end:
            risks.append({"kind": "recheck-due", "session": s.ref, "instructor": s.lead, "on": held["recheck"]})
        if s.lab and ctx.labs.get(s.lab) == "failed":
            risks.append({"kind": "lab-failing", "session": s.ref, "lab": s.lab, "on": s.start.isoformat()})
        elif s.lab and (lab_state != "ok" or ctx.labs.get(s.lab) != "passed"):
            risks.append({"kind": "lab-unchecked", "session": s.ref, "lab": s.lab, "on": s.start.isoformat()})
    soon = (ctx.on + timedelta(days=60)).isoformat()
    return {
        "as_of": ctx.now.isoformat(),
        "decisions": {"quality_triggers": triggers, "auditions": auditions},
        "risks": risks,
        "sources": _sources(ctx),
        "fine": {"instructors_active": _rows(ctx, "SELECT count(*) FROM instructors WHERE status = 'active'")[0][0],
                 "clearances_valid_60_days": _rows(ctx, "SELECT count(*) FROM clearances WHERE expires > ?", soon)[0][0]},
    }


# --- the coordinator ---------------------------------------------------------------------------------------------


def coordinator_board(ctx: Context) -> dict[str, Any]:
    since = ctx.on - timedelta(days=DELIVERED_DAYS)
    deliveries = []
    for s in ctx.sessions:
        if s.status == "cancelled" or not (since <= s.end <= ctx.on):
            continue
        got = _rows(ctx, "SELECT learners_assessed FROM outcomes WHERE delivery_ref = ?", s.ref)
        feed = ctx.received.get(s.ref) or {}
        deliveries.append({"session": s.ref, "programme": s.programme, "date": s.start.isoformat(), "lead": s.lead,
                           "expected": s.expected_learners,
                           "received": got[0][0] if got else feed.get("received"),
                           "unreadable": feed.get("unreadable")})
    deliveries.sort(key=lambda d: (d["received"] is not None, d["date"]))  # missing first
    trained = sorted(p.stem for p in (ctx.private / course_mod.RECORDS).glob("*.yaml"))
    grid = []
    for slug in trained:
        uri = f"tm:instructor/{slug}"
        grid.append({"instructor": uri, "sessions": [{"session": r["session"], "recorded": r["recorded"]}
                                                     for r in course_mod.status(ctx.private, uri, ctx.root)]})
    auditions = []
    for aid, rec, res, forms, decided in _auditions(ctx):
        stage = ("decided" if decided else "awaiting decision" if res else
                 f"forms {forms} of 2" if rec.get("observers") else "needs observers")
        auditions.append({"audition": aid, "stage": stage, "forms_in": forms})
    return {"as_of": ctx.now.isoformat(), "deliveries": deliveries, "course": grid, "auditions": auditions,
            "sources": _sources(ctx, owner="coordinator")}


# --- one instructor ----------------------------------------------------------------------------------------------


def my_record(ctx: Context, instructor: str) -> dict[str, Any]:
    ahead = []
    for s in ctx.sessions:
        if s.status == "cancelled" or s.end < ctx.on or instructor not in s.people:
            continue
        role = "lead" if s.lead == instructor else "observer" if s.observer == instructor else "co"
        ahead.append({"session": s.ref, "programme": s.programme, "unit": s.unit, "mode": s.mode,
                      "from": s.start.isoformat(), "to": s.end.isoformat(), "role": role, "lead": s.lead})
    minimum = int(ctx.rules.get("quality", {}).get("min_learners_for_metric", 15))
    observations = []
    for o in _rows(ctx, "SELECT id, at FROM observations WHERE instructor = ? ORDER BY at", instructor):
        scores = {r["domain"]: r["score"] for r in _rows(ctx, "SELECT domain, score FROM observation_scores "
                                                              "WHERE observation = ?", o["id"])}
        observations.append({"at": o["at"][:10], "scores": scores})
    return {
        "as_of": ctx.now.isoformat(),
        "instructor": instructor,
        "sessions_ahead": sorted(ahead, key=lambda a: a["from"]),
        "clearances": [{"unit": c["unit"], "modes": json.loads(c["modes"] or "[]"), "outcome": c["outcome"],
                        "expires": c["expires"], "recheck": c["recheck"]}
                       for c in _rows(ctx, "SELECT * FROM clearances WHERE instructor = ? ORDER BY issued", instructor)],
        "observations": observations,
        "outcomes": [{"delivered_on": o["delivered_on"], "learners": o["learners_assessed"], "score": o["score"],
                      "baseline": o["baseline"], "measured": (o["learners_assessed"] or 0) >= minimum}
                     for o in _rows(ctx, "SELECT * FROM outcomes WHERE instructor = ? ORDER BY delivered_on",
                                    instructor)],
        "coaching": [{"cycle": c["number"], "intensity": c["intensity"], "focus": json.loads(c["focus"] or "[]"),
                      "opened": (c["opened"] or "")[:10], "closed": (c["closed"] or "")[:10] or None,
                      "coach": c["coach"]}
                     for c in _rows(ctx, "SELECT * FROM cycles WHERE instructor = ? ORDER BY number", instructor)],
        "course": [{"session": r["session"], "title": r["title"], "recorded": r["recorded"]}
                   for r in course_mod.status(ctx.private, instructor, ctx.root)],
    }


# --- the audience policy -----------------------------------------------------------------------------------------


def policy(root: Path = ROOT) -> dict[str, Any]:
    return yaml.safe_load((Path(root) / AUDIENCE).read_text(encoding="utf-8"))


def _tree(paths: list[str]) -> dict[str, Any]:
    """Dotted field paths as a tree; a leaf of None keeps that field's whole subtree."""
    tree: dict[str, Any] = {}
    for path in paths:
        node = tree
        *parents, leaf = path.split(".")
        for part in parents:
            if part in node and node[part] is None:
                break  # the whole subtree is kept already
            node = node.setdefault(part, {})
        else:
            node[leaf] = None
    return tree


def _prune(value: Any, tree: dict[str, Any] | None) -> Any:
    if tree is None:
        return value
    if isinstance(value, list):
        return [_prune(item, tree) for item in value]
    if isinstance(value, dict):
        return {k: _prune(v, tree[k]) for k, v in value.items() if k in tree}
    return value


def _field_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [k for k in value] + [n for v in value.values() for n in _field_names(v)]
    if isinstance(value, list):
        return [n for item in value for n in _field_names(item)]
    return []


def project(model: dict[str, Any], surface: str, role: str, viewer: str | None = None,
            root: Path = ROOT) -> dict[str, Any]:
    """`model` as `role` may see it on `surface`. Raises AudienceError when the role may not open the surface, when an
    own-only role asks about someone else, or when a field the role must never receive gets through the whitelist."""
    rules = (policy(root).get("roles") or {}).get(role)
    if rules is None:
        raise AudienceError(f"no role {role!r} in {AUDIENCE.as_posix()}")
    allowed = (rules.get("surfaces") or {}).get(surface)
    if allowed is None:
        raise AudienceError(f"{role} may not open {surface} ({AUDIENCE.as_posix()})")
    if rules.get("own_only") and model.get("instructor") != viewer:
        raise AudienceError(f"{role} may open only their own record")
    seen = copy.deepcopy(model) if allowed == "*" else _prune(model, _tree(allowed))
    if leaked := [n for n in _field_names(seen) if any(w in n for w in rules.get("never") or [])]:
        raise AudienceError(f"{role} would receive {sorted(set(leaked))} on {surface}: refused")
    return seen
