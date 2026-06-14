"""Append-only audit / provenance store (SOLUTION_PLAN §6.7).

Every proposed or applied change writes one immutable JSONL event linking the
old→new value, the supporting source snapshots (content-hashed), the confidence
math, the decision, the actor, and the pipeline version — so any update is
traceable and reproducible months later. JSONL is the portable default; a SQL
table is a drop-in for production querying.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

from directory_pipeline import __version__
from directory_pipeline.models import (
    AuditEvent,
    FieldAssessment,
    ProviderRecord,
    Recommendation,
    RecommendedAction,
    SourceEvidence,
    SourceValue,
)


def _evidence(sources: list[SourceValue], value: str | None) -> list[SourceEvidence]:
    """Snapshot the sources that asserted ``value`` (or all, if value is None)."""
    chosen = [s for s in sources if value is None or s.value == value]
    return [
        SourceEvidence(
            name=s.source_name,
            label=s.source_label,
            source_class=s.source_class,
            url=s.url,
            retrieved_at=s.retrieved_at,
            asserted_value=s.raw_value if s.raw_value is not None else s.value,
            weight=round(s.weight, 4),
            freshness=round(s.freshness, 4),
            snapshot_hash=s.snapshot_hash,
        )
        for s in chosen
    ]


def build_events(
    record: ProviderRecord,
    recommendation: Recommendation,
    assessments: list[FieldAssessment],
    field_sources: dict[str, list[SourceValue]],
    *,
    geo_coord: tuple[float, float] | None = None,
    timestamp: datetime | None = None,
) -> list[AuditEvent]:
    """Turn a pipeline result into one audit event per changed field (or one
    summary event when nothing changed).

    ``geo_coord`` is the Census geocode (lat, lon) of the address, attached to the
    address event so a location update is reproducible from the audit trail alone.
    """
    timestamp = timestamp or datetime.now(timezone.utc)
    by_field = {a.field: a for a in assessments}
    events: list[AuditEvent] = []

    changed = [a for a in assessments if a.changed]
    if not changed:
        events.append(
            AuditEvent(
                event_id=str(uuid.uuid4()),
                provider_id=record.provider_id,
                npi=record.npi,
                field=None,
                old_value=None,
                new_value=None,
                decision=recommendation.recommended_action,
                field_confidence=None,
                overall_confidence=recommendation.overall_confidence,
                risk_class=None,
                conflict=False,
                sources=[],
                reason=recommendation.reason,
                pipeline_version=__version__,
                timestamp=timestamp,
            )
        )
        return events

    for change in recommendation.changes:
        assessment = by_field.get(change.field)
        is_address = change.field == "address"
        events.append(
            AuditEvent(
                event_id=str(uuid.uuid4()),
                provider_id=record.provider_id,
                npi=record.npi,
                field=change.field,
                old_value=change.old_value,
                new_value=change.new_value,
                decision=recommendation.recommended_action,
                field_confidence=change.confidence_score,
                overall_confidence=recommendation.overall_confidence,
                risk_class=assessment.risk_class if assessment else None,
                conflict=assessment.conflict if assessment else False,
                latitude=geo_coord[0] if (is_address and geo_coord) else None,
                longitude=geo_coord[1] if (is_address and geo_coord) else None,
                sources=_evidence(
                    field_sources.get(change.field, []),
                    assessment.proposed_value if assessment else None,
                ),
                reason=recommendation.reason,
                pipeline_version=__version__,
                timestamp=timestamp,
            )
        )
    return events


class AuditLog:
    """Append-only JSONL event log."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, events: Iterable[AuditEvent]) -> int:
        events = list(events)
        if not events:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            for event in events:
                fh.write(event.model_dump_json())
                fh.write("\n")
        return len(events)

    def read_all(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events: list[AuditEvent] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    events.append(AuditEvent.model_validate_json(line))
        return events

    def review_queue(self) -> list[AuditEvent]:
        """Events awaiting a human decision."""
        return [e for e in self.read_all() if e.decision == RecommendedAction.HUMAN_REVIEW]
