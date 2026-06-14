from __future__ import annotations

from directory_pipeline.normalize import (
    normalize_active,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_practice_name,
    normalize_specialty,
)


def test_phone_to_e164():
    assert normalize_phone("239-555-1234").canonical == "+12395551234"
    assert normalize_phone("(239) 555-1234").canonical == "+12395551234"


def test_phone_extension_split():
    parsed = normalize_phone("239-555-1234 ext 5")
    assert parsed.canonical == "+12395551234"
    assert parsed.extension == "5"


def test_phone_invalid_returns_none():
    assert normalize_phone("not-a-phone").canonical is None
    assert normalize_phone(None).canonical is None


def test_address_canonical_ignores_suite_and_suffix():
    a = normalize_address("100 Main St, Naples, FL 34102")
    b = normalize_address("100 Main Street, Suite 2, Naples, FL 34102")
    assert a.canonical == b.canonical == "100 MAIN ST, NAPLES, FL 34102"


def test_address_move_changes_canonical():
    a = normalize_address("100 Main St, Naples, FL 34102")
    b = normalize_address("250 Health Park Dr, Fort Myers, FL 33908")
    assert a.canonical != b.canonical


def test_address_from_components():
    addr = normalize_address(street="900 Bay Rd", city="Naples", state="FL", zip_code="34103-0001")
    assert addr.canonical == "900 BAY RD, NAPLES, FL 34103"


def test_specialty_crosswalk_both_directions():
    assert normalize_specialty(text="Cardiology") == "207RC0000X"
    assert normalize_specialty(taxonomy_code="207RC0000X") == "207RC0000X"
    assert normalize_specialty(text="Cardiology") == normalize_specialty(taxonomy_code="207RC0000X")


def test_name_parsing_variants():
    assert normalize_name("John Smith, MD").canonical == "SMITH|JOHN"
    # period-separated credential, no comma
    assert normalize_name("John Smith M.D.").canonical == "SMITH|JOHN"
    parsed = normalize_name("Jane A Doe, NP")
    assert parsed.canonical == "DOE|JANE"
    assert parsed.middle == "A"
    assert "NP" in parsed.credentials


def test_active_normalization():
    assert normalize_active(True) == "active"
    assert normalize_active("I") == "inactive"
    assert normalize_active("Deactivated") == "inactive"
    assert normalize_active(None) is None


def test_practice_name_normalization():
    assert normalize_practice_name("ABC Heart Group") == "ABC HEART"
    assert normalize_practice_name("Gulf Coast Family Care") == "GULF COAST FAMILY CARE"
