"""The expert-to-session handoff (handoff.py, standards/templates/expert-to-session.md; spec phase 6). Fictional data."""

from teachermodel import cli, handoff, units

UNIT = "sl:unit/example-agent-loop@1"


def test_the_handoff_renders_the_unit_and_lists_what_is_missing(fictional_store):
    rep = handoff.write(fictional_store, UNIT)
    text = (fictional_store / "generated" / "handoff" / "example-agent-loop-1.md").read_text(encoding="utf-8")
    assert text.startswith("# Expert-to-session handoff: Building a tool-using agent loop")
    assert "rate-limit: inject" in text and "model-retries-itself" in text and "$" not in text
    unit = units.load(UNIT)
    assert handoff.missing(unit) == [] if unit.get("authors") else any("author" in g for g in handoff.missing(unit))
    assert rep.summary.startswith("handoff: ")


def test_a_bare_unit_lists_every_gap():
    gaps = handoff.missing({"id": "sl:unit/bare@1"})
    assert len(gaps) == 6 and any("failure catalogue" in g for g in gaps)
    assert "Still missing" in handoff.render({"id": "sl:unit/bare@1"})


def test_the_handoff_command(fictional_store, capsys):
    assert cli.main(["handoff", "--private-dir", str(fictional_store), "--unit", UNIT]) == 0
    assert cli.main(["handoff", "--private-dir", str(fictional_store), "--unit", "sl:unit/none@1"]) == 1
