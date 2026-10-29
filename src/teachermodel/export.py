"""PDF export of a bench evidence pack (spec v0.2, "Evidence pack export"): `teachermodel export-pack --bench <uri>`.

The pack is the HTML file the evidence-pack step wrote (flows/bench.py, generated/bench/<slug>.html). The export prints
exactly that file to PDF through headless Chromium (the [browser] extra), after checking that its bytes are the ones the
latest evidence-pack event recorded: an edited or stale file is refused, never exported. The PDF goes next to the HTML in
the private store unless `--out` names another path, which may not be inside the repository (decision 0003).

Each export appends a `record_access` event (subject: the bench, actor: the system) with the pack's sha256 and where the
PDF went: a store-relative path, or `external`. No name, no path outside the store.

Partner reports (the spec's other use of an evidence pack) are not built: sending a pack to a partner is a disclosure no
purpose in standards/privacy/purposes.yaml covers yet.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import events
from .app import EVENT_LOG, AppError, Report, load_state
from .flows.bench import STEP_PACK, pack_path
from .standards import ROOT
from .workflow import SYSTEM_ACTOR

# (html file, pdf file) -> None; writes the PDF
Renderer = Callable[[Path, Path], None]
INSTALL_HINT = "py -m pip install -e .[browser]; py -m playwright install chromium"
# Print-only styles, added in the browser at export time so the pack file (and its recorded sha256) stays as it is: the
# full page width, and table text that wraps instead of running off the page.
PRINT_CSS = ("body{max-width:none;margin:0} table{font-size:.72rem} th,td{overflow-wrap:break-word;padding:.15rem .3rem}"
             " td:first-child{overflow-wrap:anywhere}"
             " tr{break-inside:avoid} h2{break-after:avoid}")


def chromium_pdf(html: Path, pdf: Path) -> None:
    """Print `html` to `pdf` in headless Chromium: A4 landscape (the observation table is wide), backgrounds kept."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise AppError(f"PDF export needs the [browser] extra: {INSTALL_HINT}") from exc
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(html.resolve().as_uri())
                page.add_style_tag(content=PRINT_CSS)
                page.pdf(path=str(pdf), format="A4", landscape=True, print_background=True,
                         margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
            finally:
                browser.close()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - a missing browser binary or a render failure: say how to fix it
        raise AppError(f"Chromium could not print the pack ({type(exc).__name__}); {INSTALL_HINT}") from exc


def export_pack(
    private_dir: Path | str, bench: str, *, out: Path | str | None = None, now: datetime | None = None,
    renderer: Renderer | None = None, root: Path = ROOT,
) -> Report:
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    private = Path(private_dir)
    st = load_state(private, root)
    info = st.subjects.get(bench)
    if info is None or info.get("kind") != "bench":
        raise AppError(f"{bench} is not a bench review")
    packs = [e for e in st.index.of("step", bench) if e["payload"].get("step") == STEP_PACK]
    html = private / pack_path(bench)
    if not packs or not html.is_file():
        raise AppError(f"{bench} has no evidence pack yet; run `teachermodel tick` first")
    sha = hashlib.sha256(html.read_bytes()).hexdigest()
    if sha != packs[-1]["payload"].get("evidence_pack_sha256"):
        raise AppError(f"{html.name} is not the pack on record (its bytes changed); run `teachermodel tick` to write it "
                       "again")
    target = Path(out) if out is not None else html.with_suffix(".pdf")
    resolved = target.resolve()
    if resolved.is_relative_to(Path(root).resolve()):
        raise AppError("the PDF holds personal data and may not be written inside the repository (decision 0003)")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    (renderer or chromium_pdf)(html, resolved)
    if not resolved.is_file() or resolved.read_bytes()[:5] != b"%PDF-":
        raise AppError("the export wrote no PDF")
    home = private.resolve()
    where = resolved.relative_to(home).as_posix() if resolved.is_relative_to(home) else "external"
    event = events.make_event(
        "record_access", bench, SYSTEM_ACTOR,
        {"action": "export", "record": pack_path(bench), "format": "pdf", "evidence_pack_sha256": sha, "output": where},
        at=now.isoformat(timespec="seconds"))
    events.append(private / EVENT_LOG, event)
    return Report(lines=[f"pdf: {resolved if where == 'external' else where}"],
                  summary=f"export-pack: {bench} exported as PDF")
