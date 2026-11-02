"""Audition observer pages (decision 0031): each observer scores on their own signed page, which comes back through the
sign-off mailbox and is kept with the audition, never in the event log. One-week simulated store, generated data only."""

import json
from datetime import date, datetime, timezone

import pytest
import yaml
from ingest_helpers import ingest, page_data, signoff
from privacy_helpers import tm_data

from teachermodel import app, audition, simulate
from teachermodel.standards import load_standards

UNIT = "sl:unit/example-agent-loop@1"
DAY = date(2026, 10, 23)
NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
STD = load_standards()
ORDER = [d["id"] for d in STD["framework"]["domains"]]


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LOCALAPPDATA", "Z:/teachermodel-tests/no-localappdata")
    mp.setenv("APPDATA", "Z:/teachermodel-tests/no-appdata")
    s = tmp_path_factory.mktemp("audition-pages") / "store"
    try:
        simulate.simulate(s, weeks=1, end=DAY)
        yield s
    finally:
        mp.undo()


def clearers(store):
    """Registered instructors whose mailbox carries the clearer role: the observers a sender check will accept."""
    st = app.load_state(store)
    return sorted({i["uri"] for found in st.identities.values() for i in found
                   if "clearer" in i["roles"] and i["uri"] in st.registrations})


def opened(store, monkeypatch, name, observers):
    """An audition with `observers` assigned on DAY; the pool rule itself is common.observer_pool's."""
    monkeypatch.setattr(audition, "observer_pool", lambda _st, on: list(observers) + extra(store, observers))
    a = audition.open_audition(store, UNIT, "remote", "Steps 3-4: the stop condition", "Sim Candidate", DAY,
                               audition=name)
    audition.assign(store, a, list(observers), DAY)
    return a


def extra(store, observers):
    return [c for c in clearers(store) if c not in observers][:1]


def fields(scores, unseen=()):
    return {d: ({"not_observable": True, "note": f"slice did not show {d}"} if d in unseen
                else {"score": v, "note": f"saw {d}"}) for d, v in zip(ORDER, scores)}


def subject(a):
    return f"tm:audition/{a}"


def test_assigning_draws_one_page_per_observer_with_the_slice_and_not_the_candidate(store, monkeypatch):
    first, second = clearers(store)[:2]
    a = opened(store, monkeypatch, "a-page01", [first, second])
    for o in (first, second):
        path = store / "pages" / f"{app.page_stem(audition.STEP, subject(a), o)}.html"
        html = path.read_text(encoding="utf-8")
        assert "Sim Candidate" not in html  # the name stays in identities/auditions.yaml
        data = tm_data(path)
        assert (data["step"], data["subject_uri"], data["signer"], data["template"]) == (
            audition.STEP, subject(a), o, "approve")
        assert data["inputs"]["slice"] == "Steps 3-4: the stop condition" and data["inputs"]["observer"] == o
        assert [f["name"] for f in data["fields"]] == ORDER
        assert all(f["kind"] == "evidence_score" and f["not_observable"] for f in data["fields"])


def test_a_signed_form_comes_back_through_the_mailbox_and_never_enters_the_log(store, monkeypatch):
    first, second = clearers(store)[:2]
    a = opened(store, monkeypatch, "a-page02", [first, second])
    app.do_plan(store, now=NOW)
    before = (store / app.EVENT_LOG).read_text(encoding="utf-8")
    doc = signoff(store, audition.STEP, subject(a), first, fields([3, 2, 3, 3, 0], unseen=[ORDER[4]]), now=NOW)
    rep = ingest(store, [doc], now=NOW, name="aud-1")
    assert any(f"audition {a}: form from {first} recorded" in line for line in rep.lines)
    folder = store / audition.DIR / a
    form = yaml.safe_load((folder / f"score--{first.split('/')[-1]}.yaml").read_text(encoding="utf-8"))
    assert form[ORDER[0]] == {"score": 3, "note": f"saw {ORDER[0]}"}
    assert form[ORDER[4]] == {"score": None, "not_observable": True, "note": f"slice did not show {ORDER[4]}"}
    assert json.loads((folder / f"signoff--{first.split('/')[-1]}.json").read_text(encoding="utf-8"))["id"] == doc[0]["id"]
    after = (store / app.EVENT_LOG).read_text(encoding="utf-8")
    added = after[len(before):]
    assert a not in added and audition.STEP not in added  # at most the mailbox-read check, never the audition
    assert not (store / "pages" / f"{app.page_stem(audition.STEP, subject(a), first)}.html").exists()  # scored: gone
    assert (store / "pages" / f"{app.page_stem(audition.STEP, subject(a), second)}.html").exists()

    again = ingest(store, [doc], now=NOW, name="aud-2")  # the same message read again tomorrow
    assert not any(a in line for line in again.lines)
    assert audition.status(store, a)["scored"] == [first]


def _refused(store, a, doc, sender=None):
    stored, refused = audition.receive(store, [(doc, sender or doc_sender(store, doc))], NOW)
    assert stored == []
    return refused


def doc_sender(store, doc):
    from ingest_helpers import email_of

    return email_of(store, doc["signer"])


def test_a_form_that_does_not_fit_is_refused_once_and_kept_out_of_the_score(store, monkeypatch):
    first, second = clearers(store)[:2]
    a = opened(store, monkeypatch, "a-page03", [first, second])
    good = fields([3, 3, 3, 3, 3])

    def doc(fs=good, **kw):
        return signoff(store, audition.STEP, subject(a), first, fs, now=NOW, **kw)[0]

    cases = [
        (doc({**good, ORDER[0]: {"score": 3, "note": " "}}), None, f"{ORDER[0]}: an evidence note is required"),
        (doc({**good, ORDER[1]: {"score": 5, "note": "x"}}), None, f"{ORDER[1]}: a score 1 to 4, or not observable"),
        (doc({k: v for k, v in good.items() if k != ORDER[2]}), None, "the form needs exactly the domains"),
        (doc(decision="reject"), None, "an audition form is saved with the decision approve"),
        (doc(data={**page_data(store, audition.STEP, subject(a), first), "input_sha256": "0" * 64}), None, "stale"),
        (doc(), doc_sender(store, {"signer": second}), "sender is not the named signer"),
    ]
    for d, sender, reason in cases:
        refused = _refused(store, a, d, sender)
        assert len(refused) == 1 and reason in refused[0], (reason, refused)
    log = (store / audition.DIR / a / "refused.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == len(cases)
    _refused(store, a, cases[0][0])  # read again: the same refusal is not logged twice
    assert len((store / audition.DIR / a / "refused.jsonl").read_text(encoding="utf-8").splitlines()) == len(cases)
    assert audition.status(store, a)["scored"] == []

    outsider = extra(store, [first, second])[0]
    stranger = signoff(store, audition.STEP, subject(a), first, good, now=NOW)[0] | {"signer": outsider}
    assert "is not an observer of this audition" in _refused(store, a, stranger)[0]
    assert "no audition a-nothing" in _refused(store, a, doc() | {"subject_uri": "tm:audition/a-nothing"})[0]

    second_form = doc(good | {ORDER[0]: {"score": 1, "note": "changed my mind"}}, sid="f" * 16)
    accepted, _ = audition.receive(store, [(doc(), doc_sender(store, {"signer": first}))], NOW)
    assert len(accepted) == 1
    assert "has already scored" in _refused(store, a, second_form)[0]


def test_replacing_an_observer_moves_the_page(store, monkeypatch):
    first, second = clearers(store)[:2]
    joining = extra(store, [first, second])[0]
    a = opened(store, monkeypatch, "a-page04", [first, second])
    audition.replace(store, a, second, joining, "Withdrew: on leave that week.", DAY)
    pages = store / "pages"
    assert not (pages / f"{app.page_stem(audition.STEP, subject(a), second)}.html").exists()
    assert (pages / f"{app.page_stem(audition.STEP, subject(a), joining)}.html").exists()


def test_the_tick_draws_audition_pages_too(store, monkeypatch):
    first, second = clearers(store)[:2]
    a = opened(store, monkeypatch, "a-page05", [first, second])
    page = store / "pages" / f"{app.page_stem(audition.STEP, subject(a), first)}.html"
    page.unlink()
    rep = app.do_pages(store, now=NOW)
    assert page.exists() and "audition page" in rep.summary


# --- the evidence with a domain not observable -----------------------------------------------------------------------


def two(a, b):
    return {"tm:instructor/o1": dict(zip(ORDER, a)), "tm:instructor/o2": dict(zip(ORDER, b))}


def test_a_domain_either_observer_could_not_observe_is_kept_out_of_every_mean():
    doc = audition.evidence(two([3, 2, 3, 3, None], [3, 3, 3, 4, 2]), ORDER, STD["rules"])
    last = doc["domains"][4]
    assert last == {"domain": ORDER[4], "scores": {"tm:instructor/o1": None, "tm:instructor/o2": 2}, "average": None,
                    "within_one": None, "meets_clearance_bar": None, "not_observable_by": ["tm:instructor/o1"]}
    assert doc["overall_mean"] == round((3 + 2.5 + 3 + 3.5) / 4, 2) and doc["domains_scored"] == 4
    assert doc["not_observable"] == [ORDER[4]] and doc["agreement_within_one"] == 1.0
    assert audition.starting_plan(doc, ORDER) == [(ORDER[1], 2.5)]  # the unscored domain is never a seeded gap
    none = audition.evidence(two([None] * 5, [3] * 5), ORDER, STD["rules"])
    assert none["overall_mean"] is None and not none["overall_meets_clearance_bar"] and none["domains_scored"] == 0


def test_the_paper_route_takes_not_observable_and_needs_a_note_on_every_domain(store, monkeypatch):
    first, second = clearers(store)[:2]
    a = opened(store, monkeypatch, "a-page06", [first, second])
    with pytest.raises(audition.AuditionError, match="evidence note"):
        audition.score(store, a, first, {d: {"score": 3, "note": ""} for d in ORDER})
    audition.score(store, a, first, fields([3, 3, 3, 3, 0], unseen=[ORDER[4]]))
    audition.score(store, a, second, fields([3, 3, 3, 3, 3]))
    doc = audition.result(store, a)
    assert doc["not_observable"] == [ORDER[4]] and doc["domains_scored"] == 4
    page = (store / audition.DIR / a / "result.md").read_text(encoding="utf-8")
    assert "over 4 of 5 domains" in page and "not observable" in page
