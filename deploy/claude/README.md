# Claude buttons: the deployment kit

Decision 0029. Owner's
choices (2026-10-30): Microsoft 365, Teams first, the Claude API directly, Opus 5.5 for every button, Claude may write
with the presser approving each call, enrolment through Workday Learning, the relay owned by the programme account
with IT.

Nothing in this repository calls the Claude API: the owner's development is subscription-only. Everything here is
generated or tested on fakes and generated data, and runs only in the deploying organisation's tenant.

| Path | What | Made by |
| --- | --- | --- |
| `kit/agents/<button>.md` | one Managed Agents agent per acting button (`ant apply` format): read tools `always_allow`, write tools `always_ask` | `teachermodel claude-kit` from `standards/chains.yaml` |
| `kit/environments/buttons.yaml` | limited networking, the declared MCP servers only | the same |
| `kit/drafting/<button>.json` | the Messages API request per drafting button: read-only toolsets, the draft schema as structured outputs accept it | the same |
| `kit/prompts/<button>.md` | every button's system prompt | the same |
| `kit/manifest.json` | file hashes, beta headers, connector URLs still to fill | the same |
| `relay/` | the Azure Function between Teams and the sessions: approval cards, tool confirmations, session records | by hand; `tests/test_relay.py` runs it on a fake client |
| `flows/flows.json` | the four Power Automate flows, as a specification | by hand |

The committed `kit/` is checked against `standards/chains.yaml` by `tests/test_claudekit.py`: change the chains,
regenerate the kit in the same commit.

## Setting it up in the tenant

Each step is either a command or manual with its reason.

1. **decision (IT):** the MCP URLs for Salesforce and Sana from Workday (the connector directory lists none; see
   `kit/manifest.json` `to_fill`).
2. **run:** `teachermodel claude-kit --out deploy/claude/kit --connector salesforce=<url> --connector workday=<url>`
3. **manual (IT, the tenant's Anthropic workspace):** `ant apply --dry-run kit/agents kit/environments` from
   `deploy/claude`, shown to the head of training; then `ant apply --yes kit/agents kit/environments` once they
   approve. Commit the `claude-lock.json` it writes; the relay's `RELAY_KIT` is built from it.
4. **manual (IT, the Anthropic Console only):** register the relay's `/webhook` URL as a webhook endpoint for
   `session.status_idled` and `session.status_terminated`; put its `whsec_` secret in the Function App.
5. **manual (IT, Azure):** deploy `relay/` as a Function App under the programme account with the settings listed in
   `relay/function_app.py`, and an Azure Table for de-duplication and answers.
6. **manual (IT, Power Automate):** build the four flows in `flows/flows.json` under the programme account.
7. **manual (each person, a consent only they can give):** sign in to each connector the buttons they see use; the
   flow stores the tokens in their own vault (acting buttons) and in Key Vault (drafting buttons).
8. **decision (head of training):** sign off each action kind after its shadow period of 20 approved sends
   (`standards/chains.yaml` `shadow_sends`); tickets, CRM tasks and enrolments are approved call by call always.

## To confirm at deployment

- The field names on `agent.mcp_tool_use` and `agent.mcp_tool_result` events (`relay.py` reads them through `_get`,
  which accepts the documented name and its alternatives).
- The Atlassian, Salesforce, Workday and Udemy tool names in `standards/chains.yaml`, which are as Claude's connector
  directory listed them on 2026-10-30; `mcp-client-2026-09-15` pins each server's tool list once a session has seen it.
