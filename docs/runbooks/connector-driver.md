# Connector driver runbook

The connector driver runs a read plan (`tm:contract/plan@1`) through the Microsoft 365 connector
and writes a receipt (`tm:contract/receipt@1`). Spec: `docs/specs/2026-10-24-workflow-automation-design.md` §6.
The project skill `tm-connector-driver` runs this procedure; this file is the reference.

## Prerequisite

Run `py -m pip install -e .` once in the repo, so the `teachermodel` command is on the PATH. The
skill ends by calling it.

## Rules

- Run every op in the plan, exactly as written. Never skip an op, add one, or judge a result.
- An op the connector cannot run is `status: error`. An empty search is `status: ok` with an empty
  list: the CLI decides what empty means.
- Report raw fields only (addresses, subjects, dates, attachment text). The CLI does all filtering.
- The receipt and plan live in the private store. Never paste their contents into chat.
- **Page every search to the end.** Every `outlook_email_search` and `sharepoint_*search` call uses
  `limit` 25 and follows every `nextOffset` or `nextCursor` it returns until none is left. A driver
  that stops early reports a partial list as complete, and the CLI would read a missing message as
  "not sent". If the pages cannot be exhausted (a call fails part-way, or a page token cannot be
  followed), the whole op is `status: error`, never a short `ok`.
- **Senders are SMTP addresses from the message body.** Take every `sender` from `read_resource` on
  the message, field `from.emailAddress.address`, never from the search hit: a hit can carry an
  Exchange distinguished name (`/O=EXCHANGELABS/...`) or a display name, and the CLI rejects
  anything that is not `local@domain`.
- **Attachment text is UTF-8.** `attachments[].content` is the attachment's text. If the connector
  returns the bytes as base64, put that string under `content_base64` instead and leave `content`
  out. Never decode, trim or reformat either one.
- **Timestamps carry an offset.** `run_at` is the UTC time the run began, written with a `Z`
  (`date -u +%Y-%m-%dT%H:%M:%SZ`). The CLI rejects a time with no offset instead of assuming UTC.

The `mail.sent` tag is `[tm-notice <variant>]` and differs per instructor: the base notice (`2026-11`) for an
instructor the base profile covers, the jurisdiction's variant (`2026-11-us-ca`) for any other. Search for the tag
exactly as the op gives it; a message with another variant's tag is not a hit.

## Connector scopes (checked 2026-10-24)

Read-only: Mail.Read, Mail.Read.Shared, Sites.Read.All, Files.Read.All, User.ReadBasic.All, plus
meeting recording and transcript reads. No write scope.

## Op mapping and probes

| `op` | Connector calls | `data` shape | Positive probe | Negative probe |
| --- | --- | --- | --- | --- |
| `mail.sent` | `outlook_email_search` with `recipient` = `args.to` and `query` = the tag text without brackets (no `folderName`, no `order`), paged to the end; then `read_resource` on each hit for `from.emailAddress.address` and `toRecipients` | `{messages: [{sender, to: [...], subject, sentDateTime}]}` | recipient plus a known subject word: hits returned | recipient plus `"[tm-notice zz-probe-negative-0]"`: no results |
| `mail.tagged` | see **Reading the sign-off mailbox** below | `{messages: [{sender, subject, received, attachments: [{name, content}]}]}` | message read returns `attachments[].uri` (`mail:///messages/<id>/attachments/<id>`) and `toRecipients` | same as mail.sent |
| `site.library` | `sharepoint_folder_search` with `name` = `args.name` exactly as given, paged to the end; exists when a hit's `webUrl` ends with `/` + `args.library` | `{exists: bool}` | `teachermodel pilot`: the root folder, `webUrl` ending `/teachermodel-pilot` | `zz teachermodel probe negative`: no results |
| `file.get` | unsupported | | `read_resource` returns file content only; search results carry no author | |
| `meeting.recording` | unsupported in increment 1 | | | |

### Reading the sign-off mailbox (`mail.tagged`)

`args` are `{tag, since, mailbox}`. `tag` is the bare search text `tm-signoff`; the CLI checks that
each subject contains `[tm-signoff`. `since` is a date the CLI chose (the last good read minus two
days); use it as given. `mailbox` is the shared sign-off mailbox from the settings.

1. Call `get_me` for the signed-in address.
2. If `args.mailbox` is that address: `outlook_email_search` with `query` = `args.tag` and
   `afterDateTime` = `args.since`, paged to the end.
3. If it is another mailbox (the usual case: a shared mailbox): `outlook_email_search` with
   `mailboxOwnerEmail` = `args.mailbox` and `afterDateTime` = `args.since` only, **no `query`**
   (search inside a shared mailbox may not index the bracketed tag), paged to the end. Report every
   message. The CLI drops the ones whose subject has no `[tm-signoff`.
4. `read_resource` on each message for `from.emailAddress.address`, `subject` and
   `attachments[].uri`; then `read_resource` on each `.json` attachment URI for its text
   (`content`, or `content_base64` as above). Skip attachments that do not end in `.json`.

Probe results, 2026-10-24:

- **`mail.sent`, positive:** a recipient search also returns mail sent *by* other people in the
  thread. The CLI therefore keeps a message only when its sender is the owner, the recipient is in
  `to`, the subject has the tag, and the date is in range (bridge, fix 5).
- **`mail.sent`, query results:** search hits come back with `recipients: null`. The driver must
  `read_resource` each hit to get `toRecipients`.
- **`file.get`:** the library return channel is disabled. The connector cannot report who created
  a file, so a sign-off saved in the library has no verifiable signer. Every role returns
  sign-offs by email until the Graph driver exists.
- **`site.library`:** probed against a folder, not a library root. Re-probe once IT has created the
  library. If folder search does not find a library root, switch to `sharepoint_search` with
  `folderName`.
- **`site.library`, pilot folder (2026-10-27):** `name` = `teachermodel-pilot` returned nothing. The search reads the
  hyphen as an operator. `name` = `teachermodel pilot` returned the root folder first, `webUrl`
  `.../Documents/teachermodel-pilot`, then its subfolders and some files (the search matches loosely, so the
  `webUrl` check decides). `name` = `teachermodel` returned 68 hits, none of them the root. The CLI now gives the
  search text as `args.name` (`bridge.library_search_name`), so the driver never transforms it. The negative probe
  `zz teachermodel probe negative` returned nothing.

## How far a sender can be trusted

The CLI trusts the address in `from.emailAddress.address`. For senders inside the Microsoft 365 tenant
that is the tenant's own authentication. For external senders (partner leads, partner instructors)
it is only as good as their domain's DMARC policy: a domain with no enforced DMARC (`p=none` or
no record) can be spoofed, and a forged sign-off from it would pass the sender check. Ask for
`p=quarantine` or `p=reject` on each partner domain before relying on its sign-offs.

## Still to verify with one owner-sent test message

1. **Bracketed tags:** whether `[tm-notice <version>]` and `[tm-signoff <id>]` are searchable. KQL may
   split the brackets. The driver searches the bare tag text, and the CLI checks the full tag in the
   subject.
2. **JSON attachments:** answered 2026-10-27: `read_resource` on a `.json` attachment URI returns plain
   UTF-8 text.
3. **Shared mailbox:** whether `mailboxOwnerEmail` plus `afterDateTime` lists the shared mailbox's
   messages, and that `from.emailAddress.address` is an SMTP address there.

Send yourself one email with subject `[tm-signoff probe]` and a small `.json` attachment, then run
the `mail.tagged` probe. Record the results here.

First pilot read, 2026-10-27 (the owner's own mailbox, three owner sign-offs sent by hand):

1. **Bracketed tags:** answered for the owner's own mailbox. `query` = `tm-signoff` found every
   `[tm-signoff <id>]` subject. Still open for a shared mailbox.
2. **JSON attachments:** still open. None of the messages had the sign-off file attached; the only attachments
   were inline signature images, skipped because they do not end in `.json`. The ingest stored nothing (1 check,
   0 rejected) and the steps stayed due. The page's mail link cannot attach a file; the owner must attach it by
   hand.
3. **Shared mailbox:** not tested; the pilot mailbox is the owner's own.

Owner checks, 2026-10-27 (the owner reports each done, no failure reported):

- **Negative `mail.tagged` probe:** done. A tagged search that should match nothing returned nothing.
- **`mail.sent` probe:** done, positive and negative.
- **Purview audit search** on the pilot folder: done (decision 0016's audit trail is searchable).
- **Generated `.eml` in Outlook:** done; see **Outlook draft check** below.

Still open: the shared-mailbox read (item 3), until a shared sign-off mailbox exists.

## Scheduled mailbox read (decided 2026-10-27, owner)

Until the Graph driver exists, a Claude desktop scheduled task `teachermodel-mailbox-read` runs the
`tm-connector-driver` skill on weekdays at 06:00 local time (the app adds a few minutes of dispatch delay). It
ingests and ticks, so the 07:30 Windows task `teachermodel daily` starts from fresh sign-offs. The desktop app must be
open; a run missed while it is closed runs on the next launch. The Graph driver (`graph-driver.md`) replaces this
task: set `TEACHERMODEL_M365_DRIVER=graph` and disable the desktop task.

Also seen: a message sent to yourself comes back twice (Sent Items and Inbox), with the same sign-off id; the
search hit's `hasAttachments` was `false` where `read_resource` showed inline images, so always read the
message. A message addressed elsewhere is still found through Sent Items, and the sender check decides.

Since then (2026-10-27):

- **Page:** for the mail channel, Save downloads an unsent draft (`.eml`, `X-Unsent: 1`) addressed to the sign-off
  mailbox, with the tagged subject and the sign-off file attached; the signer opens it and presses Send. The page
  also offers the file alone and a mail link, for a mail client that does not open the draft.
- **Ingest:** a tagged message with no `.json` attachment is rejected as `no sign-off file attached`, once per
  sign-off id, so `ingest` reports it instead of ignoring it.
- **Template hash:** the page template changed, so files saved from the earlier pages are rejected as
  `unknown page template`. Sign again from the regenerated pages.
- **Draft, checked 2026-10-27 (owner):** the three downloaded drafts opened in Outlook as new messages with the
  file attached and were sent unchanged. `read_resource` on each `.json` attachment URI returned the file as plain
  UTF-8 text (`content`), identical in the Sent Items and Inbox copies. Ingest stored all three sign-offs, flagged
  the three earlier messages without a file once each, and ignored the copies as duplicates.
- **`site.library`, pilot (2026-10-27):** with `args.name` = `teachermodel pilot` the root folder came first and
  `library-exists` passed.

## Outlook draft check

- **2026-10-26, owner:** `generated/it-request.eml` opened in Outlook, but the body showed the markdown source
  (`# Request: private store for teachermodel`). Since then every `.eml` carries the markdown as its plain-text
  part and a rendered HTML part (`setup._eml`), which Outlook shows instead.
- **2026-10-27, owner:** a newly generated `.eml` opened as an editable draft with headings, lists and the table
  of authorities rendered.

## Receipt

```json
{"schema": "tm:contract/receipt@1", "plan_sha256": "<from the plan>", "driver": "connector",
 "run_at": "<UTC time with Z, e.g. 2026-10-26T08:00:00Z>",
 "results": [{"op_id": "...", "status": "ok", "data": {}}]}
```

Save it as `receipts/<YYYYMMDDTHHMMSSZ>.json` (no colons: Windows rejects them in file names), then
run `teachermodel ingest <receipt path>`.
