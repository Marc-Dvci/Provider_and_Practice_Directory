from __future__ import annotations

from directory_pipeline.config import Settings
from directory_pipeline.models import SourceClass
from directory_pipeline.sources import (
    CmsSource,
    JsonEndpointWebsiteCandidateProvider,
    NppesSource,
    WebsiteDiscoverySource,
    WebsiteSearchQuery,
    WebSource,
)
from directory_pipeline.sources.census import CensusGeocoder


def test_nppes_fetch_and_values(settings: Settings):
    nppes = NppesSource(settings)
    provider = nppes.fetch("1234567890")
    assert provider is not None
    assert provider.display_name() == "JOHN SMITH, M.D."
    values = {sv.field: sv for sv in nppes.to_source_values(provider)}
    assert values["phone"].value == "+12395559000"
    assert values["specialty"].value == "207RC0000X"
    assert values["address"].source_class == SourceClass.GOV_SELF_REPORTED


def test_nppes_search(settings: Settings):
    nppes = NppesSource(settings)
    results = nppes.search(first_name="Jane", last_name="Doe", state="FL")
    assert [p.npi for p in results] == ["1002003006"]


def test_cms_fetch(settings: Settings):
    cms = CmsSource(settings)
    record = cms.fetch("1234567890")
    assert record is not None
    assert record.facility_name == "ABC Heart Group"
    values = {sv.field: sv for sv in cms.to_source_values(record)}
    assert values["address"].source_class == SourceClass.GOV_CLAIMS


def test_web_harvest(settings: Settings):
    web = WebSource(settings)
    values = web.harvest("HL_004")
    assert any(sv.field == "active" and sv.value == "inactive" for sv in values)


def test_website_discovery_selects_official_site(settings: Settings, records_by_id):
    record = records_by_id["HL_001"]
    nppes_provider = NppesSource(settings).fetch(record.npi)
    cms_record = CmsSource(settings).fetch(record.npi)

    result = WebsiteDiscoverySource(settings).discover(
        record.provider_id,
        record=record,
        nppes_provider=nppes_provider,
        cms_record=cms_record,
    )

    assert result is not None
    assert result.url == "https://abcheart.example.com"
    assert result.status == "verified_official_site"
    assert result.score >= 0.9
    assert {e.label for e in result.evidence} >= {
        "practice_name",
        "provider_roster",
        "npi_on_page",
        "phone_match",
    }


def test_website_search_query_uses_sparse_provider_clues(settings: Settings, records_by_id):
    record = records_by_id["HL_001"]
    query = WebsiteSearchQuery.from_context(
        record.provider_id,
        record=record,
        nppes_provider=NppesSource(settings).fetch(record.npi),
        cms_record=CmsSource(settings).fetch(record.npi),
    )

    assert query.provider_name == "John Smith, MD"
    assert query.npi == "1234567890"
    assert query.practice_name == "ABC Heart Group"
    assert any("ABC Heart Group" in term for term in query.search_terms())


def test_json_endpoint_candidate_provider_maps_to_candidate_schema():
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"url": "https://clinic.example.com", "fields": {}}]}

    class _Session:
        def __init__(self):
            self.calls = []

        def get(self, url, *, params, headers, timeout):
            self.calls.append((url, params, headers, timeout))
            return _Response()

    settings = Settings(
        website_search_base_url="https://search-proxy.example.com/provider-sites",
        website_search_api_key="secret",
    )
    session = _Session()
    query = WebsiteSearchQuery(
        provider_id="HL_X",
        provider_name="Jane Doe, NP",
        npi="1002003006",
        practice_name="Gulf Coast Family Care",
        address="300 1st St, Fort Myers, FL 33901",
        phone="239-555-2000",
        specialty="Family Medicine",
    )

    candidates = JsonEndpointWebsiteCandidateProvider(settings, session=session).candidates(query)

    assert candidates == [{"url": "https://clinic.example.com", "fields": {}}]
    url, params, headers, timeout = session.calls[0]
    assert url == "https://search-proxy.example.com/provider-sites"
    assert params["npi"] == "1002003006"
    assert params["top_k"] == 8
    assert headers["Authorization"] == "Bearer secret"
    assert timeout == 15.0


def test_web_harvest_discovers_site_when_fixture_missing(settings: Settings, records_by_id):
    record = records_by_id["HL_005"]
    nppes_provider = NppesSource(settings).fetch(record.npi)
    cms_record = CmsSource(settings).fetch(record.npi)

    values = WebSource(settings).harvest(
        record.provider_id,
        record=record,
        nppes_provider=nppes_provider,
        cms_record=cms_record,
    )

    discovered = [sv for sv in values if sv.source_name == "practice_web_discovered"]
    assert discovered
    assert {sv.field for sv in discovered} == {"address", "phone", "practice_name"}
    assert {sv.url for sv in discovered} == {"https://bayfrontinternal.example.com"}


def test_census_offline_standardizes(settings: Settings):
    geocoder = CensusGeocoder(settings)
    result = geocoder.standardize("100 Main St, Naples, FL 34102")
    assert result.matched
    assert result.canonical == "100 MAIN ST, NAPLES, FL 34102"
    assert geocoder.standardize(None).matched is False
