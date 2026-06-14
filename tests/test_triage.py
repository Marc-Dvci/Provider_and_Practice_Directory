from __future__ import annotations

from datetime import date

from directory_pipeline.models import ProviderRecord
from directory_pipeline.triage import build_verify_queue, risk_score


def _rec(pid: str, verified: str | None, phone: str | None = "239-555-0000") -> ProviderRecord:
    return ProviderRecord(
        provider_id=pid,
        provider_name="Test Provider",
        last_verified_date=date.fromisoformat(verified) if verified else None,
        phone=phone,
    )


def test_staler_records_rank_higher():
    as_of = date(2026, 6, 13)
    fresh = _rec("FRESH", "2026-05-01")
    stale = _rec("STALE", "2021-01-01")
    assert risk_score(stale, as_of=as_of).score > risk_score(fresh, as_of=as_of).score


def test_never_verified_is_max_staleness():
    as_of = date(2026, 6, 13)
    ts = risk_score(_rec("NONE", None), as_of=as_of)
    assert "never verified" in ts.reasons
    assert ts.score >= 0.5


def test_hard_signal_and_importance_raise_score():
    as_of = date(2026, 6, 13)
    base = risk_score(_rec("R", "2026-05-01"), as_of=as_of).score
    boosted = risk_score(
        _rec("R", "2026-05-01"), as_of=as_of, hard_signal=1.0, importance=1.0
    ).score
    assert boosted > base


def test_queue_is_sorted_desc():
    as_of = date(2026, 6, 13)
    records = [_rec("A", "2026-05-01"), _rec("B", "2020-01-01"), _rec("C", "2024-01-01")]
    queue = build_verify_queue(records, as_of=as_of)
    scores = [t.score for t in queue]
    assert scores == sorted(scores, reverse=True)
    assert queue[0].provider_id == "B"  # oldest
