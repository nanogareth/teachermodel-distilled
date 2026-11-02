"""Acceptance drill for `teachermodel audition` (decision 0025), through the real CLI and the real observer pool.

    py scripts/audition_drill.py [--weeks 4] [--store DIR]

Builds a simulated store (`dev-simulate`, decision 0020; about three minutes for four weeks, the shortest run whose
observer pool has calibrated clearers), then runs one audition end to end: new, assign (refused for an observer outside
the pool, then two from the pool), score twice (each observer's form), status, result, decide hired, and carry to a
registered instructor. Checks that the event log did not change and the candidate's name is only in
identities/auditions.yaml. Prints each step and exits 1 on the first failed check. Generated data only.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from teachermodel import app, cli, simulate  # noqa: E402
from teachermodel.flows.common import observer_pool  # noqa: E402

UNIT = "sl:unit/example-agent-loop@1"
END = date(2026, 10, 23)


def run(*args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(args))
    return code, (out.getvalue() + err.getvalue()).strip()


def check(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--store", type=Path, help="reuse or build the simulated store here (default: a temp dir)")
    args = parser.parse_args()
    # A simulated store in the temp folder sits under %LOCALAPPDATA%, which a real store may not (decision 0006); as in
    # the tests, point both variables elsewhere for this generated-data run only.
    os.environ["LOCALAPPDATA"] = "Z:/teachermodel-drill/no-localappdata"
    os.environ["APPDATA"] = "Z:/teachermodel-drill/no-appdata"
    store = args.store or Path(tempfile.mkdtemp(prefix="tm-audition-")) / "store"
    if not (store / simulate.MARKER).is_file():
        print(f"building a {args.weeks}-week simulated store in {store} ...")
        simulate.simulate(store, weeks=args.weeks, end=END)
    s = ["--private-dir", str(store)]
    st = app.load_state(store)
    pool = observer_pool(st, END)
    check(len(pool) >= 2, f"the observer pool on {END} has {len(pool)} calibrated clearers")
    outsider = next(u for u in sorted(st.registrations) if u not in pool)
    log = (store / app.EVENT_LOG).read_bytes()

    code, out = run("audition", "new", *s, "--unit", UNIT, "--mode", "remote", "--slice",
                    "Steps 3 and 4: the stop condition and tool errors", "--candidate", "Drill Candidate",
                    "--on", END.isoformat())
    check(code == 0, out)
    a = out.split("opened ")[1].split(";")[0]
    folder = store / "auditions" / a

    code, out = run("audition", "assign", a, *s, "--observer", pool[0], "--observer", outsider, "--on", END.isoformat())
    check(code == 1 and "not in the observer pool" in out, f"an observer outside the pool is refused: {out}")
    code, out = run("audition", "assign", a, *s, "--observer", pool[0], "--observer", pool[1], "--on", END.isoformat())
    check(code == 0, out)

    domains = list(yaml.safe_load((folder / "form.yaml").read_text(encoding="utf-8")))
    for observer, scores in ((pool[0], [3, 2, 1, 3, 3]), (pool[1], [3, 3, 3, 2, 3])):
        form = folder.parent / f"drill-form-{observer.split('/')[-1]}.yaml"
        form.write_text(yaml.safe_dump({d: {"score": v, "note": f"drill note on {d}"} for d, v in zip(domains, scores)}),
                        encoding="utf-8")
        code, out = run("audition", "score", a, *s, "--observer", observer, "--form", str(form))
        check(code == 0, out)
        form.unlink()
        if observer == pool[0]:
            code, out = run("audition", "result", a, *s)
            check(code == 1 and "1 of 2 forms" in out, "the result waits for the second form")

    code, out = run("audition", "result", a, *s)
    check(code == 0, out)
    page = (folder / "result.md").read_text(encoding="utf-8")
    check("conceptual-questioning" in page and "Discuss what each saw" in page, "the result flags the 2-point gap")
    code, out = run("audition", "decide", a, *s, "--decision", "hired", "--reasons",
                    "Runs the lab well; questioning needs coaching first.", "--by", "tm:person/drill-chair",
                    "--on", END.isoformat())
    check(code == 0, out)
    code, out = run("audition", "carry", a, *s, "--instructor", outsider)
    check(code == 0, out)
    plan = Path(out.split("written to ")[1]).read_text(encoding="utf-8")
    check("## conceptual-questioning (audition average 2.0)" in plan, "the starting plan leads with the lowest domain")

    check((store / app.EVENT_LOG).read_bytes() == log, "the event log is unchanged")
    text = "".join(p.read_text(encoding="utf-8") for p in folder.rglob("*") if p.is_file())
    check("Drill Candidate" not in text, "the candidate's name is not in the audition folder")
    check("Drill Candidate" in (store / "identities" / "auditions.yaml").read_text(encoding="utf-8"),
          "the name is in identities/auditions.yaml")
    print(f"audition drill passed: {a} in {store}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
