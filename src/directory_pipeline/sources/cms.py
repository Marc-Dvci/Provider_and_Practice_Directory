"""CMS Doctors & Clinicians source (Provider Data Catalog dataset ``mj5m-pzi6``).

Authoritative for Medicare-enrolled clinicians: group/practice affiliation
(PAC ID), practice locations, phone, and active enrollment. Confirms "this
provider works *here* now" — an independence class distinct from NPPES.

Live: ``GET {base}{dataset}/0`` with NPI conditions.
Offline: fixtures under ``data/fixtures/cms/{npi}.json`` (raw datastore payloads).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from directory_pipeline.config import Settings
from directory_pipeline.models import SourceClass, SourceValue
from directory_pipeline.normalize import (
    normalize_address,
    normalize_phone,
    normalize_practice_name,
)
from directory_pipeline.sources.base import HttpClient, load_fixture, snapshot_hash, utcnow

SOURCE_NAME = "cms"
SOURCE_LABEL = "CMS Doctors & Clinicians"
SOURCE_CLASS = SourceClass.GOV_CLAIMS


def _first(row: dict[str, Any], *keys: str) -> str | None:
    """Return the first present, non-empty value among differently-cased keys."""
    lower = {k.lower(): v for k, v in row.items()}
    for key in keys:
        val = lower.get(key.lower())
        if val not in (None, "", " "):
            return str(val)
    return None


@dataclass
class CmsRecord:
    npi: str
    facility_name: str | None = None
    org_pac_id: str | None = None
    address_1: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    telephone: str | None = None
    last_updated: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def address_string(self) -> str | None:
        line = ", ".join(b for b in (self.address_1, self.city) if b)
        tail = " ".join(p for p in (self.state, self.zip_code) if p)
        return ", ".join(p for p in (line, tail) if p) or None

    def data_as_of(self) -> date | None:
        """File/row date when present — drives the freshness factor."""
        if not self.last_updated:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(self.last_updated[:10], fmt).date()
            except ValueError:
                continue
        return None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CmsRecord:
        return cls(
            npi=_first(row, "NPI", "npi") or "",
            facility_name=_first(row, "Facility Name", "facility_name", "org_nm"),
            org_pac_id=_first(row, "org_pac_id", "Organization PAC ID"),
            address_1=_first(row, "adr_ln_1", "Address Line 1", "adr_ln1"),
            city=_first(row, "City/Town", "citytown", "City", "cty"),
            state=_first(row, "State", "st", "State/Province"),
            zip_code=_first(row, "ZIP Code", "zip_cd", "Zip Code"),
            telephone=_first(row, "Telephone Number", "phn_numbr", "Phone Number"),
            last_updated=_first(row, "Last Updated", "last_updated", "data_as_of"),
            raw=row,
        )


class CmsSource:
    def __init__(self, settings: Settings | None = None, http: HttpClient | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.http = http or HttpClient(self.settings)

    def fetch(self, npi: str) -> CmsRecord | None:
        rows = self._rows_for_npi(npi)
        return CmsRecord.from_row(rows[0]) if rows else None

    def _rows_for_npi(self, npi: str) -> list[dict[str, Any]]:
        if self.settings.offline:
            payload = load_fixture(self.settings, "cms", f"{npi}.json")
            return (payload or {}).get("results", []) if payload else []
        url = f"{self.settings.cms_base_url}{self.settings.cms_doctors_dataset}/0"
        params = {
            "conditions[0][property]": "NPI",
            "conditions[0][value]": npi,
            "conditions[0][operator]": "=",
            "limit": 50,
        }
        payload = self.http.get_json(url, params=params)
        return payload.get("results", []) if payload else []

    def to_source_values(self, record: CmsRecord) -> list[SourceValue]:
        retrieved_at = utcnow()
        digest = snapshot_hash(record.raw)
        as_of = record.data_as_of()

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
                url="https://data.cms.gov/provider-data/dataset/mj5m-pzi6",
                retrieved_at=retrieved_at,
                data_as_of=as_of,
                snapshot_hash=digest,
            )

        addr = normalize_address(
            street=record.address_1,
            city=record.city,
            state=record.state,
            zip_code=record.zip_code,
        )
        phone = normalize_phone(record.telephone)
        values = [
            sv("address", addr.canonical, record.address_string()),
            sv("phone", phone.canonical, record.telephone),
            sv(
                "practice_name", normalize_practice_name(record.facility_name), record.facility_name
            ),
        ]
        return [v for v in values if v is not None]
