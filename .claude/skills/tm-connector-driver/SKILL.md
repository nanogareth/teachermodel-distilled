---
name: tm-connector-driver
description: Run a teachermodel read plan through the Microsoft 365 connector and write its receipt. Use when the daily tick has written a plan, or when asked to "run the connector driver" for teachermodel.
---

# teachermodel connector driver

Reference: `docs/runbooks/connector-driver.md` (op mapping, data shapes, probes). Read it first.

Prerequisite: `py -m pip install -e .` has been run once, so `teachermodel` is on the PATH. If the
command is not found, say so and stop; do not install it yourself.

1. Load the plan: `$TEACHERMODEL_PRIVATE_DIR/plans/latest.json` (or the path given). Note
   `plan_sha256` from `plans/latest.sha256`.
2. For each op, in order, run exactly the connector calls the runbook maps it to. Do not skip,
   add, reorder by judgement, or interpret results. An unsupported op or a failed call is
   `status: error`. An empty search is `status: ok` with an empty list.
   - Every search uses `limit` 25 and follows every `nextOffset` or `nextCursor` until none is left.
     If you could not exhaust the pages, the op is `status: error`, not a short `ok`.
   - Take every `sender` from `read_resource` `from.emailAddress.address` (the SMTP address), never
     from the search hit.
   - Attachment text goes in `content` (UTF-8). If the connector returns base64, put it in
     `content_base64` instead.
   - For `mail.tagged`, follow "Reading the sign-off mailbox" in the runbook (shared mailbox: no query).
3. Take `run_at` from the shell: `date -u +%Y-%m-%dT%H:%M:%SZ`. Write
   `$TEACHERMODEL_PRIVATE_DIR/receipts/<YYYYMMDDTHHMMSSZ>.json` (the same time, no colons) per
   `tm:contract/receipt@1` with `driver: connector`.
4. Run `teachermodel ingest <receipt path>` and report its summary line only.
5. Run `teachermodel tick` and report its summary lines only (the new plan, pages and queue follow
   from what the ingest just applied).

Never print plan, receipt or message contents to chat: they hold names and email addresses. Never
quote message content, subjects or attachment text, not even in an error report.
Never write memory, notes or any file outside the private store from these runs; the only files you
create are receipts under `$TEACHERMODEL_PRIVATE_DIR/receipts/`.
Never send, draft, move or delete mail; this skill only reads.
