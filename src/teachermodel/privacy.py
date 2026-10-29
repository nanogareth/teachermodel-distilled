"""Privacy data: jurisdiction profiles, purposes and the retention table (decisions 0009 and 0010).

Pure and deterministic like rules.py: it reads the repo data files, hashes them and compares; no model, no
network. Spec: docs/specs/2026-10-24-privacy-jurisdictions-design.md sections 3, 4 and 7.

A profile counts as verified only while an approving sign-off of its verification step covers the exact bytes of
the file (`done_when.bind: input`, decision 0009). `base_verified` mirrors that rule for code that needs the
answer without going through the engine (the retention page, the notice).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from . import notice, signoff
from .pages import DPIA_CRITERION_IDS
from .standards import ROOT, memo, parse_yaml, sha256_hex, validate
from .workflow import APPROVING, PROGRAMME, REVOKE, SYSTEM_ACTOR, newest_decisive

JURISDICTIONS_DIR = "standards/privacy/jurisdictions"
PURPOSES_FILE = "standards/privacy/purposes.yaml"
STEP_BASE_PROFILE_VERIFIED = "tm:step/base-profile-verified"
STEP_RETENTION_APPROVED = "tm:step/retention-approved"
STEP_ROPA_APPROVED = "tm:step/ropa-approved"
STEP_PROFILE_PRESENT = "tm:step/profile-present"  # the overlay workflow (a jurisdiction subject)
STEP_PROFILE_VERIFIED = "tm:step/profile-verified"
STEP_RETENTION_CHECK = "tm:step/retention-check"
STEP_DPIA_DELTA_CHECK = "tm:step/dpia-delta-check"
STEP_DPIA_DELTA = "tm:step/dpia-delta"
STEP_NOTICE_VARIANT = "tm:step/notice-variant"
STEP_VARIANT_APPROVED = "tm:step/variant-approved"
DISCLOSED_PURPOSE = "disclosed-purpose"  # a CCPA word: overlay profiles only (jurisdiction.schema.json, $defs/basis)


class PrivacyError(Exception):
    """A privacy data file is missing or unusable; the message says which and why."""


# --- profiles -------------------------------------------------------------------------------------


def profile_files(root: Path = ROOT) -> list[Path]:
    return sorted((Path(root) / JURISDICTIONS_DIR).glob("*.yaml"), key=lambda p: p.name)


def _read_profile(path: Path, root: Path) -> tuple[str, dict[str, Any]]:
    """(sha256 of the file's bytes, the profile document checked against tm:contract/jurisdiction@1). Parsed and checked
    once per content: the cache key holds the file's hash and the schema's, so an edit of either is a new entry. The
    document is shared; callers must not change it."""
    path, root = Path(path), Path(root)
    data = path.read_bytes()
    sha = sha256_hex(data)
    schema_sha = sha256_hex((root / "contracts" / "jurisdiction.schema.json").read_bytes())

    def make() -> dict[str, Any]:
        try:
            doc = parse_yaml(data)
        except yaml.YAMLError as exc:
            raise PrivacyError(f"{path.name}: not readable as YAML ({str(exc).splitlines()[0]})") from exc
        errors = validate(doc, "jurisdiction.schema.json", root) if isinstance(doc, dict) else ["<root>: not a mapping"]
        if errors:
            raise PrivacyError(f"{path.name}: " + "; ".join(errors))
        return doc

    return sha, memo(("profile", str(path.resolve()), sha, schema_sha), make)


def load_profile(path: Path, root: Path = ROOT) -> dict[str, Any]:
    """A profile document, checked against tm:contract/jurisdiction@1."""
    return _read_profile(path, root)[1]


def _declared_role(path: Path) -> str | None:
    """The `role` a profile file declares, read as leniently as possible (a profile that fails its contract still says
    what it was meant to be): from the parsed YAML, else from a `role:` line."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        doc = parse_yaml(text)
        if isinstance(doc, dict) and isinstance(doc.get("role"), str):
            return doc["role"]
    except yaml.YAMLError:
        pass
    m = re.search(r"^role:[ \t]*['\"]?([A-Za-z-]+)", text, re.M)
    return m.group(1) if m else None


def _loadable_profiles(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Every profile that loads. A file that breaks its contract is skipped when it declares itself an overlay: it
    blocks only its own jurisdiction (overlay_profile names it there), never the base flows. One that declares
    anything else, or nothing, may be the base, so it stops everything (PrivacyError naming the file)."""
    found: list[tuple[Path, dict[str, Any]]] = []
    for path in profile_files(root):
        try:
            found.append((path, load_profile(path, root)))
        except PrivacyError:
            if _declared_role(path) != "overlay":
                raise
    return found


def base_profile(root: Path = ROOT) -> tuple[Path, dict[str, Any]]:
    """The single profile with role `base`. No base, or more than one, is an error."""
    bases = [(p, d) for p, d in _loadable_profiles(root) if d["role"] == "base"]
    if not bases:
        raise PrivacyError(f"no base profile under {JURISDICTIONS_DIR} (one profile must have role base)")
    if len(bases) > 1:
        raise PrivacyError("more than one base profile: " + ", ".join(p.name for p, _ in bases))
    return bases[0]


def base_codes(root: Path = ROOT) -> list[str]:
    """The jurisdiction codes the base profile covers (the engine's `base_codes`)."""
    return list(base_profile(root)[1]["codes"])


def profile_names(root: Path = ROOT) -> dict[str, str]:
    """profile id -> display name, for every profile that loads (a broken one is left out)."""
    out: dict[str, str] = {}
    for path in profile_files(root):
        try:
            doc = load_profile(path, root)
        except PrivacyError:
            continue
        out[doc["id"]] = doc.get("name", doc["id"])
    return out


def purposes_sha256(root: Path = ROOT) -> str:
    """SHA-256 of purposes.yaml's bytes: what a profile's verification also covers, because the bases a profile allows
    are judged against the purposes it is read with."""
    path = Path(root) / PURPOSES_FILE
    if not path.is_file():
        raise PrivacyError(f"missing {PURPOSES_FILE}")
    return sha256_hex(path.read_bytes())


def profile_inputs(path: Path, root: Path = ROOT) -> dict[str, Any]:
    """What the verification page shows and legal signs: the file's name, the SHA-256 of its exact bytes, the SHA-256 of
    purposes.yaml and the parsed content. The bytes decide (a comment edit moves the hash)."""
    path, root = Path(path), Path(root)
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.name
    sha, doc = _read_profile(path, root)
    return {"file": rel, "sha256": sha, "purposes_sha256": purposes_sha256(root), "profile": doc}


def approved_covers(log: Iterable[Mapping[str, Any]], step: str, inputs: Any, subject: str = PROGRAMME) -> bool:
    """True when the newest approving sign-off of `step` for `subject` has the hash of `inputs` and no revocation came
    after it. Same rule as the engine's `bind: input` (decision 0019)."""
    newest = _in_force(log, step, subject)
    return newest is not None and newest["payload"].get("input_sha256") == signoff.input_sha256(inputs)


def _in_force(log: Iterable[Mapping[str, Any]], step: str, subject: str) -> Mapping[str, Any] | None:
    return newest_decisive(
        e for e in log if e["kind"] == "signoff" and e["subject_uri"] == subject and e["payload"].get("step") == step
        and e["payload"].get("decision") in (*APPROVING, REVOKE))


def base_verified(log: Iterable[Mapping[str, Any]], root: Path = ROOT) -> bool:
    """The base profile counts only while the verification sign-off covers its current bytes. No base profile (or
    an unusable one) is not verified."""
    try:
        path, _ = base_profile(root)
        return approved_covers(log, STEP_BASE_PROFILE_VERIFIED, profile_inputs(path, root))
    except PrivacyError:
        return False


# --- overlay profiles ------------------------------------------------------------------------------


def overlay_profile(code: str, root: Path = ROOT) -> tuple[Path, dict[str, Any]] | None:
    """The profile with role `overlay` whose `codes` include `code` (compared case-insensitively, exactly otherwise),
    or None when there is none. The file named for the code (`us-ca.yaml`) is read first, and a PrivacyError from it
    (it breaks its contract; the message names the file) blocks this jurisdiction only. A broken file named for another
    code is that jurisdiction's problem, not this one's."""
    want = code.upper()
    named = Path(root) / JURISDICTIONS_DIR / f"{code.lower()}.yaml"
    if named.is_file():
        doc = load_profile(named, root)
        if doc["role"] == "overlay" and want in {c.upper() for c in doc["codes"]}:
            return named, doc
    for path in profile_files(root):
        if path == named:
            continue
        try:
            doc = load_profile(path, root)
        except PrivacyError:
            continue
        if doc["role"] == "overlay" and want in {c.upper() for c in doc["codes"]}:
            return path, doc
    return None


def overlay_profile_inputs(path: Path, base_path: Path, root: Path = ROOT) -> dict[str, Any]:
    """What an overlay's verification page shows and legal signs: the profile's inputs plus the hash of the base
    profile, so an edit of the base reopens the overlay approvals too."""
    return {**profile_inputs(path, root), "base_profile_sha256": profile_inputs(base_path, root)["sha256"]}


def effective_entries(entries: Iterable[Mapping[str, Any]], overlay_uri: str) -> list[Mapping[str, Any]]:
    """The retention entries that hold for one overlay jurisdiction: per (category, purpose) its own entry when it
    has one, else the base entry; entries of other jurisdictions are left out."""
    entries = list(entries)
    base = {(e["category"], e["purpose"]): e for e in entries if "jurisdiction" not in e}
    own = {(e["category"], e["purpose"]): e for e in entries if e.get("jurisdiction") == overlay_uri}
    return [own.get(k, e) for k, e in base.items()] + [e for k, e in own.items() if k not in base]


def overlay_retention_breaches(
    entries: Iterable[Mapping[str, Any]], base: Mapping[str, Any], overlay: Mapping[str, Any]
) -> list[str]:
    """Breaches of the entries that hold for the overlay's instructors against both profiles' limits. Where both
    apply the stricter rule holds (design section 2): the shorter maximum and the longer minimum, which is the same as
    staying inside every limit of both profiles."""
    effective = effective_entries(entries, overlay["id"])
    found = limit_breaches(effective, overlay)
    return found + [b for b in limit_breaches(effective, base) if b not in found]


def dpia_delta(overlay: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The overlay's DPIA triggers that the base screening does not cover, one per criterion with all its citations.
    The base screening answers the nine criteria of pages.DPIA_CRITERION_IDS; any other criterion id needs a decision."""
    found: dict[str, list[str]] = {}
    for t in overlay["dpia_triggers"]:
        if t["criterion"] not in DPIA_CRITERION_IDS:
            found.setdefault(t["criterion"], []).append(t["citation"])
    return [{"criterion": c, "citations": cites} for c, cites in found.items()]


def dpia_delta_inputs(path: Path, base_path: Path, root: Path = ROOT) -> dict[str, Any]:
    """What the DPIA delta page shows and the DPO signs (or what a skip covers when the delta is empty)."""
    inputs = overlay_profile_inputs(path, base_path, root)
    return {"delta": dpia_delta(inputs["profile"]), "overlay_profile_sha256": inputs["sha256"],
            "base_profile_sha256": inputs["base_profile_sha256"]}


def overlay_verified(
    log: Iterable[Mapping[str, Any]], subject: str, path: Path, base_path: Path, root: Path = ROOT
) -> bool:
    """Legal's newest approving sign-off for the overlay covers its bytes and the base profile's, as the engine's
    `bind: input` on profile-verified reads it."""
    return approved_covers(log, STEP_PROFILE_VERIFIED, overlay_profile_inputs(path, base_path, root), subject)


def dpia_delta_done(log: Iterable[Mapping[str, Any]], subject: str, inputs: Any) -> bool:
    """The DPIA delta is handled for `inputs` (dpia_delta_inputs): the DPO's newest approving sign-off covers them, or
    the newest skip event does (the engine's `skippable` rule: only the system's own skip counts)."""
    log = list(log)
    if approved_covers(log, STEP_DPIA_DELTA, inputs, subject):
        return True
    skips = [e for e in log if e["kind"] == "step" and e["subject_uri"] == subject and e["actor"] == SYSTEM_ACTOR
             and e["payload"].get("step") == STEP_DPIA_DELTA and e["payload"].get("skipped") is True]
    return bool(skips) and skips[-1]["payload"].get("input_sha256") == signoff.input_sha256(inputs)


# --- the DPIA screening ---------------------------------------------------------------------------


STEP_DPIA_SCREENING = signoff.DPIA_STEP


def ropa_approval_sha256(log: Iterable[Mapping[str, Any]], subject: str = PROGRAMME) -> str | None:
    """The input hash of the ROPA approval in force: which record of processing the DPO last approved. None while
    nobody has approved one, or after the approval was revoked (decision 0019)."""
    newest = _in_force(log, STEP_ROPA_APPROVED, subject)
    return None if newest is None else newest["payload"].get("input_sha256")


def dpia_inputs(log: Iterable[Mapping[str, Any]], root: Path = ROOT) -> dict[str, Any]:
    """What the base DPIA screening binds to: the base profile's triggers, the hash of purposes.yaml and the ROPA
    approval in force (its input hash). Editing either file, or the DPO re-approving a changed record of processing,
    reopens the DPO's clearance. The record of processing itself rides in the page's unhashed intro: it includes the
    retention table, which is edited while the screening stands, so only an approved change to it reopens the screening.

    A base trigger whose criterion is not one of the screening criterion ids is refused (PrivacyError): the page asks
    the nine criteria of pages.DPIA_CRITERION_IDS, so a free-text criterion would never be answered."""
    path, profile = base_profile(root)
    triggers = profile["dpia_triggers"]
    unknown = [t["criterion"] for t in triggers if t["criterion"] not in DPIA_CRITERION_IDS]
    if unknown:
        raise PrivacyError("; ".join(
            f"unknown DPIA criterion {c!r} in base profile {path.name} (use one of {sorted(DPIA_CRITERION_IDS)})"
            for c in unknown))
    return {"base_dpia_triggers": triggers, "purposes_sha256": purposes_sha256(root),
            "ropa_approval_sha256": ropa_approval_sha256(log)}


def dpia_current(log: Iterable[Mapping[str, Any]], root: Path = ROOT) -> bool:
    """The DPO's newest approving DPIA sign-off covers the triggers and purposes as they are now. Ingest accepts an
    approving DPIA sign-off only when the DPO decided `dpia-not-required`, so this means "cleared"."""
    try:
        log = list(log)
        return approved_covers(log, STEP_DPIA_SCREENING, dpia_inputs(log, root))
    except PrivacyError:
        return False


# --- purposes and retention coverage --------------------------------------------------------------


def load_purposes(root: Path = ROOT) -> dict[str, Any]:
    """purposes.yaml checked against tm:contract/purposes@1; parsed once per content (the document is shared)."""
    root = Path(root)
    path = root / PURPOSES_FILE
    if not path.is_file():
        raise PrivacyError(f"missing {PURPOSES_FILE}")
    data = path.read_bytes()
    schema_sha = sha256_hex((root / "contracts" / "purposes.schema.json").read_bytes())

    def make() -> dict[str, Any]:
        try:
            doc = parse_yaml(data)
        except yaml.YAMLError as exc:
            raise PrivacyError(f"{PURPOSES_FILE}: not readable as YAML ({str(exc).splitlines()[0]})") from exc
        errors = validate(doc, "purposes.schema.json", root) if isinstance(doc, dict) else ["<root>: not a mapping"]
        if errors:
            raise PrivacyError(f"{PURPOSES_FILE}: " + "; ".join(errors))
        return doc

    return memo(("purposes", str(path.resolve()), sha256_hex(data), schema_sha), make)


def required_pairs(purposes: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every (category, purpose) pair purposes.yaml uses, in file order."""
    return [(c, p["id"]) for p in purposes["purposes"] for c in p["categories"]]


def coverage_gaps(
    purposes: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], *, base_only: bool = False
) -> list[str]:
    """One line per pair with no retention entry. `base_only` counts only entries without a jurisdiction (the
    pairs the base population needs: the retention page and validate); otherwise an entry of any jurisdiction
    covers the pair."""
    have = {(e["category"], e["purpose"]) for e in entries if not (base_only and "jurisdiction" in e)}
    word = "no base retention entry for" if base_only else "no retention entry for"
    return [f"{word} {c} / {p}" for c, p in required_pairs(purposes) if (c, p) not in have]


def limit_breaches(entries: Iterable[Mapping[str, Any]], profile: Mapping[str, Any]) -> list[str]:
    """Entries outside a profile's retention limits. A period above `max_months` or below `min_months` breaks
    it. An entry that ends on an event (`until_event`) is treated as unbounded: it passes a limit that only sets a
    minimum and fails one that sets a maximum, because the event may never come. The profile has no way to allow
    an event-ended entry under a maximum; legal widens or drops the limit, or the entry gets a period.
    The caller decides which profile is verified and which entries it applies to."""
    out: list[str] = []
    for e in entries:
        for lim in profile["retention_limits"]:
            if lim["category"] != e["category"]:
                continue
            where = f"{e['category']} / {e['purpose']}"
            if "period_months" in e:
                n = e["period_months"]
                if "max_months" in lim and n > lim["max_months"]:
                    out.append(f"{where}: {n} months is above the {lim['max_months']}-month maximum "
                               f"({profile['id']}, {lim['citation']})")
                if "min_months" in lim and n < lim["min_months"]:
                    out.append(f"{where}: {n} months is below the {lim['min_months']}-month minimum "
                               f"({profile['id']}, {lim['citation']})")
            elif "max_months" in lim:
                out.append(f"{where}: ends on an event, so it has no maximum, but {profile['id']} limits it to "
                           f"{lim['max_months']} months ({lim['citation']})")
    return out


# --- validate --------------------------------------------------------------------------------------


def check_privacy(
    root: Path, *, workflow_ids: Collection[str], category_ids: Collection[str], retention: Mapping[str, Any]
) -> list[str]:
    """Cross-checks across profiles, purposes and retention (the schemas are checked on load). The caller
    passes the defined workflow ids, the data category ids and the loaded retention document."""
    root = Path(root)
    errors: list[str] = []

    profiles: dict[str, dict[str, Any]] = {}
    codes: dict[str, str] = {}
    for path in profile_files(root):
        try:
            doc = load_profile(path, root)
        except PrivacyError as exc:
            errors.append(f"privacy: {exc}")
            continue
        code = doc["id"].split("/", 1)[1]
        if path.stem != code:
            errors.append(f"privacy: {path.name} holds {doc['id']}; the file must be named {code}.yaml")
        if doc["id"] in profiles:
            errors.append(f"privacy: {path.name} repeats {doc['id']}")
        profiles[doc["id"]] = doc
        for c in doc["codes"]:
            if c in codes:
                errors.append(f"privacy: code {c} is covered by more than one profile ({codes[c]} and {doc['id']})")
            codes[c] = doc["id"]
        if doc["role"] == "base":
            for purpose, bases in doc["lawful_bases"].items():
                if DISCLOSED_PURPOSE in bases:
                    errors.append(f"privacy: {path.name} is a base profile and uses {DISCLOSED_PURPOSE} for "
                                  f"{purpose}; that basis is for overlay profiles only")
    bases = [d for d in profiles.values() if d["role"] == "base"]
    if not bases:
        errors.append(f"privacy: no base profile under {JURISDICTIONS_DIR} (one profile must have role base)")
    elif len(bases) > 1:
        errors.append("privacy: more than one base profile: " + ", ".join(d["id"] for d in bases))
    base_ids = {d["id"] for d in bases}
    for d in bases:
        for t in d["dpia_triggers"]:
            if t["criterion"] not in DPIA_CRITERION_IDS:
                errors.append(f"privacy: unknown DPIA criterion {t['criterion']!r} in base profile {d['id']}; the "
                              f"screening asks only {sorted(DPIA_CRITERION_IDS)}")
    errors += _template_errors(root, profiles)

    try:
        purposes = load_purposes(root)
    except PrivacyError as exc:
        return [*errors, f"privacy: {exc}"]
    ids: list[str] = []
    cats = set(category_ids)
    for n, p in enumerate(purposes["purposes"]):
        where = f"{PURPOSES_FILE} purposes/{n} ({p['id']})"
        if p["id"] in ids:
            errors.append(f"privacy: {where}: more than one purpose with this id")
        ids.append(p["id"])
        for c in p["categories"]:
            if c not in cats:
                errors.append(f"privacy: {where}: unknown data category {c!r}; known ids are {sorted(cats)}")
        for w in p["workflows"]:
            if w not in workflow_ids:
                errors.append(f"privacy: {where}: workflow {w} is not defined (list a workflow that is not built "
                              "yet under planned_workflows)")
        for w in p.get("planned_workflows", []):
            if w in workflow_ids:
                errors.append(f"privacy: {where}: planned workflow {w} exists as a workflow file; move it from "
                              "planned_workflows to workflows")
        for uri, prop in p.get("proposed_basis", {}).items():
            profile = profiles.get(uri)
            if profile is None:
                errors.append(f"privacy: {where}: proposed basis for unknown profile {uri}")
                continue
            allowed = profile["lawful_bases"].get(p["id"], [])
            if prop["basis"] == DISCLOSED_PURPOSE and uri in base_ids:
                errors.append(f"privacy: {where}: {DISCLOSED_PURPOSE} proposed for the base profile {uri}; that "
                              "basis is for overlay profiles only")
            elif prop["basis"] not in allowed:
                errors.append(f"privacy: {where}: proposed basis {prop['basis']} is not among the bases {uri} "
                              f"allows for {p['id']} ({allowed or 'none listed'})")
    for uri, profile in profiles.items():
        for purpose in profile["lawful_bases"]:
            if purpose not in ids:
                errors.append(f"privacy: {uri} lists lawful bases for unknown purpose {purpose}")

    entries = retention.get("entries", [])
    by_purpose = {p["id"]: p for p in purposes["purposes"]}
    for n, e in enumerate(entries):
        where = f"retention: entries/{n}"
        purpose = by_purpose.get(e["purpose"])
        if purpose is None:
            errors.append(f"{where}: unknown purpose {e['purpose']}")
        elif e["category"] not in purpose["categories"]:
            errors.append(f"{where}: category {e['category']} is not used by purpose {e['purpose']}")
        jur = e.get("jurisdiction")
        if jur is not None and jur not in profiles:
            errors.append(f"{where}: unknown jurisdiction {jur}")
        if e["basis"] == DISCLOSED_PURPOSE and (jur is None or jur in base_ids):
            errors.append(f"{where}: {DISCLOSED_PURPOSE} is for an entry of an overlay jurisdiction only")
    # A draft is allowed to be incomplete: the privacy-base workflow refuses at run time until it is whole. Once it
    # is not a draft, every pair needs a BASE entry (the retention page's rule); a jurisdiction entry only overrides.
    if retention.get("status") != "draft":
        errors += [f"retention: {g}" for g in coverage_gaps(purposes, entries, base_only=True)]
    errors += _limit_errors(entries, profiles, bases)
    return errors


def template_name(profile: Mapping[str, Any]) -> str:
    """The notice template file of a profile: the base's `privacy-notice.md`, an overlay's `privacy-notice-<code>.md`."""
    return "privacy-notice.md" if profile["role"] == "base" else f"privacy-notice-{profile['id'].split('/', 1)[1]}.md"


def _template_errors(root: Path, profiles: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """The element markers of each profile's notice template against the profile's `notice_elements`: every element needs
    a marker, and a marker needs an element. A base template that is missing is an error; an overlay without a template
    is reported when the variant is rendered. Draft markers are a render-time gate, not an error here."""
    errors: list[str] = []
    for profile in profiles.values():
        name = template_name(profile)
        path = Path(root) / "standards" / "templates" / name
        if not path.is_file():
            if profile["role"] == "base":
                errors.append(f"privacy: no notice template standards/templates/{name} for {profile['id']}")
            continue
        marked = [m.group(1) for m in notice.MARKER.finditer(path.read_text(encoding="utf-8"))]
        listed = [e["id"] for e in profile["notice_elements"]]
        errors += [f"privacy: {name} has no marker for mandatory element {eid} of {profile['id']} "
                   f"(<!-- element: {eid} -->)" for eid in listed if eid not in marked]
        errors += [f"privacy: {name} marks element {eid}, which {profile['id']} does not list in notice_elements"
                   for eid in dict.fromkeys(marked) if eid not in listed]
    return errors


def _limit_errors(
    entries: Sequence[Mapping[str, Any]], profiles: Mapping[str, Mapping[str, Any]], bases: Sequence[Mapping[str, Any]]
) -> list[str]:
    """The retention entries against the limits of every profile, draft profiles included: the limits are data the
    programme will be held to once legal verifies them, so an entry that already breaks one is an error now. Base
    entries are checked against the base profile; for each overlay, the entries that hold there (its own, else the
    base's) against both profiles."""
    found: list[str] = []
    base = bases[0] if len(bases) == 1 else None
    if base is not None:
        found += limit_breaches([e for e in entries if "jurisdiction" not in e], base)
    for profile in profiles.values():
        if profile["role"] != "overlay":
            continue
        if base is not None:
            found += overlay_retention_breaches(entries, base, profile)
        else:
            found += limit_breaches(effective_entries(entries, profile["id"]), profile)
    return [f"retention: {b}" for b in dict.fromkeys(found)]


# --- the retention approval page's inputs ----------------------------------------------------------------


def row_key(entry: Mapping[str, Any]) -> str:
    key = f"{entry['category']} / {entry['purpose']}"
    return key + (f" / {entry['jurisdiction']}" if "jurisdiction" in entry else "")


def retention_inputs(root: Path, ret: Mapping[str, Any], log: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """What the retention approval page shows and the head of training signs: one row per entry, the retention file's
    status and basis, and the hash of the base profile, so editing the profile reopens the approval.

    Refused (PrivacyError) while there are no entries, while a category and purpose pair used by purposes.yaml has no
    base entry, and, once legal has verified the base profile, while an entry breaks one of its retention limits. The
    limits bind only a VERIFIED profile: an unverified one is not yet the law of this programme."""
    root = Path(root)
    entries = ret["entries"]
    if not entries:
        raise PrivacyError("retention entries still empty: add them to standards/retention.yaml")
    purposes = load_purposes(root)
    gaps = coverage_gaps(purposes, entries, base_only=True)
    if gaps:
        raise PrivacyError("; ".join(gaps))
    path, profile = base_profile(root)
    if base_verified(log, root):
        breaches = limit_breaches(entries, profile)
        if breaches:
            raise PrivacyError("an entry breaks the verified base profile's retention limits: " + "; ".join(breaches))
    names = {p["id"]: p["name"] for p in purposes["purposes"]}
    rows = []
    for e in entries:
        period = f"{e['period_months']} months" if "period_months" in e else f"until {e['until_event']}"
        where = f" ({e['jurisdiction']})" if "jurisdiction" in e else ""
        rows.append({
            "key": row_key(e),
            "summary": (f"{e['category']} for {names.get(e['purpose'], e['purpose'])}{where}: {period}. "
                        f"Starts: {e['starts']} Why: {e['reason']} Basis: {e['basis']}."),
            "changed": True,  # constant: a flag that moved with the approval would make the approval stale
        })
    return {"rows": rows, "retention_status": ret["status"], "retention_basis": ret["basis"],
            "base_profile_sha256": profile_inputs(path, root)["sha256"]}


def retention_approved(log: Iterable[Mapping[str, Any]], root: Path, ret: Mapping[str, Any]) -> bool:
    """The newest approving retention sign-off covers the entries and the profile as they are now."""
    log = list(log)
    try:
        return approved_covers(log, STEP_RETENTION_APPROVED, retention_inputs(root, ret, log))
    except PrivacyError:
        return False
