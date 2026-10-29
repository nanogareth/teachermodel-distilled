import copy
from datetime import date, datetime, timezone

import pytest

from teachermodel import events, signoff

H = "a" * 64
PEOPLE = [
    {"person": "tm:person/head-1", "name": "Alex Example", "email": "Alex.Head@Example.com", "roles": ["head-of-training"]},
    {"person": "tm:person/mgr-1", "name": "Sam Example", "email": "sam.mgr@example.com", "roles": ["manager"]},
]
ROSTER = {
    "schema": "tm:contract/roster@2",
    "instructors": [{"instructor": "tm:instructor/eng-1", "identity": {"name": "Jo Example", "email": "jo.eng@example.com"}}],
}
IDS = signoff.identities(PEOPLE, ROSTER)


def make(**kw):
    doc = {
        "schema": "tm:contract/signoff@1",
        "id": "0123456789abcdef",
        "step": "tm:step/clearance-approve",
        "subject_uri": "tm:instructor/eng-1",
        "input_sha256": signoff.input_sha256({"x": 1}),
        "decision": "approve",
        "fields": {"note_key": "k1"},
        "signer": "tm:person/head-1",
        "signed_at": "2026-10-24T09:00:00+00:00",
        "page_template_sha256": H,
    }
    doc.update(kw)
    return doc


def run(doc=None, **kw):
    args = dict(
        current_input_sha256=signoff.input_sha256({"x": 1}),
        sender_email="alex.head@example.com",
        identities=IDS,
        step_role="head-of-training",
    )
    args.update(kw)
    return signoff.accept(doc if doc is not None else make(), **args)


def test_valid_accepted():
    r = run()
    assert r.accepted and not r.duplicate and r.reasons == []


def test_input_sha256_reuses_canonical():
    import hashlib

    obj = {"b": 1, "a": [1, 2]}
    assert signoff.input_sha256(obj) == hashlib.sha256(events.canonical(obj).encode("utf-8")).hexdigest()
    assert signoff.input_sha256({"a": 1, "b": 2}) == signoff.input_sha256({"b": 2, "a": 1})


def test_stale_hash_rejected():
    r = run(current_input_sha256=signoff.input_sha256({"x": 2}))
    assert not r.accepted
    assert len(r.reasons) == 1 and r.reasons[0].startswith("stale: ")


def test_sender_mismatch_rejected():
    r = run(sender_email="sam.mgr@example.com", step_role="manager")
    assert r.reasons == ["sender is not the named signer"]


def test_wrong_role_rejected():
    r = run(step_role="clearer")
    assert r.reasons == ["signer lacks role clearer"]


def test_duplicate_noop():
    r = run(seen_ids=frozenset({"0123456789abcdef"}))
    assert r.duplicate and not r.accepted and r.reasons == []


def test_duplicate_noop_even_when_invalid():
    r = run(make(decision="nope"), seen_ids={"0123456789abcdef"})
    assert r.duplicate and not r.accepted and r.reasons == []


def test_email_case_insensitive():
    assert run(sender_email="ALEX.HEAD@EXAMPLE.COM").accepted


def test_unknown_sender_rejected():
    r = run(sender_email="stranger@example.com")
    assert r.reasons == ["unknown sender"]


def test_schema_invalid_rejected():
    bad = make()
    del bad["signer"]
    r = run(bad)
    assert not r.accepted and r.reasons and all(x.startswith("schema: ") for x in r.reasons)
    assert r.reasons == ["schema: <root>: required"]


def test_expected_signer_enforced():
    # the instructor signs their own self-assessment
    doc = make(signer="tm:instructor/eng-1")
    ok = run(doc, sender_email="jo.eng@example.com", step_role="instructor", expected_signer="tm:instructor/eng-1")
    assert ok.accepted
    other = run(
        make(signer="tm:person/mgr-1"),
        sender_email="sam.mgr@example.com",
        step_role="manager",
        expected_signer="tm:person/other-mgr",
    )
    assert other.reasons == ["signer is not the expected tm:person/other-mgr"]


def test_identities_roster_instructor_role():
    assert IDS["jo.eng@example.com"] == [{"uri": "tm:instructor/eng-1", "roles": {"instructor"}}]
    assert IDS["alex.head@example.com"][0]["roles"] == {"head-of-training"}


def test_identities_without_roster():
    assert set(signoff.identities(PEOPLE, None)) == {"alex.head@example.com", "sam.mgr@example.com"}


def test_identities_same_email_in_people_and_roster_is_one_person_two_identities():
    dual = copy.deepcopy(ROSTER)
    dual["instructors"][0]["identity"]["email"] = "ALEX.HEAD@example.com"
    ids = signoff.identities(PEOPLE, dual)
    assert [e["uri"] for e in ids["alex.head@example.com"]] == ["tm:person/head-1", "tm:instructor/eng-1"]
    assert ids["alex.head@example.com"][1]["roles"] == {"instructor"}


def test_identities_two_roster_instructors_with_one_email_raise():
    dup = copy.deepcopy(ROSTER)
    dup["instructors"].append({"instructor": "tm:instructor/eng-2", "identity": {"name": "Ky Example", "email": "JO.ENG@example.com"}})
    with pytest.raises(ValueError, match="duplicate email"):
        signoff.identities(PEOPLE, dup)


def test_accept_picks_the_identity_named_by_the_signer():
    dual = copy.deepcopy(ROSTER)
    dual["instructors"][0]["identity"]["email"] = "ALEX.HEAD@example.com"
    ids = signoff.identities(PEOPLE, dual)
    as_head = run(make(), identities=ids)
    assert as_head.accepted
    as_instructor = run(make(signer="tm:instructor/eng-1"), identities=ids, step_role="instructor",
                        expected_signer="tm:instructor/eng-1")
    assert as_instructor.accepted
    # the sender holds neither identity named by the signer, or lacks the role under the named one
    assert run(make(signer="tm:person/mgr-1"), identities=ids, step_role="manager").reasons == [
        "sender is not the named signer"]
    assert run(make(signer="tm:instructor/eng-1"), identities=ids, step_role="head-of-training").reasons == [
        "signer lacks role head-of-training"]


def test_identities_duplicate_email_within_people_raises():
    rows = PEOPLE + [{"person": "tm:person/x", "name": "X", "email": "SAM.MGR@example.com", "roles": ["manager"]}]
    with pytest.raises(ValueError, match="duplicate email"):
        signoff.identities(rows, None)


def test_to_event_verifies():
    ev = signoff.to_event(make(), "alex.head@example.com")
    assert events.check_event(ev) == []
    assert ev["kind"] == "signoff" and ev["actor"] == "tm:person/head-1"
    assert ev["subject_uri"] == "tm:instructor/eng-1"
    assert ev["payload"] == {
        "step": "tm:step/clearance-approve",
        "decision": "approve",
        "fields_sha256": signoff.input_sha256({"id": "0123456789abcdef", "fields": {"note_key": "k1"}}),
        "input_sha256": signoff.input_sha256({"x": 1}),
        "signoff_id": "0123456789abcdef",
        "page_template_sha256": H,
        "signed_at": "2026-10-24T09:00:00+00:00",
    }
    assert "alex" not in str(ev).lower()  # no sender email or name in the event
    assert "fields" not in ev["payload"] and "k1" not in str(ev)  # free-text fields stay in the private store


# --- review fixes ---------------------------------------------------------------------------


def test_schema_reasons_carry_no_value_text():
    r = run(make(signer="Jane Doe <jane.doe@example.com>"))
    assert r.reasons == ["schema: signer: pattern"]
    assert "jane" not in str(r.reasons).lower()


@pytest.mark.parametrize(
    "kw",
    [
        {"subject_uri": "tm:nope"},
        {"subject_uri": "not-a-uri"},
        {"step": "tm:step/Bad Step"},
        {"step": "tm:step/"},
        {"step": "tm:step/a b"},
    ],
)
def test_schema_tightened_subject_and_step(kw):
    r = run(make(**kw))
    assert not r.accepted and r.reasons and r.reasons[0].startswith("schema: ")


def test_signed_at_must_parse():
    assert run(make(signed_at="2026-99-99T99:99")).reasons == ["signed_at is not a valid date-time"]
    assert run(make(signed_at="2026-10-24T09:00:00Z")).accepted


def test_non_str_id_and_sender_do_not_raise():
    r = run(make(id=["x"]))
    assert not r.accepted and not r.duplicate and r.reasons[0].startswith("schema: ")
    r = run(make(id=123))
    assert not r.accepted
    r = run(sender_email=None)
    assert not r.accepted and "unknown sender" in r.reasons
    r = run(sender_email=7)
    assert not r.accepted and "unknown sender" in r.reasons


STEP_INSTR = {"id": "tm:step/baseline-self-assessment", "role": "instructor"}
STEP_MGR = {"id": "tm:step/commitment-manager", "role": "manager"}
STEP_PL = {"id": "tm:step/commitment-partner-lead", "role": "partner-lead"}
STEP_OTHER = {"id": "tm:step/it-done", "role": "it"}
REG = {"type": "sme-engineer", "level": "shadow",
       "engagement": {"manager": "tm:person/mgr-1", "nominated_by": "tm:person/lead-9"}}


def test_expected_signer_for_roles():
    uri = "tm:instructor/eng-1"
    assert signoff.expected_signer_for(STEP_INSTR, uri, REG) == uri
    assert signoff.expected_signer_for(STEP_MGR, uri, REG) == "tm:person/mgr-1"
    assert signoff.expected_signer_for(STEP_PL, uri, REG) == "tm:person/lead-9"
    assert signoff.expected_signer_for(STEP_OTHER, uri, REG) is None


def test_expected_signer_for_missing_data_is_none():
    uri = "tm:instructor/eng-1"
    assert signoff.expected_signer_for(STEP_MGR, uri, None) is None
    assert signoff.expected_signer_for(STEP_MGR, uri, {"type": "x"}) is None
    assert signoff.expected_signer_for(STEP_MGR, uri, {"engagement": "oops"}) is None
    assert signoff.expected_signer_for(STEP_PL, uri, {"engagement": {"nominated_by": 5}}) is None
    assert signoff.expected_signer_for(STEP_MGR, uri, REG | {"engagement": {}}) is None


def test_subject_bound_roles_listed():
    assert signoff.SUBJECT_BOUND_ROLES == frozenset({"instructor", "manager", "partner-lead"})


# --- content rules on approving sign-offs ---------------------------------------------------------


def dpia(dpo="dpia-not-required", **kw):
    return make(step="tm:step/dpia-screening", fields={"dpo-decision": dpo}, **kw)


@pytest.mark.parametrize("decision", ["dpia-required", "needs-more-information", None, 7])
def test_approving_dpia_needs_not_required(decision):
    doc = dpia(decision)
    assert signoff.content_reasons(doc) == ["DPIA required or undecided"]
    assert signoff.content_reasons(make(step="tm:step/dpia-screening", fields={})) == ["DPIA required or undecided"]


def test_dpia_not_required_is_clean_and_non_approving_is_not_checked():
    assert signoff.content_reasons(dpia("dpia-not-required")) == []
    assert signoff.content_reasons(dpia("dpia-required", decision="changes")) == []


def test_record_counts_as_approving_for_content_rules():
    assert signoff.content_reasons(dpia("dpia-required", decision="record")) == ["DPIA required or undecided"]


BATCH_STEP = "tm:step/gap-list-approved"


@pytest.mark.parametrize("step", ["tm:step/gap-list-approved", "tm:step/lead-observed-level", "tm:step/retention-approved"])
@pytest.mark.parametrize("rows", [{"a": "approve", "b": "reject"}, {"a": "approve", "b": "unreviewed"}, {"a": 1},
                                  [], None, "approve"])
def test_approving_batch_needs_every_row_approved(step, rows):
    assert signoff.content_reasons(make(step=step, fields={"rows": rows})) == ["batch rows not all approved"]


def test_batch_missing_rows_is_rejected_but_empty_and_full_pass():
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={})) == ["batch rows not all approved"]
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {}}), set()) == []
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {"a": "approve", "b": "approve"}}), {"a", "b"}) == []


def test_batch_rows_must_match_the_page():
    # An empty or partial rows map must not approve a non-empty page; unknown rows (None) reject.
    want = ["batch rows do not match the rows the page showed"]
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {}}), {"a"}) == want
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {"a": "approve"}}), {"a", "b"}) == want
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {"a": "approve"}}), None) == want
    assert signoff.content_reasons(make(step=BATCH_STEP, fields={"rows": {"a": "reject"}}, decision="changes")) == []


def test_other_steps_have_no_content_rules():
    assert signoff.content_reasons(make()) == []
    assert signoff.content_reasons({"step": 5}) == []


def test_dpia_delta_counts_only_when_the_dpo_says_not_required():
    step = "tm:step/dpia-delta"
    assert signoff.content_reasons(make(step=step, fields={"dpo-decision": "dpia-not-required"})) == []
    for answer in ("dpia-required", "needs-more-information", None):
        assert signoff.content_reasons(make(step=step, fields={"dpo-decision": answer})) == [
            "DPIA required or undecided"], answer
    assert signoff.content_reasons(make(step=step, fields={})) == ["DPIA required or undecided"]
    assert signoff.content_reasons(make(step=step, fields={"dpo-decision": "dpia-required"}, decision="changes")) == []


# --- child-subject signers and the people-to-instructor mapping (decision 0012) ------------------------------------

OBSERVE = {"id": "tm:step/observe", "role": "clearer", "subject": "assignment", "type": "human", "signer": "attrs.observer"}
SELF = {"id": "tm:step/self-assessment", "role": "instructor", "subject": "assignment", "type": "human",
        "signer": "attrs.instructor"}
SCORE = {"id": "tm:step/calibration-score", "role": "instructor", "subject": "exercise", "type": "human",
         "signer": "attrs.observers"}
ASSIGNMENT = {"kind": "assignment", "observer": "tm:instructor/o-1", "instructor": "tm:instructor/i-1"}
EXERCISE = {"kind": "exercise", "observers": ["tm:instructor/o-1", "tm:instructor/o-2"]}


def test_allowed_signers_come_from_the_subjects_attrs():
    assert signoff.allowed_signers(OBSERVE, ASSIGNMENT) == {"tm:instructor/o-1"}
    assert signoff.allowed_signers(SELF, ASSIGNMENT) == {"tm:instructor/i-1"}
    assert signoff.allowed_signers(SCORE, EXERCISE) == {"tm:instructor/o-1", "tm:instructor/o-2"}


def test_allowed_signers_is_none_without_a_signer_and_empty_when_the_attrs_are_missing():
    assert signoff.allowed_signers({"role": "instructor"}, ASSIGNMENT) is None
    assert signoff.allowed_signers(OBSERVE, {"kind": "assignment"}) == set()
    assert signoff.allowed_signers(OBSERVE, None) == set()
    assert signoff.allowed_signers(SCORE, {"observers": [5, None, ""]}) == set()


def test_expected_signer_for_a_signer_step_is_the_one_named_signer():
    assert signoff.expected_signer_for(OBSERVE, "tm:assignment/x", None, ASSIGNMENT) == "tm:instructor/o-1"
    assert signoff.expected_signer_for(SELF, "tm:assignment/x", None, ASSIGNMENT) == "tm:instructor/i-1"
    assert signoff.expected_signer_for(SCORE, "tm:exercise/x", None, EXERCISE) is None  # several: allowed_signers
    assert signoff.expected_signer_for(SELF, "tm:assignment/x", None, None) is None  # never the subject URI itself


def test_accept_takes_one_of_several_expected_signers():
    ids = signoff.identities([], {"instructors": [
        {"instructor": f"tm:instructor/o-{n}", "identity": {"name": "X", "email": f"o{n}@example.com"}} for n in (1, 2, 3)]})
    doc = make(signer="tm:instructor/o-2", step="tm:step/calibration-score", subject_uri="tm:exercise/x")
    ok = run(doc, identities=ids, sender_email="o2@example.com", step_role="instructor",
             expected_signers=EXERCISE["observers"])
    assert ok.accepted, ok.reasons
    other = run(make(signer="tm:instructor/o-3"), identities=ids, sender_email="o3@example.com", step_role="instructor",
                expected_signers=EXERCISE["observers"])
    assert other.reasons == ["signer is not an expected signer of this subject"]


def test_roster_instructors_hold_clearer_only_while_in_the_clearers_set():
    roster = {"instructors": [{"instructor": "tm:instructor/o-1", "identity": {"name": "X", "email": "o1@example.com"}},
                              {"instructor": "tm:instructor/o-2", "identity": {"name": "Y", "email": "o2@example.com"}}]}
    ids = signoff.identities([], roster, clearers=["tm:instructor/o-1"])
    assert ids["o1@example.com"][0]["roles"] == {"instructor", "clearer"}
    assert ids["o2@example.com"][0]["roles"] == {"instructor"}
    assert signoff.identities([], roster)["o1@example.com"][0]["roles"] == {"instructor"}


def test_a_mapped_person_is_also_that_instructor_under_their_own_mailbox():
    people = PEOPLE + [{"person": "tm:person/obs-1", "name": "Ola", "email": "ola@example.com", "roles": ["clearer"],
                        "instructor": "tm:instructor/o-1"}]
    ids = signoff.identities(people, ROSTER, clearers=["tm:instructor/o-1"])  # clearer by level, not by the people list
    assert [(e["uri"], sorted(e["roles"])) for e in ids["ola@example.com"]] == [
        ("tm:person/obs-1", ["clearer"]), ("tm:instructor/o-1", ["clearer", "instructor"])]
    # as that instructor, the person can sign a clearer step and an instructor step
    doc = make(signer="tm:instructor/o-1", step="tm:step/observe", subject_uri="tm:assignment/x")
    assert run(doc, identities=ids, sender_email="ola@example.com", step_role="clearer",
               expected_signers={"tm:instructor/o-1"}).accepted
    assert run(doc, identities=ids, sender_email="ola@example.com", step_role="instructor").accepted


def test_the_mapping_alone_links_a_person_to_an_instructor():
    people = PEOPLE + [{"person": "tm:person/jo-eng", "name": "J", "email": "other@example.com", "roles": ["clearer"]}]
    ids = signoff.identities(people, ROSTER)  # a slug in common with tm:instructor/eng-1 would link them if it counted
    assert [e["uri"] for e in ids["other@example.com"]] == ["tm:person/jo-eng"]


def test_assignments_approved_is_a_batch_step():
    assert "tm:step/assignments-approved" in signoff.BATCH_STEPS


def test_a_mapped_persons_clearer_role_is_not_a_grant_by_itself():
    # integration review finding 5: the people list may name a person a clearer, but clearer status comes from the
    # instructor's level (a level_change or the registration), so the role alone grants nothing under either URI.
    people = PEOPLE + [{"person": "tm:person/obs-1", "name": "Ola", "email": "ola@example.com", "roles": ["clearer", "coach"],
                        "instructor": "tm:instructor/o-1"}]
    ids = signoff.identities(people, ROSTER)  # o-1 is not in the clearers set
    assert [(e["uri"], sorted(e["roles"])) for e in ids["ola@example.com"]] == [
        ("tm:person/obs-1", ["coach"]), ("tm:instructor/o-1", ["coach", "instructor"])]
    at_level = signoff.identities(people, ROSTER, clearers=["tm:instructor/o-1"])
    assert [(e["uri"], sorted(e["roles"])) for e in at_level["ola@example.com"]] == [
        ("tm:person/obs-1", ["clearer", "coach"]), ("tm:instructor/o-1", ["clearer", "coach", "instructor"])]


# --- when a sign-off was signed (integration review finding 1) ----------------------------------------------------

NOW = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


def test_signed_at_before_the_step_opened_is_rejected():
    r = run(make(signed_at="2026-10-23T23:59:00+00:00"), opened_on=date(2026, 10, 24), now=NOW)
    assert r.reasons == ["signed_at is before the step opened"]
    assert not r.accepted


def test_signed_at_on_the_day_the_step_opened_counts():
    assert run(make(signed_at="2026-10-24T00:00:00+00:00"), opened_on=date(2026, 10, 24), now=NOW).accepted
    # the day is the UTC day: an offset that puts the instant on the previous UTC day is before it
    assert run(make(signed_at="2026-10-24T01:00:00+02:00"), opened_on=date(2026, 10, 24), now=NOW).reasons == [
        "signed_at is before the step opened"]


def test_signed_at_more_than_a_day_after_now_is_rejected():
    ok = run(make(signed_at="2026-10-27T09:00:00+00:00"), now=NOW)  # exactly one day of clock skew
    assert ok.accepted
    r = run(make(signed_at="2026-10-27T09:00:01+00:00"), now=NOW)
    assert r.reasons == ["signed_at is in the future"]


def test_without_a_resolver_or_a_clock_only_the_other_bound_applies():
    assert run(make(signed_at="2001-01-01T00:00:00+00:00")).accepted  # the old call shape checks neither bound
    assert run(make(signed_at="2001-01-01T00:00:00+00:00"), now=NOW).accepted  # a past stamp with no opened_on
    assert run(make(signed_at="2099-01-01T00:00:00+00:00"), opened_on=date(2026, 10, 24)).accepted  # no clock


def test_a_naive_signed_at_counts_as_utc():
    assert run(make(signed_at="2026-10-24T09:00:00"), opened_on=date(2026, 10, 24), now=NOW).accepted
    assert run(make(signed_at="2026-10-23T09:00:00"), opened_on=date(2026, 10, 24), now=NOW).reasons == [
        "signed_at is before the step opened"]


# --- blindness: the logged hash of the fields is salted with the sign-off id (finding 11) -------------------------------


def test_fields_sha256_is_salted_with_the_signoff_id():
    a = signoff.to_event(make(id="a" * 16), "x@example.com")
    b = signoff.to_event(make(id="b" * 16), "x@example.com")
    assert a["payload"]["fields_sha256"] != b["payload"]["fields_sha256"]  # identical fields, different hashes
    assert a["payload"]["fields_sha256"] != signoff.input_sha256(make()["fields"])  # not a bare hash of the fields
    assert signoff.fields_sha256(make(id="a" * 16)) == a["payload"]["fields_sha256"]


def test_a_single_decision_step_is_decided_once_per_inputs_and_again_when_they_return():
    """Integration review finding 16: only the latest approving sign-off counts, so inputs A, B, A may be decided again."""
    from teachermodel.signoff import SINGLE_DECISION_STEPS, already_decided

    step, subject = "tm:step/levels-decided", "tm:programme/teachermodel"
    assert step in SINGLE_DECISION_STEPS and "tm:step/bench-decision" in SINGLE_DECISION_STEPS

    def signed(sha, decision="approve"):
        return {"kind": "signoff", "subject_uri": subject, "payload": {"step": step, "decision": decision,
                                                                       "input_sha256": sha}}

    assert not already_decided([], step, subject, "a")
    assert already_decided([signed("a")], step, subject, "a")
    assert not already_decided([signed("a"), signed("b")], step, subject, "a")  # A, B, then A again: open
    assert not already_decided([signed("a", "reject")], step, subject, "a")
    assert not already_decided([signed("a")], "tm:step/observe", subject, "a")  # not a single-decision step
