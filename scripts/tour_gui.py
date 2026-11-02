"""A browser window to present the tour from (owner, 2026-10-28): `py scripts/tour.py --gui`.

A small server on this machine only (127.0.0.1) serves one page, `tour_gui.html`, beside this script. The page lists the
stops of `scripts/tour.py`, shows what to say, runs each stop's commands and shows the pages of the tour store in a
viewer. It can run only the tour's own commands, by stop and item number, never one sent to it, and it serves only files
inside the tour store. Requests must name this machine as their host, and a run must come from the page itself (a JSON
body from the same origin), so another site open in the browser cannot drive it.

The stops stay in `scripts/tour.py`, the single source: this file only presents them.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlparse

PAGE = Path(__file__).with_name("tour_gui.html")
MAX_BODY = 1_000_000  # far past any request the page sends; a longer body is read and thrown away
Runner = Callable[[Any, Path, dict[str, str]], tuple[list[str], int, str]]


def stops_payload(tour: ModuleType, store: Path, kept: dict[str, str]) -> list[dict[str, Any]]:
    """The stops as the page shows them: each command as it will run, each page by its path in the store (None when the
    store has no match, which the page shows as missing)."""
    out = []
    for n, stop in enumerate(tour.STOPS, 1):
        items = []
        for i, item in enumerate(stop.show):
            if isinstance(item, tour.Run):
                items.append({"kind": "run", "index": i, "expect": item.exit,
                              "command": "teachermodel " + " ".join(a.format_map(_Missing(kept)) for a in item.args)})
            else:
                found = sorted(store.glob(item.glob))
                items.append({"kind": "open", "index": i, "glob": item.glob,
                              "path": found[0].relative_to(store).as_posix() if found else None})
        out.append({"n": n, "title": stop.title, "audiences": list(stop.audiences), "say": list(stop.say), "show": items})
    return out


class _Missing(dict):
    """Leaves a placeholder no stop has kept yet as it is, instead of failing."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def verdict(output: str) -> str | None:
    """The staffing check's verdict, when the output is its JSON answer."""
    try:
        found = json.loads(output)
    except ValueError:
        return None
    return found.get("verdict") if isinstance(found, dict) and isinstance(found.get("verdict"), str) else None


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False  # closing never waits on a request thread (a browser can hold a connection open)


def make_server(tour: ModuleType, store: Path, *, port: int = 8765, audience: str | None = None,
                runner: Runner | None = None, kept: dict[str, str] | None = None) -> ThreadingHTTPServer:
    """The server, not yet serving (`port=0` picks a free one). `runner` defaults to `tour.execute`."""
    run = runner or tour.execute
    kept = dict(kept or {})
    lock = threading.Lock()  # one command at a time: runs share `kept` and the store

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
            pass

        def _allowed_host(self) -> bool:
            port_now = self.server.server_address[1]
            return self.headers.get("Host") in (f"127.0.0.1:{port_now}", f"localhost:{port_now}")

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, doc: Any) -> None:
            self._send(status, json.dumps(doc).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 - the base class's name
            if not self._allowed_host():
                return self._json(403, {"error": "this server answers only to this machine"})
            path = urlparse(self.path).path
            if path == "/":
                return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/stops":
                return self._json(200, {"audiences": tour.AUDIENCES, "audience": audience, "store": str(store),
                                        "stops": stops_payload(tour, store, kept)})
            if path.startswith("/store/"):
                target = (store / unquote(path[len("/store/"):])).resolve()
                if not target.is_relative_to(store.resolve()) or not target.is_file():
                    return self._json(404, {"error": "not in the tour store"})
                kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                if kind.startswith("text/"):
                    kind += "; charset=utf-8"
                return self._send(200, target.read_bytes(), kind)
            return self._json(404, {"error": "not found"})

        def _body(self) -> bytes:
            """The whole request body, read before any answer: closing a socket with unread data sends a reset, which can
            destroy a refusal on its way to the client. Empty when the length is nonsense or over MAX_BODY."""
            try:
                left = max(int(self.headers.get("Content-Length") or 0), 0)
            except ValueError:
                return b""
            over, kept = left > MAX_BODY, bytearray()
            while left:
                chunk = self.rfile.read(min(left, 65536))
                if not chunk:
                    break
                left -= len(chunk)
                if not over:
                    kept += chunk
            return bytes(kept)

        def do_POST(self) -> None:  # noqa: N802 - the base class's name
            raw = self._body()
            origin = self.headers.get("Origin")
            if not self._allowed_host() or (origin and urlparse(origin).netloc != self.headers.get("Host")):
                return self._json(403, {"error": "this server answers only to its own page"})
            if urlparse(self.path).path != "/api/run":
                return self._json(404, {"error": "not found"})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"error": "send JSON"})
            try:
                body = json.loads(raw or b"{}")
                stop = tour.STOPS[int(body["stop"]) - 1] if int(body["stop"]) >= 1 else None
                item = stop.show[int(body["index"])] if stop else None
            except (ValueError, KeyError, IndexError, TypeError):
                item = None
            if not isinstance(item, tour.Run):
                return self._json(400, {"error": "name a command of the tour by its stop and item"})
            with lock:
                args, status, output = run(item, store, kept)
            return self._json(200, {"command": "teachermodel " + " ".join(args), "exit": status, "expect": item.exit,
                                    "ok": status == item.exit, "output": output, "verdict": verdict(output)})

    return _Server(("127.0.0.1", port), Handler)


def serve(tour: ModuleType, store: Path, *, port: int = 8765, audience: str | None = None, open_browser: bool = True) -> int:
    print("Reading the tour store ...", flush=True)
    server = make_server(tour, store, port=port, audience=audience, kept=tour.collect_kept(store))
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Tour GUI at {url} (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
