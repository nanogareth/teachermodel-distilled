"""Paper fallback (paper.py, decision 0022): the printable run sheet and rubric, and a session held on paper entered
afterwards through an ad-hoc assignment with `held_on`. Fictional people only."""

import pytest
from test_adhoc_assignment import CANDIDATE, COORD, STEP, adhoc, page_fields, reasons
from test_observation import STEP_OBSERVE, observe_fields, store

from teachermodel import app, cli, flows, paper
from teachermodel.flows import observation

UNIT = "sl:unit/example-agent-loop@1"


def test_the_run_sheet_and_rubric_are_written_for_a_unit(fictional_store, capsys):
    rep = paper.write(fictional_store, UNIT)
    out = fictional_store / "generated" / "paper" / "example-agent-loop-1"
    sheet = (out / "run-sheet.html").read_text(encoding="utf-8")
    rubric = (out / "rubric.html").read_text(encoding="utf-8")
    assert "rate-limit" in sheet and "model-retries-itself" in sheet and "tool-use loop" in sheet
    assert "Technical depth" in rubric and "exemplary" in rubric and "Evidence note" in rubric
    import re

    assert not re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", sheet + rubric) and "paper:" in rep.summary  # no address
    assert cli.main(["paper", "--private-dir", str(fictional_store), "--unit", UNIT]) == 0
    assert cli.main(["paper", "--private-dir", str(fictional_store), "--unit", "sl:unit/nope@1"]) == 1


def test_held_on_is_bounded_to_the_paper_window(fictional_store, example_roster):
    from test_observation import K7

    store(fictional_store, example_roster)
    at = "2026-10-27T09:00:00+00:00"
    assert reasons(fictional_store, page_fields(K7, held_on="2026-10-20"), at=at) == []
    assert any("held_on" in r for r in reasons(fictional_store, page_fields(K7, held_on="2026-10-28"), at=at))
    assert any("14 days" in r for r in reasons(fictional_store, page_fields(K7, held_on="2026-10-01"), at=at))
    assert any("held_on" in r for r in reasons(fictional_store, page_fields(K7, held_on="last week"), at=at))
    assert observation.PAPER_BACKDATE_DAYS == 14


def test_a_paper_session_is_entered_afterwards_with_its_own_date(fictional_store, example_roster):
    from test_adhoc_assignment import make_signoff, ingest
    from test_observation import K7, T0

    store(fictional_store, example_roster)
    app.do_run(fictional_store, now=T0)
    st = app.load_state(fictional_store)
    from test_adhoc_assignment import sign

    sign(fictional_store, STEP, CANDIDATE, COORD, page_fields(K7, held_on="2026-10-21"), at="2026-10-27T09:00:00+00:00")
    (opened,) = adhoc(fictional_store)
    assert opened["payload"]["attrs"]["held_on"] == "2026-10-21"
    a = opened["subject_uri"]
    doc = {"step": STEP_OBSERVE, "subject_uri": a, "decision": "approve", "signer": K7,
           "signed_at": "2026-10-28T09:00:00+00:00", "fields": observe_fields(day="2026-10-21")}
    assert not any("before the assignment" in r for r in flows.content_reasons(app.load_state(fictional_store), doc))
    doc["fields"] = observe_fields(day="2026-10-20")  # before the paper session: still refused
    assert any("before the assignment" in r for r in flows.content_reasons(app.load_state(fictional_store), doc))
