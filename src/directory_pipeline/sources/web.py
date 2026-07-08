"""Practice-website / state-board corroborators (Tier 3, gated & residual-only).

In production these are scrape + LLM-extract (the website) and per-state license
lookups (the board) — the only paid/effortful tier, reached only for records the
free tiers couldn't resolve. The LLM *extracts* values from fetched page text and
never invents them; the extracted value must still clear the scoring gate.

Here, to keep the demo deterministic and offline, this source reads either
pre-captured extractions from ``data/fixtures/web/{provider_id}.json`` or discovered
website candidates from ``data/fixtures/web_discovery/{provider_id}.json``. The
fixture shapes mirror what licensed search + extraction providers would emit, so
the rest of the pipeline is identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from directory_pipeline.config import Settings
from directory_pipeline.logging_config import get_logger
from directory_pipeline.models import ProviderRecord, SourceClass, SourceValue
from directory_pipeline.normalize import (
    normalize_active,
    normalize_address,
    normalize_phone,
    normalize_practice_name,
)
from directory_pipeline.sources.base import load_fixture, snapshot_hash, utcnow
from directory_pipeline.sources.web_discovery import WebsiteDiscoverySource

if TYPE_CHECKING:
    from directory_pipeline.sources.cms import CmsRecord
    from directory_pipeline.sources.nppes import NppesProvider

log = get_logger("sources.web")

_NORMALIZERS = {
    "phone": lambda v: normalize_phone(v).canonical,
    "address": lambda v: normalize_address(v).canonical,
    "practice_name": normalize_practice_name,
    "active": normalize_active,
    "website": lambda v: (v or "").strip().lower() or None,
}


class WebSource:
    """Residual corroborator. Offline-only here; production would scrape + extract."""

    def __init__(
        self,
        settings: Settings | None = None,
        discovery: WebsiteDiscoverySource | None = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.discovery = discovery or WebsiteDiscoverySource(self.settings)

    def harvest(
        self,
        provider_id: str,
        *,
        record: ProviderRecord | None = None,
        nppes_provider: NppesProvider | None = None,
        cms_record: CmsRecord | None = None,
    ) -> list[SourceValue]:
        payload = self._load(provider_id)
        if payload is None and record is not None:
            result = self.discovery.discover(
                provider_id,
                record=record,
                nppes_provider=nppes_provider,
                cms_record=cms_record,
            )
            payload = self.discovery.to_web_payload(result)
        if not payload:
            return []
        retrieved_at = utcnow()
        digest = snapshot_hash(payload)
        out: list[SourceValue] = []
        for sub in payload.get("sources", []):
            source_class = SourceClass(sub["source_class"])
            label = sub.get("source_label", sub["source_name"])
            url = sub.get("url")
            for field_name, spec in sub.get("fields", {}).items():
                raw_value = spec.get("value") if isinstance(spec, dict) else spec
                normalizer = _NORMALIZERS.get(field_name, lambda v: v)
                value = normalizer(raw_value) if raw_value is not None else None
                if value is None:
                    continue
                out.append(
                    SourceValue(
                        field=field_name,
                        value=value,
                        raw_value=raw_value,
                        source_name=sub["source_name"],
                        source_label=label,
                        source_class=source_class,
                        url=url,
                        retrieved_at=retrieved_at,
                        snapshot_hash=digest,
                    )
                )
        return out

    def _load(self, provider_id: str) -> dict[str, Any] | None:
        if not self.settings.offline:
            # Production hook: dispatch the scrape + LLM-extraction agent here. The
            # MVP intentionally does not perform live scraping.
            log.info(
                "web/board harvest skipped in live mode for %s (Tier-3 not wired)", provider_id
            )
            return None
        return load_fixture(self.settings, "web", f"{provider_id}.json")
