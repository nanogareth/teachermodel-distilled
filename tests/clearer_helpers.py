"""Helpers for tests that need clearers by level and calibrations on the record (fictional people only).

A clearer is an instructor whose latest level is clearer; an observer must also be calibrated on the day (W5, rules.yaml
`calibration.renewal_months`). The calibration events here are written directly, as `records.calibrations` reads them.
"""

import hashlib

from teachermodel import app, events

CALIBRATED_ON = "2026-09-01T08:00:00+00:00"  # inside the renewal period of every test date in October 2026
SYSTEM = "tm:system/teachermodel"


def set_level(private, uri, to, at="2026-10-26T07:00:00+00:00"):
    events.append(private / app.EVENT_LOG, events.make_event(
        "level_change", uri, "tm:person/hot-1", {"from": "cleared", "to": to, "basis": "test"}, at=at))


def calibrate(private, *instructors, at=CALIBRATED_ON, passed=True, unit="sl:unit/example-agent-loop@1"):
    """A `calibration` event for each instructor (a slug or a URI), passed unless `passed` is False."""
    for who in instructors:
        uri = who if who.startswith("tm:") else f"tm:instructor/{who}"
        sid = hashlib.sha256(f"{uri}|{at}".encode()).hexdigest()[:16]
        share = 1.0 if passed else 0.0
        events.append(private / app.EVENT_LOG, events.make_event(
            "calibration", uri, SYSTEM,
            {"exercise": "tm:exercise/0123456789abcdef", "observer": uri, "unit": unit, "rubric_version": "0.2.0",
             "within_one_share": share, "exact_share": share, "passed": passed, "signoff_id": sid}, at=at))
