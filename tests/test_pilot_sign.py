"""`teachermodel pilot-sign` (decision 0016; owner, 2026-10-26): generated signers in a pilot store sign through a
pilot-only path, since no mail can come from an example.com address. Fictional owner only."""

import json
from datetime import date, datetime, timedelta, timezone

import pytest
import yaml
from ingest_helpers import signoff, signoff_events
from privacy_helpers import tm_data
from test_roster_gate import seed_all

from teachermodel import app, cli, pilot
from teachermodel.flows.calibration import open_exercise

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
OWNER = {"owner_name": "Olive Owner", "owner_email": "olive.owner@company.ie"}
CLEARERS = ["v6k2r", "m8t4w", "h3q9n"]


def _answer(f):
    kind = f["kind"]
    if kind == "evidence_score":
        return {"score": 3, "note": f"Generated evidence for {f['name']}."}
    if kind == "checklist":
        return {i["id"]: {"result": "pass", "note": ""} for i in f["items"]}
    if not f.get("required"):
        return None
    return {"enum": (f.get("options") or [None])[0], "score": 3, "bool": True, "date": date(2026, 10, 26).isoformat(),
            "number": f.get("min", 1)}.get(kind, f"generated {f['name']}")


def _fields(data):
    return {f["name"]: v for f in data["fields"] if (v := _answer(f)) is not None}


@pytest.fixture
def store(tmp_path, privacy_root):
    """A pilot store with the generated roster imported, the clearers in a calibration exercise, and a tick done."""
    s = tmp_path / "pilot"
    pilot.init_pilot(s, **OWNER, set_env=False, root=privacy_root)
    seed_all(s, privacy_root)
    app.do_import_roster(s, s / "inputs" / "roster.yaml", now=T0, root=privacy_root)
    open_exercise(s, unit="sl:unit/example-agent-loop@1", recording_ref="recordings/pilot-001.mp4",
                  observers=CLEARERS, reference=s / "inputs" / "calibration-reference.yaml", now=T0, root=privacy_root)
    app.do_tick(s, now=T1, root=privacy_root)
    return s


def _page_of(store, signer):
    for path in sorted((store / "pages").glob("*.html")):
        data = tm_data(path)
        if data["signer"] == signer:
            return data
    raise AssertionError(f"no page for {signer}")


def _signed_file(store, data, tmp_path, name="signoff.json"):
    doc, _ = signoff(store, data["step"], data["subject_uri"], data["signer"], _fields(data), now=T1, data=data)
    path = tmp_path / name
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path, doc


def test_a_generated_clearer_signs_through_the_pilot_path(store, privacy_root, tmp_path):
    data = _page_of(store, "tm:instructor/v6k2r")
    path, doc = _signed_file(store, data, tmp_path)
    reads_before = [e for e in app.read_events(store) if e["payload"].get("result") == app.MAILBOX_READ]
    rep = pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=1), root=privacy_root)
    assert rep.ok, rep.all_lines()
    assert [e["payload"]["signoff_id"] for e in signoff_events(store, data["step"], data["subject_uri"])] == [doc["id"]]
    # The real mailbox was not read: the connector's next search must not start after it.
    reads_after = [e for e in app.read_events(store) if e["payload"].get("result") == app.MAILBOX_READ]
    assert reads_after == reads_before
    # Signing the same file again adds nothing.
    again = pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=2), root=privacy_root)
    assert len(signoff_events(store, data["step"], data["subject_uri"])) == 1 and "0 event(s)" in again.summary


def _draft(path, attachments):
    """An unsent draft shaped like the page's Save download: tagged subject, X-Unsent, the files attached."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["To"], msg["Subject"], msg["X-Unsent"] = "olive.owner@company.ie", "[tm-signoff x]", "1"
    msg.set_content("The sign-off file is attached. Send this message unchanged.")
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="json", filename=name)
    path.write_bytes(bytes(msg))
    return path


def test_a_generated_clearer_signs_with_the_draft_the_page_saves(store, privacy_root, tmp_path):
    # owner, 2026-10-27: generated signers use the same Save button as everyone else
    data = _page_of(store, "tm:instructor/v6k2r")
    path, doc = _signed_file(store, data, tmp_path)
    eml = _draft(tmp_path / "signoff.eml", [(path.name, path.read_bytes())])
    rep = pilot.pilot_sign(store, [eml], now=T1 + timedelta(hours=1), root=privacy_root)
    assert rep.ok, rep.all_lines()
    assert [e["payload"]["signoff_id"] for e in signoff_events(store, data["step"], data["subject_uri"])] == [doc["id"]]
    again = pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=2), root=privacy_root)  # the same file alone
    assert "0 event(s)" in again.summary


@pytest.mark.parametrize("files", [[], [("a.json", b"{}"), ("b.json", b"{}")]])
def test_a_draft_without_exactly_one_signoff_file_is_refused(store, privacy_root, tmp_path, files):
    eml = _draft(tmp_path / "d.eml", files)
    with pytest.raises(pilot.PilotError, match="exactly one .json"):
        pilot.pilot_sign(store, [eml], now=T1, root=privacy_root)
    assert not list((store / "receipts").glob("pilot-*.json"))


def test_ingest_never_accepts_a_pilot_receipt(store, privacy_root, tmp_path):
    path, _ = _signed_file(store, _page_of(store, "tm:instructor/m8t4w"), tmp_path)
    pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=1), root=privacy_root)
    receipt = next((store / "receipts").glob("pilot-*.json"))
    assert json.loads(receipt.read_text(encoding="utf-8"))["driver"] == "pilot"
    before = len(app.read_events(store))
    rep = app.do_ingest(store, receipt, now=T1 + timedelta(hours=1), root=privacy_root)
    assert not rep.ok and len(app.read_events(store)) == before


def test_a_real_persons_sign_off_is_refused(store, privacy_root, tmp_path):
    data = _page_of(store, pilot.OWNER)
    path, _ = _signed_file(store, data, tmp_path)
    with pytest.raises(pilot.PilotError, match="not a generated signer"):
        pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=1), root=privacy_root)
    assert not list((store / "receipts").glob("pilot-*.json"))


def test_a_store_that_is_not_a_pilot_refuses(store, privacy_root, tmp_path):
    path, _ = _signed_file(store, _page_of(store, "tm:instructor/h3q9n"), tmp_path)
    settings = store / "settings.yaml"
    doc = yaml.safe_load(settings.read_text(encoding="utf-8"))
    settings.write_text(yaml.safe_dump({k: v for k, v in doc.items() if k != "pilot"}), encoding="utf-8")
    with pytest.raises(pilot.PilotError, match="only in a pilot store"):
        pilot.pilot_sign(store, [path], now=T1 + timedelta(hours=1), root=privacy_root)


def test_a_file_that_is_not_a_sign_off_is_refused(store, privacy_root, tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"schema": "tm:contract/receipt@1"}', encoding="utf-8")
    with pytest.raises(pilot.PilotError, match="not a sign-off file"):
        pilot.pilot_sign(store, [path], now=T1, root=privacy_root)


def test_the_cli_refuses_outside_a_pilot_store(fictional_store, tmp_path, capsys):
    path = tmp_path / "s.json"
    path.write_text("{}", encoding="utf-8")
    assert cli.main(["pilot-sign", "--private-dir", str(fictional_store), str(path)]) == 1
    assert "only in a pilot store" in capsys.readouterr().err
