import copy

import pytest

from teachermodel import cli, roster
from teachermodel.standards import ROOT

EXAMPLE = ROOT / "standards" / "templates" / "roster.example.yaml"


@pytest.fixture
def doc():
    return roster.load(EXAMPLE)


def row(doc, type_):
    return next(r for r in doc["instructors"] if r["type"] == type_)


def test_example_is_valid_and_covers_every_type(doc):
    assert roster.check_roster(doc) == []
    assert {r["type"] for r in doc["instructors"]} == {"sme-engineer", "professional", "contractor", "partner"}


def test_dates_load_as_strings(doc):
    assert doc["as_of"] == "2026-10-24"


def test_cli_check_roster(capsys):
    assert cli.main(["check-roster", str(EXAMPLE)]) == 0


def test_sme_engineer_needs_manager_and_protected_time(doc):
    del row(doc, "sme-engineer")["engagement"]["protected_hours_per_month"]
    assert roster.check_roster(doc)


def test_protected_time_must_be_positive(doc):
    row(doc, "sme-engineer")["engagement"]["protected_hours_per_month"] = 0
    assert roster.check_roster(doc)


def test_partner_needs_nominator(doc):
    del row(doc, "partner")["engagement"]["nominated_by"]
    assert roster.check_roster(doc)


def test_ended_engagement_needs_end_date(doc):
    row(doc, "professional")["engagement"]["status"] = "ended"
    assert roster.check_roster(doc)


def test_notice_is_optional_at_import(doc):
    # The setup workflow sends the notice after import (spec §7); given_on comes from a notice event.
    del row(doc, "professional")["notice"]
    assert roster.check_roster(doc) == []


def test_partial_notice_rejected(doc):
    del row(doc, "professional")["notice"]["given_on"]
    assert roster.check_roster(doc)


def test_unknown_level_rejected(doc):
    row(doc, "professional")["level"] = "senior"
    assert any("not in framework levels" in e for e in roster.check_roster(doc))


def test_duplicate_id_and_email_rejected(doc):
    doc["instructors"].append(copy.deepcopy(doc["instructors"][0]))
    errors = roster.check_roster(doc)
    assert any("duplicate instructor id" in e for e in errors)
    assert any("duplicate email" in e for e in errors)


def test_id_derived_from_name_rejected(doc):
    row(doc, "professional")["instructor"] = "tm:instructor/professional-1"
    assert any("meaningless" in e for e in roster.check_roster(doc))


def test_end_before_start_rejected(doc):
    row(doc, "contractor")["engagement"]["end"] = "2026-05-31"
    assert any("ends before it starts" in e for e in roster.check_roster(doc))


def test_impossible_calendar_date_rejected(doc):
    row(doc, "contractor")["engagement"]["start"] = "2026-02-30"
    assert any("not a calendar date" in e for e in roster.check_roster(doc))


def test_unknown_field_rejected(doc):
    row(doc, "professional")["identity"]["home_address"] = "1 Example Street"
    assert roster.check_roster(doc)
