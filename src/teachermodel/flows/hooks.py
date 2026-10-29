"""The two registries a flow uses to extend `app` without editing it: auto steps and sign-off hooks.

Re-exported by `teachermodel.flows`, so a flow module writes `from . import auto_step, on_signoff`.

`@auto_step(step_id, refresh=False, per="programme")` registers the runner of an auto step:

    fn(state, subject_uri, now) -> list[event]

`state` is the loaded `State` (`state.private` and `state.root` are the store and the repo-data root, for runners that
write generated files); `now` is the aware datetime of the run. `per` is how often and for which subject `do_run`
calls it:
  - "programme" (the default): once per `do_run` for all due subjects, called with `PROGRAMME`. A step whose workflow
    subject is not the programme (notice-drafts is per instructor) still runs once and handles all its subjects itself.
  - "instructor", "jurisdiction", "candidate", "assignment", "exercise", "cycle", "sample", "bench", "override": once per due subject of that kind, called with
    that subject's URI.
`refresh=True` also runs the step again, after the main loop, whenever it is done but its needs are still met (for a
subject of the step's own kind; for "programme" when any of them qualifies). Its outputs derive from files an edit can
change; a run whose output is unchanged must append nothing (events are deduped by id). The returned events are
appended with `append_new`, so an event already in the log is dropped.

`@on_signoff(step_id)` registers a hook called by `do_ingest` for each newly accepted APPROVING sign-off of that step:

    fn(state, signoff_event, stored_document, now) -> (events, documents)

`signoff_event` is the logged `signoff` event; `stored_document` is the full sign-off from the receipt, including its
free-text `fields` (which never enter the log); `state.events` already holds everything this ingest has produced so far
(the log, the accepted events up to and including this sign-off, and what earlier hooks returned), so a hook sees its
own earlier effects. The one return shape is a pair: `events` is a list of event dicts, appended after the sign-off
events of the receipt and deduped by id like all events; `documents` is a list of `(relpath, document)` private
documents to write (JSON, an idempotent overwrite) before the events are appended. A `relpath` must stay inside the
private dir and outside `events/`. Return `([], [])` for nothing. Several hooks may be registered for one step; they run
in registration order.

`@content_check(step_id)` registers a rule on the content of an approving sign-off of that step, run by ingest after the
envelope is accepted (signer, freshness, template) and before the sign-off counts:

    fn(state, signoff_document) -> list[str]

It returns the reasons the sign-off cannot count (empty to accept), each naming a field and never quoting its value; any
reason rejects the sign-off, which is then not stored and leaves the step open. `state` is the loaded `State`. Several
checks may be registered for one step. Use `content_reasons(state, document)` to run them.

All three registries raise on a mistake at registration (a second runner for one step, an unknown `per`), so a flow module
fails at import, not during a run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .. import signoff
from ..workflow import APPROVING
from .common import State

PER_KINDS = ("programme", "instructor", "jurisdiction", "candidate", "assignment", "exercise",
             "cycle", "sample", "bench", "override", "appeal")

Event = dict[str, Any]
AutoRunner = Callable[[State, str, datetime], list[Event]]
SignoffResult = tuple[list[Event], list[tuple[str, dict[str, Any]]]]
SignoffHook = Callable[[State, Event, dict[str, Any], datetime], SignoffResult]


@dataclass(frozen=True)
class AutoStep:
    step: str
    run: AutoRunner
    per: str
    refresh: bool


ContentCheck = Callable[[State, dict[str, Any]], list[str]]

AUTO_STEPS: dict[str, AutoStep] = {}
SIGNOFF_HOOKS: dict[str, list[SignoffHook]] = {}
CONTENT_CHECKS: dict[str, list[ContentCheck]] = {}


def auto_step(step_id: str, *, refresh: bool = False, per: str = "programme") -> Callable[[AutoRunner], AutoRunner]:
    """Register `fn(state, subject_uri, now) -> list[event]` as the runner of an auto step. One runner per step."""
    if per not in PER_KINDS:
        raise ValueError(f"auto step {step_id}: per must be one of {PER_KINDS}, not {per!r}")

    def decorate(fn: AutoRunner) -> AutoRunner:
        if step_id in AUTO_STEPS:
            raise ValueError(f"auto step runner for {step_id} is already registered")
        AUTO_STEPS[step_id] = AutoStep(step_id, fn, per, refresh)
        return fn

    return decorate


def on_signoff(step_id: str) -> Callable[[SignoffHook], SignoffHook]:
    """Register `fn(state, signoff_event, stored_document, now) -> (events, [(relpath, document)])` for each newly
    accepted approving sign-off of `step_id`."""

    def decorate(fn: SignoffHook) -> SignoffHook:
        SIGNOFF_HOOKS.setdefault(step_id, []).append(fn)
        return fn

    return decorate


def content_check(step_id: str) -> Callable[[ContentCheck], ContentCheck]:
    """Register `fn(state, signoff_document) -> reasons` as a content rule of the approving sign-offs of `step_id`."""

    def decorate(fn: ContentCheck) -> ContentCheck:
        CONTENT_CHECKS.setdefault(step_id, []).append(fn)
        return fn

    return decorate


def content_reasons(state: State, document: dict[str, Any]) -> list[str]:
    """The reasons the registered checks of the sign-off's step give for its content; none for a sign-off that does not
    approve (it never completes a step), a step without checks, or a document without a step. A check that raises
    rejects the sign-off ("content check failed"): a document that breaks a rule's assumptions is not accepted."""
    if document.get("decision") not in APPROVING:
        return []
    out: list[str] = []
    step, subject = document.get("step"), document.get("subject_uri")
    if step in signoff.SINGLE_DECISION_STEPS and isinstance(subject, str) and signoff.already_decided(
            state.index.of("signoff", subject), step, subject, document.get("input_sha256")):
        out.append(signoff.ALREADY_DECIDED)  # integration review finding 16: the first accepted decision stands
    for check in CONTENT_CHECKS.get(step, ()):
        try:
            out.extend(check(state, document))
        except Exception:  # noqa: BLE001 - never let a malformed attachment abort the whole receipt
            out.append("content check failed")
    return out
