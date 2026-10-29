"""A guided tour of teachermodel on a simulated store, for a live demo (owner, 2026-10-27).

    py scripts/tour.py --gui                  # present from a browser window (scripts/tour_gui.py)
    py scripts/tour.py                        # build the tour store if needed, then walk the stops in the terminal
    py scripts/tour.py --audience leadership  # only the stops for one audience
    py scripts/tour.py --from 5               # start at stop 5
    py scripts/tour.py --prepare              # (re)build the tour store and stop
    py scripts/tour.py --check                # run every stop without pausing or opening, and check each result
    py scripts/tour.py --sheet                # rewrite docs/tour/run-sheet.md from the stops below

The tour store is a `teachermodel dev-simulate` store (decision 0020) of 26 weeks ending 2026-10-27, outside the repo
(default `~/teachermodel-tour`). Its people are generated, so nothing shown is personal data, and the kept development
store is never touched. The stops below are the single source: the run sheet is rendered from them, and
`tests/test_tour.py` checks that the sheet is current and that every command parses.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHEET = REPO / "docs" / "tour" / "run-sheet.md"
DEFAULT_STORE = Path.home() / "teachermodel-tour"
END = "2026-10-27"
UNIT = "sl:unit/example-agent-loop@1"
AUDIENCES = {"leadership": "Leadership", "instructors": "Instructors and clearers", "team": "Training team"}


@dataclass(frozen=True)
class Run:
    """A command shown and run live. `exit` is the status the tour expects; `keep` names a value to remember."""
    args: tuple[str, ...]
    exit: int = 0
    keep: str | None = None  # remember the JSON output's "clearance" under this name


@dataclass(frozen=True)
class Open:
    """A file in the tour store opened in the browser: the first match of a glob."""
    glob: str


@dataclass(frozen=True)
class Stop:
    title: str
    audiences: tuple[str, ...]
    say: tuple[str, ...]
    show: tuple[Run | Open, ...] = field(default=())


def _check(instructor: str, mode: str, date: str, *extra: str, exit: int = 0, keep: str | None = None) -> Run:
    return Run(("staffing-check", "--instructor", f"tm:instructor/{instructor}", "--unit", UNIT, "--mode", mode,
                "--date", date, *extra), exit, keep)


STOPS: tuple[Stop, ...] = (
    Stop("Where we stand: the gates", ("leadership", "team"), (
        "Every phase gate and acceptance criterion in the spec is computed from the record, not ticked on a "
        "spreadsheet. Read only: running it changes nothing.",
        "This store is six months of generated use (15 instructors, 4 clearers, a partner) on the real standards. "
        "14 of 19 criteria are met from the log and 3 are attested (a person confirms them). The 2 unmet are the "
        "system doing its job: s5v2t was returned to co-teaching yesterday, which changed the gap list, and the "
        "owner's re-approval of it is still waiting. Every approval is pinned to what it approved.",
        "On real data the same command shows what is still open. Today that is the baseline, because real data waits "
        "on legal and the new tenant.",
    ), (Run(("gates",)),)),
    Stop("Who can teach what: the clearance matrix", ("leadership", "instructors", "team"), (
        "One row per instructor, one column per unit and delivery mode. Each cell is a clearance: its outcome, "
        "expiry, recheck date, scope and the two clearers who decided it.",
        "Filters for instructor type, organisation, region and mode. Amber is expiring within 30 days.",
        "'Founding' marks the first clearers, cleared before anyone held the unit (decision 0017).",
        "Pages and views show instructor ids, never names (owner, 2026-10-27).",
    ), (Open("views/clearance-matrix.html"),)),
    Stop("The staffing check: may this person deliver this?", ("leadership", "team"), (
        "Scheduling asks one question per delivery: instructor, unit, mode, date, and the partner and region if any. "
        "The answer is ok, warn or block, and the exit status says the same (0, 3, 2), so other systems can call it.",
        "a1c4f in person: ok. j2t6x holds a conditional clearance with a recheck on 2027-01-17: in early January "
        "the check warns, and after a missed recheck it blocks.",
        "k8d6w is cleared for the partner in Ireland only. The same delivery in California is blocked.",
        "Scheduling sees only 'not cleared'. The reasons behind it, with --detail, are for the head of "
        "training (decision 0005: status only, never scores).",
    ), (
        _check("a1c4f", "in-person", "2026-10-28"),
        _check("j2t6x", "remote", "2027-01-05", exit=3),
        _check("j2t6x", "remote", "2027-01-20", exit=2),
        _check("k8d6w", "remote", "2026-10-28", "--partner", "tm:org/sim-partner", "--region", "IE",
               keep="partner_clearance"),
        _check("k8d6w", "remote", "2026-10-28", "--partner", "tm:org/sim-partner", "--region", "US-CA", exit=2),
        _check("k8d6w", "remote", "2026-10-28", "--partner", "tm:org/sim-partner", "--region", "US-CA", "--detail",
               exit=2),
    )),
    Stop("Blocks, bench and the head's override", ("leadership", "team"), (
        "u4f7m struggled, went to a bench review and was returned to co-teaching, so the check blocks them.",
        "Only the head of training can override a block, with a written reason, and an override covers "
        "exactly one delivery: instructor, unit, mode, date, partner and region (decision 0018, approved today). "
        "If the block's reasons change, the override lifts nothing.",
        "Every override and bench decision is an event in the log. Gate A1 counts them: every delivery was cleared "
        "or overridden.",
    ), (
        _check("u4f7m", "remote", "2026-10-28", "--detail", exit=2),
        Open("pages/override-decision--*.html"),
    )),
    Stop("Earning a clearance: blind observation", ("instructors", "team"), (
        "A clearance needs observed sessions against the rubric's anchors, from more than one observer.",
        "Observers score blind: neither sees the other's scores until both have submitted.",
        "Every page works the same way. Read the summary, give your answer, press 'Save sign-off file'. That "
        "opens an email draft with the sign-off attached; send it from your own work mailbox. Nobody logs in "
        "anywhere.",
        "The daily job reads the sign-off mailbox, checks each sign-off against the page it came from, and writes "
        "the event.",
    ), (Open("pages/observe--*.html"),)),
    Stop("Two clearers decide, independently", ("instructors", "leadership"), (
        "Once the evidence is in (enough observations and a passed dry run for this unit and mode), two calibrated "
        "clearers decide on their own. Neither sees the other's decision.",
        "If they differ, the head of training resolves it. A clearance can come with conditions and a "
        "recheck date.",
        "The page pins the evidence by hash. If the evidence changes, the page reopens instead of approving "
        "something different.",
    ), (Open("pages/clearer-decision-1--*.html"),)),
    Stop("The record explains itself: a clearance's history", ("leadership",), (
        "Any clearance can be traced from the append-only event log alone: the round, the observations and "
        "observers, the dry run, the two clearers and the framework version.",
        "Nothing is edited or deleted. A correction is a new event, so the history an auditor reads is the "
        "history that happened.",
    ), (Run(("history", "--clearance", "{partner_clearance}")),)),
    Stop("What an instructor sees: their record, and a right to reply", ("instructors",), (
        "Each instructor has one page with everything held about them: clearances, observations with the domain "
        "scores, coaching cycles, and decisions.",
        "They can reply to any decision, or appeal it to the head of training. The reply sits on the "
        "record beside the decision (decision 0021).",
    ), (Open("views/instructors/n3c8h.html"), Open("pages/reply-or-appeal--*.html"))),
    Stop("Coaching", ("instructors", "team"), (
        "Every active instructor is in a coaching cycle: observe, feedback within 5 working days, a practice task, "
        "re-observe. A quality trigger raises the cycle's intensity.",
        "The coach's words stay in the private store. The log records only the phase and the sign-off.",
    ), (Open("views/coaching-log.html"), Open("pages/coach-feedback--*.html"))),
    Stop("The quality loop: outcomes, read fairly", ("leadership", "team"), (
        "Learner outcomes come in as aggregates per delivery, never per learner. They are read against the cohort "
        "baseline and hidden below 15 learners.",
        "Outcomes alone never bench anyone. A drop opens triggered coaching first, and every trigger has to be "
        "actioned (gate A7).",
    ), (Open("views/quality-review.html"),)),
    Stop("Keeping the judges honest: calibration and audit", ("instructors", "leadership"), (
        "Clearers stay clearers only while they keep passing calibration: scoring recordings that have reference "
        "scores.",
        "Each quarter a sample of observations is double-scored. The sample is drawn by hash ranking, so nobody "
        "picks it and anyone can repeat it.",
    ), (Open("pages/calibration-score--*.html"), Run(("audit-export", "--quarter", "2026Q3")))),
    Stop("A bench decision has its evidence pack", ("leadership",), (
        "Before a bench decision the head gets a pack with the evidence from two or more observers. The decision "
        "needs a written rationale and is pinned to the pack's hash.",
        "The pack exports as a PDF for the meeting.",
    ), (Run(("export-pack", "--bench", "tm:bench/u4f7m--1")), Open("generated/bench/u4f7m--1.pdf"))),
    Stop("When things break, and a new expert's first session", ("team",), (
        "If the system is down, 'paper' prints the run sheet and rubric for a unit, and the session is entered "
        "afterwards with the date it was held (decision 0022).",
        "'handoff' prepares a subject-matter expert's first session from the unit's template and lists what the "
        "unit still lacks.",
    ), (Run(("paper", "--unit", UNIT)), Run(("handoff", "--unit", UNIT)))),
    Stop("Day to day: what is waiting for whom", ("team", "leadership"), (
        "'next' lists every open step and whose it is. A scheduled job runs each weekday at 07:30: it executes the "
        "automatic steps, writes the pages that are due and plans the mailbox read.",
        "People only sign, decide and send. The system prepares every page and draft, and checks every result.",
        "Before real data: legal review of the IE and California profiles, the retention periods and the notice "
        "text; the new tenant's library; and who is controller after the move.",
    ), (Run(("next",)),)),
)


def render_sheet() -> str:
    lines = ["# Tour run sheet", "",
             "Generated by `py scripts/tour.py --sheet` from the stops in `scripts/tour.py`; edit the stops, not this "
             "file.", "",
             "## Before the demo", "",
             "```powershell", "py scripts/tour.py --check", "```", "",
             "This builds the tour store if it is missing (about 25 minutes for 26 simulated weeks, so run it the day "
             "before), runs every stop without opening anything, and checks each result. Then present from the "
             "browser:", "",
             "```powershell", "py scripts/tour.py --gui", "```", "",
             "It opens http://127.0.0.1:8765/ on this machine only. On the left are the stops, in the middle what to "
             "say and what each stop shows, and on the right the viewer: each command runs when you arrive at its "
             "stop, and the pages and the PDF open there too. Keys:", "",
             "| Key | Does |", "| --- | --- |",
             "| Left and right arrows | previous and next stop |",
             "| Up and down arrows | the stop's commands and pages |",
             "| R | run the command again |",
             "| N | hide or show what to say (when you share the whole window) |",
             "| F | present: the viewer alone, for the audience |", "",
             "The audience menu shows only the stops for one audience (`--audience leadership` starts with it set). "
             "After a click inside a page, click the bar above it before using the keys again. Without the browser, "
             "`py scripts/tour.py --audience leadership` walks the same stops in the terminal (Enter for the next "
             "stop, `b` to go back, `q` to quit) and opens each page in the default browser.", "",
             "To type commands yourself during questions, point the CLI at the tour store first:", "",
             "```powershell", "$env:TEACHERMODEL_PRIVATE_DIR = \"$HOME\\teachermodel-tour\"", "```", "",
             "## Stops by audience", "",
             "| Stop | " + " | ".join(AUDIENCES.values()) + " |",
             "| --- |" + " :---: |" * len(AUDIENCES)]
    for n, stop in enumerate(STOPS, 1):
        marks = " | ".join("x" if a in stop.audiences else "" for a in AUDIENCES)
        lines.append(f"| {n}. {stop.title} | {marks} |")
    for n, stop in enumerate(STOPS, 1):
        lines += ["", f"## {n}. {stop.title}", "",
                  "For: " + ", ".join(AUDIENCES[a] for a in stop.audiences) + ".", ""]
        lines += [f"- {point}" for point in stop.say]
        if stop.show:
            lines += ["", "Shows:", ""]
            for item in stop.show:
                if isinstance(item, Run):
                    status = f" (exit {item.exit})" if item.exit else ""
                    lines.append(f"- `teachermodel {' '.join(item.args)}`{status}")
                else:
                    lines.append(f"- opens `{item.glob}` in the tour store")
    return "\n".join(lines) + "\n"


def _teachermodel() -> str:
    exe = shutil.which("teachermodel")
    if not exe:
        raise SystemExit("teachermodel is not on PATH: py -m pip install -e .")
    return exe


def prepare(store: Path, rebuild: bool = False) -> None:
    marker = store / "simulation.json"
    if marker.exists() and not rebuild:
        if json.loads(marker.read_text(encoding="utf-8")).get("end") == END:
            return
    print(f"Building the tour store in {store} (26 simulated weeks to {END}) ...", flush=True)
    args = [_teachermodel(), "dev-simulate", "--store", str(store), "--end", END]
    if store.exists():
        args.append("--reset")
    subprocess.run(args, check=True)
    subprocess.run([_teachermodel(), "views", "--private-dir", str(store)], check=True, stdout=subprocess.DEVNULL)


def execute(item: Run, store: Path, kept: dict[str, str]) -> tuple[list[str], int, str]:
    """Run one command on the tour store: (its arguments, exit status, output). Keeps the value `item.keep` names."""
    args = [a.format(**kept) for a in item.args]
    env = {**os.environ, "TEACHERMODEL_PRIVATE_DIR": str(store), "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run([_teachermodel(), *args], env=env, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if item.keep and done.returncode == item.exit:
        kept[item.keep] = json.loads(done.stdout)["clearance"]
    return args, done.returncode, (done.stdout + done.stderr).rstrip()


def collect_kept(store: Path) -> dict[str, str]:
    """The values a later stop uses that an earlier one keeps (the partner clearance), collected quietly first."""
    kept: dict[str, str] = {}
    for stop in STOPS:
        for item in stop.show:
            if isinstance(item, Run) and item.keep:
                execute(item, store, kept)
    return kept


def _run(item: Run, store: Path, kept: dict[str, str], echo: bool) -> str | None:
    print(f"\n> teachermodel {' '.join(a.format(**kept) for a in item.args)}", flush=True)
    _args, status, out = execute(item, store, kept)
    if echo:
        print(out)
    if status != item.exit:
        return f"exit {status}, expected {item.exit}: {out[-300:]}"
    return None


def _open(item: Open, store: Path, browse: bool) -> str | None:
    found = sorted(store.glob(item.glob))
    if not found:
        return f"nothing matches {item.glob}"
    print(f"\n[opens] {found[0].relative_to(store)}", flush=True)
    if browse:
        webbrowser.open(found[0].as_uri())
    return None


def walk(store: Path, stops: list[int], *, interactive: bool, browse: bool, echo: bool) -> list[str]:
    """Show the given stops (1-based). Returns the problems found; empty when every result was as expected."""
    problems: list[str] = []
    kept = collect_kept(store)
    i = 0
    while i < len(stops):
        n = stops[i]
        stop = STOPS[n - 1]
        print(f"\n{'=' * 78}\n{n}. {stop.title}\n   for: {', '.join(AUDIENCES[a] for a in stop.audiences)}\n")
        for point in stop.say:
            print(f"  - {point}")
        for item in stop.show:
            problem = _run(item, store, kept, echo) if isinstance(item, Run) else _open(item, store, browse)
            if problem:
                problems.append(f"stop {n}: {problem}")
                print(f"  !! {problem}")
        if not interactive:
            i += 1
            continue
        answer = input("\n[Enter] next  [b] back  [q] quit > ").strip().lower()
        if answer == "q":
            break
        i = max(i - 1, 0) if answer == "b" else i + 1
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE, help="the tour store (outside the repo)")
    ap.add_argument("--audience", choices=sorted(AUDIENCES), help="only the stops for this audience")
    ap.add_argument("--from", dest="start", type=int, default=1, help="start at this stop")
    ap.add_argument("--prepare", action="store_true", help="rebuild the tour store and stop")
    ap.add_argument("--check", action="store_true", help="run every stop without pausing or opening; check results")
    ap.add_argument("--sheet", action="store_true", help=f"rewrite {SHEET.relative_to(REPO)}")
    ap.add_argument("--gui", action="store_true", help="present from a browser window (scripts/tour_gui.py)")
    ap.add_argument("--port", type=int, default=8765, help="the GUI's port on this machine (default 8765)")
    ap.add_argument("--no-browser", action="store_true", help="start the GUI without opening a browser")
    args = ap.parse_args(argv)

    if args.sheet:
        SHEET.parent.mkdir(parents=True, exist_ok=True)
        SHEET.write_bytes(render_sheet().encode("utf-8"))
        print(f"wrote {SHEET.relative_to(REPO)}")
        return 0
    store = args.store.resolve()
    if REPO in store.parents or store == REPO:
        raise SystemExit("the tour store must be outside the repository (decision 0003)")
    prepare(store, rebuild=args.prepare)
    if args.prepare:
        return 0
    if args.gui:
        import tour_gui  # beside this script

        return tour_gui.serve(sys.modules[__name__], store, port=args.port, audience=args.audience,
                              open_browser=not args.no_browser)
    stops = [n for n in range(args.start, len(STOPS) + 1) if not args.audience or args.audience in STOPS[n - 1].audiences]
    problems = walk(store, stops, interactive=not args.check, browse=not args.check, echo=not args.check)
    if args.check:
        print("\n".join(problems) if problems else f"tour check: {len(stops)} stops ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
