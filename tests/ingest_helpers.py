"""Helpers for tests that push sign-offs through the real mail round trip: a page's `tm-data` -> a sign-off document
-> a fixture receipt -> `app.do_ingest` (importable: pythonpath has tests/). Fictional people only."""

import json
from datetime import timedelta

from privacy_helpers import tm_data

from teachermodel import app
from teachermodel.signoff import input_sha256

FIXTURE_DRIVERS = ("connector", "graph", "fixture")


def page_data(private, step, subject, signer):
    """The tm-data of the generated page of `signer` for (step, subject); the page must have been written by a tick."""
    return tm_data(private / "pages" / f"{app.page_stem(step, subject, signer)}.html")


def email_of(private, uri):
    """A mailbox that reaches the identity `uri` (the first, in sorted order, when several do)."""
    found = sorted(e for e, entries in app.load_state(private).identities.items() if any(i["uri"] == uri for i in entries))
    assert found, f"no identity for {uri}"
    return found[0]


def signoff(private, step, subject, signer, fields, *, now, decision="approve", sid=None, sender=None, data=None):
    """(document, sender email) for a sign-off of the page of `signer`, signed half an hour after `now`. `data` replaces the
    page's tm-data when the test wants to sign stale or altered inputs."""
    data = data or page_data(private, step, subject, signer)
    sid = sid or input_sha256([step, subject, signer, decision, fields])[:16]
    doc = {
        "schema": "tm:contract/signoff@1", "id": sid, "step": data["step"], "subject_uri": data["subject_uri"],
        "input_sha256": data["input_sha256"], "decision": decision, "signer": data["signer"],
        "signed_at": (now + timedelta(minutes=30)).isoformat(timespec="seconds"),
        "page_template_sha256": data["page_template_sha256"], "fields": fields,
    }
    return doc, sender or email_of(private, signer)


def ingest(private, signoffs, *, now, name="r"):
    """One fixture receipt carrying `signoffs` ((document, sender) pairs) for the latest plan, ingested an hour and a half
    after `now` (the time the plan was made by a tick). Returns the report."""
    plan = json.loads((private / "plans" / "latest.json").read_text(encoding="utf-8"))
    (tagged,) = [o for o in plan["ops"] if o["op"] == "mail.tagged"]
    messages = [{"sender": sender, "subject": f"[tm-signoff {doc['id']}]",
                 "received": (now + timedelta(minutes=40)).isoformat(timespec="seconds"),
                 "attachments": [{"name": "signoff.json", "content": json.dumps(doc)}]} for doc, sender in signoffs]
    receipt = {
        "schema": "tm:contract/receipt@1",
        "plan_sha256": (private / "plans" / "latest.sha256").read_text(encoding="ascii").strip(),
        "driver": "fixture", "run_at": (now + timedelta(hours=1)).isoformat(timespec="seconds"),
        "results": [{"op_id": tagged["op_id"], "status": "ok", "data": {"messages": messages}}],
    }
    path = private / "receipts" / f"{name}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return app.do_ingest(private, path, now=now + timedelta(minutes=90), allowed_drivers=FIXTURE_DRIVERS)


def signoff_events(private, step=None, subject=None):
    return [e for e in app.read_events(private) if e["kind"] == "signoff"
            and (step is None or e["payload"]["step"] == step) and (subject is None or e["subject_uri"] == subject)]
