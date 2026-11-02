"""The tour GUI's server (scripts/tour_gui.py): what it serves and what it refuses. A fake store and a fake runner stand in
for the 26-week tour store; the page itself is checked in the browser pane, not here."""

import http.client
import importlib.util
import json
import sys
import threading
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def modules():
    return _load("tour"), _load("tour_gui")


@pytest.fixture
def server(modules, tmp_path):
    tour, gui = modules
    store = tmp_path / "store"
    (store / "views").mkdir(parents=True)
    (store / "views" / "clearance-matrix.html").write_text("<p>matrix</p>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    calls = []

    def runner(item, where, kept):
        calls.append((item.args, where))
        return list(item.args), item.exit, '{"verdict": "ok", "reasons": []}' if item.args[0] == "staffing-check" else "fine"

    srv = gui.make_server(tour, store, port=0, runner=runner, kept={"partner_clearance": "tm:clearance/abc"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, calls, tour
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, headers=None):
    port = srv.server_address[1]
    con = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    hdrs = {"Host": f"127.0.0.1:{port}", **(headers or {})}
    payload = json.dumps(body).encode() if body is not None else None
    if payload is not None:
        hdrs.setdefault("Content-Type", "application/json")
    con.request(method, path, body=payload, headers=hdrs)
    res = con.getresponse()
    return res.status, res.read()


def test_the_page_and_the_stops(server):
    srv, _calls, tour = server
    status, page = request(srv, "GET", "/")
    assert status == 200 and b"teachermodel tour" in page
    status, body = request(srv, "GET", "/api/stops")
    doc = json.loads(body)
    assert status == 200 and len(doc["stops"]) == len(tour.STOPS)
    shown = {i["path"] for s in doc["stops"] for i in s["show"] if i["kind"] == "open"}
    assert "views/clearance-matrix.html" in shown and None in shown  # a page the fake store lacks shows as missing
    history = next(i for s in doc["stops"] for i in s["show"] if i["kind"] == "run" and "history" in i["command"])
    assert history["command"].endswith("tm:clearance/abc")  # a kept value is filled in


def test_a_store_file_is_served_and_nothing_outside_it(server):
    srv, _calls, _tour = server
    assert request(srv, "GET", "/store/views/clearance-matrix.html") == (200, b"<p>matrix</p>")
    for path in ("/store/../secret.txt", "/store/%2e%2e/secret.txt", "/store/views/none.html"):
        assert request(srv, "GET", path)[0] == 404, path


def test_a_run_is_one_of_the_tours_own_commands(server):
    srv, calls, tour = server
    stop = next(n for n, s in enumerate(tour.STOPS, 1) if any(isinstance(i, tour.Run) for i in s.show))
    index = next(i for i, item in enumerate(tour.STOPS[stop - 1].show) if isinstance(item, tour.Run))
    status, body = request(srv, "POST", "/api/run", {"stop": stop, "index": index})
    doc = json.loads(body)
    assert status == 200 and doc["ok"] and len(calls) == 1
    open_item = next((n, i) for n, s in enumerate(tour.STOPS, 1) for i, item in enumerate(s.show)
                     if isinstance(item, tour.Open))
    for bad in ({"stop": 0, "index": 0}, {"stop": 99, "index": 0}, {"stop": open_item[0], "index": open_item[1]},
                {"command": "gates"}, {"stop": "x", "index": 0}):
        assert request(srv, "POST", "/api/run", bad)[0] == 400, bad
    assert len(calls) == 1


def test_the_staffing_verdict_is_read_from_the_output(server):
    srv, _calls, tour = server
    stop = next(n for n, s in enumerate(tour.STOPS, 1)
                if any(isinstance(i, tour.Run) and i.args[0] == "staffing-check" for i in s.show))
    doc = json.loads(request(srv, "POST", "/api/run", {"stop": stop, "index": 0})[1])
    assert doc["verdict"] == "ok"


@pytest.mark.parametrize("method, path, headers", [
    ("GET", "/", {"Host": "evil.example:80"}),
    ("POST", "/api/run", {"Origin": "http://evil.example"}),
    ("POST", "/api/run", {"Content-Type": "text/plain"}),
])
def test_another_host_another_origin_or_a_form_post_is_refused(server, method, path, headers):
    srv, calls, _tour = server
    status, _ = request(srv, method, path, {"stop": 3, "index": 0} if method == "POST" else None, headers)
    assert status in (403, 415) and calls == []


def test_a_refusal_reaches_the_client_even_with_a_body_it_never_wanted(server):
    """A refusal used to leave the body unread: closing a socket with unread data resets it, and the reset can destroy the
    response in flight. A large body lost about one answer in four, so forty in a row do not pass by luck."""
    srv, calls, _tour = server
    big = {"stop": 3, "index": 0, "pad": "x" * 300_000}
    for _ in range(40):
        assert request(srv, "POST", "/api/run", big, {"Content-Type": "text/plain"})[0] == 415
        assert request(srv, "POST", "/api/run", big, {"Origin": "http://evil.example"})[0] == 403
        assert request(srv, "POST", "/elsewhere", big)[0] == 404
    assert calls == []


@pytest.mark.parametrize("length", ["-1", "not-a-number"])
def test_a_nonsense_content_length_is_answered_at_once(server, length):
    srv, calls, _tour = server
    status, _ = request(srv, "POST", "/api/run", None, {"Content-Type": "application/json", "Content-Length": length})
    assert status == 400 and calls == []


def test_a_body_over_the_limit_is_not_read_and_runs_nothing(server, modules):
    srv, calls, _tour = server
    _, gui = modules
    status, _ = request(srv, "POST", "/api/run", {"stop": 3, "index": 0, "pad": "x" * (gui.MAX_BODY + 1)})
    assert status == 400 and calls == []


def test_the_server_listens_on_this_machine_only(server):
    srv, _calls, _tour = server
    assert srv.server_address[0] == "127.0.0.1"
