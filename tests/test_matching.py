from __future__ import annotations

from directory_pipeline.matching import (
    find_duplicate_clusters,
    haversine_km,
    is_move,
    record_match_score,
    soundex,
)
from directory_pipeline.models import ProviderRecord


def test_soundex():
    assert soundex("Robert") == soundex("Rupert")
    assert soundex("Smith")[0] == "S"
    assert soundex("") == ""


def test_identical_npi_is_certain_match():
    a = ProviderRecord(provider_id="A", provider_name="John Smith", npi="1234567890")
    b = ProviderRecord(provider_id="B", provider_name="J Smith", npi="1234567890")
    score, reason = record_match_score(a, b)
    assert score == 1.0
    assert "NPI" in reason


def test_fuzzy_duplicate_without_npi():
    a = ProviderRecord(
        provider_id="A",
        provider_name="Robert Lee, MD",
        address="75 Pine Ave, Naples, FL 34102",
        phone="239-555-3000",
    )
    b = ProviderRecord(
        provider_id="B",
        provider_name="Robert Lee",
        address="75 Pine Avenue, Naples, FL 34102",
        phone="239-555-3000",
    )
    clusters = find_duplicate_clusters([a, b])
    assert len(clusters) == 1
    assert set(clusters[0].provider_ids) == {"A", "B"}


def test_no_false_duplicate():
    a = ProviderRecord(
        provider_id="A", provider_name="Robert Lee", address="75 Pine Ave, Naples, FL 34102"
    )
    b = ProviderRecord(
        provider_id="B", provider_name="Maria Garcia", address="900 Bay Rd, Naples, FL 34103"
    )
    assert find_duplicate_clusters([a, b]) == []


def test_is_move():
    assert is_move("100 Main St, Naples, FL 34102", "250 Health Park Dr, Fort Myers, FL 33908")
    assert not is_move("100 Main St, Naples, FL 34102", "100 Main Street, Naples, FL 34102")
    assert not is_move(None, "x")


def test_haversine_km():
    # Naples FL to Fort Myers FL is roughly 40-50 km.
    d = haversine_km((26.142, -81.794), (26.640, -81.872))
    assert 40 <= d <= 70


def test_geocoded_proximity_drives_address_match():
    # Same building, differently-typed address strings: string similarity is weak,
    # but co-located geocodes make it a confident match.
    a = ProviderRecord(provider_id="A", provider_name="Robert Lee", address="75 Pine Ave, Naples")
    b = ProviderRecord(
        provider_id="B", provider_name="Robert Lee", address="Suite 200, 75 Pine Avenue, Naples FL"
    )
    coord = (26.1420, -81.7948)
    with_geo, reason = record_match_score(a, b, coord_a=coord, coord_b=coord)
    without_geo, _ = record_match_score(a, b)
    assert with_geo >= without_geo
    assert "geo=" in reason
