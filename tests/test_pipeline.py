from __future__ import annotations

from directory_pipeline.audit import AuditLog
from directory_pipeline.models import RecommendedAction
from directory_pipeline.pipeline import Pipeline


def test_directory_actions(pipeline, directory):
    results = {r.record.provider_id: r.recommendation for r in pipeline.run(directory)}

    assert results["HL_001"].recommended_action == RecommendedAction.HUMAN_REVIEW
    assert results["HL_002"].recommended_action == RecommendedAction.AUTO_UPDATE
    assert results["HL_004"].recommended_action == RecommendedAction.HUMAN_REVIEW
    assert results["HL_005"].recommended_action == RecommendedAction.NO_CHANGE


def test_cold_start_fills_npi(pipeline, directory):
    results = {r.record.provider_id: r for r in pipeline.run(directory)}
    # HL_002 arrives with no NPI; the pipeline recovers it.
    assert results["HL_002"].recommendation.npi == "1002003006"


def test_auto_update_changes_match_brief_fields(pipeline, records_by_id):
    result = pipeline.process_record(records_by_id["HL_002"])
    changed = {c.field for c in result.recommendation.changes}
    assert changed == {"address", "phone"}
    for change in result.recommendation.changes:
        assert len(change.supporting_sources) >= 2  # corroboration gate


def test_practice_relocation_detected(pipeline, records_by_id):
    # HL_006 is a Type-2 practice record whose location moved.
    result = pipeline.process_record(records_by_id["HL_006"])
    assert result.recommendation.recommended_action == RecommendedAction.AUTO_UPDATE
    changed = {c.field for c in result.recommendation.changes}
    assert "address" in changed
    assert any(s.startswith("practice relocation") for s in result.signals)


def test_high_risk_active_never_silent(pipeline, records_by_id):
    result = pipeline.process_record(records_by_id["HL_004"])
    assert result.recommendation.recommended_action == RecommendedAction.HUMAN_REVIEW
    assert any(c.field == "active" for c in result.recommendation.changes)


def test_duplicate_detection(pipeline, directory):
    clusters = pipeline.duplicates(directory)
    assert len(clusters) == 1
    assert set(clusters[0].provider_ids) == {"HL_001", "HL_003"}


def test_output_matches_brief_schema(pipeline, records_by_id):
    rec = pipeline.process_record(records_by_id["HL_001"]).recommendation
    payload = rec.model_dump(mode="json")
    assert set(payload) == {
        "provider_id",
        "npi",
        "change_detected",
        "changes",
        "overall_confidence",
        "recommended_action",
        "reason",
    }
    assert set(payload["changes"][0]) == {
        "field",
        "old_value",
        "new_value",
        "confidence_score",
        "supporting_sources",
    }


def test_audit_log_roundtrip(settings, directory, tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    Pipeline(settings, audit_log=audit).run(directory)
    events = audit.read_all()
    assert events
    assert audit.review_queue()
    assert all(e.pipeline_version for e in events)
