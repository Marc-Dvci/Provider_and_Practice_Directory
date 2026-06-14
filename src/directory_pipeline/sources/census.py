"""US Census geocoder — address standardization/validation only (SOLUTION_PLAN §4).

Used to canonicalize and confirm an address we already hold (free, no key); per
the brief it is a *validator*, not a value source, so it does not assert directory
values into the confidence formula. Offline, it echoes the locally-normalized form.
"""

from __future__ import annotations

from dataclasses import dataclass

from directory_pipeline.config import Settings
from directory_pipeline.logging_config import get_logger
from directory_pipeline.normalize import normalize_address
from directory_pipeline.sources.base import HttpClient

log = get_logger("sources.census")


@dataclass(frozen=True)
class GeocodeResult:
    matched: bool
    canonical: str | None
    lat: float | None = None
    lon: float | None = None


class CensusGeocoder:
    def __init__(self, settings: Settings | None = None, http: HttpClient | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self.http = http or HttpClient(self.settings)

    def standardize(self, address: str | None) -> GeocodeResult:
        if not address:
            return GeocodeResult(matched=False, canonical=None)
        if self.settings.offline:
            return GeocodeResult(matched=True, canonical=normalize_address(address).canonical)
        try:
            payload = self.http.get_json(
                f"{self.settings.census_base_url}locations/onelineaddress",
                params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
            )
            matches = payload.get("result", {}).get("addressMatches", [])
            if not matches:
                return GeocodeResult(matched=False, canonical=normalize_address(address).canonical)
            top = matches[0]
            coords = top.get("coordinates", {})
            return GeocodeResult(
                matched=True,
                canonical=normalize_address(top.get("matchedAddress", address)).canonical,
                lat=coords.get("y"),
                lon=coords.get("x"),
            )
        except Exception as exc:  # geocoding is best-effort; never block the pipeline
            log.warning("census geocode failed for %r: %s", address, exc)
            return GeocodeResult(matched=False, canonical=normalize_address(address).canonical)
