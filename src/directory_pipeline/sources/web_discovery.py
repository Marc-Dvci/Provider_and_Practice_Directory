"""Practice-website discovery from sparse provider clues.

The production path can plug in licensed search providers (Places, Bing, etc.) to
generate candidates. The scorer here is deterministic and source-agnostic: given
candidate pages, it verifies whether a URL is likely the provider/practice's own
site using NPI/name/practice/address/phone evidence before any extracted values
enter the normal confidence engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

import requests

from directory_pipeline.config import Settings
from directory_pipeline.models import ProviderRecord
from directory_pipeline.normalize import (
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_practice_name,
)
from directory_pipeline.sources.base import load_fixture

if TYPE_CHECKING:
    from directory_pipeline.sources.cms import CmsRecord
    from directory_pipeline.sources.nppes import NppesProvider


_AGGREGATOR_DOMAINS = {
    "healthgrades.com",
    "www.healthgrades.com",
    "webmd.com",
    "doctor.webmd.com",
    "zocdoc.com",
    "www.zocdoc.com",
    "yelp.com",
    "www.yelp.com",
    "npiprofile.com",
    "npidb.org",
    "npiregistry.cms.hhs.gov",
    "data.cms.gov",
}


@dataclass(frozen=True)
class DiscoveryEvidence:
    label: str
    points: float
    detail: str


@dataclass(frozen=True)
class WebsiteCandidateScore:
    provider_id: str
    url: str
    score: float
    status: str
    evidence: list[DiscoveryEvidence] = field(default_factory=list)
    candidate: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebsiteSearchQuery:
    """Normalized search request handed to a licensed search adapter."""

    provider_id: str
    provider_name: str | None = None
    npi: str | None = None
    practice_name: str | None = None
    address: str | None = None
    phone: str | None = None
    specialty: str | None = None

    @classmethod
    def from_context(
        cls,
        provider_id: str,
        *,
        record: ProviderRecord,
        nppes_provider: NppesProvider | None = None,
        cms_record: CmsRecord | None = None,
    ) -> WebsiteSearchQuery:
        provider_name = record.provider_name
        if not provider_name and nppes_provider is not None and not nppes_provider.is_organization:
            provider_name = nppes_provider.display_name()
        practice_name = record.practice_name or getattr(cms_record, "facility_name", None)
        address = (
            record.address
            or (cms_record.address_string() if cms_record is not None else None)
            or (nppes_provider.address_string() if nppes_provider is not None else None)
        )
        phone = (
            record.phone
            or getattr(cms_record, "telephone", None)
            or getattr(nppes_provider, "telephone", None)
        )
        return cls(
            provider_id=provider_id,
            provider_name=provider_name,
            npi=record.npi or getattr(nppes_provider, "npi", None),
            practice_name=practice_name,
            address=address,
            phone=phone,
            specialty=record.specialty,
        )

    def search_terms(self) -> list[str]:
        """Ordered query strings for adapters that expose text search."""
        terms: list[str] = []
        locality = self.address or ""
        if self.practice_name and locality:
            terms.append(f"{self.practice_name} {locality}")
        if self.provider_name and locality:
            terms.append(f"{self.provider_name} {locality}")
        if self.provider_name and self.specialty:
            terms.append(f"{self.provider_name} {self.specialty}")
        if self.npi:
            terms.append(f"NPI {self.npi}")
        return list(dict.fromkeys(t for t in terms if t.strip()))


class WebsiteCandidateProvider(Protocol):
    """Adapter seam for fixture, Places, Bing, or a custom licensed search proxy."""

    def candidates(self, query: WebsiteSearchQuery) -> list[dict[str, Any]]: ...


class FixtureWebsiteCandidateProvider:
    """Offline candidate source used by tests and the reproducible demo."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def candidates(self, query: WebsiteSearchQuery) -> list[dict[str, Any]]:
        payload = load_fixture(self.settings, "web_discovery", f"{query.provider_id}.json")
        return payload.get("candidates", []) if payload else []


class JsonEndpointWebsiteCandidateProvider:
    """Generic licensed-search adapter.

    Point ``DIRPIPE_WEBSITE_SEARCH_BASE_URL`` at a thin internal proxy for Google
    Places, Bing Web Search, or another licensed source. The endpoint receives the
    sparse provider clues as query parameters and returns either a list of candidate
    dictionaries or ``{"candidates": [...]}`` in this module's candidate schema.
    """

    def __init__(self, settings: Settings, session: requests.Session | None = None) -> None:
        self.settings = settings
        self.session = session or requests.Session()

    def candidates(self, query: WebsiteSearchQuery) -> list[dict[str, Any]]:
        if not self.settings.website_search_base_url:
            return []
        headers = {}
        if self.settings.website_search_api_key:
            headers["Authorization"] = f"Bearer {self.settings.website_search_api_key}"
        params = {
            "provider_id": query.provider_id,
            "provider_name": query.provider_name,
            "npi": query.npi,
            "practice_name": query.practice_name,
            "address": query.address,
            "phone": query.phone,
            "specialty": query.specialty,
            "queries": query.search_terms(),
            "top_k": self.settings.website_search_top_k,
        }
        response = self.session.get(
            self.settings.website_search_base_url,
            params={k: v for k, v in params.items() if v not in (None, "", [])},
            headers=headers,
            timeout=self.settings.http_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            return payload
        return payload.get("candidates", []) if isinstance(payload, dict) else []


def _norm_domain(url: str | None) -> str:
    if not url:
        return ""
    netloc = urlparse(url if "://" in url else f"https://{url}").netloc.lower()
    return netloc.removeprefix("www.")


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"[^A-Za-z0-9]+", " ", value.upper())
    return re.sub(r"\s+", " ", text).strip() or None


def _iter_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v not in (None, "")]
    return [str(value)]


def _contains_any(haystack: str | None, needles: list[str]) -> bool:
    if not haystack:
        return False
    return any(n and n in haystack for n in needles)


class WebsiteDiscoverySource:
    """Score candidate official-practice websites for a provider/practice record."""

    verified_threshold = 0.72
    probable_threshold = 0.55

    def __init__(
        self,
        settings: Settings | None = None,
        candidate_provider: WebsiteCandidateProvider | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.candidate_provider = candidate_provider or self._default_candidate_provider()

    def discover(
        self,
        provider_id: str,
        *,
        record: ProviderRecord,
        nppes_provider: NppesProvider | None = None,
        cms_record: CmsRecord | None = None,
    ) -> WebsiteCandidateScore | None:
        query = WebsiteSearchQuery.from_context(
            provider_id,
            record=record,
            nppes_provider=nppes_provider,
            cms_record=cms_record,
        )
        candidates = self.candidate_provider.candidates(query)
        scored = [
            self.score_candidate(
                provider_id,
                candidate,
                record=record,
                nppes_provider=nppes_provider,
                cms_record=cms_record,
            )
            for candidate in candidates
        ]
        scored = [s for s in scored if s.url]
        return max(scored, key=lambda s: s.score, default=None)

    def to_web_payload(self, result: WebsiteCandidateScore | None) -> dict[str, Any] | None:
        if result is None or result.status not in {"verified_official_site", "probable_site"}:
            return None
        fields = result.candidate.get("fields", {})
        allowed = {
            k: v
            for k, v in fields.items()
            if k in {"address", "phone", "practice_name", "provider_name", "active"}
            and v not in (None, "")
        }
        if not allowed:
            return None
        return {
            "provider_id": result.provider_id,
            "discovery": {
                "status": result.status,
                "score": result.score,
                "evidence": [
                    {"label": e.label, "points": e.points, "detail": e.detail}
                    for e in result.evidence
                ],
            },
            "sources": [
                {
                    "source_name": "practice_web_discovered",
                    "source_label": "Discovered Practice Website",
                    "source_class": "practice_web",
                    "url": result.url,
                    "fields": {k: {"value": v} for k, v in allowed.items()},
                }
            ],
        }

    def score_candidate(
        self,
        provider_id: str,
        candidate: dict[str, Any],
        *,
        record: ProviderRecord,
        nppes_provider: NppesProvider | None = None,
        cms_record: CmsRecord | None = None,
    ) -> WebsiteCandidateScore:
        url = str(candidate.get("url") or "")
        fields = candidate.get("fields", {})
        evidence: list[DiscoveryEvidence] = []

        domain = _norm_domain(url)
        if domain in _AGGREGATOR_DOMAINS:
            evidence.append(
                DiscoveryEvidence("aggregator_penalty", -0.35, f"{domain} is not an official site")
            )
        elif domain:
            evidence.append(DiscoveryEvidence("own_domain", 0.05, f"{domain} is eligible"))

        practice_targets = self._practice_targets(record, nppes_provider, cms_record)
        cand_practice = normalize_practice_name(fields.get("practice_name"))
        if cand_practice and cand_practice in practice_targets:
            evidence.append(DiscoveryEvidence("practice_name", 0.20, fields["practice_name"]))

        provider_targets = self._provider_targets(record, nppes_provider)
        candidate_names = [
            normalize_name(v).canonical
            for v in _iter_values(fields.get("provider_names") or fields.get("provider_name"))
        ]
        if provider_targets and any(n in provider_targets for n in candidate_names if n):
            evidence.append(DiscoveryEvidence("provider_roster", 0.20, "provider appears on site"))

        npi_targets = {v for v in (record.npi, getattr(nppes_provider, "npi", None)) if v}
        npi_values = {v for v in _iter_values(fields.get("npi") or fields.get("npis")) if v}
        if npi_targets and npi_targets & npi_values:
            evidence.append(
                DiscoveryEvidence("npi_on_page", 0.15, ", ".join(sorted(npi_targets & npi_values)))
            )

        candidate_phone = normalize_phone(fields.get("phone")).canonical
        if candidate_phone and candidate_phone in self._phone_targets(
            record, nppes_provider, cms_record
        ):
            evidence.append(DiscoveryEvidence("phone_match", 0.18, fields["phone"]))

        candidate_address = normalize_address(fields.get("address")).canonical
        if candidate_address and candidate_address in self._address_targets(
            record, nppes_provider, cms_record
        ):
            evidence.append(DiscoveryEvidence("address_match", 0.20, fields["address"]))

        page_text = _clean_text(fields.get("page_text"))
        text_needles = [_clean_text(v) for v in _iter_values(record.provider_name)]
        text_needles += [_clean_text(v) for v in _iter_values(record.practice_name)]
        if _contains_any(page_text, [v for v in text_needles if v]):
            evidence.append(DiscoveryEvidence("page_text_match", 0.07, "page text mentions record"))

        score = round(min(max(sum(e.points for e in evidence), 0.0), 1.0), 4)
        if score >= self.verified_threshold:
            status = "verified_official_site"
        elif score >= self.probable_threshold:
            status = "probable_site"
        else:
            status = "ambiguous_or_rejected"
        return WebsiteCandidateScore(provider_id, url, score, status, evidence, candidate)

    def _default_candidate_provider(self) -> WebsiteCandidateProvider:
        if not self.settings.offline and self.settings.website_search_base_url:
            return JsonEndpointWebsiteCandidateProvider(self.settings)
        return FixtureWebsiteCandidateProvider(self.settings)

    @staticmethod
    def _practice_targets(
        record: ProviderRecord,
        nppes_provider: NppesProvider | None,
        cms_record: CmsRecord | None,
    ) -> set[str]:
        names = [record.practice_name, getattr(cms_record, "facility_name", None)]
        if nppes_provider is not None and getattr(nppes_provider, "is_organization", False):
            names.append(getattr(nppes_provider, "organization_name", None))
        return {v for v in (normalize_practice_name(n) for n in names) if v}

    @staticmethod
    def _provider_targets(record: ProviderRecord, nppes_provider: NppesProvider | None) -> set[str]:
        names = [normalize_name(record.provider_name).canonical]
        if nppes_provider is not None and not getattr(nppes_provider, "is_organization", False):
            names.append(nppes_provider.normalized_name().canonical)
        return {v for v in names if v}

    @staticmethod
    def _phone_targets(
        record: ProviderRecord,
        nppes_provider: NppesProvider | None,
        cms_record: CmsRecord | None,
    ) -> set[str]:
        phones = [
            record.phone,
            getattr(nppes_provider, "telephone", None),
            getattr(cms_record, "telephone", None),
        ]
        return {v for v in (normalize_phone(p).canonical for p in phones) if v}

    @staticmethod
    def _address_targets(
        record: ProviderRecord,
        nppes_provider: NppesProvider | None,
        cms_record: CmsRecord | None,
    ) -> set[str]:
        addresses = [
            record.address,
            nppes_provider.address_string() if nppes_provider is not None else None,
            cms_record.address_string() if cms_record is not None else None,
        ]
        return {v for v in (normalize_address(a).canonical for a in addresses) if v}
