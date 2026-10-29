"""`teachermodel import-outcomes` (flows/quality.py): outcome-import@1 files in, `outcome` events out.

The whole file is refused on any error, naming the field and never a value. Only registered instructors; a re-import of a
delivery with the same numbers adds nothing, with changed numbers is refused (a correction is a new delivery_ref).
The file is kept, once valid, in imports/ (private). Fictional data only.
"""

import copy
import hashlib
import json
from datetime import datetime, timezone

import pytest
from conftest import make_fictional_store
from privacy_helpers import import_roster_ungated

from teachermodel import app, cli, events
from teachermodel.flows import quality

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
UNIT = "sl:unit/example-agent-loop@1"
K7 = "tm:instructor/k7m2q"
LEARNER_NAME = "Zelda Learnerton"  # appears only inside refused files: it must never be echoed


def delivery(n=1, **over):
    row = {"delivery_ref": f"delivery-{n}", "instructor": K7, "unit": UNIT, "mode": "remote",
           "delivered_on": f"2026-10-{n:02d}", "learners_assessed": 18, "score": 71.5, "baseline": 80.0,
           "feedback": 4.1, "feedback_median": 4.4}
    row.update(over)
    return row


def doc(*rows, **over):
    d = {"schema": "tm:contract/outcome-import@1", "source": "lms-export", "exported_at": "2026-10-26T07:00:00Z",
         "deliveries": list(rows) or [delivery()]}
    d.update(over)
    return d


def write(tmp_path, document, name="export.json"):
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def store(fictional_store, example_roster, cached_world):
    data = example_roster.read_bytes()

    def build(base):
        private = make_fictional_store(base)
        roster = base / "roster-in.yaml"
        roster.write_bytes(data)
        import_roster_ungated(private, roster, T0)
        events.append(private / app.EVENT_LOG, events.make_event(
            "notice", K7, "tm:system/teachermodel", {"step": "tm:step/notice-sent", "notice_variant": "2026-11"}))

    cached_world(("quality_import_store", hashlib.sha256(data).hexdigest()), build)
    return fictional_store


def outcomes(private):
    return [e for e in app.read_events(private) if e["kind"] == "outcome"]


def refuses(store, tmp_path, document, *, text=None):
    """The import raises QualityError, appends nothing, keeps nothing; returns the message."""
    before = app.read_events(store)
    path = write(tmp_path, document, "refused.json")
    if text is not None:
        path.write_text(text, encoding="utf-8")
    with pytest.raises(quality.QualityError) as exc:
        quality.import_outcomes(store, path, now=T0)
    assert app.read_events(store) == before
    assert not (store / "imports").exists() or not list((store / "imports").glob("outcomes-*"))
    assert LEARNER_NAME not in str(exc.value)
    return str(exc.value)


# --- a valid file -------------------------------------------------------------------------------------------------


def test_a_valid_file_appends_one_outcome_event_per_delivery(store, tmp_path):
    done = quality.import_outcomes(store, write(tmp_path, doc(delivery(1), delivery(2))), now=T0)
    assert (done.appended, done.unchanged) == (2, 0)
    found = outcomes(store)
    assert [e["payload"]["delivery_ref"] for e in found] == ["delivery-1", "delivery-2"]
    first = found[0]
    assert first["subject_uri"] == K7 and first["actor"] == "tm:system/teachermodel"
    assert first["payload"] == {**delivery(1), "source": "lms-export"}
    assert events.check_event(first) == []
    assert events.verify(store / app.EVENT_LOG) == []


def test_the_event_id_depends_on_the_delivery_ref_only(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1))), now=T0)
    (first,) = outcomes(store)
    assert first["id"] == quality.outcome_id("delivery-1") != quality.outcome_id("delivery-2")


def test_optional_feedback_fields_may_be_absent(store, tmp_path):
    row = {k: v for k, v in delivery(1).items() if k not in ("feedback", "feedback_median")}
    quality.import_outcomes(store, write(tmp_path, doc(row)), now=T0)
    assert "feedback" not in outcomes(store)[0]["payload"]


def test_the_file_is_kept_in_imports(store, tmp_path):
    src = write(tmp_path, doc())
    done = quality.import_outcomes(store, src, now=T0)
    kept = store / "imports" / "outcomes-20261026T080000Z.json"
    assert done.copy == kept and json.loads(kept.read_bytes()) == json.loads(src.read_bytes())  # the validated document, re-serialised


def test_a_yaml_export_with_bare_dates_is_accepted(store, tmp_path):
    text = ("schema: tm:contract/outcome-import@1\nsource: lms-export\nexported_at: 2026-10-26T07:00:00Z\ndeliveries:\n"
            f"  - {{delivery_ref: d-1, instructor: {K7}, unit: {UNIT}, mode: remote, delivered_on: 2026-10-05,\n"
            "     learners_assessed: 20, score: 70, baseline: 80}\n")
    path = tmp_path / "export.yaml"
    path.write_text(text, encoding="utf-8")
    assert quality.import_outcomes(store, path, now=T0).appended == 1
    assert outcomes(store)[0]["payload"]["delivered_on"] == "2026-10-05"


# --- learner identifiers and other schema breaches -----------------------------------------------------------------


def test_an_extra_learner_field_refuses_the_whole_file_and_names_the_field_only(store, tmp_path):
    rows = [delivery(1), delivery(2, learner_name=LEARNER_NAME)]
    message = refuses(store, tmp_path, doc(*rows))
    assert "learner_name" in message and "deliveries/1" in message


@pytest.mark.parametrize("field", ["learner_email", "learners", "scores", "learner_id", "comments"])
def test_other_learner_shaped_fields_are_refused(store, tmp_path, field):
    message = refuses(store, tmp_path, doc(delivery(1, **{field: LEARNER_NAME})))
    assert field in message


def test_a_field_named_after_a_learner_is_refused_without_printing_the_name(store, tmp_path):
    message = refuses(store, tmp_path, doc(delivery(1, **{LEARNER_NAME: 71})))
    assert "deliveries/0" in message


def test_an_extra_top_level_field_is_refused(store, tmp_path):
    message = refuses(store, tmp_path, doc(roster_of_learners=[LEARNER_NAME]))
    assert "roster_of_learners" in message


def test_a_missing_field_is_named(store, tmp_path):
    row = {k: v for k, v in delivery(1).items() if k != "baseline"}
    assert "baseline" in refuses(store, tmp_path, doc(row))


def test_a_wrong_value_names_the_field_and_never_the_value(store, tmp_path):
    message = refuses(store, tmp_path, doc(delivery(1, score=LEARNER_NAME)))
    assert "deliveries/0/score" in message
    message = refuses(store, tmp_path, doc(delivery(1, instructor=LEARNER_NAME)))
    assert "deliveries/0/instructor" in message


def test_an_impossible_date_is_refused(store, tmp_path):
    assert "delivered_on" in refuses(store, tmp_path, doc(delivery(1, delivered_on="2026-13-45")))


def test_one_bad_row_refuses_the_good_ones_too(store, tmp_path):
    refuses(store, tmp_path, doc(delivery(1), delivery(2, learners_assessed=-1)))
    assert outcomes(store) == []


def test_a_file_that_is_not_json_or_yaml_is_refused(store, tmp_path):
    message = refuses(store, tmp_path, {}, text="{ not: [valid")
    assert "export.json" not in message and "readable" in message


def test_a_missing_file_is_refused(store, tmp_path):
    with pytest.raises(quality.QualityError, match="no such file"):
        quality.import_outcomes(store, tmp_path / "nope.json", now=T0)


def test_the_wrong_schema_id_is_refused(store, tmp_path):
    assert "schema" in refuses(store, tmp_path, doc(schema="tm:contract/outcome-import@2"))


# --- instructors and delivery refs ---------------------------------------------------------------------------------


def test_an_unregistered_instructor_refuses_the_whole_file(store, tmp_path):
    message = refuses(store, tmp_path, doc(delivery(1), delivery(2, instructor="tm:instructor/zzzzz")))
    assert "deliveries/1/instructor" in message and "not a registered instructor" in message
    assert "zzzzz" not in message


def test_a_delivery_ref_twice_in_one_file_is_refused(store, tmp_path):
    message = refuses(store, tmp_path, doc(delivery(1), delivery(1, score=60)))
    assert "deliveries/1/delivery_ref" in message and "twice" in message


# --- re-imports ---------------------------------------------------------------------------------------------------


def test_reimporting_the_same_delivery_appends_nothing(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1))), now=T0)
    before = app.read_events(store)
    again = quality.import_outcomes(store, write(tmp_path, doc(delivery(1)), "again.json"), now=T0)
    assert (again.appended, again.unchanged) == (0, 1) and app.read_events(store) == before


def test_a_reimport_with_a_new_row_adds_only_that_row(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1))), now=T0)
    again = quality.import_outcomes(store, write(tmp_path, doc(delivery(1), delivery(2)), "again.json"), now=T0)
    assert (again.appended, again.unchanged) == (1, 1) and len(outcomes(store)) == 2


def test_a_reimport_of_a_delivery_with_changed_numbers_is_refused_and_says_how_to_correct(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1))), now=T0)
    before = app.read_events(store)
    changed = write(tmp_path, doc(delivery(2), delivery(1, score=50)), "changed.json")
    with pytest.raises(quality.QualityError) as exc:
        quality.import_outcomes(store, changed, now=T0)
    message = str(exc.value)
    assert "deliveries/1" in message and "changed" in message and "new delivery_ref" in message
    assert "50" not in message and "71.5" not in message
    assert app.read_events(store) == before  # the good second row was not imported either


def test_a_reimport_that_only_changes_the_source_is_not_a_change(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1))), now=T0)
    again = quality.import_outcomes(store, write(tmp_path, doc(delivery(1), source="other-export"), "s.json"), now=T0)
    assert again.appended == 0 and again.unchanged == 1


# --- the command ---------------------------------------------------------------------------------------------------


def test_the_command_imports_and_prints_a_summary(store, tmp_path, capsys):
    path = write(tmp_path, doc(delivery(1), delivery(2)))
    assert cli.main(["import-outcomes", str(path), "--private-dir", str(store)]) == 0
    out = capsys.readouterr().out
    assert "import-outcomes: 2 outcome event(s) appended" in out and len(outcomes(store)) == 2


def test_the_command_exits_1_and_prints_the_error_for_a_refused_file(store, tmp_path, capsys):
    path = write(tmp_path, doc(delivery(1, learner_name=LEARNER_NAME)))
    assert cli.main(["import-outcomes", str(path), "--private-dir", str(store)]) == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err and "learner_name" in captured.err
    assert LEARNER_NAME not in captured.out + captured.err and outcomes(store) == []


def test_the_command_is_listed_in_the_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "import-outcomes" in capsys.readouterr().out


def test_the_imported_outcomes_feed_the_review(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(5, score=70), delivery(12, score=70))), now=T0)
    app.do_run(store, now=T0)
    found = [e for e in app.read_events(store) if e["kind"] == "check" and e["payload"].get("trigger") == "score-drop"]
    assert len(found) == 1 and found[0]["subject_uri"] == K7
    assert copy.deepcopy(found[0]["payload"])["step"] == "tm:step/quality-review"
