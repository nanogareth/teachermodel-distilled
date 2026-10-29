"""Overlay workflow auto steps (tm:workflow/privacy-overlay). Spec: docs/specs/2026-10-24-privacy-jurisdictions-design.md
section 4.

One run per jurisdiction subject, like the setup steps: each function takes the private dir, the event list, the
subject (`tm:jurisdiction/<code>`), its ISO code and the time, writes any output under `<private>/generated/` and
returns the events to append; it never writes the log. A run whose result is unchanged returns `[]`, and a step that
cannot run yet returns one `check` event with `result: blocked`, reported once until its reasons change.

The engine's `needs` gate every step; the checks here are the second lock (a bound approval can lapse after a step
is done, and a done step is not re-run by the engine). Nothing here judges what the law requires: profiles are data
that legal verifies, and these steps only compare the programme's own files with them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from . import notice, privacy, setup, signoff
from . import workflow as wf
from .privacy import PrivacyError
from .setup import _blocked, _decision, _event, _latest, _notice_path, _output, _render, _sha
from .standards import ROOT


def _context(root: Path, code: str) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    """(base path, base profile, overlay path, overlay profile) for a code, or PrivacyError saying what is missing."""
    found = privacy.overlay_profile(code, root)
    if found is None:
        raise PrivacyError(f"no profile for {code}")
    base_path, base = privacy.base_profile(root)
    return base_path, base, found[0], found[1]


def _once(log: Iterable[Mapping[str, Any]], subject: str, step: str, payload: dict[str, Any], now: Any) -> list[dict[str, Any]]:
    """One `step` event with `payload`, unless the latest one for (subject, step) already says the same."""
    latest = _latest(log, "step", subject, step)
    if latest is not None and latest["payload"] == payload:
        return []
    return [_event("step", subject, payload, now)]


def _unverified(code: str) -> str:
    return f"profile for {code} is not verified"


# --- profile-present ----------------------------------------------------------------------------------


def profile_present(private_dir, events, subject, code, now, *, root: Path = ROOT) -> list[dict[str, Any]]:
    """tm:step/profile-present: done once a profile with role overlay covers the code; blocked ("no profile for DE")
    until then."""
    log = list(events)
    try:
        found = privacy.overlay_profile(code, root)
    except PrivacyError as exc:
        return _blocked(log, privacy.STEP_PROFILE_PRESENT, subject, [str(exc)], now)
    if found is None:
        return _blocked(log, privacy.STEP_PROFILE_PRESENT, subject, [f"no profile for {code}"], now)
    path, doc = found
    payload = {"step": privacy.STEP_PROFILE_PRESENT, "profile": doc["id"],
               "profile_sha256": privacy.profile_inputs(path, root)["sha256"]}
    return _once(log, subject, privacy.STEP_PROFILE_PRESENT, payload, now)


# --- retention-check ----------------------------------------------------------------------------------


def _retention_reasons(
    ret: Mapping[str, Any], base: Mapping[str, Any], overlay: Mapping[str, Any]
) -> list[str]:
    if not ret["entries"]:
        return ["retention entries still empty: add them to standards/retention.yaml"]
    return privacy.overlay_retention_breaches(ret["entries"], base, overlay)


def retention_check(private_dir, events, subject, code, now, *, root: Path = ROOT, retention_path: Path | None = None):
    """tm:step/retention-check: the retention that holds for this jurisdiction (its own entry for a category and
    purpose, else the base entry) against the limits of the overlay and of the base. Where both apply the stricter
    rule holds: the shorter maximum, the longer minimum. Blocked, naming each breach, until the entries fit."""
    log = list(events)
    try:
        base_path, base, path, doc = _context(root, code)
    except PrivacyError as exc:
        return _blocked(log, privacy.STEP_RETENTION_CHECK, subject, [str(exc)], now)
    reasons = [] if privacy.overlay_verified(log, subject, path, base_path, root) else [_unverified(code)]
    ret: Mapping[str, Any] = {"entries": []}
    try:
        ret = setup.load_retention(retention_path or root / "standards" / "retention.yaml", root)
        reasons += _retention_reasons(ret, base, doc)
    except setup.SetupError as exc:
        reasons.append(str(exc))
    if reasons:
        return _blocked(log, privacy.STEP_RETENTION_CHECK, subject, reasons, now)
    inputs = privacy.overlay_profile_inputs(path, base_path, root)
    digest = signoff.input_sha256({"entries": privacy.effective_entries(ret["entries"], doc["id"]),
                                   "overlay_profile_sha256": inputs["sha256"],
                                   "base_profile_sha256": inputs["base_profile_sha256"]})
    return _once(log, subject, privacy.STEP_RETENTION_CHECK, {"step": privacy.STEP_RETENTION_CHECK, "input_sha256": digest}, now)


# --- dpia-delta-check ---------------------------------------------------------------------------------


def dpia_delta_check(private_dir, events, subject, code, now, *, root: Path = ROOT) -> list[dict[str, Any]]:
    """tm:step/dpia-delta-check: which triggers of the overlay the base screening does not cover. With none, the DPIA
    delta does not apply: a `step` event for tm:step/dpia-delta marked skipped ("no delta") closes it while the
    profiles stay as they are. With some, only the check is recorded and the DPO decides on the delta page."""
    log = list(events)
    try:
        base_path, _, path, _ = _context(root, code)
    except PrivacyError as exc:
        return _blocked(log, privacy.STEP_DPIA_DELTA_CHECK, subject, [str(exc)], now)
    if not privacy.overlay_verified(log, subject, path, base_path, root):
        return _blocked(log, privacy.STEP_DPIA_DELTA_CHECK, subject, [_unverified(code)], now)
    inputs = privacy.dpia_delta_inputs(path, base_path, root)
    delta = [d["criterion"] for d in inputs["delta"]]
    out = _once(log, subject, privacy.STEP_DPIA_DELTA_CHECK,
                {"step": privacy.STEP_DPIA_DELTA_CHECK, "delta": delta}, now)
    if not delta:
        out += _once(log, subject, privacy.STEP_DPIA_DELTA,
                     {"step": privacy.STEP_DPIA_DELTA, "skipped": True, "reason": "no delta",
                      "input_sha256": signoff.input_sha256(inputs)}, now)
    return out


# --- notice-variant -----------------------------------------------------------------------------------


def notice_variant(
    private_dir, events, settings, subject, code, now, *, root: Path = ROOT,
    decisions_dir: Path | None = None, retention_path: Path | None = None,
) -> list[dict[str, Any]]:
    """tm:step/notice-variant: the base notice plus the overlay's own sections, rendered for the retention that holds
    for this jurisdiction, as `generated/notice-<version>-<code>.md`.

    Blocked while the overlay is not verified, the base notice is not approved (for the retention as it is now), the
    DPIA delta is not handled, decision 0005 is not accepted, the retention entries are not approved, an entry breaks a
    limit, a purpose has no proposed basis, or the overlay template (`standards/templates/privacy-notice-<code>.md`) is
    missing, uses an unknown placeholder, still holds draft text, or lacks a marker (or renders an empty section) for a
    mandatory element of either profile. It never changes the text of a variant that has already been sent."""
    private, log = Path(private_dir), list(events)
    step = privacy.STEP_NOTICE_VARIANT
    try:
        base_path, base, path, doc = _context(root, code)
        purposes = privacy.load_purposes(root)
        base_sha = privacy.profile_inputs(base_path, root)["sha256"]
        delta_inputs = privacy.dpia_delta_inputs(path, base_path, root)
    except PrivacyError as exc:
        return _blocked(log, step, subject, [str(exc)], now)
    version = settings["notice_version"]
    retention_path = retention_path or setup.retention_file(private, settings, root)
    variant = wf.notice_variant(version, code, base["codes"])
    reasons: list[str] = []
    if not privacy.overlay_verified(log, subject, path, base_path, root):
        reasons.append(_unverified(code))
    ret: Mapping[str, Any] = {"entries": []}
    retention_sha = ""
    try:
        ret = setup.load_retention(retention_path, root)
        reasons += _retention_reasons(ret, base, doc)
        if ret["entries"] and not privacy.retention_approved(log, root, ret):
            reasons.append("retention not approved")
        retention_sha = setup.retention_digest(root, log, retention_path)
    except (setup.SetupError, PrivacyError) as exc:
        if str(exc) not in reasons:
            reasons.append(str(exc))
    base_notice = private / _notice_path(version)
    if not base_notice.is_file():
        reasons.append(f"base notice {version} is not rendered")
    elif not retention_sha or not privacy.approved_covers(
            log, setup.STEP_NOTICE_APPROVED,
            setup.notice_inputs(base_notice.read_text(encoding="utf-8"), version, base_sha, retention_sha)):
        reasons.append(f"base notice {version} is not approved")
    if not privacy.dpia_delta_done(log, subject, delta_inputs):
        reasons.append("DPIA delta not handled: the DPO has not signed the delta for the profiles as they are now")
    status, separation, d_path = _decision(decisions_dir or root / "docs" / "decisions", "0005")
    if d_path is None:
        reasons.append("decision 0005 (performance-management separation) not found")
    elif status != "accepted":
        reasons.append(f"decision 0005 is {status}; the notice must state its answer, so it must be accepted")
    elif not separation:
        reasons.append("decision 0005 has no '## Decision' text to quote")
    base_purposes, base_reasons = notice.purposes_md(purposes, base["id"])
    overlay_purposes, overlay_reasons = notice.purposes_md(purposes, doc["id"])
    reasons += base_reasons + overlay_reasons
    template = f"privacy-notice-{code.lower()}.md"
    if not (root / "standards" / "templates" / template).is_file():
        reasons.append(f"no notice template standards/templates/{template} for {code}")
    if reasons:
        return _blocked(log, step, subject, reasons, now)
    # The notice states what holds for this jurisdiction's instructors, so the entries lose their jurisdiction tag.
    held = [{k: v for k, v in e.items() if k != "jurisdiction"} for e in privacy.effective_entries(ret["entries"], doc["id"])]
    values = setup.notice_values(root, settings, base, purposes, base_purposes, {**ret, "entries": held}, separation)
    values |= {"overlay_purposes": overlay_purposes, "overlay_complaint": notice.regulator_md(doc)}
    try:
        base_part = _render(root, "privacy-notice.md", version=variant, **values)
        overlay_part = _render(root, template, version=variant, **values)
    except (KeyError, ValueError) as exc:
        return _blocked(log, step, subject, [f"notice template uses an unknown placeholder or a stray $: {exc}"], now)
    rendered = base_part.rstrip("\n") + "\n\n" + overlay_part
    if settings.get("simulated") is True:  # decision 0020
        rendered = notice.simulated(rendered)
    problems = notice.element_problems(rendered, [e["id"] for e in [*base["notice_elements"], *doc["notice_elements"]]])
    if problems:
        return _blocked(log, step, subject, problems, now)
    data = notice.strip_markers(rendered).encode("utf-8")
    if setup.changed_under_sent(private, log, variant, data):
        return _blocked(log, step, subject,
                        [f"notice text changed under variant {variant}: bump notice_version in settings"], now)
    return _output(private, log, step, subject, _notice_path(variant), data, now,
                   text_sha256=_sha(data), notice_version=version, notice_variant=variant, retention_sha256=retention_sha)
