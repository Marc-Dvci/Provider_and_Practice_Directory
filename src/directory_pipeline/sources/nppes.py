"""NPPES NPI Registry source (SOLUTION_PLAN §4).

Authoritative for identity, NPI, taxonomy→specialty, practice/mailing address,
phone, and deactivation. Covers both halves of the brief: Type-1 NPIs are
individual providers, Type-2 NPIs are organizations/practices. Free API, no key.

Live: ``GET {base}?version=2.1&number={npi}`` and name/org searches.
Offline: fixtures under ``data/fixtures/nppes/{npi}.json`` and
``data/fixtures/nppes_search/{key}.json`` (raw API-shaped payloads).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from directory_pipeline.config import Settings
from directory_pipeline.models import SourceClass, SourceValue
from directory_pipeline.normalize import (
    NormalizedName,
    normalize_active,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_practice_name,
    normalize_specialty,
    specialty_label,
)
from directory_pipeline.sources.base import HttpClient, load_fixture, snapshot_hash, utcnow

SOURCE_NAME = "nppes"
SOURCE_LABEL = "NPI Registry"
SOURCE_CLASS = SourceClass.GOV_SELF_REPORTED


@dataclass
class NppesProvider:
    """Parsed NPPES record (the fields the pipeline consumes)."""

    npi: str
    enumeration_type: str
    status: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    credential: str | None = None
    organization_name: str | None = None
    taxonomy_code: str | None = None
    taxonomy_desc: str | None = None
    address_1: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    telephone: str | None = None
    last_updated: str | None = None  # NPPES "basic.last_updated" (YYYY-MM-DD)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_organization(self) -> bool:
        return self.enumeration_type.upper().endswith("2")

    def data_as_of(self) -> date | None:
        """The date NPPES last updated this record — drives the freshness factor."""
        return _parse_date(self.last_updated)

    def normalized_name(self) -> NormalizedName:
        if self.is_organization:
            return NormalizedName()
        full = " ".join(p for p in (self.first_name, self.last_name) if p)
        return normalize_name(full)

    def display_name(self) -> str:
        if self.is_organization:
            return self.organization_name or self.npi
        parts = [p for p in (self.first_name, self.last_name) if p]
        name = " ".join(parts)
        return f"{name}, {self.credential}" if self.credential else name

    def address_string(self) -> str | None:
        # NPPES returns ZIP as 9 digits with no hyphen ("341090000"); format it so
        # the displayed/raw value is clean and parseable (ZIP5 or ZIP5-4).
        tail = " ".join(p for p in (self.state, _format_zip(self.postal_code)) if p)
        line = ", ".join(b for b in (self.address_1, self.city) if b)
        return ", ".join(p for p in (line, tail) if p) or None

    @classmethod
    def from_api_result(cls, result: dict[str, Any]) -> NppesProvider:
        basic = result.get("basic", {}) or {}
        taxonomies = result.get("taxonomies", []) or []
        primary = next(
            (t for t in taxonomies if t.get("primary")), taxonomies[0] if taxonomies else {}
        )
        addresses = result.get("addresses", []) or []
        location = next(
            (a for a in addresses if a.get("address_purpose") == "LOCATION"),
            addresses[0] if addresses else {},
        )
        return cls(
            npi=str(result.get("number", "")),
            enumeration_type=str(result.get("enumeration_type", "NPI-1")),
            status=basic.get("status"),
            first_name=basic.get("first_name"),
            last_name=basic.get("last_name"),
            credential=basic.get("credential"),
            organization_name=basic.get("organization_name"),
            taxonomy_code=primary.get("code"),
            taxonomy_desc=primary.get("desc"),
            address_1=location.get("address_1"),
            city=location.get("city"),
            state=location.get("state"),
            postal_code=location.get("postal_code"),
            telephone=location.get("telephone_number"),
            last_updated=basic.get("last_updated"),
            raw=result,
        )


class NppesSource:
    """Fetch/search NPPES and emit :class:`SourceValue`s."""

    def __init__(
        self,
        settings: Settings | None = None,
        http: HttpClient | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.http = http or HttpClient(self.settings)

    # -- lookups ---------------------------------------------------------- #
    def fetch(self, npi: str) -> NppesProvider | None:
        results = self._results_for_npi(npi)
        if not results:
            return None
        return NppesProvider.from_api_result(results[0])

    def search(
        self,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        organization_name: str | None = None,
        state: str | None = None,
        taxonomy_description: str | None = None,
    ) -> list[NppesProvider]:
        results = self._search_results(
            first_name=first_name,
            last_name=last_name,
            organization_name=organization_name,
            state=state,
            taxonomy_description=taxonomy_description,
        )
        return [NppesProvider.from_api_result(r) for r in results]

    # -- transport -------------------------------------------------------- #
    def _results_for_npi(self, npi: str) -> list[dict[str, Any]]:
        if self.settings.offline:
            payload = load_fixture(self.settings, "nppes", f"{npi}.json")
            return (payload or {}).get("results", []) if payload else []
        payload = self.http.get_json(
            self.settings.nppes_base_url, params={"version": "2.1", "number": npi}
        )
        return payload.get("results", []) if payload else []

    def _search_results(self, **params: str | None) -> list[dict[str, Any]]:
        if self.settings.offline:
            key = _search_key(params)
            payload = load_fixture(self.settings, "nppes_search", f"{key}.json")
            return (payload or {}).get("results", []) if payload else []
        query: dict[str, Any] = {"version": "2.1", "limit": 20}
        for k, v in params.items():
            if v:
                query[k] = v
        payload = self.http.get_json(self.settings.nppes_base_url, params=query)
        return payload.get("results", []) if payload else []

    # -- value extraction ------------------------------------------------- #
    def to_source_values(self, provider: NppesProvider) -> list[SourceValue]:
        retrieved_at = utcnow()
        digest = snapshot_hash(provider.raw)
        as_of = provider.data_as_of()

        def sv(field_name: str, value: str | None, raw_value: str | None) -> SourceValue | None:
            if value is None:
                return None
            return SourceValue(
                field=field_name,
                value=value,
                raw_value=raw_value,
                source_name=SOURCE_NAME,
                source_label=SOURCE_LABEL,
                source_class=SOURCE_CLASS,
                url=f"https://npiregistry.cms.hhs.gov/provider-view/{provider.npi}",
                retrieved_at=retrieved_at,
                data_as_of=as_of,
                snapshot_hash=digest,
            )

        values: list[SourceValue | None] = []
        if provider.is_organization:
            values.append(
                sv(
                    "practice_name",
                    normalize_practice_name(provider.organization_name),
                    provider.organization_name,
                )
            )
        else:
            name = provider.normalized_name()
            values.append(sv("provider_name", name.canonical, provider.display_name()))
            values.append(
                sv(
                    "specialty",
                    normalize_specialty(taxonomy_code=provider.taxonomy_code),
                    provider.taxonomy_desc or specialty_label(provider.taxonomy_code),
                )
            )
            values.append(
                sv("active", normalize_active(provider.status), _status_label(provider.status))
            )

        addr = normalize_address(
            street=provider.address_1,
            city=provider.city,
            state=provider.state,
            zip_code=provider.postal_code,
        )
        values.append(sv("address", addr.canonical, provider.address_string()))
        phone = normalize_phone(provider.telephone)
        values.append(sv("phone", phone.canonical, _pretty_phone(provider.telephone)))

        return [v for v in values if v is not None]


def _format_zip(postal_code: str | None) -> str | None:
    """Format an NPPES postal code to ZIP5 or ZIP5-4 for clean display/parsing."""
    if not postal_code:
        return None
    digits = re.sub(r"\D", "", postal_code)
    if len(digits) >= 9 and digits[5:9] != "0000":
        return f"{digits[:5]}-{digits[5:9]}"
    return digits[:5] if len(digits) >= 5 else (digits or None)


def _parse_date(value: str | None) -> date | None:
    """Parse an NPPES ``YYYY-MM-DD`` (or ``MM/DD/YYYY``) date string, tolerantly."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value[:10], fmt).date()
        except ValueError:
            continue
    return None


def _status_label(status: str | None) -> str | None:
    if status is None:
        return None
    return {"A": "Active", "I": "Deactivated"}.get(status.upper(), status)


def _pretty_phone(raw: str | None) -> str | None:
    return raw


def _search_key(params: dict[str, str | None]) -> str:
    """Deterministic fixture key for an offline search."""
    org = params.get("organization_name")
    if org:
        base = re.sub(r"[^a-z0-9]+", "_", org.lower()).strip("_")
        return f"org_{base}"
    last = (params.get("last_name") or "").lower()
    first = (params.get("first_name") or "").lower()
    return re.sub(r"[^a-z0-9]+", "_", f"{last}_{first}").strip("_")
