"""PDF export of a bench evidence pack (export.py, `teachermodel export-pack`). Fictional people only."""

import os

import pytest
from test_bench import BENCH, T0, pack_file, requested, world  # noqa: F401 - world is a fixture

from teachermodel import app, cli, events, export
from teachermodel.standards import ROOT

# conftest points LOCALAPPDATA away from the real one for every test; Playwright finds its browsers there by default
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")


def fake_pdf(html, pdf):
    pdf.write_bytes(b"%PDF-1.7 fake " + html.name.encode())


def accesses(private):
    return [e for e in app.read_events(private) if e["kind"] == "record_access"]


def test_the_pack_is_exported_next_to_its_html_and_the_export_is_logged(world):
    requested(world)
    rep = export.export_pack(world, BENCH, renderer=fake_pdf, now=T0)
    pdf = pack_file(world).with_suffix(".pdf")
    assert pdf.read_bytes().startswith(b"%PDF-") and rep.lines == ["pdf: generated/bench/k7m2q--1.pdf"]
    (e,) = accesses(world)
    assert e["subject_uri"] == BENCH and e["actor"] == "tm:system/teachermodel"
    assert e["payload"] == {"action": "export", "record": "generated/bench/k7m2q--1.html", "format": "pdf",
                            "evidence_pack_sha256": e["payload"]["evidence_pack_sha256"],
                            "output": "generated/bench/k7m2q--1.pdf"}
    assert events.check_event(e) == []


def test_an_edited_pack_is_refused(world):
    requested(world)
    html = pack_file(world)
    html.write_bytes(html.read_bytes() + b"<!-- edited -->")
    with pytest.raises(app.AppError, match="not the pack on record"):
        export.export_pack(world, BENCH, renderer=fake_pdf)
    assert not accesses(world)


def test_no_pack_or_not_a_bench_is_refused(world):
    with pytest.raises(app.AppError, match="not a bench review"):
        export.export_pack(world, BENCH, renderer=fake_pdf)
    with pytest.raises(app.AppError, match="not a bench review"):
        export.export_pack(world, "tm:instructor/k7m2q", renderer=fake_pdf)


def test_a_pdf_inside_the_repository_is_refused(world):
    requested(world)
    with pytest.raises(app.AppError, match="inside the repository"):
        export.export_pack(world, BENCH, out=ROOT / "pack.pdf", renderer=fake_pdf)
    assert not (ROOT / "pack.pdf").exists()


def test_an_export_outside_the_store_logs_external_and_no_path(world, tmp_path):
    requested(world)
    out = tmp_path / "outside" / "pack.pdf"
    export.export_pack(world, BENCH, out=out, renderer=fake_pdf)
    assert out.is_file()
    (e,) = accesses(world)
    assert e["payload"]["output"] == "external" and str(tmp_path) not in str(e)


def test_a_renderer_that_writes_no_pdf_fails_and_logs_nothing(world):
    requested(world)
    with pytest.raises(app.AppError, match="no PDF"):
        export.export_pack(world, BENCH, renderer=lambda html, pdf: pdf.write_bytes(b"<html>"))
    assert not accesses(world)


def test_the_export_pack_command(world, capsys, monkeypatch):
    requested(world)
    monkeypatch.setattr(export, "chromium_pdf", fake_pdf)
    assert cli.main(["export-pack", "--private-dir", str(world), "--bench", BENCH]) == 0
    out = capsys.readouterr().out
    assert "pdf: generated/bench/k7m2q--1.pdf" in out and "export-pack:" in out
    assert cli.main(["export-pack", "--private-dir", str(world), "--bench", "tm:bench/nobody--9"]) == 1
    assert "not a bench review" in capsys.readouterr().err


@pytest.mark.browser
def test_chromium_prints_the_real_pack(world, monkeypatch):
    pytest.importorskip("playwright")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", BROWSERS)
    requested(world)
    export.export_pack(world, BENCH, now=T0)
    pdf = pack_file(world).with_suffix(".pdf")
    data = pdf.read_bytes()
    assert data.startswith(b"%PDF-") and len(data) > 2000
