"""Page builders and auto-step runners for the privacy-overlay workflow (standards/workflows/privacy-overlay.yaml).

The subject is a jurisdiction (`tm:jurisdiction/<code>`). Every page's inputs carry the hash of the base profile as well
as the overlay's, so editing either reopens the approval; anything that depends on the sign-off history (the profile
diff) rides in the unhashed `intro`, as for the base workflow.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .. import overlay
from .. import pages as pagegen
from .. import privacy
from .. import setup as tm_setup
from ..privacy import PrivacyError
from . import auto_step, register
from .common import PageProblem, State, generated, per_signer
from .privacy_base import profile_diff


def _profiles(st: State, subject: str) -> tuple[Path, Path, dict[str, Any], str]:
    """(base path, overlay path, overlay profile, code) for a jurisdiction subject, or a PageProblem."""
    info = st.subjects.get(subject)
    if info is None or info.get("kind") != "jurisdiction":
        raise PageProblem(f"{subject} is not a jurisdiction")
    code = info["code"]
    try:
        found = privacy.overlay_profile(code, st.root)
        base_path, _ = privacy.base_profile(st.root)
    except PrivacyError as exc:
        raise PageProblem(str(exc)) from exc
    if found is None:
        raise PageProblem(f"no profile for {code}")
    return base_path, found[0], found[1], code


@register(privacy.STEP_PROFILE_VERIFIED)
def _b_profile(st: State, subject: str):
    base_path, path, doc, code = _profiles(st, subject)
    inputs = privacy.overlay_profile_inputs(path, base_path, st.root)
    sources = "; ".join(f"{s['title']} ({s['url']}, accessed {s['accessed']})" for s in doc["sources"])
    intro = (
        f"This overlay adds the duties of {code} to the base profile, and the stricter rule holds. Check each rule "
        "against its cited source, and the review notes against your own view. Signing approves these exact file bytes "
        f"(sha256 {inputs['sha256']}) beside the base profile (sha256 {inputs['base_profile_sha256']}); any later edit "
        f"of either reopens this step.\n\nSources ({len(doc['sources'])}): {sources}\n\n"
        + profile_diff(st, privacy.STEP_PROFILE_VERIFIED, subject, inputs)
    )
    fields = [{"name": "note", "label": "Note", "kind": "textarea", "required": False,
               "help": "Optional. Anything the programme owner should know about this verification."}]
    return per_signer(st, privacy.STEP_PROFILE_VERIFIED, subject, "approve", inputs, fields, intro=intro)


@register(privacy.STEP_DPIA_DELTA)
def _b_delta(st: State, subject: str):
    base_path, path, _, code = _profiles(st, subject)
    inputs = privacy.dpia_delta_inputs(path, base_path, st.root)
    return per_signer(st, privacy.STEP_DPIA_DELTA, subject, "dpia_screening", inputs,
                      pagegen.dpia_delta_fields(inputs["delta"]),
                      intro=f"The {code} profile lists these triggers that the base screening does not cover. Decide "
                            "each, then record whether a DPIA is required. Only 'dpia-not-required' completes this step.")


@register(privacy.STEP_VARIANT_APPROVED)
def _b_variant(st: State, subject: str):
    base_path, path, _, code = _profiles(st, subject)
    text, payload = generated(st, privacy.STEP_NOTICE_VARIANT, subject)
    variant = payload.get("notice_variant")
    if not isinstance(variant, str):
        raise PageProblem(f"the rendered notice variant for {code} names no variant")
    try:
        base_sha = privacy.profile_inputs(base_path, st.root)["sha256"]
        overlay_sha = privacy.profile_inputs(path, st.root)["sha256"]
        retention_sha = tm_setup.retention_digest(st.root, st.events, tm_setup.retention_file(st.private, st.settings, st.root))
    except (PrivacyError, tm_setup.SetupError) as exc:
        raise PageProblem(str(exc)) from exc
    if payload.get("retention_sha256") != retention_sha:
        raise PageProblem(f"the {code} variant was rendered against another retention than the one in force now; it is "
                          "rendered again on the next run")
    return per_signer(st, privacy.STEP_VARIANT_APPROVED, subject, "approve",
                      tm_setup.variant_inputs(text, variant, base_sha, overlay_sha, retention_sha),
                      intro=f"Approving this exact text, rendered against the {code} profile, the base profile and the "
                            f"retention whose hashes are shown, releases the notice drafts of {variant}.")


# --- auto steps, run once per jurisdiction subject; all after profile-present re-run too while their needs are met ---


@auto_step(privacy.STEP_PROFILE_PRESENT, per="jurisdiction")
def _run_profile_present(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return overlay.profile_present(st.private, st.events, subject, st.subjects[subject]["code"], now, root=st.root)


@auto_step(privacy.STEP_RETENTION_CHECK, per="jurisdiction", refresh=True)
def _run_retention_check(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return overlay.retention_check(st.private, st.events, subject, st.subjects[subject]["code"], now, root=st.root,
                                  retention_path=tm_setup.retention_file(st.private, st.settings, st.root))


@auto_step(privacy.STEP_DPIA_DELTA_CHECK, per="jurisdiction", refresh=True)
def _run_dpia_delta_check(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return overlay.dpia_delta_check(st.private, st.events, subject, st.subjects[subject]["code"], now, root=st.root)


@auto_step(privacy.STEP_NOTICE_VARIANT, per="jurisdiction", refresh=True)
def _run_notice_variant(st: State, subject: str, now: datetime) -> list[dict[str, Any]]:
    return overlay.notice_variant(st.private, st.events, st.settings, subject, st.subjects[subject]["code"], now,
                                  root=st.root)
