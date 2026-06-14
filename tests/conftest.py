"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from directory_pipeline import config
from directory_pipeline.ingest import load_directory
from directory_pipeline.models import ProviderRecord
from directory_pipeline.pipeline import Pipeline
from directory_pipeline.sources import CmsSource, NppesSource, WebSource


@pytest.fixture()
def settings() -> config.Settings:
    """Offline settings pointing at the bundled fixtures."""
    return config.Settings(offline=True)


@pytest.fixture()
def nppes(settings: config.Settings) -> NppesSource:
    return NppesSource(settings)


@pytest.fixture()
def pipeline(settings: config.Settings) -> Pipeline:
    return Pipeline(
        settings,
        nppes=NppesSource(settings),
        cms=CmsSource(settings),
        web=WebSource(settings),
    )


@pytest.fixture()
def directory() -> list[ProviderRecord]:
    return load_directory()


@pytest.fixture()
def records_by_id(directory: list[ProviderRecord]) -> dict[str, ProviderRecord]:
    return {r.provider_id: r for r in directory}
