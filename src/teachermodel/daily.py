"""The deterministic daily job (owner, 2026-10-27): `teachermodel daily`, its development toggle and its Windows task.

`daily` imports any feed files dropped in the store's `inbox/` (feeds.py, decision 0028), ticks the store and logs each to `logs/daily.log`, the tick's line last. With
`dev_autosign: true` in the settings (a pilot store only, settings@1) it runs `dev-autosign` instead, which ticks before and after it signs. No model runs here:
with `TEACHERMODEL_M365_DRIVER=graph` in the environment it first reads the sign-off mailbox through the Graph driver
(graph.py) and ingests the receipt. Without it the mailbox is read by the connector skill in a Claude session (the
desktop task `teachermodel-mailbox-read`), a separate step.

`schedule-daily` creates the Windows scheduled task that runs `daily` (setup is a command, never a manual step), with
pythonw so no console window opens.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import app, devsign, feeds, graph, setup
from .standards import ROOT

LOG = Path("logs") / "daily.log"
TASK_NAME = "teachermodel daily"
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_TOGGLE = re.compile(r"^dev_autosign:.*$", re.M)


def daily(private_dir: Path | str, *, now: datetime | None = None, root: Path = ROOT) -> app.Report:
    """Tick, or run dev-autosign when the store's toggle is on; log one line either way."""
    private = Path(private_dir)
    now = now or datetime.now(timezone.utc).replace(microsecond=0)
    settings = setup.load_settings(private)
    arrived = feeds.drain_inbox(private, root)
    refused = sum(": refused: " in line for line in arrived)
    inbox = app.Report(lines=arrived, summary=f"{len(arrived) - refused} kept, {refused} refused", ok=not refused)
    read = None
    if os.environ.get(graph.ENV_DRIVER, "").strip() == "graph":
        try:
            read = app.do_graph_read(private, now=now, root=root)
        except app.AppError as exc:
            read = app.Report(summary=f"graph-read failed: {exc}", ok=False)
    if settings.get("dev_autosign") is True:
        mode, rep = "dev-autosign", devsign.autosign(private, root=root)
    else:
        reports = app.do_tick(private, now=now, root=root)
        mode, rep = "tick", app.Report(lines=[r.summary for r in reports[:-1]], summary=reports[-1].summary,
                                       ok=all(r.ok for r in reports))
    log = private / LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8", newline="\n") as f:
        if arrived:
            f.write(f"{now.isoformat(timespec='seconds')} inbox {'ok' if inbox.ok else 'FAILED'}: {inbox.summary}\n")
        if read is not None:
            f.write(f"{now.isoformat(timespec='seconds')} graph-read {'ok' if read.ok else 'FAILED'}: {read.summary}\n")
        f.write(f"{now.isoformat(timespec='seconds')} {mode} {'ok' if rep.ok else 'FAILED'}: {rep.summary}\n")
    if read is not None:
        rep = app.Report(lines=[*read.all_lines(), *rep.lines], summary=rep.summary, ok=rep.ok and read.ok)
    if arrived:
        rep = app.Report(lines=[*arrived, *rep.lines], summary=rep.summary, ok=rep.ok and inbox.ok)
    return rep


def set_dev_mode(private_dir: Path | str, on: bool) -> bool:
    """Set `dev_autosign` in the store's settings.yaml, editing that one line so the rest of the file stays as it is.
    Refused (SetupError, nothing written) where the settings would not validate, such as a store that is not a pilot."""
    path = Path(private_dir) / "settings.yaml"
    before = path.read_text(encoding="utf-8")
    line = f"dev_autosign: {'true' if on else 'false'}"
    after = _TOGGLE.sub(line, before) if _TOGGLE.search(before) else before.rstrip("\n") + f"\n{line}\n"
    path.write_text(after, encoding="utf-8", newline="\n")
    try:
        settings = setup.load_settings(path.parent)
    except setup.SetupError as exc:
        path.write_text(before, encoding="utf-8", newline="\n")
        raise setup.SetupError(f"dev mode works only in a pilot store (settings 'pilot: true'): {exc}") from exc
    return settings["dev_autosign"]


def dev_mode(private_dir: Path | str) -> bool:
    return setup.load_settings(private_dir).get("dev_autosign") is True


def schtasks_create(private_dir: Path | str, *, python: str = sys.executable, at: str = "07:30",
                    weekdays: bool = True) -> list[str]:
    """The schtasks command line that creates (or replaces) the daily task."""
    if not _TIME.match(at):
        raise ValueError(f"time must be HH:MM (24-hour), got {at!r}")
    exe = Path(python)
    windowless = exe.with_name("pythonw.exe") if exe.name.lower() == "python.exe" else exe
    run = f'"{windowless}" -m teachermodel.cli daily --private-dir "{Path(private_dir)}"'
    if len(run) > 261:
        raise ValueError("the task's command line is longer than the 261 characters schtasks takes")
    when = ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI"] if weekdays else ["/SC", "DAILY"]
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", run, *when, "/ST", at, "/F"]


def schtasks_delete() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def schedule(private_dir: Path | str, *, at: str = "07:30", weekdays: bool = True, remove: bool = False) -> str:
    """Create, replace or remove the Windows task; returns schtasks' own message."""
    if sys.platform != "win32":
        raise setup.SetupError("schedule-daily uses Windows Task Scheduler; on another system run `teachermodel daily` "
                               "from cron")
    args = schtasks_delete() if remove else schtasks_create(private_dir, at=at, weekdays=weekdays)
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode != 0:
        raise setup.SetupError(f"schtasks failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout.strip()
