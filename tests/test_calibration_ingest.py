"""W5 calibration through the mail round trip: scoring pages -> receipt -> ingest -> result.

The ingest of a sign-off on an `exercise` subject takes the expected signers from the exercise's `observers`
(`signer: attrs.observers` on the step, decision 0012). Fictional people only.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from privacy_helpers import import_roster_ungated, tm_data
from test_calibration import A, B, DOMAINS, NOW, calibration_events, open_exercise, result_steps

from teachermodel import app

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
SENDERS = {A: "professional@example.com", B: "sme.engineer@example.com"}


def receipt_for(private, exercise, scores_by_observer, *, now):
    """One receipt carrying a sign-off from each observer's generated page, mailed by that observer."""
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    slug = exercise.split("/")[1]
    messages = []
    for n, (observer, scores) in enumerate(scores_by_observer.items()):
        page = tm_data(private / "pages" / f"calibration-score--{slug}--{observer.split('/')[1]}.html")
        sid = f"{n + 1:016x}"
        doc = {
            "schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
            "input_sha256": page["input_sha256"], "decision": "approve", "signer": page["signer"],
            "signed_at": (now + timedelta(minutes=30)).isoformat(), "page_template_sha256": page["page_template_sha256"],
            "fields": {d: {"score": s, "note": "fictional evidence"} for d, s in scores.items()},
        }
        messages.append({"sender": SENDERS[observer], "subject": f"[tm-signoff {sid}]",
                         "received": (now + timedelta(minutes=40)).isoformat(),
                         "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]})
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": messages}}],
    }
    path = private / "receipts" / "calibration.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path


def test_observers_sign_through_ingest_and_the_result_follows(fictional_store, example_roster, tmp_path):
    import_roster_ungated(fictional_store, example_roster, T0)
    opened = open_exercise(fictional_store, tmp_path)
    app.do_tick(fictional_store, now=NOW)
    good = {d: 2 for d in DOMAINS}
    off = {d: 4 for d in DOMAINS}
    later = NOW + timedelta(hours=2)
    rep = app.do_ingest(fictional_store, receipt_for(fictional_store, opened.exercise, {A: good, B: off}, now=NOW),
                        now=later, allowed_drivers=("connector", "graph", "fixture"))
    assert "2 signoff" in rep.summary and "0 rejected" in rep.summary, rep.all_lines()
    app.do_run(fictional_store, now=later)
    assert {e["subject_uri"]: e["payload"]["passed"] for e in calibration_events(fictional_store)} == {A: True, B: False}
    assert len(result_steps(fictional_store)) == 1


# --- who may sign, and what the scores must contain (decision 0012) -----------------------------------------------

from ingest_helpers import email_of, ingest, signoff, signoff_events  # noqa: E402

C = "tm:instructor/c5w1t"  # a registered instructor the exercise does not list


def opened_and_ticked(store, example_roster, tmp_path):
    import_roster_ungated(store, example_roster, T0)
    opened = open_exercise(store, tmp_path)
    app.do_tick(store, now=NOW)
    return opened.exercise


def score_fields(value=2):
    return {d: {"score": value, "note": "fictional evidence"} for d in DOMAINS}


def test_an_unlisted_instructor_cannot_sign_a_scoring_page(fictional_store, example_roster, tmp_path):
    exercise = opened_and_ticked(fictional_store, example_roster, tmp_path)
    page = signoff(fictional_store, "tm:step/calibration-score", exercise, A, score_fields(), now=NOW)[0]
    forged = {**page, "signer": C, "id": "d" * 16}
    rep = ingest(fictional_store, [(forged, email_of(fictional_store, C))], now=NOW)
    assert "1 rejected" in rep.summary and any("not an expected signer" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store) == []


def test_an_observer_signs_once(fictional_store, example_roster, tmp_path):
    exercise = opened_and_ticked(fictional_store, example_roster, tmp_path)
    first = signoff(fictional_store, "tm:step/calibration-score", exercise, A, score_fields(), now=NOW, sid="e" * 16)
    rep = ingest(fictional_store, [first], now=NOW)
    assert "1 signoff" in rep.summary, rep.all_lines()
    second = signoff(fictional_store, "tm:step/calibration-score", exercise, A, score_fields(4), now=NOW, sid="f" * 16)
    rep = ingest(fictional_store, [second], now=NOW, name="again")
    assert "1 rejected" in rep.summary and any("already signed" in line for line in rep.lines), rep.all_lines()
    assert [e["actor"] for e in signoff_events(fictional_store)] == [A]


def test_two_sign_offs_by_one_observer_in_one_receipt_count_once(fictional_store, example_roster, tmp_path):
    exercise = opened_and_ticked(fictional_store, example_roster, tmp_path)
    pair = [signoff(fictional_store, "tm:step/calibration-score", exercise, A, score_fields(v), now=NOW, sid=s * 16)
            for v, s in ((2, "1"), (3, "2"))]
    rep = ingest(fictional_store, pair, now=NOW)
    assert "1 signoff" in rep.summary and "1 rejected" in rep.summary, rep.all_lines()


@pytest.mark.parametrize("damage", ["missing domain", "score out of range", "no note", "score is a string"])
def test_scores_the_result_could_not_use_are_rejected_at_ingest(fictional_store, example_roster, tmp_path, damage):
    exercise = opened_and_ticked(fictional_store, example_roster, tmp_path)
    fields = score_fields()
    first = DOMAINS[0]
    if damage == "missing domain":
        del fields[first]
    elif damage == "score out of range":
        fields[first]["score"] = 0
    elif damage == "no note":
        fields[first]["note"] = ""
    else:
        fields[first]["score"] = "3"
    rep = ingest(fictional_store, [signoff(fictional_store, "tm:step/calibration-score", exercise, A, fields, now=NOW)], now=NOW)
    assert "1 rejected" in rep.summary and any(f"domain {first}" in line for line in rep.lines), rep.all_lines()
    assert signoff_events(fictional_store) == []
    assert ("tm:step/calibration-score", exercise) in {(d.step, d.subject) for d in app.due_steps(
        app.load_state(fictional_store), NOW.date())}
