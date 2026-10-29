"""The Graph driver: runs a read plan (tm:contract/plan@1) against Microsoft Graph with an app-only token and writes the
receipt (tm:contract/receipt@1, driver `graph`). Spec: docs/specs/2026-10-24-workflow-automation-design.md section 6.

It follows the connector driver's rules (docs/runbooks/connector-driver.md) without a model in the loop:

- every op in the plan, in order; an op it cannot run is `status: error` (file.get and meeting.recording until the
  plan asks for them), an empty read is `ok` with an empty list;
- every list is paged to the end through `@odata.nextLink`; a failed page makes the whole op `error`, never a short ok;
- raw fields only (SMTP addresses from `from.emailAddress.address`, subjects, times, attachment bytes as base64); the CLI
  does all filtering (bridge.apply_receipt);
- driver error text never enters the receipt's `data`; the `error` field carries the HTTP status only.

Configuration comes from the environment, never from git or the private store (the secret is a credential):

    TEACHERMODEL_GRAPH_TENANT         directory (tenant) id
    TEACHERMODEL_GRAPH_CLIENT_ID      application (client) id of the admin-consented app
    TEACHERMODEL_GRAPH_CLIENT_SECRET  its client secret
    TEACHERMODEL_GRAPH_SITE           optional: the site that holds the library, as `<host>:/sites/<path>`;
                                      without it `site.library` is an error

The app needs the application permissions Mail.Read (scoped by an application access policy to the sign-off and owner
mailboxes) and Sites.Read.All. HTTP goes through `Transport`, so the tests run on fixtures and no network.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
ENV_TENANT = "TEACHERMODEL_GRAPH_TENANT"
ENV_CLIENT_ID = "TEACHERMODEL_GRAPH_CLIENT_ID"
ENV_SECRET = "TEACHERMODEL_GRAPH_CLIENT_SECRET"
ENV_SITE = "TEACHERMODEL_GRAPH_SITE"
ENV_DRIVER = "TEACHERMODEL_M365_DRIVER"  # connector (default) | graph: which driver the daily job uses
PAGE_SIZE = 50
MAX_PAGES = 200  # a runaway nextLink chain is an error, not an endless loop

# (method, url, headers, body) -> (HTTP status, parsed JSON body or None)
Transport = Callable[[str, str, Mapping[str, str], "bytes | None"], tuple[int, Any]]


class GraphError(Exception):
    """The driver cannot start (configuration or token); the message says what to fix and holds no secret."""


class _OpFailed(Exception):
    def __init__(self, status: int | str) -> None:
        super().__init__(str(status))
        self.status = status


@dataclass(frozen=True)
class Config:
    tenant: str
    client_id: str
    secret: str
    site: str | None = None


def config_from_env(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    missing = [k for k in (ENV_TENANT, ENV_CLIENT_ID, ENV_SECRET) if not env.get(k, "").strip()]
    if missing:
        raise GraphError(f"the Graph driver needs {', '.join(missing)} in the environment")
    site = env.get(ENV_SITE, "").strip() or None
    return Config(env[ENV_TENANT].strip(), env[ENV_CLIENT_ID].strip(), env[ENV_SECRET].strip(), site)


def urllib_transport(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> tuple[int, Any]:
    """The real transport: one HTTPS request, the JSON body parsed (None when empty or not JSON)."""
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - fixed https endpoints only
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, None
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeError):
        return status, None


def token(cfg: Config, transport: Transport) -> str:
    """An app-only access token (OAuth 2.0 client credentials, scope Graph `.default`)."""
    body = urllib.parse.urlencode({
        "client_id": cfg.client_id, "client_secret": cfg.secret, "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }).encode("ascii")
    url = f"{LOGIN}/{urllib.parse.quote(cfg.tenant, safe='')}/oauth2/v2.0/token"
    status, doc = transport("POST", url, {"Content-Type": "application/x-www-form-urlencoded"}, body)
    if status != 200 or not isinstance(doc, dict) or not isinstance(doc.get("access_token"), str):
        raise GraphError(f"no Graph token (HTTP {status}); check the tenant, client id, secret and admin consent")
    return doc["access_token"]


class _Client:
    def __init__(self, access_token: str, transport: Transport) -> None:
        self._headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        self._transport = transport

    def get(self, url: str) -> dict[str, Any]:
        status, doc = self._transport("GET", url, self._headers, None)
        if status != 200 or not isinstance(doc, dict):
            raise _OpFailed(status)
        return doc

    def pages(self, url: str) -> list[dict[str, Any]]:
        """Every item of a collection, following `@odata.nextLink` to the end."""
        items: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            doc = self.get(url)
            value = doc.get("value")
            if not isinstance(value, list):
                raise _OpFailed("no value")
            items += [v for v in value if isinstance(v, dict)]
            url = doc.get("@odata.nextLink")
            if not url:
                return items
            if not isinstance(url, str) or not url.startswith(GRAPH):
                raise _OpFailed("bad nextLink")
        raise _OpFailed("too many pages")


def _user(address: str) -> str:
    return f"{GRAPH}/users/{urllib.parse.quote(address, safe='@')}"


def _since(value: Any) -> str:
    """A Graph DateTimeOffset literal for a plan's `since` (a date, or a date-time with an offset)."""
    text = str(value).strip()
    if len(text) == 10:
        return f"{datetime.fromisoformat(text).date().isoformat()}T00:00:00Z"
    when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("since carries no offset")
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _query(**params: str) -> str:
    return urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="$,'():")


def _address(field: Any) -> str | None:
    if isinstance(field, dict) and isinstance(field.get("emailAddress"), dict):
        addr = field["emailAddress"].get("address")
        return addr if isinstance(addr, str) else None
    return None


def mail_tagged(client: _Client, args: Mapping[str, Any]) -> dict[str, Any]:
    """Every message in the sign-off mailbox received since `args.since` (all folders, so Sent Items too), with its
    `.json` attachments as base64. No search on the tag: the CLI keeps the subjects that carry it."""
    mailbox = _user(str(args["mailbox"]))
    url = (f"{mailbox}/messages?"
           + _query(**{"$filter": f"receivedDateTime ge {_since(args['since'])}",
                       "$select": "id,subject,from,receivedDateTime,hasAttachments", "$top": str(PAGE_SIZE)}))
    out = []
    for m in client.pages(url):
        attachments = []
        if m.get("hasAttachments") and isinstance(m.get("id"), str):
            att_url = f"{mailbox}/messages/{urllib.parse.quote(m['id'], safe='')}/attachments"
            for a in client.pages(att_url):
                name = a.get("name")
                if (a.get("@odata.type") == "#microsoft.graph.fileAttachment" and isinstance(name, str)
                        and name.lower().endswith(".json") and isinstance(a.get("contentBytes"), str)):
                    attachments.append({"name": name, "content_base64": a["contentBytes"]})
        out.append({"sender": _address(m.get("from")), "subject": m.get("subject"), "received": m.get("receivedDateTime"),
                    "attachments": attachments})
    return {"messages": out}


def mail_sent(client: _Client, args: Mapping[str, Any], owner: str) -> dict[str, Any]:
    """Every message in the owner's Sent Items since `args.since`; the CLI keeps those to `args.to` with `args.tag`."""
    url = (f"{_user(owner)}/mailFolders/sentitems/messages?"
           + _query(**{"$filter": f"sentDateTime ge {_since(args['since'])}",
                       "$select": "subject,from,toRecipients,sentDateTime", "$top": str(PAGE_SIZE)}))
    out = []
    for m in client.pages(url):
        to = [a for a in (_address(r) for r in m.get("toRecipients") or []) if a]
        out.append({"sender": _address(m.get("from")), "to": to, "subject": m.get("subject"),
                    "sentDateTime": m.get("sentDateTime")})
    return {"messages": out}


def site_library(client: _Client, args: Mapping[str, Any], site: str | None) -> dict[str, Any]:
    """Whether the configured site has a document library named as the last segment of `args.library`."""
    if not site:
        raise _OpFailed(f"no {ENV_SITE}")
    want = [seg for seg in str(args["library"]).split("/") if seg][-1].lower()
    site_doc = client.get(f"{GRAPH}/sites/{urllib.parse.quote(site, safe=':/')}?$select=id")
    if not isinstance(site_doc.get("id"), str):
        raise _OpFailed("no site id")
    drives = client.pages(f"{GRAPH}/sites/{urllib.parse.quote(site_doc['id'], safe=',')}/drives?$select=name,webUrl")
    exists = any(str(d.get("name", "")).lower() == want
                 or str(d.get("webUrl", "")).rstrip("/").lower().endswith("/" + want) for d in drives)
    return {"exists": exists}


def run_plan(plan: Mapping[str, Any], *, cfg: Config, owner: str, transport: Transport = urllib_transport,
             now: datetime | None = None) -> dict[str, Any]:
    """The receipt for `plan`. Raises GraphError when no token can be had (nothing is written then)."""
    from .bridge import plan_sha256

    run_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    client = _Client(token(cfg, transport), transport)
    results = []
    for op in plan["ops"]:
        oid, kind, args = op["op_id"], op["op"], op.get("args") or {}
        try:
            if kind == "mail.tagged":
                data = mail_tagged(client, args)
            elif kind == "mail.sent":
                data = mail_sent(client, args, owner)
            elif kind == "site.library":
                data = site_library(client, args, cfg.site)
            else:
                raise _OpFailed("unsupported op")
            results.append({"op_id": oid, "status": "ok", "data": data})
        except _OpFailed as exc:
            results.append({"op_id": oid, "status": "error", "data": {}, "error": f"graph: {exc.status}"})
        except (KeyError, ValueError, TypeError):
            results.append({"op_id": oid, "status": "error", "data": {}, "error": "graph: bad op args"})
    return {"schema": "tm:contract/receipt@1", "plan_sha256": plan_sha256(plan), "driver": "graph", "run_at": run_at,
            "results": results}
