from __future__ import annotations

from directory_pipeline.config import Settings
from directory_pipeline.models import SourceClass
from directory_pipeline.sources import CmsSource, NppesSource, WebSource
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


def test_census_offline_standardizes(settings: Settings):
    geocoder = CensusGeocoder(settings)
    result = geocoder.standardize("100 Main St, Naples, FL 34102")
    assert result.matched
    assert result.canonical == "100 MAIN ST, NAPLES, FL 34102"
    assert geocoder.standardize(None).matched is False
