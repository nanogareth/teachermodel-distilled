"""W8 quality review (standards/workflows/quality.yaml): `teachermodel import-outcomes` and the `quality-review` step.

    import-outcomes <file>   an outcome-import@1 file (aggregates per delivery) -> one `outcome` event (outcome@1) per delivery
    quality-review           auto, per instructor, refreshed: rules.quality_triggers -> one trigger `check` event per NEW
                             trigger, and generated/quality/<slug>.json for the views

Import. The whole file is refused on any error (schema, an unregistered instructor, a delivery_ref twice, a delivery
imported before with other numbers) and nothing is appended or kept. A refusal names the field (`deliveries/1/score`) and
never prints a value: a file that carries a learner identifier fails the schema (additionalProperties is false at every
level), and the field name is shown only when it looks like a plain identifier, so a key that is itself a name is not echoed.
An outcome event's id comes from its delivery_ref alone, so a re-import of a delivery with the same numbers appends nothing.
A re-import with changed numbers is refused: a correction is a new delivery_ref (a `correction` event may carry it later).
A delivery with fewer than `rules.quality.min_learners_for_metric` learners assessed is written with a null score and a null
feedback before any event is made (`redact`; the summary shows it as "insufficient data"). A valid file is kept under imports/
in the private store as the validated document re-serialised (JSON, with that change), not as the bytes received.

Review. One trigger `check` per new trigger, exactly the fixed contract (increment-3 plan, "Quality triggers"):
`{step: tm:step/quality-review, instructor, result: "trigger", trigger: <reason id>, domain?}` on the instructor's subject.
The reason ids are `score-drop`, `feedback-below-median` and `domain-one-confirmed` (with `domain`). The event id derives from
(instructor, reason, the delivery that completed the trigger), so a run that finds the same trigger adds nothing: the latest
measured delivery for a score drop, the latest rated measured delivery for feedback, and, for a domain at 1, the latest
observation that scored it 1 in the confirmation window (and the domain). A later delivery that extends a run is a new trigger.

Only deliveries with at least `rules.quality.min_learners_for_metric` learners are read by the rules, for the feedback
trigger as well as the score trigger (an outcome from a smaller cohort neither shows nor triggers). The step never opens a
bench: coaching (W7) reads these events and the bench (W10) counts them.

The summary is aggregates only: per delivery the performance-task score against the cohort baseline, null with
"insufficient data" below the minimum learner count (feedback is hidden with it), and the instructor's trigger events.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .. import events, records, rules, signoff
from ..standards import ROOT, load_schema, load_standards, parse_yaml
from ..util import iso_seconds, slug, write_if_changed
from ..workflow import SYSTEM_ACTOR
from . import auto_step
from .common import State, bench_block, cached, observations

STEP_REVIEW = "tm:step/quality-review"
EVENT_LOG = "events/events.jsonl"
IMPORTS_DIR = "imports"
SUMMARY_DIR = "generated/quality"  # under the private dir: <instructor slug>.json
SUMMARY_SCHEMA = "tm:quality-summary@1"
INSUFFICIENT = "insufficient data"
MAX_REPORTED = 20  # errors named in one refusal

SCORE_DROP, FEEDBACK, DOMAIN_ONE = "score-drop", "feedback-below-median", "domain-one-confirmed"
_DOMAIN_REASON = re.compile(r"^domain (.+) scored 1 by \d+ observers$")
_PLAIN_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,40}\Z")


class QualityError(Exception):
    """`import-outcomes` refused its input; the message names the fields to fix, never their values."""


@dataclass(frozen=True)
class Imported:
    appended: int  # outcome events written
    unchanged: int  # deliveries already on record with the same numbers
    copy: Path  # where the file was kept


# --- ids ------------------------------------------------------------------------------------------------------------


def outcome_id(delivery_ref: str) -> str:
    """Deterministic id of the `outcome` event of a delivery: the same delivery_ref is the same event."""
    return signoff.input_sha256({"outcome": delivery_ref})[:32]


def trigger_id(instructor: str, reason: str, key: str) -> str:
    """Deterministic id of a trigger `check`: (instructor, reason, the delivery or observation that completed it)."""
    return signoff.input_sha256({"quality_trigger": [instructor, reason, key]})[:32]


def reason_id(text: str) -> tuple[str, str | None]:
    """The reason id (and the domain, for `domain-one-confirmed`) of a reason `rules.quality_triggers` gives.

    The rule returns prose; an unknown text is an error, not a dropped trigger."""
    if text.startswith("performance-task score"):
        return SCORE_DROP, None
    if text.startswith("feedback below median"):
        return FEEDBACK, None
    found = _DOMAIN_REASON.match(text)
    if found:
        return DOMAIN_ONE, found.group(1)
    raise ValueError(f"unknown quality trigger {text!r}: map it in flows/quality.reason_id")


# --- import-outcomes ------------------------------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """The document with dates and datetimes (which YAML makes of bare timestamps) as ISO strings."""
    if isinstance(value, date):  # a datetime too
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _field(name: Any) -> str:
    return name if isinstance(name, str) and _PLAIN_NAME.match(name) else "<unnamed field>"


def _describe(err: Any) -> str:
    where = "/".join(str(p) for p in err.absolute_path) or "<root>"
    if err.validator == "additionalProperties" and isinstance(err.instance, dict):
        extra = sorted(set(err.instance) - set(err.schema.get("properties", {})), key=str)
        return f"{where}: field(s) not allowed ({', '.join(_field(n) for n in extra)}); the import carries aggregates only"
    if err.validator == "required" and isinstance(err.instance, dict):
        missing = [n for n in err.schema.get("required", []) if n not in err.instance]
        return f"{where}: required field(s) missing ({', '.join(missing)})"
    return f"{where}: invalid value ({err.validator})"


def _read(src: Path) -> Any:
    try:
        return _plain(parse_yaml(src.read_bytes().decode("utf-8-sig")))  # YAML, so JSON too
    except (OSError, UnicodeError, yaml.YAMLError):
        raise QualityError(f"{src.name}: not readable as JSON or YAML") from None


def _latest_outcomes(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["payload"]["delivery_ref"]: e["payload"] for e in log if e["kind"] == "outcome"}


def redact(row: dict[str, Any], minimum: int) -> dict[str, Any]:
    """A delivery below `minimum` learners assessed with its score and feedback dropped (null; the views say "insufficient
    data"): the numbers of a cohort that small can point at individuals, and no rule reads them (decision 0015). The baseline and
    the median feedback of comparable deliveries are not this cohort's and stay."""
    if row["learners_assessed"] >= minimum:
        return row
    out = {**row, "score": None}
    if "feedback" in out:
        out["feedback"] = None
    return out


def import_outcomes(
    private_dir: Path | str, path: Path | str, *, now: datetime | None = None, root: Path = ROOT
) -> Imported:
    """Validate the outcome-import@1 file, then keep it under imports/ and append its `outcome` events. Raises QualityError
    (and writes nothing) when any part of the file is refused."""
    now = now or datetime.now(timezone.utc)
    private, src = Path(private_dir), Path(path)
    if not src.is_file():
        raise QualityError(f"{src}: no such file")
    doc = _read(src)
    validator = Draft202012Validator(load_schema("outcome-import.schema.json", root))
    errors = sorted(_describe(e) for e in validator.iter_errors(doc))
    if errors:
        raise _refusal(errors)

    log_path = private / EVENT_LOG
    log = list(events.read(log_path)) if log_path.is_file() else []
    registered = {e["subject_uri"] for e in log if e["kind"] == "registration"}
    on_record = _latest_outcomes(log)
    minimum = load_standards(root)["rules"]["quality"]["min_learners_for_metric"]
    doc = {**doc, "deliveries": [redact(row, minimum) for row in doc["deliveries"]]}  # nothing below the minimum is kept
    rows, seen, unchanged = [], set(), 0
    for n, row in enumerate(doc["deliveries"]):
        where = f"deliveries/{n}"
        try:
            date.fromisoformat(row["delivered_on"])
        except ValueError:
            errors.append(f"{where}/delivered_on: not a calendar date")
        if row["instructor"] not in registered:
            errors.append(f"{where}/instructor: not a registered instructor")
        if row["delivery_ref"] in seen:
            errors.append(f"{where}/delivery_ref: appears twice in this file")
        seen.add(row["delivery_ref"])
        before = on_record.get(row["delivery_ref"])
        if before is not None:
            if redact({k: v for k, v in before.items() if k != "source"}, minimum) != row:
                errors.append(f"{where}/delivery_ref: imported before and its numbers have changed; import a correction "
                              "under a new delivery_ref")
            else:
                unchanged += 1
            continue
        rows.append(row)
    if errors:
        raise _refusal(errors)

    # The validated document, re-serialised: not the file as received (a comment, a stray note or a name in a YAML export is
    # not kept), and with a small cohort's numbers dropped as in the log.
    kept = private / IMPORTS_DIR / f"outcomes-{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_bytes((json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    stamp = iso_seconds(now)
    for row in rows:
        events.append(log_path, events.make_event(
            "outcome", row["instructor"], SYSTEM_ACTOR, {**row, "source": doc["source"]},
            id=outcome_id(row["delivery_ref"]), at=stamp))
    return Imported(appended=len(rows), unchanged=unchanged, copy=kept)


def _refusal(errors: list[str]) -> QualityError:
    shown = errors[:MAX_REPORTED]
    more = f"; and {len(errors) - MAX_REPORTED} more" if len(errors) > MAX_REPORTED else ""
    return QualityError("outcome file refused, nothing imported: " + "; ".join(shown) + more)


# --- quality-review -------------------------------------------------------------------------------------------------


def _trigger_key(reason: str, domain: str | None, measured: list[rules.Outcome], mine: list[rules.Observation],
                 today: date, window_days: int) -> str:
    """What completed the trigger: the delivery (or, for a domain at 1, the observation) whose arrival made it true."""
    if reason == SCORE_DROP:
        return measured[-1].delivery
    if reason == FEEDBACK:
        return [o for o in measured if o.feedback is not None and o.feedback_median is not None][-1].delivery
    since = date.fromordinal(today.toordinal() - window_days)
    return [o.id for o in mine if since <= o.at <= today and o.scores.get(domain) == 1][-1] + "|" + str(domain)


def _is_trigger(e: dict[str, Any], instructor: str) -> bool:
    p = e["payload"]
    return (e["kind"] == "check" and e["subject_uri"] == instructor and p.get("step") == STEP_REVIEW
            and p.get("result") == "trigger")


def _outcomes_of(st: State, instructor: str) -> list[rules.Outcome]:
    """The instructor's outcomes, oldest first: `records.outcomes` once per state, grouped (a refresh asks for every
    instructor)."""
    def build() -> dict[str, list[rules.Outcome]]:
        found: dict[str, list[rules.Outcome]] = {}
        for o in records.outcomes(st.events):
            found.setdefault(o.instructor, []).append(o)
        return found

    return cached(st, "outcomes_by_instructor", build).get(instructor, [])


def summary_document(st: State, instructor: str, triggers: list[dict[str, Any]]) -> dict[str, Any]:
    """The views' summary: aggregates only, the score hidden below the minimum learner count."""
    minimum = st.standards["rules"]["quality"]["min_learners_for_metric"]
    payloads = cached(st, "latest_outcome_payloads", lambda: _latest_outcomes(st.events))
    out = []
    for o in _outcomes_of(st, instructor):
        shown = o.learners_assessed >= minimum
        p = payloads[o.delivery]
        out.append({
            "delivery_ref": o.delivery, "unit": p["unit"], "mode": p["mode"], "delivered_on": o.at.isoformat(),
            "learners_assessed": o.learners_assessed,
            "score": o.score if shown else None, "baseline": o.baseline if shown else None,
            "gap": round(o.score - o.baseline, 6) if shown else None,
            "feedback": o.feedback if shown else None, "feedback_median": o.feedback_median if shown else None,
            "status": "ok" if shown else INSUFFICIENT,
        })
    listed = sorted(({"trigger": e["payload"]["trigger"], **({"domain": e["payload"]["domain"]} if "domain" in e["payload"] else {}),
                      "at": e["at"][:10]} for e in triggers), key=lambda t: (t["at"], t["trigger"], t.get("domain", "")))
    return {"schema": SUMMARY_SCHEMA, "instructor": instructor, "minimum_learners": minimum, "deliveries": out,
            "triggers": listed}


def _write_summary(target: Path, document: dict[str, Any]) -> None:
    write_if_changed(target, (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


@auto_step(STEP_REVIEW, refresh=True, per="instructor")
def quality_review(st: State, instructor: str, now: datetime) -> list[dict[str, Any]]:
    """The trigger `check` events not yet on record for `instructor`, the summary file, and the `step` event that closes the
    step for this instructor (written once, so the refresh keeps the step done and only ever adds new triggers)."""
    rule_set = st.standards["rules"]
    q = rule_set["quality"]
    today = now.date()
    measured = [o for o in _outcomes_of(st, instructor) if o.learners_assessed >= q["min_learners_for_metric"]]
    mine = [o for o in observations(st) if o.instructor == instructor]
    stamp = iso_seconds(now)
    found: list[dict[str, Any]] = []
    exited = bench_block(st, instructor, today) == "exit"  # decision 0015, finding 3: no new triggers after an exit
    for text in ([] if exited else rules.quality_triggers(instructor, measured, mine, today, rule_set)):
        reason, domain = reason_id(text)
        key = _trigger_key(reason, domain, measured, mine, today, q["confirmation_window_days"])
        payload = {"step": STEP_REVIEW, "instructor": instructor, "result": "trigger", "trigger": reason}
        if domain is not None:
            payload["domain"] = domain
        found.append(events.make_event("check", instructor, SYSTEM_ACTOR, payload, id=trigger_id(instructor, reason, key),
                                       at=stamp))
    known = {e["id"] for e in st.index.of("check", instructor)}
    new = [e for e in found if e["id"] not in known]
    on_record = [e for e in st.index.of("check", instructor) if _is_trigger(e, instructor)]
    relpath = f"{SUMMARY_DIR}/{slug(instructor)}.json"
    checked = cached(st, "quality_summaries_checked", set)  # a file already compared or written for this state is not read again
    if relpath not in checked or new:
        _write_summary(st.private / relpath, summary_document(st, instructor, [*on_record, *new]))
        checked.add(relpath)
    done = events.make_event("step", instructor, SYSTEM_ACTOR, {"step": STEP_REVIEW, "output": relpath},
                             id=signoff.input_sha256({"quality_review": instructor})[:32], at=stamp)
    return [done, *new]

