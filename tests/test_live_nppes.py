"""Live smoke test against the real NPPES NPI Registry API.

Deselected by default (it needs network); run explicitly with::

    pytest -m live

It proves the live wiring end-to-end: the same ``NppesSource`` the pipeline uses,
pointed at the real API with no offline fixtures, resolves a known, stable NPI and
emits the expected normalized source values. Mayo Clinic's Type-2 NPI (1881018208)
is a public, long-lived organization record — a safe, non-personal anchor.
"""

from __future__ import annotations

import pytest

from directory_pipeline.config import Settings
from directory_pipeline.models import SourceClass
from directory_pipeline.resolve import is_valid_npi
from directory_pipeline.sources import NppesSource

# A stable, public Type-2 (organization) NPI: Mayo Clinic.
MAYO_NPI = "1881018208"


@pytest.mark.live
def test_live_nppes_lookup_real_npi() -> None:
    settings = Settings(offline=False, http_cache=False)
    nppes = NppesSource(settings)

    provider = nppes.fetch(MAYO_NPI)
    assert provider is not None, "NPPES returned no record for a known NPI"
    assert provider.npi == MAYO_NPI
    assert is_valid_npi(provider.npi), "real NPIs must pass the Luhn check digit"
    assert provider.is_organization
    assert provider.organization_name  # non-empty legal business name

    values = {sv.field: sv for sv in nppes.to_source_values(provider)}
    # An organization record yields at least a practice_name, from the gov class.
    assert "practice_name" in values
    assert values["practice_name"].source_class == SourceClass.GOV_SELF_REPORTED
    assert values["practice_name"].snapshot_hash  # provenance captured for the audit trail


@pytest.mark.live
def test_live_nppes_search_returns_results() -> None:
    settings = Settings(offline=False, http_cache=False)
    nppes = NppesSource(settings)
    results = nppes.search(organization_name="Mayo Clinic", state="MN")
    assert results, "name/org search should return candidates from the live API"
    assert all(is_valid_npi(p.npi) for p in results)
