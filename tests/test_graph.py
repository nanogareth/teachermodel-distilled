"""The Graph driver (graph.py): a read plan run against Microsoft Graph with an app-only token, the receipt it writes, and
`graph-read` / `daily` with TEACHERMODEL_M365_DRIVER=graph. No network: a fake transport serves Graph-shaped fixtures.
Fictional people only."""

import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from privacy_helpers import LEGAL, PROGRAMME, STEP_VERIFIED, due_ids, tm_data

from teachermodel import app, bridge, daily, graph
from teachermodel.standards import validate

T0 = datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc)
CFG = graph.Config("tenant-0", "client-0", "SECRET-CLIENT-SECRET", "contoso.sharepoint.com:/sites/training")
MAILBOX = "signoffs@example.com"
OWNER = "olive.owner@example.com"
G = graph.GRAPH


@pytest.fixture(autouse=True)
def _no_driver_env(monkeypatch):
    for k in (graph.ENV_DRIVER, graph.ENV_TENANT, graph.ENV_CLIENT_ID, graph.ENV_SECRET, graph.ENV_SITE):
        monkeypatch.delenv(k, raising=False)


class Fake:
    """Routes (method, path) to canned responses; records every request. A route value is (status, body)."""

    def __init__(self, routes=None, token_status=200):
        self.routes = dict(routes or {})
        self.token_status = token_status
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url.startswith(graph.LOGIN):
            if self.token_status != 200:
                return self.token_status, {"error": "invalid_client"}
            return 200, {"access_token": "tok-123", "token_type": "Bearer", "expires_in": 3599}
        assert headers.get("Authorization") == "Bearer tok-123"
        if url in self.routes:  # a full URL (a next page) wins over its path
            return self.routes[url]
        path = url.split("?", 1)[0]
        if path in self.routes:
            return self.routes[path]
        return 404, {"error": {"code": "itemNotFound"}}

    def urls(self):
        return [u for _, u, _, _ in self.calls]


def plan_of(*ops):
    built = [bridge._op(op, args, None, None) for op, args in ops]
    return {"schema": "tm:contract/plan@1", "created": "2026-10-26T08:00:00+00:00", "ops": built}


def tagged(since="2026-10-25"):
    return ("mail.tagged", {"tag": "tm-signoff", "since": since, "mailbox": MAILBOX})


def message(mid, subject, sender="lena@example.com", attachments=True, received="2026-10-26T08:40:00Z"):
    return {"id": mid, "subject": subject, "from": {"emailAddress": {"name": "Lena", "address": sender}},
            "receivedDateTime": received, "hasAttachments": attachments}


def file_att(name, text):
    return {"@odata.type": "#microsoft.graph.fileAttachment", "name": name,
            "contentBytes": base64.b64encode(text.encode("utf-8")).decode("ascii")}


MSGS = f"{G}/users/{MAILBOX}/messages"


def att_url(mid):
    return f"{G}/users/{MAILBOX}/messages/{mid}/attachments"


# --- configuration and token -----------------------------------------------------------------------------------------


def test_config_comes_from_the_environment_and_names_what_is_missing():
    with pytest.raises(graph.GraphError, match="TEACHERMODEL_GRAPH_TENANT.*TEACHERMODEL_GRAPH_CLIENT_SECRET"):
        graph.config_from_env({graph.ENV_CLIENT_ID: "c"})
    cfg = graph.config_from_env({graph.ENV_TENANT: "t", graph.ENV_CLIENT_ID: "c", graph.ENV_SECRET: "s"})
    assert cfg == graph.Config("t", "c", "s", None)


def test_the_token_is_a_client_credentials_grant_for_the_graph_default_scope():
    fake = Fake()
    assert graph.token(CFG, fake) == "tok-123"
    method, url, headers, body = fake.calls[0]
    form = urllib.parse.parse_qs(body.decode("ascii"))
    assert method == "POST" and url == f"{graph.LOGIN}/tenant-0/oauth2/v2.0/token"
    assert form == {"client_id": ["client-0"], "client_secret": ["SECRET-CLIENT-SECRET"],
                    "grant_type": ["client_credentials"], "scope": ["https://graph.microsoft.com/.default"]}


def test_no_token_stops_the_run_without_leaking_the_secret():
    with pytest.raises(graph.GraphError) as exc:
        graph.run_plan(plan_of(tagged()), cfg=CFG, owner=OWNER, transport=Fake(token_status=401))
    assert "401" in str(exc.value) and "SECRET" not in str(exc.value)


# --- mail.tagged ------------------------------------------------------------------------------------------------------


def test_mail_tagged_pages_to_the_end_and_keeps_only_json_file_attachments():
    page2 = f"{MSGS}?$skiptoken=abc"
    fake = Fake({
        MSGS: (200, {"value": [message("m1", "[tm-signoff aaaa]")], "@odata.nextLink": page2}),
        page2: (200, {"value": [message("m2", "Lunch?", attachments=False)]}),
        att_url("m1"): (200, {"value": [file_att("signoff.json", '{"a": 1}'), file_att("logo.png", "x"),
                                        {"@odata.type": "#microsoft.graph.itemAttachment", "name": "x.json"}]}),
    })
    receipt = graph.run_plan(plan_of(tagged()), cfg=CFG, owner=OWNER, transport=fake, now=T0)
    (r,) = receipt["results"]
    assert r["status"] == "ok"
    m1, m2 = r["data"]["messages"]
    assert m1 == {"sender": "lena@example.com", "subject": "[tm-signoff aaaa]", "received": "2026-10-26T08:40:00Z",
                  "attachments": [{"name": "signoff.json",
                                   "content_base64": base64.b64encode(b'{"a": 1}').decode("ascii")}]}
    assert m2["attachments"] == [] and m2["subject"] == "Lunch?"  # the CLI drops untagged subjects, not the driver
    first = urllib.parse.unquote(fake.urls()[1])
    assert "receivedDateTime ge 2026-10-25T00:00:00Z" in first and "$search" not in first
    assert not any("m2/attachments" in u for u in fake.urls())  # no attachment read for a message without any


def test_a_failed_page_makes_the_whole_op_an_error_not_a_short_ok():
    page2 = f"{MSGS}?$skiptoken=abc"
    fake = Fake({MSGS: (200, {"value": [message("m1", "[tm-signoff a]", attachments=False)], "@odata.nextLink": page2}),
                 page2: (503, None)})
    (r,) = graph.run_plan(plan_of(tagged()), cfg=CFG, owner=OWNER, transport=fake, now=T0)["results"]
    assert r == {"op_id": r["op_id"], "status": "error", "data": {}, "error": "graph: 503"}


def test_a_next_link_off_graph_is_refused():
    fake = Fake({MSGS: (200, {"value": [], "@odata.nextLink": "https://evil.example.com/next"})})
    (r,) = graph.run_plan(plan_of(tagged()), cfg=CFG, owner=OWNER, transport=fake, now=T0)["results"]
    assert r["status"] == "error" and len(fake.calls) == 2  # token, first page; the foreign link is never fetched


def test_a_since_with_an_offset_becomes_utc():
    fake = Fake({MSGS: (200, {"value": []})})
    graph.run_plan(plan_of(tagged("2026-10-25T09:00:00+01:00")), cfg=CFG, owner=OWNER, transport=fake, now=T0)
    assert "receivedDateTime ge 2026-10-25T08:00:00Z" in urllib.parse.unquote(fake.urls()[1])


# --- mail.sent and site.library -------------------------------------------------------------------------------------


def test_mail_sent_reads_the_owner_sent_items_with_recipients():
    sent = f"{G}/users/{OWNER}/mailFolders/sentitems/messages"
    fake = Fake({sent: (200, {"value": [{
        "subject": "[tm-notice 2026-11] Your notice", "from": {"emailAddress": {"address": OWNER}},
        "toRecipients": [{"emailAddress": {"address": "kim@example.com"}}, {"emailAddress": {}}],
        "sentDateTime": "2026-10-26T07:00:00Z"}]})})
    op = ("mail.sent", {"to": "kim@example.com", "tag": "[tm-notice 2026-11]", "since": "2026-10-20"})
    (r,) = graph.run_plan(plan_of(op), cfg=CFG, owner=OWNER, transport=fake, now=T0)["results"]
    assert r["status"] == "ok" and r["data"]["messages"] == [
        {"sender": OWNER, "to": ["kim@example.com"], "subject": "[tm-notice 2026-11] Your notice",
         "sentDateTime": "2026-10-26T07:00:00Z"}]


@pytest.mark.parametrize("drives, exists", [
    ([{"name": "Documents", "webUrl": "https://x/sites/training/Shared Documents"},
      {"name": "teachermodel-records", "webUrl": "https://x/sites/training/teachermodel-records"}], True),
    ([{"name": "Documents", "webUrl": "https://x/sites/training/Shared Documents"}], False),
])
def test_site_library_looks_for_a_drive_of_that_name_on_the_configured_site(drives, exists):
    site = f"{G}/sites/contoso.sharepoint.com:/sites/training"
    fake = Fake({site: (200, {"id": "contoso.sharepoint.com,1,2"}),
                 f"{G}/sites/contoso.sharepoint.com,1,2/drives": (200, {"value": drives})})
    op = ("site.library", {"library": "teachermodel-records", "name": "teachermodel records"})
    (r,) = graph.run_plan(plan_of(op), cfg=CFG, owner=OWNER, transport=fake, now=T0)["results"]
    assert r == {"op_id": r["op_id"], "status": "ok", "data": {"exists": exists}}


def test_site_library_without_a_configured_site_and_unsupported_ops_are_errors():
    cfg = graph.Config("t", "c", "s", None)
    ops = [("site.library", {"library": "x", "name": "x"}), ("file.get", {"path": "x"}), ("meeting.recording", {})]
    results = graph.run_plan(plan_of(*ops), cfg=cfg, owner=OWNER, transport=Fake(), now=T0)["results"]
    assert [r["status"] for r in results] == ["error", "error", "error"]


def test_the_receipt_fits_the_contract_and_names_the_plan():
    plan = plan_of(tagged())
    receipt = graph.run_plan(plan, cfg=CFG, owner=OWNER, transport=Fake({MSGS: (200, {"value": []})}), now=T0)
    assert validate(receipt, "receipt.schema.json") == []
    assert receipt["driver"] == "graph" and receipt["run_at"] == "2026-10-26T08:00:00Z"
    assert receipt["plan_sha256"] == bridge.plan_sha256(plan)
    assert "SECRET" not in json.dumps(receipt)


# --- graph-read on a store: a real sign-off through the Graph driver ------------------------------------------------


@pytest.fixture
def world(fictional_store, privacy_root):
    return fictional_store, privacy_root


def _signoff_routes(private, sid, sender=LEGAL):
    page = tm_data(private / "pages" / "base-profile-verified--teachermodel--legal-1.html")
    doc = {"schema": "tm:contract/signoff@1", "id": sid, "step": page["step"], "subject_uri": page["subject_uri"],
           "input_sha256": page["input_sha256"], "decision": "approve", "fields": {}, "signer": page["signer"],
           "signed_at": (T0 + timedelta(minutes=30)).isoformat(), "page_template_sha256": page["page_template_sha256"]}
    mailbox = app.load_state(private).settings["mailbox"]
    msgs = f"{G}/users/{mailbox}/messages"
    return {msgs: (200, {"value": [message("m1", f"[tm-signoff {sid}]", sender=sender)]}),
            f"{msgs}/m1/attachments": (200, {"value": [file_att("signoff.json", json.dumps(doc))]})}


def test_graph_read_writes_the_receipt_ingests_the_signoff_and_ticks(world):
    private, root = world
    app.do_tick(private, now=T0, root=root)
    fake = Fake(_signoff_routes(private, "9000000000000001"))
    now = T0 + timedelta(hours=1)
    rep = app.do_graph_read(private, cfg=CFG, transport=fake, now=now, tick=True, root=root)
    assert rep.ok and rep.summary == "graph-read: 1 op(s), 0 failed", rep.all_lines()
    assert any("1 signoff" in line and "0 rejected" in line for line in rep.lines), rep.lines
    assert (private / "receipts" / "20261026T090000Z.json").is_file()
    assert (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, T0.date())
    assert "SECRET" not in (private / "receipts" / "20261026T090000Z.json").read_text(encoding="utf-8")


def test_graph_read_needs_a_plan(tmp_path):
    with pytest.raises(app.AppError, match="no plan yet"):
        app.do_graph_read(tmp_path, cfg=CFG, transport=Fake())


# --- daily with TEACHERMODEL_M365_DRIVER=graph -------------------------------------------------------------------------


def test_daily_reads_through_graph_before_it_ticks_when_the_driver_is_graph(world, monkeypatch):
    private, root = world
    app.do_tick(private, now=T0, root=root)
    fake = Fake(_signoff_routes(private, "9000000000000002"))
    monkeypatch.setattr(graph, "urllib_transport", fake)
    monkeypatch.setenv(graph.ENV_DRIVER, "graph")
    for k, v in ((graph.ENV_TENANT, "t"), (graph.ENV_CLIENT_ID, "c"), (graph.ENV_SECRET, "SECRET-CLIENT-SECRET")):
        monkeypatch.setenv(k, v)
    rep = daily.daily(private, now=T0 + timedelta(hours=1), root=root)
    log = (private / daily.LOG).read_text(encoding="utf-8").splitlines()
    assert log[0].endswith("graph-read ok: graph-read: 1 op(s), 0 failed") and " tick ok: " in log[1]
    assert rep.ok and (STEP_VERIFIED, PROGRAMME) not in due_ids(private, root, T0.date())


def test_daily_logs_a_failed_graph_read_and_still_ticks(world, monkeypatch):
    private, root = world
    app.do_tick(private, now=T0, root=root)
    monkeypatch.setenv(graph.ENV_DRIVER, "graph")  # no tenant, client or secret configured
    rep = daily.daily(private, now=T0 + timedelta(hours=1), root=root)
    log = (private / daily.LOG).read_text(encoding="utf-8").splitlines()
    assert "graph-read FAILED" in log[0] and "TEACHERMODEL_GRAPH_TENANT" in log[0] and " tick ok: " in log[1]
    assert not rep.ok


def test_daily_does_not_touch_graph_with_the_connector_driver(world, monkeypatch):
    private, root = world
    app.do_tick(private, now=T0, root=root)
    monkeypatch.setattr(app, "do_graph_read", lambda *a, **k: pytest.fail("graph read without the graph driver"))
    daily.daily(private, now=T0 + timedelta(hours=1), root=root)
    assert "graph-read" not in (private / daily.LOG).read_text(encoding="utf-8")
