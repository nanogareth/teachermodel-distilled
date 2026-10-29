"""Page builders for the privacy-base workflow (standards/workflows/privacy-base.yaml).

Every builder returns the page specs for a human step. The inputs of a `bind: input` page are what the signer
approves; they must not change when the sign-off itself is recorded, so anything that depends on the sign-off history
(the diff on the profile review page) rides in the unhashed `intro`.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

import yaml

from .. import pages as pagegen
from .. import privacy
from .. import setup as tm_setup
from ..privacy import PrivacyError
from ..workflow import APPROVING, PROGRAMME
from . import register
from .common import PageProblem, State, generated, per_signer


class _Indented(yaml.SafeDumper):
    """Sequences indented under their key, so a diff line reads like the file."""

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow, False)


def _dump(doc: Any) -> list[str]:
    return yaml.dump(doc, Dumper=_Indented, sort_keys=False, allow_unicode=True, width=100).splitlines()


def last_verified_inputs(
    st: State, step: str, subject: str = PROGRAMME
) -> tuple[str, dict[str, Any] | None] | None:
    """(sign-off id, the inputs it covered) for the newest approving sign-off of `step` for `subject`, or None when
    there is none. The inputs are None when the stored copy (signoffs/<id>.inputs.json, written at ingest) is missing."""
    newest = None
    for e in st.events:
        p = e["payload"]
        if e["kind"] == "signoff" and e["subject_uri"] == subject and p.get("step") == step \
                and p.get("decision") in APPROVING:
            newest = p.get("signoff_id")
    if newest is None:
        return None
    path = st.private / "signoffs" / f"{newest}.inputs.json"
    try:
        return newest, json.loads(path.read_text(encoding="utf-8"))["inputs"]
    except (OSError, ValueError, KeyError, TypeError):
        return newest, None


def profile_diff(st: State, step: str, subject: str, inputs: dict[str, Any]) -> str:
    """What changed in the profile since the version the newest approving sign-off of `step` covered."""
    last = last_verified_inputs(st, step, subject)
    if last is None:
        return "This is the first verification of this profile, so there is no earlier version to compare with."
    sid, old = last
    if old is None:
        return (f"The version verified by sign-off {sid} is not stored, so no comparison can be shown. "
                "Read the whole profile.")
    diff = list(difflib.unified_diff(_dump(old["profile"]), _dump(inputs["profile"]),
                                     f"last verified (sign-off {sid})", "current", lineterm="", n=2))
    if not diff:
        return f"The content is the same as the version verified by sign-off {sid}; only comments or layout differ."
    return f"Changes since the version verified by sign-off {sid}:\n\n```\n" + "\n".join(diff) + "\n```"


@register(privacy.STEP_BASE_PROFILE_VERIFIED)
def _b_profile(st: State, subject: str):
    try:
        path, doc = privacy.base_profile(st.root)
        inputs = privacy.profile_inputs(path, st.root)
    except PrivacyError as exc:
        raise PageProblem(str(exc)) from exc
    sources = "\n".join(f"- [{s['title']}]({s['url']}) (accessed {s['accessed']})" for s in doc["sources"])
    intro = (
        "Check each rule in this profile against its cited source, and the review notes against your own view. "
        f"Signing approves these exact file bytes (sha256 {inputs['sha256']}); any later edit reopens this step.\n\n"
        f"Sources ({len(doc['sources'])}), with the date each was accessed:\n\n{sources}\n\n"
        + profile_diff(st, privacy.STEP_BASE_PROFILE_VERIFIED, PROGRAMME, inputs)
    )
    fields = [{"name": "note", "label": "Note", "kind": "textarea", "required": False,
               "help": "Optional. Anything the head of training should know about this verification."}]
    return per_signer(st, privacy.STEP_BASE_PROFILE_VERIFIED, subject, "approve", inputs, fields, intro=intro)


@register("tm:step/ropa-approved")
def _b_ropa_approved(st: State, subject: str):
    text, _ = generated(st, tm_setup.STEP_ROPA)
    fields = [{"name": "note", "label": "Note", "kind": "textarea", "required": False,
               "help": "Optional. Anything the programme owner should know about this approval."}]
    return per_signer(st, "tm:step/ropa-approved", subject, "approve", {"ropa_text": text}, fields,
                      intro="Signing approves this exact record of processing. Any change to it (for example the "
                            "retention table being filled in, or the controller changing) reopens this step.")


@register("tm:step/dpia-screening")
def _b_dpia(st: State, subject: str):
    text, _ = generated(st, tm_setup.STEP_ROPA)
    try:
        _, doc = privacy.base_profile(st.root)
        inputs = privacy.dpia_inputs(st.events, st.root)
    except PrivacyError as exc:
        raise PageProblem(str(exc)) from exc
    # Signing binds to the base profile's triggers, the purposes and the ROPA approval in force (the inputs). The record
    # of processing text is read, not bound: it holds the retention table, which is still being edited while the
    # screening stands; only the DPO's re-approval of a changed record reopens the screening.
    return per_signer(st, "tm:step/dpia-screening", subject, "dpia_screening", inputs,
                      pagegen.dpia_fields(doc["dpia_triggers"]),
                      intro="Check each screening criterion against the record of processing below, then decide. The "
                            "base profile cites the rule behind each criterion it lists. Editing the base profile's "
                            "triggers or the purposes, or re-approving a changed record of processing, reopens this screening.\n\nRecord of processing:\n\n" + text)


@register(privacy.STEP_RETENTION_APPROVED)
def _b_retention(st: State, subject: str):
    try:
        ret = tm_setup.load_retention(tm_setup.retention_file(st.private, st.settings, st.root), st.root)
        inputs = privacy.retention_inputs(st.root, ret, st.events)
    except (PrivacyError, tm_setup.SetupError) as exc:
        raise PageProblem(str(exc)) from exc
    return per_signer(st, privacy.STEP_RETENTION_APPROVED, subject, "batch_approve", inputs,
                      intro="Approve each category and purpose with its period, the event that starts it and the "
                            "reason, on legal advice. Editing the base profile or any entry reopens this approval.")


@register(tm_setup.STEP_NOTICE_APPROVED)
def _b_notice(st: State, subject: str):
    text, payload = generated(st, tm_setup.STEP_NOTICE_TEXT)
    version = payload.get("notice_version") or st.settings["notice_version"]
    try:
        path, _ = privacy.base_profile(st.root)
        sha = privacy.profile_inputs(path, st.root)["sha256"]
        retention_sha = tm_setup.retention_digest(st.root, st.events, tm_setup.retention_file(st.private, st.settings, st.root))
    except (PrivacyError, tm_setup.SetupError) as exc:
        raise PageProblem(str(exc)) from exc
    if payload.get("retention_sha256") != retention_sha:
        raise PageProblem("the notice text was rendered against another retention than the one in force now; it is "
                          "rendered again on the next run")
    return per_signer(st, tm_setup.STEP_NOTICE_APPROVED, subject, "approve",
                      tm_setup.notice_inputs(text, version, sha, retention_sha),
                      intro="Approving this exact text, rendered against the base profile and the retention whose hashes "
                            "are shown, releases the notice drafts. Editing the profile or any retention entry reopens "
                            "this approval.")
