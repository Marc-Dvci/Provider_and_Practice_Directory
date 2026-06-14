from __future__ import annotations

from datetime import datetime, timezone

from directory_pipeline.models import RecommendedAction, SourceClass, SourceValue
from directory_pipeline.scoring import assess_field, decide


def sv(field, value, source_class, label="src", name="src", raw=None):
    return SourceValue(
        field=field,
        value=value,
        raw_value=raw if raw is not None else value,
        source_name=name,
        source_label=label,
        source_class=source_class,
        retrieved_at=datetime.now(timezone.utc),
    )


def test_corroborated_change_is_confident_and_unconflicted():
    sources = [
        sv("phone", "+12395559000", SourceClass.GOV_SELF_REPORTED, "NPI Registry"),
        sv("phone", "+12395559000", SourceClass.PRACTICE_WEB, "Practice Website"),
    ]
    a = assess_field("phone", "+12395551234", "239-555-1234", sources)
    assert a is not None
    assert a.changed is True
    assert a.proposed_value == "+12395559000"
    assert a.conflict is False
    assert a.corroborating_classes == 2
    assert 0.85 <= a.confidence <= 0.92
    assert set(a.supporting_sources) == {"NPI Registry", "Practice Website"}


def test_conflict_detected_when_classes_disagree():
    sources = [
        sv(
            "address",
            "100 MAIN ST, NAPLES, FL 34102",
            SourceClass.GOV_SELF_REPORTED,
            "NPI Registry",
        ),
        sv("address", "250 HEALTH PARK DR, FORT MYERS, FL 33908", SourceClass.GOV_CLAIMS, "CMS"),
        sv("address", "250 HEALTH PARK DR, FORT MYERS, FL 33908", SourceClass.PRACTICE_WEB, "Web"),
    ]
    a = assess_field("address", "100 MAIN ST, NAPLES, FL 34102", "100 Main St", sources)
    assert a is not None
    assert a.changed is True
    assert a.proposed_value == "250 HEALTH PARK DR, FORT MYERS, FL 33908"
    assert a.conflict is True


def test_no_change_when_source_confirms_current():
    sources = [sv("specialty", "207RC0000X", SourceClass.GOV_SELF_REPORTED, "NPI Registry")]
    a = assess_field("specialty", "207RC0000X", "Cardiology", sources)
    assert a is not None
    assert a.changed is False


def test_same_class_sources_are_decorrelated():
    same_class = [
        sv("phone", "+12395559000", SourceClass.GOV_SELF_REPORTED),
        sv("phone", "+12395559000", SourceClass.GOV_SELF_REPORTED),
    ]
    diff_class = [
        sv("phone", "+12395559000", SourceClass.GOV_SELF_REPORTED),
        sv("phone", "+12395559000", SourceClass.PRACTICE_WEB),
    ]
    a_same = assess_field("phone", "+12395551234", "old", same_class)
    a_diff = assess_field("phone", "+12395551234", "old", diff_class)
    assert a_same.confidence < a_diff.confidence
    assert a_same.corroborating_classes == 1
    assert a_diff.corroborating_classes == 2


def test_no_sources_returns_none():
    assert assess_field("phone", "+1", "x", []) is None


def test_inactive_downgrade_is_not_silently_ignored():
    # NPPES still lists the provider active (and outweighs the board), but the state
    # board reports the license inactive. The record matches the strongest source,
    # so nothing "changes" — yet this must NOT be left as no_change.
    sources = [
        sv("active", "active", SourceClass.GOV_SELF_REPORTED, "NPI Registry"),
        sv("active", "inactive", SourceClass.REGULATORY_BOARD, "State Medical Board"),
    ]
    a = assess_field("active", "active", "Active", sources)
    assert a is not None
    assert a.changed is False  # the weighted winner equals the current value
    assert a.dissent is True
    assert a.dissent_value == "inactive"

    action, _conf, reason = decide([a])
    assert action == RecommendedAction.HUMAN_REVIEW
    assert "inactive" in reason.lower()
