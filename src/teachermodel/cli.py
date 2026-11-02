"""Command line. Argument parsing and printing only; the commands live in app.py."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

from . import app, config, daily, devsign, events, pilot, roster, setup, staffing, standards
from .audition import AuditionError
from .course import CourseError
from .matching import MatchError
from .feeds import FeedError
from .schedule import ScheduleError
from .flows.bench import BenchError, request_bench
from .flows.calibration import ExerciseError, open_exercise
from .flows.override import OverrideError, request_override
from .flows.quality import QualityError, import_outcomes

STORE_COMMANDS = {
    "next": "print the open steps (queue); --json writes tm:contract/queue@1",
    "run": "execute due auto steps and append their events",
    "pages": "write sign-off pages for due human steps",
    "plan": "write the read plan for due verify steps",
    "tick": "run, plan, pages, next, in that order",
}


def _store_parser(sub, name: str, help_: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, help=help_)
    p.add_argument("--private-dir", type=Path, default=None,
                   help=f"private store (default: ${config.ENV_VAR}); must be outside the git tree (decision 0006)")
    return p


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="teachermodel")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="schema-check the standards and their cross-references")
    v = sub.add_parser("verify-events", help="check schema, receipts and ids of an event log")
    v.add_argument("path", type=Path)
    r = sub.add_parser("check-roster", help="check a roster file against tm:contract/roster@2")
    r.add_argument("path", type=Path)
    q = sub.add_parser("check-questions", help="check a train-the-trainer session 2 question set against its unit")
    q.add_argument("path", type=Path)
    fl = sub.add_parser("check-failure-log", help="check a train-the-trainer session 3 failure log against the lab")
    fl.add_argument("path", type=Path)
    fl.add_argument("--catalogue", type=Path, required=True,
                    help="the lab's staff/catalogue.yaml (or a unit file): its failure_catalogue")
    cs = sub.add_parser("compare-scores", help="train-the-trainer session 5: scores of reference recordings against the "
                                               "reference, domain by domain (formative, not a calibration)")
    cs.add_argument("path", type=Path)
    cs.add_argument("--reference", type=Path, required=True, help="the reference scores, kept in the private store")
    cs.add_argument("--out", type=Path, help="write the comparison here (the session's evidence)")
    for name, help_ in STORE_COMMANDS.items():
        p = _store_parser(sub, name, help_)
        if name == "next":
            p.add_argument("--role", default=None, help="only steps for this role")
            p.add_argument("--json", type=Path, default=None, dest="json_path", help="write the queue here")
    ip = _store_parser(sub, "init-pilot", "set up a pilot store with generated data (decision 0016): layout, "
                                          "settings, people, generated inputs, and the environment variable")
    ip.add_argument("--owner-name", required=True, help="your name, for the people list in the store")
    ip.add_argument("--owner-email", required=True, help="your work mailbox: sign-off pages for every office role")
    ip.add_argument("--force", action="store_true", help="replace generated files that differ")
    ip.add_argument("--no-set-env", dest="set_env", action="store_false",
                    help=f"do not point the user variable {config.ENV_VAR} at the store")
    ps = _store_parser(sub, "pilot-sign", "pilot store only (decision 0016): ingest sign-off files saved from the "
                                          "pages of generated signers, who have no mailbox")
    ps.add_argument("files", type=Path, nargs="+",
                    help="the .eml drafts the pages' Save button downloads, or the sign-off .json files alone")
    da = _store_parser(sub, "dev-autosign", "pilot store only, for development (owner, 2026-10-27): tick, import the "
                                           "generated inputs, open calibration and sign every due page with generated "
                                           "answers, round after round")
    da.add_argument("--generated-only", action="store_true",
                    help="leave your own pages for the sign-off mailbox, the path the pilot tests")
    da.add_argument("--rounds", type=int, default=20, help="most rounds to run (default 20)")
    _store_parser(sub, "graph-read", "run the latest read plan through the Graph driver (app-only; configured by "
                  "TEACHERMODEL_GRAPH_* environment variables), ingest the receipt and tick")
    _store_parser(sub, "daily", "the daily job: tick, or dev-autosign when dev mode is on; logs one line to logs/daily.log")
    dm = _store_parser(sub, "dev-mode", "pilot store only: turn on or off the development toggle that makes `daily` run "
                                        "dev-autosign")
    dm.add_argument("state", choices=["on", "off", "status"])
    sd = _store_parser(sub, "schedule-daily", "create or replace the Windows scheduled task that runs `daily`")
    sd.add_argument("--time", default="07:30", help="HH:MM, 24-hour, local time (default 07:30)")
    sd.add_argument("--every-day", action="store_true", help="every day, not Monday to Friday")
    sd.add_argument("--remove", action="store_true", help="remove the task")
    imp = _store_parser(sub, "import-roster", "import a roster file: identities to the store, references to events")
    imp.add_argument("path", type=Path)
    io = _store_parser(sub, "import-outcomes",
                       "import an outcome-import@1 file (aggregates per delivery; any learner field refuses the file)")
    io.add_argument("file", type=Path)
    au = _store_parser(sub, "audition", "a candidate's audition on the clearance rubric, kept apart from the instructor "
                                        "record (decision 0025): new, assign, replace, score, status, result, decide, "
                                        "carry")
    au.add_argument("action", choices=["new", "assign", "replace", "score", "status", "result", "decide", "carry"])
    au.add_argument("audition", nargs="?", help="the audition id (every action but new)")
    au.add_argument("--unit", help="new: sl:unit/<slug>@<n>")
    au.add_argument("--mode", help="new: in-person, remote or hybrid")
    au.add_argument("--slice", help="new: the 15-minute slice of the lab the candidate teaches")
    au.add_argument("--candidate", help="new: the candidate's name (kept only in identities/auditions.yaml)")
    au.add_argument("--observer", action="append", default=[], help="assign (twice), score: tm:instructor/<id>")
    au.add_argument("--form", type=Path, help="score: the observer's filled form.yaml")
    au.add_argument("--decision", choices=["hired", "not-hired"], help="decide")
    au.add_argument("--reasons", help="decide: the panel's reasons; replace: why the observer is replaced")
    au.add_argument("--leaving", help="replace: the observer who drops out, before they have scored")
    au.add_argument("--joining", help="replace: their replacement, from the observer pool")
    au.add_argument("--by", help="decide: the panel chair, tm:person/<id>")
    au.add_argument("--instructor", help="carry: the hired candidate's tm:instructor/<id>, once registered")
    au.add_argument("--on", help="the day, YYYY-MM-DD (default: today)")
    sch = _store_parser(sub, "import-schedule", "check a calendar export of sessions (tm:contract/schedule@1) and keep "
                                                 "it as inputs/schedule.yaml (decision 0027)")
    sch.add_argument("file", type=Path)
    fd = _store_parser(sub, "import-feed", "check a lab feed (tm:contract/release-status@1 or results-received@1) and "
                                           "keep it under inputs/ (decision 0028); the daily job also drains inbox/")
    fd.add_argument("file", type=Path)
    sm = _store_parser(sub, "staffing-match", "who may teach a unit in a mode on a programme's dates, who is free and "
                                              "their travel load (decision 0026); writes views/staffing-match.html")
    sm.add_argument("--unit", required=True)
    sm.add_argument("--mode", required=True)
    sm.add_argument("--from", dest="start", required=True, help="first day, YYYY-MM-DD")
    sm.add_argument("--to", dest="end", required=True, help="last day, YYYY-MM-DD")
    sm.add_argument("--region", help="where the programme is, ISO code (IE, US-CA)")
    sm.add_argument("--partner", help="the partner organisation the programme is for, tm:org/<id>")
    sm.add_argument("--all", action="store_true", help="include blocked instructors")
    co = _store_parser(sub, "course", "the train-the-trainer course record: record a completed session, or show a "
                                      "participant's sessions (docs/train-the-trainer/DESIGN.md)")
    co.add_argument("action", choices=["record", "status"])
    co.add_argument("--instructor", required=True, help="tm:instructor/<id>")
    co.add_argument("--session", help="record: a session id from standards/train-the-trainer.yaml")
    co.add_argument("--evidence-ref", help="record: the private-store key of the session's evidence")
    co.add_argument("--on", help="record: the day, YYYY-MM-DD (default: today)")
    ing = _store_parser(sub, "ingest", "apply a driver receipt (sign-offs arrive only inside a receipt)")
    ing.add_argument("receipt", type=Path)
    ex = _store_parser(sub, "open-exercise", "open a calibration exercise (head of training): reference scores go to the store")
    ex.add_argument("--unit", required=True, help="the unit the recording is of, sl:unit/<slug>@<version>")
    ex.add_argument("--recording-ref", required=True, help="key of the recording in the private store")
    ex.add_argument("--observers", required=True, help="comma-separated registered instructors (slug or tm:instructor/<slug>)")
    ex.add_argument("--reference", required=True, type=Path, help="YAML or JSON file: a score 1-4 for every framework domain")
    sc = _store_parser(sub, "staffing-check",
                       "may this instructor deliver this unit in this mode on this date? prints tm:contract/staffing-check@2 "
                       "JSON; exit status 0 ok, 3 warn, 2 block, 1 a request outside the contract")
    sc.description = ("Prints the tm:contract/staffing-check@2 response as JSON. Exit status: 0 ok, 3 warn, 2 block, "
                      "1 a request outside the contract (or another error).")
    sc.add_argument("--instructor", required=True, help="tm:instructor/<slug>")
    sc.add_argument("--unit", required=True, help="sl:unit/<slug>@<version>")
    sc.add_argument("--mode", required=True, help="in-person, remote or hybrid")
    sc.add_argument("--date", required=True, help="the delivery date, YYYY-MM-DD")
    sc.add_argument("--partner", default=None,
                    help="the partner organisation the delivery is for, tm:org/<slug> (a clearance scoped to a partner covers only this)")
    sc.add_argument("--region", default=None,
                    help="the region the delivery is in, e.g. IE or US-CA (a clearance scoped to regions covers only these)")
    sc.add_argument("--detail", action="store_true",
                    help="the detailed reasons, for the head of training only; without it the reasons are what "
                         "delivery scheduling receives: not cleared, clearance expiring, recheck due or override <id> "
                         "(decision 0005)")
    rb = _store_parser(sub, "request-bench", "open a bench review for an instructor (head of training); the reason is 'requested'")
    rb.add_argument("--instructor", required=True, help="a registered instructor (slug or tm:instructor/<slug>)")
    rb.add_argument("--concern", default=None, choices=["teaching-quality", "other"],
                    help="what the review is about; teaching-quality makes return to co-teaching the default decision")
    sim = sub.add_parser("dev-simulate", help="build a simulated store: months of generated use on the real standards "
                         "(decision 0020)")
    sim.add_argument("--store", type=Path, required=True, help="a new or empty directory outside the repo and AppData")
    sim.add_argument("--weeks", type=int, default=26, help="how many weeks to simulate (default 26)")
    sim.add_argument("--end", default=None, help="the last simulated day, YYYY-MM-DD (default: today)")
    sim.add_argument("--reset", action="store_true", help="replace a previous simulation in --store")
    ho = _store_parser(sub, "handoff", "render the expert-to-session handoff for a unit and list what it still lacks")
    ho.add_argument("--unit", required=True, help="sl:unit/<slug>@<version>")
    pp = _store_parser(sub, "paper", "write the printable run sheet and rubric for a unit (paper fallback, decision 0022)")
    pp.add_argument("--unit", required=True, help="sl:unit/<slug>@<version>")
    hi = _store_parser(sub, "history", "the full history of one clearance, from the event log alone")
    hi.add_argument("--clearance", required=True, help="tm:clearance/<id>")
    ax = _store_parser(sub, "audit-export", "a quarter's audit samples and their agreement as JSON (exports/)")
    ax.add_argument("--quarter", required=True, help="the quarter, YYYYQn (e.g. 2026Q3)")
    _store_parser(sub, "views", "rebuild the index and write the read views (views/: clearance matrix, coaching logs, "
                  "quality review, monthly outcomes, instructor records)")
    _store_parser(sub, "index", "rebuild the disposable SQLite index (index/teachermodel.sqlite) from the event log")
    gt = _store_parser(sub, "gates", "the spec's phase gates and acceptance criteria, computed from the store (read only)")
    gt.add_argument("--on", default=None, help="the day to judge on, YYYY-MM-DD (default: the newest event's day)")
    ep = _store_parser(sub, "export-pack", "print a bench review's evidence pack to PDF (needs the [browser] extra)")
    ep.add_argument("--bench", required=True, help="the bench review, tm:bench/<instructor slug>--<n>")
    ep.add_argument("--out", type=Path, default=None,
                    help="where to write the PDF (default: next to the pack in the private store; never inside the repo)")
    rv = _store_parser(sub, "revoke-page",
                       "write a page on which a holder of the step's role can revoke an approval in force (decision 0019)")
    rv.add_argument("--step", required=True, help="a revocable step, e.g. tm:step/ropa-approved")
    rv.add_argument("--subject", default="tm:programme/teachermodel",
                    help="the subject of the approval (default: the programme)")
    ro = _store_parser(sub, "request-override",
                       "ask the head of training to override a staffing block for one instructor, unit, mode and date")
    ro.add_argument("--instructor", required=True, help="a registered instructor (slug or tm:instructor/<slug>)")
    ro.add_argument("--unit", required=True, help="sl:unit/<slug>@<version>")
    ro.add_argument("--mode", required=True, help="in-person, remote or hybrid")
    ro.add_argument("--date", required=True, help="the delivery date, YYYY-MM-DD")
    ro.add_argument("--note", default=None, help="why it is needed; kept in the private store, never in the log")
    ro.add_argument("--partner", default=None,
                    help="the partner organisation the delivery is for, tm:org/<slug>; the override covers only this partner")
    ro.add_argument("--region", default=None,
                    help="the region the delivery is in, e.g. IE or US-CA; the override covers only this region")
    return parser


def _print(report: app.Report, *, details: bool = True) -> None:
    for line in (report.all_lines() if details else [report.summary]):
        print(line)


def _finish(report: app.Report) -> int:
    """Print a report; the exit status is 1 when it is not ok."""
    _print(report)
    return 0 if report.ok else 1


def _store_command(args: argparse.Namespace) -> int:
    private = config.private_dir(args.private_dir)
    if args.cmd == "init-pilot":
        res = pilot.init_pilot(private, owner_name=args.owner_name, owner_email=args.owner_email, force=args.force,
                               set_env=args.set_env)
        print("\n".join(res.lines))
        print(f"init-pilot: {private} is ready; run 'teachermodel tick' next")
    elif args.cmd == "pilot-sign":
        return _finish(pilot.pilot_sign(private, list(args.files)))
    elif args.cmd == "graph-read":
        return _finish(app.do_graph_read(private, tick=True))
    elif args.cmd == "daily":
        return _finish(daily.daily(private))
    elif args.cmd == "dev-mode":
        on = daily.dev_mode(private) if args.state == "status" else daily.set_dev_mode(private, args.state == "on")
        print(f"dev-mode: {'on' if on else 'off'} ({private})")
    elif args.cmd == "schedule-daily":
        print(daily.schedule(private, at=args.time, weekdays=not args.every_day, remove=args.remove) or "done")
        if not args.remove:
            print(f"schedule-daily: '{daily.TASK_NAME}' runs `teachermodel daily` at {args.time} "
                  f"{'every day' if args.every_day else 'Monday to Friday'}")
    elif args.cmd == "dev-autosign":
        return _finish(devsign.autosign(private, rounds=args.rounds, generated_only=args.generated_only))
    elif args.cmd == "next":
        _print(app.do_next(private, role=args.role, json_path=args.json_path))
    elif args.cmd == "run":
        _print(app.do_run(private))
    elif args.cmd == "pages":
        _print(app.do_pages(private))
    elif args.cmd == "plan":
        _print(app.do_plan(private))
    elif args.cmd == "import-roster":
        _print(app.do_import_roster(private, args.path))
    elif args.cmd == "import-outcomes":
        done = import_outcomes(private, args.file)
        print(f"import-outcomes: {done.appended} outcome event(s) appended, {done.unchanged} unchanged; "
              "copy kept in imports/")
    elif args.cmd == "open-exercise":
        opened = open_exercise(private, unit=args.unit, recording_ref=args.recording_ref,
                               observers=[o for o in args.observers.split(",") if o.strip()], reference=args.reference)
        print(f"open-exercise: {opened.exercise} {'opened' if opened.created else 'was already open'}")
    elif args.cmd == "request-bench":
        opened = request_bench(private, instructor=args.instructor, concern=args.concern)
        print(f"request-bench: {opened.bench} {'opened' if opened.created else 'was already open'}")
    elif args.cmd == "handoff":
        from . import handoff

        _print(handoff.write(private, args.unit))
    elif args.cmd == "paper":
        from . import paper

        _print(paper.write(private, args.unit))
    elif args.cmd == "history":
        from . import history

        return _finish(history.clearance_history(private, args.clearance))
    elif args.cmd == "audit-export":
        from . import history

        _print(history.audit_export(private, args.quarter))
    elif args.cmd == "views":
        from . import views

        _print(views.build(private))
    elif args.cmd == "index":
        from . import index

        _print(index.build(private))
    elif args.cmd == "gates":
        from . import gates

        _print(gates.do_gates(private, on=date.fromisoformat(args.on) if args.on else None))
    elif args.cmd == "export-pack":
        from . import export

        _print(export.export_pack(private, args.bench, out=args.out))
    elif args.cmd == "revoke-page":
        _print(app.do_revoke_page(private, step=args.step, subject=args.subject))
    elif args.cmd == "request-override":
        opened = request_override(private, instructor=args.instructor, unit=args.unit, mode=args.mode, date=args.date,
                                  note=args.note, partner=args.partner, region=args.region)
        print(f"request-override: {opened.override} {'opened' if opened.created else 'was already open'}")
    elif args.cmd == "staffing-check":
        request = {"instructor": args.instructor, "unit": args.unit, "mode": args.mode, "date": args.date}
        request.update({k: v for k, v in (("partner", args.partner), ("region", args.region)) if v is not None})
        response = app.do_staffing_check(private, request, detail=args.detail)
        print(json.dumps(response, indent=2))
        return staffing.EXIT_CODES[response["verdict"]]
    elif args.cmd == "ingest":
        return _finish(app.do_ingest(private, args.receipt))
    elif args.cmd == "import-schedule":
        from . import schedule

        got = schedule.import_schedule(private, args.file, setup.load_settings(private))
        print(f"import-schedule: {len(got.sessions)} session(s), exported {got.exported_at}")
    elif args.cmd == "import-feed":
        from . import feeds

        got = feeds.import_feed(private, args.file)
        print(f"import-feed: {got.schema} of {got.at} kept as {got.path.relative_to(private).as_posix()}")
    elif args.cmd == "staffing-match":
        from . import matching

        request = {"unit": args.unit, "mode": args.mode, "start": date.fromisoformat(args.start),
                   "end": date.fromisoformat(args.end), "region": args.region, "partner": args.partner}
        rows, view = matching.staffing_match(private, request, include_blocked=args.all)
        for r in rows:
            print(f"{r.verdict:5}  {r.instructor:28}  expires {str(r.expires or '-'):10}  "
                  f"{'booked ' + ','.join(r.booked) if r.booked else 'free':24}  travel {r.travel_share:.0%}"
                  + ("  OVER" if r.travel_flag else ""))
        print(f"staffing-match: {len(rows)} instructor(s); view in {view}")
    elif args.cmd == "course":
        from . import course

        if args.action == "record":
            if not (args.session and args.evidence_ref):
                raise course.CourseError("course record needs --session and --evidence-ref")
            on = date.fromisoformat(args.on) if args.on else date.today()
            course.record(private, args.instructor, args.session, args.evidence_ref, on,
                          app.load_state(private).registrations)
            print(f"course: {args.session} recorded for {args.instructor} on {on}")
        else:
            rows = course.status(private, args.instructor)
            for r in rows:
                print(f"{r['recorded']:10}  {r['session']:18}  {r['title']}")
            done = sum(r["recorded"] != "missing" for r in rows)
            print(f"course: {done} of {len(rows)} sessions recorded for {args.instructor}")
    elif args.cmd == "audition":
        return _audition(private, args)
    else:  # tick
        for rep in app.do_tick(private):
            _print(rep, details=rep.summary.startswith("next:"))
    return 0


def _audition(private: Path, args: argparse.Namespace) -> int:
    from . import audition as au

    on = date.fromisoformat(args.on) if args.on else date.today()
    if args.action != "new" and not args.audition:
        raise au.AuditionError(f"audition {args.action} needs the audition id")
    if args.action == "new":
        missing = [f"--{k}" for k in ("unit", "mode", "slice", "candidate") if not getattr(args, k)]
        if missing:
            raise au.AuditionError("audition new needs " + ", ".join(missing))
        made = au.open_audition(private, args.unit, args.mode, args.slice, args.candidate, on)
        print(f"audition: opened {made}; the pack and a blank form.yaml are in auditions/{made}/")
    elif args.action == "assign":
        au.assign(private, args.audition, args.observer, on)
        print(f"audition: {args.audition} assigned to {', '.join(sorted(args.observer))} on {on}")
    elif args.action == "replace":
        if not (args.leaving and args.joining and args.reasons):
            raise au.AuditionError("audition replace needs --leaving, --joining and --reasons")
        au.replace(private, args.audition, args.leaving, args.joining, args.reasons, on)
        print(f"audition: {args.leaving} replaced by {args.joining} on {args.audition}")
    elif args.action == "score":
        if len(args.observer) != 1 or not args.form:
            raise au.AuditionError("audition score needs one --observer and --form")
        au.score(private, args.audition, args.observer[0], yaml.safe_load(args.form.read_text(encoding="utf-8")))
        print(f"audition: {args.observer[0]}'s form recorded for {args.audition}")
    elif args.action == "status":
        print(json.dumps(au.status(private, args.audition), indent=2))
    elif args.action == "result":
        doc = au.result(private, args.audition)
        print(f"audition: evidence for the panel in auditions/{args.audition}/result.md (overall mean "
              f"{doc['overall_mean']}; observers within one on {doc['agreement_within_one']:.0%} of domains)")
    elif args.action == "decide":
        if not (args.decision and args.reasons and args.by):
            raise au.AuditionError("audition decide needs --decision, --reasons and --by")
        au.decide(private, args.audition, args.decision, args.reasons, args.by, on)
        print(f"audition: {args.audition} decided {args.decision}")
    else:
        if not args.instructor:
            raise au.AuditionError("audition carry needs --instructor")
        print(f"audition: starting plan written to {au.carry(private, args.audition, args.instructor)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd in ("validate", "verify-events", "check-roster", "check-questions", "check-failure-log"):
        if args.cmd == "validate":
            errors = standards.check_standards()
        elif args.cmd == "verify-events":
            errors = events.verify(args.path)
        elif args.cmd == "check-questions":
            from . import course

            errors = course.question_set_errors(yaml.safe_load(args.path.read_text(encoding="utf-8")))
        elif args.cmd == "check-failure-log":
            from . import course

            errors = course.failure_log_errors(yaml.safe_load(args.path.read_text(encoding="utf-8")),
                                               yaml.safe_load(args.catalogue.read_text(encoding="utf-8")))
        else:
            errors = roster.check_roster(roster.load(args.path))
        for e in errors:
            print(e, file=sys.stderr)
        print("ok" if not errors else f"{len(errors)} problem(s)")
        return 1 if errors else 0

    if args.cmd == "compare-scores":
        from . import course

        rows, errors = course.compare_scores(yaml.safe_load(args.path.read_text(encoding="utf-8")),
                                             yaml.safe_load(args.reference.read_text(encoding="utf-8")))
        for e in errors:
            print(e, file=sys.stderr)
        if errors:
            print(f"{len(errors)} problem(s)")
            return 1
        for r in rows:
            print(f"{r['recording']}: exact {r['exact']:.0%}, within one point {r['within_one']:.0%}")
            for d in r["domains"]:
                print(f"  {d['domain']:24} {d['score']}  reference {d['reference']}  {d['difference']:+d}")
        bar = standards.load_standards()["rules"]["calibration"]
        print(f"for comparison only: calibration (W5) asks for {bar['within_one_point_share']:.0%} within one point and "
              f"{bar['exact_agreement_share']:.0%} exact; this is not a calibration")
        if args.out:
            args.out.write_text(yaml.safe_dump({"recordings": rows}, sort_keys=False), encoding="utf-8", newline="\n")
        return 0

    if args.cmd == "dev-simulate":
        from . import simulate

        try:
            end = date.fromisoformat(args.end) if args.end else None
            rep = simulate.simulate(args.store, weeks=args.weeks, end=end, reset=args.reset, progress=print)
        except (ValueError, simulate.SimulationError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        _print(rep)
        return 0

    try:
        return _store_command(args)
    except (config.ConfigError, setup.SetupError, app.AppError, pilot.PilotError, devsign.DevSignError, ExerciseError,
            QualityError, BenchError, OverrideError, AuditionError, MatchError, CourseError, ScheduleError,
            FeedError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
