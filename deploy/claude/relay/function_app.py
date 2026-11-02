"""Azure Functions binding for the relay (relay.py). Deployed by IT under the programme account (owner, 2026-10-30).

Environment (set in the Function App, never in this repository):
    ANTHROPIC_API_KEY                the programme workspace's key (or Workload Identity Federation variables)
    ANTHROPIC_WEBHOOK_SIGNING_KEY    the whsec_ secret of the webhook endpoint registered in the Console
    RELAY_KIT                        JSON: {"agents": {button: agent id}, "environment": env id}, from claude-lock.json
    RELAY_CARD_URL, RELAY_STORE_URL  the Power Automate HTTP triggers that post a card and write a record to the library
    RELAY_TABLE                      the Azure Table connection string for de-duplication and recorded answers
"""

from __future__ import annotations

import json
import os

import anthropic
import azure.functions as func
import requests
from azure.data.tables import TableClient

import relay

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
client = anthropic.Anthropic()
table = TableClient.from_connection_string(os.environ["RELAY_TABLE"], table_name="relay")


class AzureIO:
    def post_card(self, to, card):
        requests.post(os.environ["RELAY_CARD_URL"], json={"to": to, "card": card}, timeout=30).raise_for_status()

    def store(self, record):
        requests.post(os.environ["RELAY_STORE_URL"], json=record, timeout=30).raise_for_status()

    def seen(self, webhook_id):
        try:
            table.create_entity({"PartitionKey": "webhook", "RowKey": webhook_id})
            return False
        except Exception:  # already there: a retried delivery
            return True

    def remember(self, key, value=None):
        if value is not None:
            table.upsert_entity({"PartitionKey": "answer", "RowKey": key, "value": json.dumps(value)})
            return value
        try:
            return json.loads(table.get_entity("answer", key)["value"])
        except Exception:
            return None


@app.route(route="press", methods=["POST"])
def press(req: func.HttpRequest) -> func.HttpResponse:
    data = req.get_json()
    session_id = relay.start(client, relay.Press(**data), json.loads(os.environ["RELAY_KIT"]))
    return func.HttpResponse(json.dumps({"session_id": session_id}), mimetype="application/json")


@app.route(route="webhook", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)  # signed by Anthropic instead
def webhook(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse(relay.on_webhook(client, req.get_body().decode("utf-8"), dict(req.headers), AzureIO()))


@app.route(route="answer", methods=["POST"])
def answer(req: func.HttpRequest) -> func.HttpResponse:
    try:
        return func.HttpResponse(relay.on_answer(client, relay.Answer(**req.get_json()), AzureIO()))
    except PermissionError as exc:
        return func.HttpResponse(str(exc), status_code=403)
    except ValueError as exc:
        return func.HttpResponse(str(exc), status_code=409)
