# Graph driver reference

`src/teachermodel/graph.py` runs a read plan (`tm:contract/plan@1`) against Microsoft Graph with an app-only token and
writes a receipt (`tm:contract/receipt@1`, driver `graph`). It follows the connector driver's rules
(`connector-driver.md`) with no model in the loop. It replaces the desktop task `teachermodel-mailbox-read` once the
tenant has the app (after the tenant move).

## What IT provides

One app registration in the tenant, admin-consented, with these application permissions:

| Permission | For | Scope it down with |
| --- | --- | --- |
| `Mail.Read` | `mail.tagged` (sign-off mailbox), `mail.sent` (owner's Sent Items) | an Exchange application access policy, or RBAC for Applications, limited to those two mailboxes |
| `Sites.Read.All` | `site.library` | `Sites.Selected` on the one site, if IT prefers |

IT hands over the tenant id, the client id and a client secret. The secret is a credential: it goes into the
environment of the account that runs the daily task, never into git or the private store.

## Configuration

| Variable | Value |
| --- | --- |
| `TEACHERMODEL_GRAPH_TENANT` | directory (tenant) id |
| `TEACHERMODEL_GRAPH_CLIENT_ID` | application (client) id |
| `TEACHERMODEL_GRAPH_CLIENT_SECRET` | client secret |
| `TEACHERMODEL_GRAPH_SITE` | the site that holds the library, as `<host>:/sites/<path>` |
| `TEACHERMODEL_M365_DRIVER` | `graph` makes `teachermodel daily` read the mailbox through Graph before it ticks |

`teachermodel graph-read` runs the latest plan once, ingests the receipt and ticks. `daily` logs a `graph-read` line
before its tick line; a failed read is logged as `FAILED` and the tick still runs.

## Op mapping

| `op` | Graph calls | Notes |
| --- | --- | --- |
| `mail.tagged` | `GET /users/{mailbox}/messages?$filter=receivedDateTime ge {since}`, then `GET .../messages/{id}/attachments` for messages with attachments | all folders, so Sent Items copies come too; no search on the tag (the CLI filters); only `fileAttachment` items named `*.json`, as `content_base64` |
| `mail.sent` | `GET /users/{owner}/mailFolders/sentitems/messages?$filter=sentDateTime ge {since}` | the owner is the store's programme-owner; the CLI keeps messages to `args.to` with `args.tag` |
| `site.library` | `GET /sites/{site}`, then `GET /sites/{id}/drives` | exists when a drive's name, or the end of its `webUrl`, is the last segment of `args.library` |
| `file.get`, `meeting.recording` | none | `error`, as with the connector, until the plan asks for them |

Every list follows `@odata.nextLink` to the end; a failed page, or a next link that leaves Graph, makes the op `error`.
The receipt's `error` field holds the HTTP status only.

## Not verified yet

The driver is tested against Graph-shaped fixtures (`tests/test_graph.py`), not a live tenant. On the first run with
the real app, compare one `graph-read` receipt with a connector receipt for the same plan, and record the result here.
