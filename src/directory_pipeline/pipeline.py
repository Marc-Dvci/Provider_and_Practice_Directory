"""Pipeline orchestration (SOLUTION_PLAN §5).

Wires the components into the deterministic-first funnel for one record:

    resolve identity → harvest free sources (NPPES, CMS) + gated web/board
    → normalize → score → decide → audit.

Tiers are honored by *ordering and gating*, not by spending: the free government
sources are always consulted; the residual web/board corroborator only contributes
when fixtures/scrapes exist for that record.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from directory_pipeline import config
from directory_pipeline.audit import AuditLog, build_events
from directory_pipeline.logging_config import get_logger
from directory_pipeline.matching import find_duplicate_clusters, is_move
from directory_pipeline.models import (
    DuplicateCluster,
    FieldAssessment,
    ProviderRecord,
    Recommendation,
    RecommendedAction,
    SourceValue,
)
from directory_pipeline.normalize import (
    normalize_active,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_practice_name,
    normalize_specialty,
)
from directory_pipeline.resolve import ResolutionResult, ResolutionStatus, resolve_identity
from directory_pipeline.scoring import build_recommendation
from directory_pipeline.sources import CmsSource, NppesSource, WebSource
from directory_pipeline.sources.census import CensusGeocoder, GeocodeResult

log = get_logger("pipeline")


@dataclass
class PipelineResult:
    record: ProviderRecord
    resolution: ResolutionResult
    recommendation: Recommendation
    assessments: list[FieldAssessment]
    field_sources: dict[str, list[SourceValue]]
    geocode: GeocodeResult | None = None
    signals: list[str] = field(default_factory=list)


def _current_values(record: ProviderRecord) -> dict[str, tuple[str | None, str | None]]:
    active_raw = None if record.active is None else ("Active" if record.active else "Inactive")
    return {
        "provider_name": (normalize_name(record.provider_name).canonical, record.provider_name),
        "specialty": (normalize_specialty(text=record.specialty), record.specialty),
        "address": (normalize_address(record.address).canonical, record.address),
        "phone": (normalize_phone(record.phone).canonical, record.phone),
        "active": (normalize_active(record.active), active_raw),
        "practice_name": (normalize_practice_name(record.practice_name), record.practice_name),
        "website": ((record.website or "").lower() or None, record.website),
    }


class Pipeline:
    """End-to-end reconciliation pipeline."""

    def __init__(
        self,
        settings: config.Settings | None = None,
        *,
        nppes: NppesSource | None = None,
        cms: CmsSource | None = None,
        web: WebSource | None = None,
        geocoder: CensusGeocoder | None = None,
        audit_log: AuditLog | None = None,
        policy: config.ScoringPolicy = config.DEFAULT_POLICY,
        as_of: date | None = None,
    ) -> None:
        self.settings = settings or config.Settings.from_env()
        self.nppes = nppes or NppesSource(self.settings)
        self.cms = cms or CmsSource(self.settings)
        self.web = web or WebSource(self.settings)
        self.geocoder = geocoder or CensusGeocoder(self.settings)
        self.audit = audit_log
        self.policy = policy
        self.as_of = as_of

    # -- single record ---------------------------------------------------- #
    def process_record(self, record: ProviderRecord) -> PipelineResult:
        resolution = resolve_identity(record, self.nppes)

        if not resolution.usable:
            return self._unresolved_result(record, resolution)

        # Trust the resolved NPI downstream (cold-start fills a missing one).
        working = record.model_copy(update={"npi": resolution.npi or record.npi})

        field_sources = self._harvest(working, resolution)
        recommendation, assessments = build_recommendation(
            working,
            field_sources,
            _current_values(working),
            policy=self.policy,
            as_of=self.as_of,
        )
        recommendation = self._annotate_resolution(recommendation, resolution)

        # Validate/standardize the effective address with the free Census geocoder
        # (the proposed value if address is changing, otherwise what we hold).
        geocode = self.geocoder.standardize(self._effective_address(working, recommendation))
        signals = self._detect_signals(working, recommendation)

        self._write_audit(working, recommendation, assessments, field_sources, geocode)
        return PipelineResult(
            working, resolution, recommendation, assessments, field_sources, geocode, signals
        )

    @staticmethod
    def _detect_signals(record: ProviderRecord, recommendation: Recommendation) -> list[str]:
        """Label lifecycle events behind the field changes (SOLUTION_PLAN §6.3):
        provider movement / practice relocation, closure, rebrand, NPI repair."""
        is_org = record.provider_name is None and record.practice_name is not None
        changed = {c.field: c for c in recommendation.changes}
        signals: list[str] = []
        addr = changed.get("address")
        if addr is not None and is_move(
            str(addr.old_value) if addr.old_value else None,
            str(addr.new_value) if addr.new_value else None,
        ):
            kind = "practice relocation" if is_org else "provider movement"
            signals.append(f"{kind}: {addr.old_value} -> {addr.new_value}")
        active = changed.get("active")
        if active is not None and normalize_active(active.new_value) == "inactive":
            signals.append("practice closure" if is_org else "provider inactive/retired")
        rebrand = changed.get("practice_name")
        if rebrand is not None:
            signals.append(f"practice rebrand: {rebrand.old_value} -> {rebrand.new_value}")
        if "npi" in changed:
            signals.append("NPI mismatch -> dedup/repair ticket")
        return signals

    @staticmethod
    def _effective_address(record: ProviderRecord, recommendation: Recommendation) -> str | None:
        for change in recommendation.changes:
            if change.field == "address" and change.new_value:
                return str(change.new_value)
        return record.address

    def _harvest(
        self, record: ProviderRecord, resolution: ResolutionResult
    ) -> dict[str, list[SourceValue]]:
        sources: list[SourceValue] = []
        if resolution.provider is not None:
            sources.extend(self.nppes.to_source_values(resolution.provider))
        cms_record = None
        if record.npi:
            cms_record = self.cms.fetch(record.npi)
            if cms_record is not None:
                sources.extend(self.cms.to_source_values(cms_record))
        sources.extend(
            self.web.harvest(
                record.provider_id,
                record=record,
                nppes_provider=resolution.provider,
                cms_record=cms_record,
            )
        )

        grouped: dict[str, list[SourceValue]] = defaultdict(list)
        for sv in sources:
            grouped[sv.field].append(sv)
        return dict(grouped)

    def _unresolved_result(
        self, record: ProviderRecord, resolution: ResolutionResult
    ) -> PipelineResult:
        # MISMATCH and UNRESOLVED both go to a human: one is a repair ticket, the
        # other a quarantined record we couldn't identify confidently.
        recommendation = Recommendation(
            provider_id=record.provider_id,
            npi=record.npi,
            change_detected=False,
            changes=[],
            overall_confidence=round(resolution.confidence, 4),
            recommended_action=RecommendedAction.HUMAN_REVIEW,
            reason=resolution.note,
        )
        self._write_audit(record, recommendation, [], {}, None)
        return PipelineResult(record, resolution, recommendation, [], {}, None)

    @staticmethod
    def _annotate_resolution(
        recommendation: Recommendation, resolution: ResolutionResult
    ) -> Recommendation:
        if resolution.status in {
            ResolutionStatus.RESOLVED_BY_SEARCH,
            ResolutionStatus.BAD_CHECKDIGIT,
        }:
            recommendation = recommendation.model_copy(
                update={"reason": f"{resolution.note} {recommendation.reason}"}
            )
        return recommendation

    def _write_audit(
        self,
        record: ProviderRecord,
        recommendation: Recommendation,
        assessments: list[FieldAssessment],
        field_sources: dict[str, list[SourceValue]],
        geocode: GeocodeResult | None,
    ) -> None:
        if self.audit is None:
            return
        geo_coord = (
            (geocode.lat, geocode.lon)
            if geocode and geocode.lat is not None and geocode.lon is not None
            else None
        )
        events = build_events(
            record, recommendation, assessments, field_sources, geo_coord=geo_coord
        )
        self.audit.append(events)

    # -- whole directory -------------------------------------------------- #
    def run(self, records: list[ProviderRecord]) -> list[PipelineResult]:
        return [self.process_record(r) for r in records]

    def duplicates(self, records: list[ProviderRecord]) -> list[DuplicateCluster]:
        """Detect duplicate records, using Census-geocoded proximity when available."""
        coords: dict[str, tuple[float, float]] = {}
        for rec in records:
            geo = self.geocoder.standardize(rec.address)
            if geo.lat is not None and geo.lon is not None:
                coords[rec.provider_id] = (geo.lat, geo.lon)
        return find_duplicate_clusters(records, coords=coords)
