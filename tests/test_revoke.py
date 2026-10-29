"""Revoking a bound approval (decision 0019).

    teachermodel revoke-page --step <id> [--subject <uri>]   a page per holder of the step's role: the inputs of the
                                                              approval in force, a required reason, decision `revoke`
    the revoke sign-off, returned by mail                     accepted only for a revocable step whose approval is in
                                                              force; the step opens again until a new approval

Fictional people only.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from privacy_helpers import LEGAL, PROGRAMME, STEP_DPIA, STEP_ROPA_APPROVED, STEP_VERIFIED, due_ids, sign_step, tm_data

from teachermodel import app, cli, flows, privacy, signoff, workflow
from teachermodel.standards import load_standards

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
TODAY = T0.date()
VERIFY_PAGE = "base-profile-verified--teachermodel--legal-1.html"
REVOKE_PAGE = "revoke--" + VERIFY_PAGE
REASON = "SECRET-REASON the verification relied on a superseded statute"
REVOCABLE = {"tm:step/base-profile-verified", "tm:step/ropa-approved", "tm:step/dpia-screening",
             "tm:step/retention-approved", "tm:step/notice-approved", "tm:step/profile-verified", "tm:step/dpia-delta",
             "tm:step/variant-approved", "tm:step/gap-list-approved"}


@pytest.fixture
def world(fictional_store, privacy_root):
    return fictional_store, privacy_root


def tick(private, root, now):
    return app.do_tick(private, now=now, root=root)


def send(private, root, page_name, *, sid, now, decision="approve", fields=None, sender=LEGAL):
    """Return a sign-off of the page `page_name` through a fixture receipt for the latest plan, as the mailbox would."""
    page = tm_data(private / "pages" / page_name)
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
        "input_sha256": page["input_sha256"], "decision": decision, "fields": fields or {}, "signer": page["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(), "page_template_sha256": page["page_template_sha256"],
    }
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    msg = {"sender": sender, "subject": f"[tm-signoff {sid}]", "received": (now + timedelta(minutes=40)).isoformat(),
           "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]}
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": [msg]}}],
    }
    path = private / "receipts" / f"{sid}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return app.do_ingest(private, path, now=now + timedelta(minutes=90), allowed_drivers=("fixture",), root=root)


def rejections(private):
    return [r for e in app.read_events(private) if e["kind"] == "check" and e["payload"].get("result") == "rejected"
            for r in e["payload"]["reasons"]]


def verified(private, root):
    """tick, legal verifies the base profile through the mailbox; then a new tick, so the next receipt has a fresh plan."""
    tick(private, root, T0)
    rep = send(private, root, VERIFY_PAGE, sid="a000000000000001", now=T0)
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)
    tick(private, root, T0 + timedelta(hours=2))
    return T0 + timedelta(hours=2)


# --- which steps are revocable -----------------------------------------------------------------------------------


def test_the_privacy_and_setup_approvals_are_revocable_and_nothing_with_a_hook_is():
    defs = {s["id"]: s for wf in load_standards()["workflows"]["workflows"] for s in wf["steps"]}
    marked = {sid for sid, s in defs.items() if s["done_when"].get("revocable")}
    assert marked == REVOCABLE
    assert {sid for sid, s in defs.items() if app.revocable_step(s)} == REVOCABLE
    assert not marked & set(flows.SIGNOFF_HOOKS) and not marked & signoff.SINGLE_DECISION_STEPS


def test_a_marked_step_with_a_hook_is_still_not_revocable():
    step = {"id": "tm:step/clearer-decision-2", "done_when": {"kind": "signoff", "bind": "input", "revocable": True}}
    assert "tm:step/clearer-decision-2" in flows.SIGNOFF_HOOKS
    assert not app.revocable_step(step)


# --- the engine: the newest approve-or-revoke decides ------------------------------------------------------------


def _signed(decision, digest, at):
    return {"kind": "signoff", "subject_uri": PROGRAMME, "actor": "tm:person/legal-1", "at": at, "id": at,
            "payload": {"step": "tm:step/x", "decision": decision, "input_sha256": digest}}


STEP = {"id": "tm:step/x", "done_when": {"kind": "signoff", "match": {"step": "tm:step/x"}, "bind": "input",
                                         "revocable": True}}


def done(log, digest="h1"):
    return bool(workflow._completions(STEP, PROGRAMME, log, lambda step, uri: digest))


def test_a_revocation_after_the_approval_reopens_the_step_and_a_new_approval_closes_it():
    approve = _signed("approve", "h1", "2026-10-26T09:00:00+00:00")
    revoke = _signed("revoke", "h1", "2026-10-26T10:00:00+00:00")
    again = _signed("approve", "h1", "2026-10-26T11:00:00+00:00")
    assert done([approve])
    assert not done([approve, revoke])
    assert done([approve, revoke, again])
    assert done([approve, _signed("changes", "h1", "2026-10-26T10:00:00+00:00")])  # changes is not a revocation
    assert workflow.newest_decisive([approve, revoke]) is None and workflow.newest_decisive([]) is None


def test_privacy_approved_covers_honours_a_revocation(world):
    private, root = world
    tick(private, root, T0)
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T09:00:00+00:00")
    path, _ = privacy.base_profile(root)
    inputs = privacy.profile_inputs(path, root)
    assert privacy.base_verified(app.read_events(private), root)
    sign_step(private, root, STEP_VERIFIED, decision="revoke", at="2026-10-26T10:00:00+00:00")
    log = app.read_events(private)
    assert not privacy.base_verified(log, root) and not privacy.approved_covers(log, STEP_VERIFIED, inputs)
    assert (STEP_VERIFIED, PROGRAMME) in due_ids(private, root, TODAY)


def test_revoking_the_ropa_approval_takes_it_out_of_the_dpia_inputs_until_re_approved(world):
    private, root = world
    tick(private, root, T0)
    sign_step(private, root, STEP_VERIFIED, at="2026-10-26T09:00:00+00:00")
    sign_step(private, root, STEP_ROPA_APPROVED, at="2026-10-26T09:01:00+00:00")
    sign_step(private, root, STEP_DPIA, at="2026-10-26T09:02:00+00:00")
    approved_hash = privacy.ropa_approval_sha256(app.read_events(private))
    assert approved_hash is not None
    sign_step(private, root, STEP_ROPA_APPROVED, decision="revoke", at="2026-10-26T10:00:00+00:00")
    assert privacy.ropa_approval_sha256(app.read_events(private)) is None
    due = due_ids(private, root, TODAY)
    assert (STEP_ROPA_APPROVED, PROGRAMME) in due and (STEP_DPIA, PROGRAMME) not in due  # its need is open again
    sign_step(private, root, STEP_ROPA_APPROVED, at="2026-10-26T11:00:00+00:00")  # the same text, approved again
    assert privacy.ropa_approval_sha256(app.read_events(private)) == approved_hash
    assert (STEP_DPIA, PROGRAMME) not in due_ids(private, root, TODAY)  # screened against that same approval


# --- revoke-page ----------------------------------------------------------------------------------------------------


def test_revoke_page_writes_a_page_with_the_approval_inputs_a_reason_and_only_revoke(world):
    private, root = world
    verified(private, root)
    rep = app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    assert "1 page(s)" in rep.summary
    page = tm_data(private / "pages" / REVOKE_PAGE)
    approval = tm_data(private / "pages" / VERIFY_PAGE)
    assert page["template"] == "revoke" and page["step"] == STEP_VERIFIED
    assert page["input_sha256"] == approval["input_sha256"]
    assert [(f["name"], f["required"]) for f in page["fields"]] == [("reason", True)]
    html = (private / "pages" / REVOKE_PAGE).read_text(encoding="utf-8")
    assert '<option value="revoke">' in html and 'value="approve"' not in html


def test_revoke_page_refuses_a_step_that_is_not_revocable_or_has_no_approval_in_force(world):
    private, root = world
    tick(private, root, T0)
    with pytest.raises(app.AppError, match="nothing to revoke"):
        app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    with pytest.raises(app.AppError, match="not revocable"):
        app.do_revoke_page(private, step="tm:step/it-done", root=root)
    with pytest.raises(app.AppError, match="unknown step"):
        app.do_revoke_page(private, step="tm:step/no-such-step", root=root)


def test_the_revoke_page_command(world, capsys, monkeypatch):
    private, root = world
    verified(private, root)
    monkeypatch.setattr(app, "ROOT", root)
    real = app.do_revoke_page
    monkeypatch.setattr(app, "do_revoke_page", lambda p, **kw: real(p, root=root, **kw))
    assert cli.main(["revoke-page", "--private-dir", str(private), "--step", STEP_VERIFIED]) == 0
    out = capsys.readouterr().out
    assert REVOKE_PAGE in out and "revoke-page: 1 page(s)" in out
    assert cli.main(["revoke-page", "--private-dir", str(private), "--step", "tm:step/it-done"]) == 1
    assert "not revocable" in capsys.readouterr().err


# --- the revoke sign-off through the mailbox ------------------------------------------------------------------------


def test_a_revocation_through_the_mail_reopens_the_step_and_a_new_approval_closes_it(world):
    private, root = world
    now = verified(private, root)
    app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    rep = send(private, root, REVOKE_PAGE, sid="b000000000000001", now=now, decision="revoke", fields={"reason": REASON})
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, (rep.summary, rejections(private))
    assert (STEP_VERIFIED, PROGRAMME) in due_ids(private, root, TODAY)
    assert REASON not in (private / app.EVENT_LOG).read_text(encoding="utf-8")  # the reason stays in the private store
    assert REASON in (private / "signoffs" / "b000000000000001.json").read_text(encoding="utf-8")
    later = now + timedelta(hours=2)
    tick(private, root, later)
    rep = send(private, root, VERIFY_PAGE, sid="b000000000000002", now=later)  # the same inputs, approved again
    assert "1 signoff" in rep.summary and "0 rejected" in rep.summary, (rep.summary, rejections(private))
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)


def test_a_revocation_without_a_reason_is_rejected(world):
    private, root = world
    now = verified(private, root)
    app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    rep = send(private, root, REVOKE_PAGE, sid="c000000000000001", now=now, decision="revoke", fields={"reason": "  "})
    assert "1 rejected" in rep.summary
    assert any("reason" in r and "revoke" in r for r in rejections(private))
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)


def test_a_second_revocation_has_nothing_to_revoke(world):
    private, root = world
    now = verified(private, root)
    app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    send(private, root, REVOKE_PAGE, sid="d000000000000001", now=now, decision="revoke", fields={"reason": REASON})
    later = now + timedelta(hours=2)
    tick(private, root, later)
    rep = send(private, root, REVOKE_PAGE, sid="d000000000000002", now=later, decision="revoke",
               fields={"reason": REASON})
    assert "1 rejected" in rep.summary
    assert any(r.startswith("nothing to revoke") for r in rejections(private))


def test_a_revocation_of_an_open_step_is_rejected(world):
    private, root = world
    tick(private, root, T0)
    page = private / "pages" / VERIFY_PAGE  # no approval yet: sign the approval page's inputs with decision revoke
    assert page.is_file()
    rep = send(private, root, VERIFY_PAGE, sid="e000000000000001", now=T0, decision="revoke", fields={"reason": REASON})
    assert "1 rejected" in rep.summary
    assert any(r.startswith("nothing to revoke") for r in rejections(private))


def test_a_revocation_from_someone_without_the_role_is_rejected(world):
    private, root = world
    now = verified(private, root)
    app.do_revoke_page(private, step=STEP_VERIFIED, root=root)
    rep = send(private, root, REVOKE_PAGE, sid="f000000000000001", now=now, decision="revoke",
               fields={"reason": REASON}, sender="dana.dpo@example.com")
    assert "1 rejected" in rep.summary
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, TODAY)


def test_the_revoke_decision_fits_the_signoff_contract():
    from teachermodel.standards import load_schema

    assert "revoke" in load_schema("signoff.schema.json")["properties"]["decision"]["enum"]
