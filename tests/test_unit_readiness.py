"""W12 unit readiness (spec v0.2 W12; increment 3 plan, stream I).

A unit file may list its SME `authors`. When a new unit version appears, `open-candidates` opens a candidate (instructor x
unit x mode) for each author who is a registered instructor and holds no valid clearance for that unit and mode yet, which
puts the author's own unit through the dry run (W3) and the clearance (W4) with no new decision logic. Fictional data only.
"""

import shutil
from datetime import datetime, timezone

import pytest
import yaml
from conftest import make_fictional_store
from privacy_helpers import import_roster_ungated, make_privacy_root
from test_clearance import hold

from teachermodel import app, events, signoff as tm_signoff, units, workflow
from teachermodel.standards import ROOT, validate

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
V1 = "sl:unit/example-agent-loop@1"
V2 = "sl:unit/example-agent-loop@2"
SME = "tm:instructor/k7m2q"  # co-deliver in the example roster; delivers V1 in-person and hybrid
PARTNER = "tm:instructor/r8n4h"  # shadow
UNKNOWN = "tm:instructor/zz9top"


def candidates(private):
    return sorted(e["subject_uri"] for e in app.read_events(private)
                  if e["kind"] == "subject" and e["payload"]["subject_kind"] == "candidate")


def add_unit_version(root, version=2, authors=(SME,)):
    doc = yaml.safe_load((root / "standards" / "units" / "example-agent-loop@1.yaml").read_text(encoding="utf-8"))
    doc["id"] = f"sl:unit/example-agent-loop@{version}"
    if authors is not None:
        doc["authors"] = list(authors)
    path = root / "standards" / "units" / f"example-agent-loop@{version}.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture
def world(tmp_path, example_roster):
    private = make_fictional_store(tmp_path)
    root = make_privacy_root(tmp_path)
    import_roster_ungated(private, example_roster, T0)
    return private, root


# --- the unit contract ---------------------------------------------------------------------------------------------


def test_a_unit_may_list_its_authors():
    doc = yaml.safe_load((ROOT / "standards" / "units" / "example-agent-loop@1.yaml").read_text(encoding="utf-8"))
    assert validate(doc, "unit-requirements.schema.json") == []
    assert validate({**doc, "authors": [SME, PARTNER]}, "unit-requirements.schema.json") == []


@pytest.mark.parametrize("authors", [["Pat Author"], [SME, SME], ["tm:person/someone"], [], SME])
def test_authors_must_be_distinct_instructor_uris(authors):
    doc = yaml.safe_load((ROOT / "standards" / "units" / "example-agent-loop@1.yaml").read_text(encoding="utf-8"))
    assert validate({**doc, "authors": authors}, "unit-requirements.schema.json")


def test_authors_do_not_move_the_environment_hash(tmp_path):
    root = make_privacy_root(tmp_path)
    add_unit_version(root, 3, authors=None)
    add_unit_version(root, 4, authors=(SME,))
    plain = units.environment_sha256(units.load("sl:unit/example-agent-loop@3", root))
    authored = units.environment_sha256(units.load("sl:unit/example-agent-loop@4", root))
    assert plain == authored


def test_units_authors_reads_them_sorted_and_defaults_to_none(tmp_path):
    root = make_privacy_root(tmp_path)
    add_unit_version(root, 2, authors=(PARTNER, SME))
    assert units.authors(units.load(V2, root)) == [SME, PARTNER]
    assert units.authors(units.load(V1, root)) == []


# --- opening the authors' candidates --------------------------------------------------------------------------------


def test_a_new_unit_version_opens_a_candidate_for_each_mode_for_its_author(world):
    private, root = world
    app.do_run(private, now=T0, root=root)
    before = candidates(private)
    assert not any("example-agent-loop-2" in c for c in before)  # no author yet: nothing for version 2
    add_unit_version(root)
    app.do_run(private, now=T0, root=root)
    assert [c for c in candidates(private) if c not in before] == [
        "tm:candidate/k7m2q--example-agent-loop-2--hybrid",
        "tm:candidate/k7m2q--example-agent-loop-2--in-person",
        "tm:candidate/k7m2q--example-agent-loop-2--remote",
    ]


def test_the_author_need_not_be_at_lead_observed_yet(world):
    private, root = world
    add_unit_version(root, authors=(PARTNER,))  # the partner instructor is at shadow
    app.do_run(private, now=T0, root=root)
    assert "tm:candidate/r8n4h--example-agent-loop-2--remote" in candidates(private)


def test_an_author_who_is_not_a_registered_instructor_opens_nothing(world):
    private, root = world
    add_unit_version(root, authors=(UNKNOWN,))
    app.do_run(private, now=T0, root=root)
    assert not any("zz9top" in c for c in candidates(private))


def test_a_unit_without_authors_opens_nothing_new(world):
    private, root = world
    app.do_run(private, now=T0, root=root)
    before = candidates(private)
    add_unit_version(root, authors=None)
    app.do_run(private, now=T0, root=root)
    assert candidates(private) == before


def test_running_again_opens_nothing_twice(world):
    private, root = world
    add_unit_version(root)
    app.do_run(private, now=T0, root=root)
    first = candidates(private)
    log_size = len(app.read_events(private))
    app.do_run(private, now=T0, root=root)
    assert candidates(private) == first and len(app.read_events(private)) == log_size


def test_a_mode_the_author_is_already_cleared_for_is_not_opened_again(world):
    private, root = world
    add_unit_version(root)
    hold(private, SME, unit=V2)  # a valid in-person clearance for the unit version, from before
    app.do_run(private, now=T0, root=root)
    mine = [c for c in candidates(private) if "k7m2q--example-agent-loop-2" in c]
    assert mine == ["tm:candidate/k7m2q--example-agent-loop-2--hybrid", "tm:candidate/k7m2q--example-agent-loop-2--remote"]


def test_the_authors_candidates_go_through_the_dry_run_workflow_as_they_are(world):
    private, root = world
    add_unit_version(root)
    app.do_run(private, now=T0, root=root)
    due = {(d.step, d.subject) for d in app.due_steps(app.load_state(private, root), T0.date())}
    cand = "tm:candidate/k7m2q--example-agent-loop-2--remote"
    assert ("tm:step/dry-run", cand) in due and ("tm:step/evidence-ready", cand) in due


def test_a_unit_file_that_does_not_validate_does_not_stop_the_step(world):
    private, root = world
    (root / "standards" / "units" / "example-agent-loop@9.yaml").write_text("not: a unit\n", encoding="utf-8")
    add_unit_version(root)
    app.do_run(private, now=T0, root=root)
    assert "tm:candidate/k7m2q--example-agent-loop-2--remote" in candidates(private)


# --- the clearers of the previous version clear the authors of the new one (integration review finding 9) ----------------


def _decide(private, root, step, signer, subject, at="2026-10-27T09:00:00+00:00"):
    """Sign as ingest would, on the state read with this test's standards root (the new unit version lives there)."""
    from teachermodel import bridge, flows
    from teachermodel import pages as pagegen

    st = app.load_state(private, root)
    (spec,) = [s for s in app._page_specs(st, step, subject) if s["signer"] == signer]
    doc = {"schema": "tm:contract/signoff@1", "id": tm_signoff.input_sha256([step, subject, signer, at])[:16], "step": step,
           "subject_uri": subject, "input_sha256": tm_signoff.input_sha256(spec["inputs"]), "decision": "approve",
           "fields": {"outcome": "cleared"}, "signer": signer, "signed_at": at,
           "page_template_sha256": pagegen.template_sha256(spec["template"])}
    assert flows.content_reasons(st, doc) == []
    event = tm_signoff.to_event(doc, "sender@example.com")
    applied = bridge.Applied(events=[event], private=[(f"signoffs/{doc['id']}.json", doc)])
    hook_events, hook_docs = app._signoff_hooks(st, applied, datetime.fromisoformat(at))
    app._store_documents(private, applied.private)
    app._store_documents(private, hook_docs, under="")
    app.append_new(private, [event, *hook_events])


def test_an_author_is_cleared_on_the_new_version_by_clearers_of_the_previous_one(world):
    from clearer_helpers import calibrate, set_level
    from test_clearance import put

    from teachermodel.flows import clearance

    private, root = world
    p3, c5 = "tm:instructor/p3x9d", "tm:instructor/c5w1t"
    for c in (p3, c5):
        set_level(private, c, "clearer")
        calibrate(private, c)
        hold(private, c)  # a clearance for version 1, none for version 2
    add_unit_version(root)
    app.do_run(private, now=T0, root=root)
    cand = "tm:candidate/k7m2q--example-agent-loop-2--in-person"
    unit = units.load(V2, root)
    domains = [d["id"] for d in app.load_state(private, root).standards["framework"]["domains"]]
    for n, observer in enumerate((p3, c5)):
        put(private, events.make_event(
            "observation", SME, observer,
            {"instructor": SME, "unit": V2, "observer": observer, "length": "full", "lead": True, "mode": "in-person",
             "rubric_version": "0.2.0", "scores": {d: 3 for d in domains}},
            id=tm_signoff.input_sha256(["w12-obs", observer, n])[:32], at="2026-10-20T10:00:00+00:00"))
    put(private, events.make_event(
        "dry_run", cand, "tm:person/clearer-1",
        {"candidate": cand, "instructor": SME, "unit": V2, "mode": "in-person", "passed": True, "checks": {"clock": "pass"},
         "failure_injected": unit["failure_catalogue"][0]["id"], "fallback_exercised": True,
         "environment_sha256": units.environment_sha256(unit), "signoff_id": "ab" * 8},
        at="2026-10-21T10:00:00+00:00"))
    app.do_run(private, now=T0, root=root)
    st = app.load_state(private, root)
    assert clearance.holds_unit(st, p3, V2, T0.date()) and not clearance.holds_unit(st, p3, "sl:unit/example-agent-loop@3",
                                                                                    T0.date())
    assert sorted(s["signer"] for s in app._page_specs(st, "tm:step/clearer-decision-1", cand)) == [c5, p3]
    _decide(private, root, "tm:step/clearer-decision-1", p3, cand)
    _decide(private, root, "tm:step/clearer-decision-2", c5, cand)
    app.do_run(private, now=T0.replace(day=27), root=root)
    (issued,) = [e for e in app.read_events(private) if e["kind"] == "clearance" and e["subject_uri"] == cand]
    assert issued["payload"]["unit"] == V2 and issued["payload"]["outcome"] == "cleared"
    assert sorted(issued["payload"]["clearers"]) == [c5, p3]


def test_previous_version_reads_the_unit_reference():
    from teachermodel.flows import clearance

    assert clearance.previous_version(V2) == V1
    assert clearance.previous_version(V1) is None
    assert clearance.previous_version("not-a-unit") is None
