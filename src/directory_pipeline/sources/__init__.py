"""Source harvesters (SOLUTION_PLAN §4, box 2).

Each source knows how to turn an authoritative feed into a list of
:class:`~directory_pipeline.models.SourceValue` objects (field, normalized value,
provenance). Free government feeds (NPPES, CMS) are always queried; the practice
website / state board are gated, residual-only corroborators.

Every source runs in two modes: **live** (real HTTP) and **offline** (bundled
fixtures), selected by :class:`~directory_pipeline.config.Settings`.offline so the
demo and CI run with no network and no API keys.
"""

from __future__ import annotations

from directory_pipeline.sources.cms import CmsSource
from directory_pipeline.sources.nppes import NppesProvider, NppesSource
from directory_pipeline.sources.web import WebSource
from directory_pipeline.sources.web_discovery import (
    FixtureWebsiteCandidateProvider,
    JsonEndpointWebsiteCandidateProvider,
    WebsiteCandidateProvider,
    WebsiteDiscoverySource,
    WebsiteSearchQuery,
)

__all__ = [
    "CmsSource",
    "FixtureWebsiteCandidateProvider",
    "JsonEndpointWebsiteCandidateProvider",
    "NppesProvider",
    "NppesSource",
    "WebSource",
    "WebsiteCandidateProvider",
    "WebsiteDiscoverySource",
    "WebsiteSearchQuery",
]
