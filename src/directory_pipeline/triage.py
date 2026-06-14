"""Triage / risk selection (SOLUTION_PLAN §6.1) — *don't re-verify everything*.

The cheapest verification is the one you skip. Each record gets a risk score so a
cycle actively harvests only the top of the queue (the records most likely to be
wrong) and lets everything else ride the free monthly batch diff. This is the
single biggest cost lever in the pipeline and it directly answers the brief's
"identify provider and practice records that may be outdated".

    risk = w1·staleness        # days since last_verified_date vs the NSA 90-day clock
         + w2·volatility       # contact fields (phone/suite) churn faster than names
         + w3·hard_signal      # NPI deactivation-file hit, NPPES monthly diff, bounce-back
         + w4·importance       # high-traffic / sold-to-payer records first

Weights are config (here as defaults); in production they are tuned from review
outcomes, but the shape is fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from directory_pipeline.models import ProviderRecord

# Verification cadence the No Surprises Act sets for payers (and the clock the REAL
# Health Providers Act will enforce for Medicare Advantage from PY2028).
NSA_CADENCE_DAYS = 90

# Risk weights (sum to 1.0). SOLUTION_PLAN §6.1.
W_STALENESS = 0.50
W_VOLATILITY = 0.20
W_HARD_SIGNAL = 0.20
W_IMPORTANCE = 0.10

# Staleness saturates at this many NSA windows overdue (~6 years), so the queue still
# differentiates among the many records that are well past the 90-day window.
_STALENESS_SATURATION = 24.0


@dataclass(frozen=True)
class TriageScore:
    provider_id: str
    score: float
    staleness_days: int
    reasons: list[str] = field(default_factory=list)


def _staleness(last_verified: date | None, as_of: date) -> tuple[float, int, list[str]]:
    if last_verified is None:
        return 1.0, 10**6, ["never verified"]
    days = max((as_of - last_verified).days, 0)
    windows = days / NSA_CADENCE_DAYS
    factor = min(windows / _STALENESS_SATURATION, 1.0)
    reasons = []
    if days > NSA_CADENCE_DAYS:
        reasons.append(f"{days}d since last verify (> {NSA_CADENCE_DAYS}d window)")
    return factor, days, reasons


def risk_score(
    record: ProviderRecord,
    *,
    as_of: date | None = None,
    hard_signal: float = 0.0,
    importance: float = 0.5,
) -> TriageScore:
    """Score how urgently a record should be re-verified (0..1, higher = sooner).

    ``hard_signal`` (0..1) carries external triggers the caller already knows about
    — an NPI in the monthly deactivation file, an NPPES diff, a bounced letter.
    ``importance`` (0..1) lets high-traffic / revenue records jump the queue.
    """
    as_of = as_of or date.today()
    staleness, days, reasons = _staleness(record.last_verified_date, as_of)
    volatility = 0.6 if record.phone else 0.3  # contact-bearing records churn faster
    if hard_signal > 0:
        reasons.append("hard signal (deactivation / diff / bounce-back)")
    score = (
        W_STALENESS * staleness
        + W_VOLATILITY * volatility
        + W_HARD_SIGNAL * min(max(hard_signal, 0.0), 1.0)
        + W_IMPORTANCE * min(max(importance, 0.0), 1.0)
    )
    return TriageScore(record.provider_id, round(min(score, 1.0), 4), days, reasons)


def build_verify_queue(
    records: list[ProviderRecord],
    *,
    as_of: date | None = None,
    hard_signals: dict[str, float] | None = None,
    importance: dict[str, float] | None = None,
) -> list[TriageScore]:
    """Rank records most-at-risk first. Only the top of this queue needs active
    (Tier-3) harvesting each cycle; the rest ride the free batch reconcile."""
    hard_signals = hard_signals or {}
    importance = importance or {}
    scored = [
        risk_score(
            r,
            as_of=as_of,
            hard_signal=hard_signals.get(r.provider_id, 0.0),
            importance=importance.get(r.provider_id, 0.5),
        )
        for r in records
    ]
    return sorted(scored, key=lambda t: t.score, reverse=True)
