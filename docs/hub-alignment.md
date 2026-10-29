# Alignment with the hub conventions

teachermodel is designed as a spoke of a larger training platform (the hub): it keeps its own roadmap and
integrates only through versioned contracts. The table maps each hub convention to what teachermodel does.

| Hub convention | teachermodel |
| --- | --- |
| `contracts/`: JSON Schema for every shared shape, semver | `contracts/*.schema.json` with `$id` `tm:contract/<name>@<major>`; superseded majors kept in `contracts/v<N>/` |
| Stable, meaningless IDs; URI form `sl:<kind>/<slug>` | Own entities `tm:<kind>/<slug>`; shared units (`sl:unit/<slug>@<version>`, 0008) and competencies keep `sl:` IDs from the registry |
| Files are the database; reference data versioned and reviewed | `standards/*.yaml`, schema-validated by `teachermodel validate` |
| Actuals: append-only JSONL `{id, at, kind, subject_uri, actor, payload, receipt_sha256}` | `src/teachermodel/events.py`, same shape; corrections are new events |
| Personal data only in `.cohort/`, outside git | Instructor personal data only in the private store (outside git, `TEACHERMODEL_PRIVATE_DIR`, decision 0006) |
| SQLite index emitted by the build for the console | Phase 3: index build from standards + events |
| Lifecycle status `draft/active/parked/retired` | `status` on every standards file |
| Decisions as MADR with `status` and `supersedes` | `docs/decisions/NNNN-*.md` |
| Sign-offs bind to input hashes | Event `receipt_sha256`; dry-run sign-off to carry unit + environment hash (phase 3) |
| Session lifecycle in `delivery/` | Staffing check contract (`contracts/staffing-check.schema.json`) consumed by delivery scheduling |
| Subscription-only, Windows host, `py` | No model API calls in the decision path; pure Python, Windows-safe paths |

## Contracts offered to the hub (candidates)

These shapes are generic enough for other spokes. They stay teachermodel's until the hub adopts them
(`tm:contract/<name>@1`); a change that breaks them is a new major with a decision record.

| Contract | What it is | Hub use |
| --- | --- | --- |
| `plan@1` | Read-only operations a driver must run (`site.library`, `mail.sent`, `mail.tagged`, `file.get`), each with a hash id; a plan is identified by `plan_sha256`, the hash of its creation stamp and ops | Any spoke that verifies facts in M365 through a driver |
| `receipt@1` | The driver's result per op, bound to one plan by `plan_sha256`; only `ok` is evidence, errors never satisfy a step | Same drivers; one ingest rule for every spoke |
| `signoff@1` | A decision returned from a generated page, bound to the exact inputs it showed (`input_sha256`) and the page template hash | Any approval that must name its signer and survive a changed input |
| `queue@1` | What is open now: step, workflow, subject, role, type, due, overdue, page; tm URIs and dates only, never a name | The console and the portfolio inbox read this to list work across spokes |

`queue@1` is the one the console should read first: it holds no personal data and
is written by `teachermodel next --json <path>`.

## Hub registry reads (planned)

- Units: read `sl:unit/...@version` from the registry; a clearance and a dry-run bind to one unit version (0008).
- Competencies: instructor competency domains stay local (`tm:`); they are not learner competencies
  and do not enter the ESCO crosswalk.
