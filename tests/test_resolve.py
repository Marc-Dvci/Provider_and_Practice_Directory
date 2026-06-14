from __future__ import annotations

from directory_pipeline.models import ProviderRecord
from directory_pipeline.resolve import ResolutionStatus, is_valid_npi, resolve_identity


def test_is_valid_npi():
    assert is_valid_npi("1234567893") is True
    assert is_valid_npi("1234567890") is False  # the brief's placeholder
    assert is_valid_npi("123") is False
    assert is_valid_npi(None) is False
    assert is_valid_npi("abcdefghij") is False


def test_resolve_validated(records_by_id, nppes):
    result = resolve_identity(records_by_id["HL_005"], nppes)
    assert result.status == ResolutionStatus.VALIDATED
    assert result.npi == "1938475609"
    assert result.usable


def test_resolve_bad_checkdigit_still_usable(records_by_id, nppes):
    result = resolve_identity(records_by_id["HL_001"], nppes)
    assert result.status == ResolutionStatus.BAD_CHECKDIGIT
    assert result.usable


def test_resolve_cold_start_by_search(records_by_id, nppes):
    result = resolve_identity(records_by_id["HL_002"], nppes)
    assert result.status == ResolutionStatus.RESOLVED_BY_SEARCH
    assert result.npi == "1002003006"
    assert result.usable


def test_resolve_mismatch_is_not_usable(nppes):
    record = ProviderRecord(
        provider_id="X", provider_name="Totally Different Person", npi="1938475609"
    )
    result = resolve_identity(record, nppes)
    assert result.status == ResolutionStatus.MISMATCH
    assert not result.usable
