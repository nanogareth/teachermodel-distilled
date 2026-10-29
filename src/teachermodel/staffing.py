"""The staffing check (tm:contract/staffing-check@2): may this instructor deliver this unit in this mode on this date?

Pure and deterministic: the event log and the rules in, the contract's response out (`rules.staffing_check` over
`records.clearances`). Delivery scheduling (the hub) calls `check` directly; `teachermodel staffing-check` is the same
function over the private store's log. No model and no clock: the date is part of the request.

What leaves for delivery scheduling is clearance status only (decision 0005; integration review finding 12): the reasons
are reduced to a fixed vocabulary (`OUTBOUND`): "not cleared" for a block, "clearance expiring" and "recheck due" for a warn,
and "override <id>" for an ok that rests on an override. The detailed reasons (a bench decision, a retired framework, a scope,
the number of days) are for the training function: `check(..., detail=True)`, the command's `--detail` flag, which the head
of training uses on the private store.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from . import records, rules
from .records import bench_blocks
from .standards import ROOT, load_schema

SCHEMA = "staffing-check.schema.json"
EXIT_CODES = {"ok": 0, "warn": 3, "block": 2}  # the command's exit status per verdict; 1 is a refused request
NOT_CLEARED, EXPIRING, RECHECK = "not cleared", "clearance expiring", "recheck due"
OUTBOUND = (NOT_CLEARED, EXPIRING, RECHECK, "override tm:override/<id>")  # every reason delivery scheduling can receive


class RequestError(ValueError):
    """The request does not fit the contract; the message names the fields."""


def _validator(part: str, root=ROOT) -> Draft202012Validator:
    schema = load_schema(SCHEMA, root)
    return Draft202012Validator({"$defs": schema["$defs"], "$ref": f"#/$defs/{part}"}, format_checker=FormatChecker())


def check_request(request: Any, root=ROOT) -> list[str]:
    """Why the request does not fit `#/$defs/request` (field names only, never the value); empty when it does."""
    if not isinstance(request, Mapping):
        return ["the request must be an object"]
    found = {f"{'/'.join(map(str, e.path)) or '<root>'}: {e.validator}"
             for e in _validator("request", root).iter_errors(dict(request))}
    if not found:
        try:
            date.fromisoformat(request["date"])
        except ValueError:
            found.add("date: format")
    return sorted(found)


def check(events: Iterable[dict[str, Any]], request: Mapping[str, Any], rules_doc: Mapping[str, Any],
          root=ROOT, *, detail: bool = False) -> dict[str, Any]:
    """The staffing-check@2 response for `request` ({instructor, unit, mode, date, partner?, region?}) over the clearances in
    `events`. `partner` and `region` (optional, additive to the request, W11) say whom and where the delivery is for: a
    clearance scoped to a partner or to regions covers only a request that names them. The reasons are the outbound ones
    (`outbound`) unless `detail` is True. Raises RequestError when the request does not fit the contract."""
    problems = check_request(request, root)
    if problems:
        raise RequestError("staffing-check request: " + "; ".join(problems))
    response = detailed(list(events), request["instructor"], request["unit"], request["mode"],
                        date.fromisoformat(request["date"]), rules_doc,
                        partner=request.get("partner"), region=request.get("region"))
    return response if detail else outbound(response)


def detailed(log: list[dict[str, Any]], instructor: str, unit: str, mode: str, on: date, rules_doc: Mapping[str, Any], *,
             partner: str | None = None, region: str | None = None, overrides: bool = True) -> dict[str, Any]:
    """`rules.staffing_check` over the log with every reason in full: the clearances, the instructor's latest blocking bench
    decision on or before `on` (`records.bench_blocks.latest_blocking`: a later renew or convert does not lift it, finding 2)
    and the day of their latest bench decision of any kind (an override decided before it is ignored, finding 5), and, unless
    `overrides` is False, the staffing overrides."""
    blocking = bench_blocks.latest_blocking(log, instructor, on)
    decided = bench_blocks.latest_decided(log, instructor, on)
    found = [rules.Override(o["override"], o["instructor"], o["unit"], o["mode"], o["date"], o["decision"] == "approved",
                            o["block"], o["decided"], o["partner"], o["region"])
             for o in records.overrides(log)] if overrides else []
    return rules.staffing_check(records.clearances(log), instructor, unit, mode, on, dict(rules_doc),
                                partner=partner, region=region,
                                bench=(blocking["decision"], blocking["at"]) if blocking else None,
                                overrides=found, bench_decided=decided["at"] if decided else None)


def block_reasons(log: list[dict[str, Any]], instructor: str, unit: str, mode: str, on: date,
                  rules_doc: Mapping[str, Any], *, partner: str | None = None, region: str | None = None) -> list[str]:
    """The detailed reasons the check blocks this request with (the partner and region it names, if any), overrides set
    aside; empty when it does not block. An override records them and is bound to them (decision 0015, finding 5; partner
    and region, decision 0018)."""
    res = detailed(log, instructor, unit, mode, on, rules_doc, partner=partner, region=region, overrides=False)
    return list(res["reasons"]) if res["verdict"] == "block" else []


def outbound(response: Mapping[str, Any]) -> dict[str, Any]:
    """The response delivery scheduling receives: the verdict and the clearance as they are, the reasons reduced to
    `OUTBOUND` (decision 0005: scheduling sees clearance status, not why). A block says only "not cleared"; a warn says
    "clearance expiring" and/or "recheck due"; an ok on an override names the override and nothing it overrode."""
    reasons = list(response["reasons"])
    if response["verdict"] == "block":
        out = [NOT_CLEARED]
    elif response["verdict"] == "warn":
        out = [*([EXPIRING] if any(r.startswith("clearance expires") for r in reasons) else []),
               *([RECHECK] if any("recheck due" in r for r in reasons) else [])]
    else:
        out = [r for r in reasons if r.startswith("override ")][:1]
    return {**dict(response), "reasons": out}
