"""Integration review finding 13: import-outcomes keeps a small cohort's numbers out of the log, and keeps the validated
document rather than the raw bytes.

A delivery with fewer than `rules.quality.min_learners_for_metric` learners assessed is written with a null score and a null
feedback (the summary shows it as "insufficient data"), and the copy kept under imports/ is the re-serialised document with
the same change: a file's comments, ordering and whitespace are not kept. Fictional data only.
"""

import json

import pytest
from test_quality_import import K7, T0, UNIT, delivery, doc, outcomes, store, write  # noqa: F401 - store is a fixture

from teachermodel import app, events
from teachermodel.flows import quality

MINIMUM = 15


def test_a_delivery_below_the_minimum_is_written_without_score_and_feedback(store, tmp_path):
    small = delivery(1, learners_assessed=MINIMUM - 1, score=12.345, feedback=1.2345)
    quality.import_outcomes(store, write(tmp_path, doc(small)), now=T0)
    (event,) = outcomes(store)
    payload = event["payload"]
    assert payload["score"] is None and payload["feedback"] is None
    assert payload["learners_assessed"] == MINIMUM - 1 and payload["baseline"] == 80.0
    raw = (store / app.EVENT_LOG).read_text(encoding="utf-8")
    assert "12.345" not in raw and "1.2345" not in raw
    assert events.check_event(event) == [] and events.verify(store / app.EVENT_LOG) == []


def test_a_delivery_at_the_minimum_keeps_its_numbers(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1, learners_assessed=MINIMUM))), now=T0)
    assert (outcomes(store)[0]["payload"]["score"], outcomes(store)[0]["payload"]["feedback"]) == (71.5, 4.1)


def test_a_small_delivery_without_feedback_stays_without_it(store, tmp_path):
    row = {k: v for k, v in delivery(1, learners_assessed=3).items() if k not in ("feedback", "feedback_median")}
    quality.import_outcomes(store, write(tmp_path, doc(row)), now=T0)
    payload = outcomes(store)[0]["payload"]
    assert payload["score"] is None and "feedback" not in payload


def test_the_summary_shows_a_small_delivery_as_insufficient_data(store, tmp_path):
    quality.import_outcomes(store, write(tmp_path, doc(delivery(1, learners_assessed=3))), now=T0)
    st = app.load_state(store)
    summary = quality.summary_document(st, K7, [])
    (row,) = summary["deliveries"]
    assert row["status"] == quality.INSUFFICIENT and row["score"] is None and row["feedback"] is None


def test_reimporting_the_same_small_delivery_is_unchanged_and_a_changed_one_is_refused(store, tmp_path):
    first = write(tmp_path, doc(delivery(1, learners_assessed=3)), "a.json")
    assert quality.import_outcomes(store, first, now=T0).appended == 1
    again = quality.import_outcomes(store, first, now=T0.replace(minute=5))
    assert (again.appended, again.unchanged) == (0, 1)
    changed = write(tmp_path, doc(delivery(1, learners_assessed=4)), "b.json")
    with pytest.raises(quality.QualityError):
        quality.import_outcomes(store, changed, now=T0.replace(minute=6))


def test_the_kept_copy_is_the_validated_document_not_the_raw_bytes(store, tmp_path):
    text = ("# Exported by hand; ask Zelda Learnerton about the second cohort.\n"
            "schema: tm:contract/outcome-import@1\nsource: lms-export\nexported_at: 2026-10-26T07:00:00Z\ndeliveries:\n"
            f"  - {{delivery_ref: d-1, instructor: {K7}, unit: {UNIT}, mode: remote, delivered_on: 2026-10-05,\n"
            "     learners_assessed: 20, score: 70, baseline: 80}\n"
            f"  - {{delivery_ref: d-2, instructor: {K7}, unit: {UNIT}, mode: remote, delivered_on: 2026-10-06,\n"
            "     learners_assessed: 4, score: 55.5, baseline: 80, feedback: 2.5, feedback_median: 4.0}\n")
    src = tmp_path / "export.yaml"
    src.write_text(text, encoding="utf-8")
    done = quality.import_outcomes(store, src, now=T0)
    assert done.copy.suffix == ".json" and done.copy.parent == store / "imports"
    kept = done.copy.read_bytes()
    assert b"Zelda" not in kept and b"55.5" not in kept and b"2.5" not in kept  # no comment, no small cohort's numbers
    document = json.loads(kept)
    assert document["source"] == "lms-export" and [d["delivery_ref"] for d in document["deliveries"]] == ["d-1", "d-2"]
    assert document["deliveries"][0]["score"] == 70 and document["deliveries"][1]["score"] is None
    assert kept.endswith(b"\n") and kept == (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def test_a_refused_file_still_keeps_nothing(store, tmp_path):
    before = app.read_events(store)
    with pytest.raises(quality.QualityError):
        quality.import_outcomes(store, write(tmp_path, doc(delivery(1), delivery(2, learners_assessed=-1))), now=T0)
    assert app.read_events(store) == before and not (store / "imports").exists()
