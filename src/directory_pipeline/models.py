"""Typed data models for the pipeline.

The public output models (:class:`Recommendation`, :class:`FieldChange`) match the
challenge brief's JSON schema *verbatim* so that consumers see instant compliance.
Internal models (:class:`SourceValue`, :class:`FieldAssessment`, :class:`AuditEvent`)
carry the richer provenance and scoring detail used for decisions and the audit log.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RecommendedAction(str, Enum):
    """Terminal routing decision for a record."""

    NO_CHANGE = "no_change"
    AUTO_UPDATE = "auto_update"
    HUMAN_REVIEW = "human_review"
    DISCARD = "discard"


class RiskClass(str, Enum):
    """How dangerous it is to change a field silently (governs thresholds)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SourceClass(str, Enum):
    """Independence class of a source.

    Corroboration must span *distinct* classes: NPPES and CMS are both ultimately
    provider-self-reported to CMS, so two agreeing government sources are not two
    independent confirmations. See ``scoring.py`` and SOLUTION_PLAN §6.4.
    """

    GOV_SELF_REPORTED = "gov_self_reported"  # NPPES (provider self-attests to CMS)
    GOV_CLAIMS = "gov_claims"  # CMS PECOS / Doctors & Clinicians (enrollment-derived)
    PRACTICE_WEB = "practice_web"  # the practice's own website / roster
    REGULATORY_BOARD = "regulatory_board"  # state medical board license lookup
    GEOCODER = "geocoder"  # US Census geocoder (address validation only, not a value source)


class ProviderRecord(BaseModel):
    """A directory record as held by HealthLynked (the system of record)."""

    model_config = ConfigDict(extra="ignore")

    provider_id: str
    provider_name: str | None = None
    npi: str | None = None
    specialty: str | None = None
    practice_name: str | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    active: bool | None = None
    last_verified_date: date | None = None


class SourceValue(BaseModel):
    """A single field value asserted by a single source, after normalization.

    ``value`` is the canonical/normalized form used for comparison; ``raw_value``
    preserves what the source actually returned for the audit trail. ``weight`` and
    ``freshness`` are populated by the scorer, not the harvester.
    """

    field: str
    value: str | None
    raw_value: str | None = None
    source_name: str  # machine id, e.g. "nppes"
    source_label: str  # human display, e.g. "NPI Registry"
    source_class: SourceClass
    url: str | None = None
    retrieved_at: datetime
    data_as_of: date | None = None
    weight: float = 0.0
    freshness: float = 1.0
    snapshot_hash: str | None = None


class FieldChange(BaseModel):
    """A single proposed field change — matches the brief's ``changes[]`` items."""

    field: str
    old_value: Any | None = None
    new_value: Any | None = None
    confidence_score: float
    supporting_sources: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    """The pipeline's structured recommendation — matches the brief's schema verbatim."""

    provider_id: str
    npi: str | None = None
    change_detected: bool
    changes: list[FieldChange] = Field(default_factory=list)
    overall_confidence: float
    recommended_action: RecommendedAction
    reason: str


class FieldAssessment(BaseModel):
    """Internal per-field scoring detail (not part of the brief output schema)."""

    field: str
    risk_class: RiskClass
    current_value: str | None
    proposed_value: str | None
    changed: bool
    confidence: float
    conflict: bool
    corroborating_classes: int
    # A credible source contradicts the *current* value even though the record's
    # value is the weighted winner (e.g. a board reports inactive while NPPES still
    # lists active). For high-risk fields this must never be silently ignored.
    dissent: bool = False
    dissent_value: str | None = None
    supporting_sources: list[str] = Field(default_factory=list)
    competing_sources: list[str] = Field(default_factory=list)
    raw_current: str | None = None
    raw_proposed: str | None = None


class SourceEvidence(BaseModel):
    """Provenance for one source value, frozen into an audit event."""

    name: str
    label: str
    source_class: SourceClass
    url: str | None = None
    retrieved_at: datetime
    asserted_value: str | None = None
    weight: float
    freshness: float
    snapshot_hash: str | None = None


class AuditEvent(BaseModel):
    """One immutable, append-only audit record (SOLUTION_PLAN §6.7)."""

    event_id: str
    provider_id: str
    npi: str | None = None
    field: str | None = None
    old_value: Any | None = None
    new_value: Any | None = None
    decision: RecommendedAction
    field_confidence: float | None = None
    overall_confidence: float
    risk_class: RiskClass | None = None
    conflict: bool = False
    latitude: float | None = None  # Census geocode of the address field (when matched)
    longitude: float | None = None
    sources: list[SourceEvidence] = Field(default_factory=list)
    reason: str = ""
    actor: str = "pipeline"
    pipeline_version: str
    timestamp: datetime


class DuplicateCluster(BaseModel):
    """A set of directory records judged to be the same real-world entity."""

    cluster_id: str
    provider_ids: list[str]
    npi: str | None = None
    match_score: float
    reason: str
