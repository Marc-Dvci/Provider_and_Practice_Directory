"""Confidence scoring + decision engine (SOLUTION_PLAN §6.4–6.5).

For a field ``f`` with candidate value ``v`` asserted by sources ``S``::

    field_conf(f, v) = R(v) * A(v)

    A(v) = Σ_{s: val=v} w(s,f)·φ(s) / Σ_{s∈S} w(s,f)·φ(s)      (agreement share)
    R(v) = 1 − Π_{s: val=v} (1 − w(s,f)·φ(s))                   (noisy-OR strength)

``A`` drags confidence toward the middle when sources disagree; ``R`` rewards
multiple independent confirmations. Same-class sources are de-correlated before
both terms (the 2nd+ source in a class contributes only ``1 − ρ`` of its weight),
so two agreeing government feeds can't masquerade as independent corroboration.

Decisions then apply per-field risk thresholds and the corroboration gate.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone

from directory_pipeline import config
from directory_pipeline.models import (
    FieldAssessment,
    FieldChange,
    ProviderRecord,
    Recommendation,
    RecommendedAction,
    RiskClass,
    SourceValue,
)

_RISK_ORDER = {RiskClass.LOW: 0, RiskClass.MEDIUM: 1, RiskClass.HIGH: 2}


def freshness_factor(data_as_of: date | None, as_of: date, policy: config.ScoringPolicy) -> float:
    """φ(s): exponential decay on source-data age, floored so old data still counts."""
    if data_as_of is None:
        return 1.0
    age_days = max((as_of - data_as_of).days, 0)
    decay = 0.5 ** (age_days / policy.halflife_days)
    return max(decay, policy.freshness_floor)


def _decorrelated_strengths(svs: list[SourceValue], policy: config.ScoringPolicy) -> list[float]:
    """Per-source effective strength (w·φ) after same-class correlation discount."""
    by_class: dict[str, list[float]] = defaultdict(list)
    for sv in svs:
        by_class[sv.source_class.value].append(sv.weight * sv.freshness)
    strengths: list[float] = []
    for vals in by_class.values():
        for i, s in enumerate(sorted(vals, reverse=True)):
            strengths.append(s if i == 0 else s * (1.0 - policy.rho))
    return strengths


def _eff_sum(svs: list[SourceValue], policy: config.ScoringPolicy) -> float:
    return sum(_decorrelated_strengths(svs, policy))


def _noisy_or(svs: list[SourceValue], policy: config.ScoringPolicy) -> float:
    product = 1.0
    for s in _decorrelated_strengths(svs, policy):
        product *= 1.0 - min(max(s, 0.0), 0.999)
    return 1.0 - product


def _ordered_labels(svs: list[SourceValue]) -> list[str]:
    seen: dict[str, float] = {}
    for sv in svs:
        seen[sv.source_label] = max(seen.get(sv.source_label, 0.0), sv.weight * sv.freshness)
    return [label for label, _ in sorted(seen.items(), key=lambda t: t[1], reverse=True)]


def assess_field(
    field: str,
    current_value: str | None,
    raw_current: str | None,
    sources: list[SourceValue],
    *,
    policy: config.ScoringPolicy = config.DEFAULT_POLICY,
    as_of: date | None = None,
) -> FieldAssessment | None:
    """Score a single field. Returns ``None`` if no source asserts a value for it."""
    as_of = as_of or datetime.now(timezone.utc).date()
    valued = [sv for sv in sources if sv.value is not None]
    if not valued:
        return None

    # Populate reliability weight and freshness on each source value.
    for sv in valued:
        sv.weight = config.weight_for(field, sv.source_class)
        sv.freshness = freshness_factor(sv.data_as_of, as_of, policy)

    by_value: dict[str, list[SourceValue]] = defaultdict(list)
    for sv in valued:
        by_value[sv.value].append(sv)  # type: ignore[index]

    denom = _eff_sum(valued, policy)
    if denom <= 0:
        return None

    best_value = max(by_value, key=lambda v: _eff_sum(by_value[v], policy))
    best_group = by_value[best_value]
    agreement = _eff_sum(best_group, policy) / denom
    strength = _noisy_or(best_group, policy)
    confidence = round(strength * agreement, 4)

    classes_best = {sv.source_class for sv in best_group}
    competing = [sv for sv in valued if sv.value != best_value]
    classes_other = {sv.source_class for sv in competing}
    alt_share = (
        max((_eff_sum(g, policy) for v, g in by_value.items() if v != best_value), default=0.0)
        / denom
    )
    conflict = bool(classes_other - classes_best) and alt_share >= policy.conflict_min_share

    changed = best_value != current_value
    raw_proposed = best_group[0].raw_value if changed else raw_current

    # Dissent: a credible source contradicts the *current* value even though the
    # current value is the weighted winner. This catches the dangerous case where
    # one authority (e.g. a state board) reports a provider inactive while the
    # record — backed by a still-stale stronger source — keeps showing active.
    dissent = False
    dissent_value: str | None = None
    if current_value is not None:
        non_current = [(v, _eff_sum(g, policy)) for v, g in by_value.items() if v != current_value]
        if non_current:
            dval, dsum = max(non_current, key=lambda t: t[1])
            if dsum / denom >= policy.conflict_min_share:
                dissent = True
                dissent_value = dval

    return FieldAssessment(
        field=field,
        risk_class=config.risk_class_for(field),
        current_value=current_value,
        proposed_value=best_value,
        changed=changed,
        confidence=confidence,
        conflict=conflict,
        corroborating_classes=len(classes_best),
        dissent=dissent,
        dissent_value=dissent_value,
        supporting_sources=_ordered_labels(best_group),
        competing_sources=_ordered_labels(competing),
        raw_current=raw_current,
        raw_proposed=raw_proposed,
    )


def _max_risk(assessments: list[FieldAssessment]) -> RiskClass:
    return max((a.risk_class for a in assessments), key=lambda r: _RISK_ORDER[r])


def decide(
    assessments: list[FieldAssessment], policy: config.ScoringPolicy = config.DEFAULT_POLICY
) -> tuple[RecommendedAction, float, str]:
    """Apply safe-update rules to per-field assessments → (action, overall, reason)."""
    changed = [a for a in assessments if a.changed]

    # Safety net: a reliable source contradicting the current value of a high-risk
    # field (e.g. an inactive/closure signal the directory hasn't caught up to) is
    # never silently kept — it is routed to a human even if no field "changed".
    dissent_high = [a for a in assessments if a.dissent and a.risk_class == RiskClass.HIGH]

    if not changed:
        confirmation = (
            round(sum(a.confidence for a in assessments) / len(assessments), 2)
            if assessments
            else 1.0
        )
        if dissent_high:
            a = dissent_high[0]
            return (
                RecommendedAction.HUMAN_REVIEW,
                confirmation,
                f"A reliable source reports {a.field}={a.dissent_value!r} while the record "
                f"still shows {a.current_value!r}; flagged for verification (high-risk field "
                "never silently left stale).",
            )
        return (
            RecommendedAction.NO_CHANGE,
            confirmation,
            "All checked fields match authoritative sources; record confirmed accurate.",
        )

    overall = round(sum(a.confidence for a in changed) / len(changed), 2)

    # Special rule: an NPI never legitimately changes — it's a repair, not an update.
    npi_changed = next((a for a in changed if a.field == "npi"), None)
    if npi_changed is not None:
        return (
            RecommendedAction.HUMAN_REVIEW,
            overall,
            "NPI differs from the record — this indicates a data-entry error or a "
            "merged duplicate, not a field update. Routed to repair/dedup.",
        )

    conflicted = [a for a in changed if a.conflict]
    if conflicted:
        a = conflicted[0]
        sup = ", ".join(a.supporting_sources) or "newer sources"
        comp = ", ".join(a.competing_sources) or "the existing record"
        return (
            RecommendedAction.HUMAN_REVIEW,
            overall,
            f"{sup} and {comp} disagree on {a.field}; manual verification recommended.",
        )

    never_auto = [a for a in changed if a.field in policy.never_auto]
    if never_auto:
        fields = ", ".join(sorted({a.field for a in never_auto}))
        return (
            RecommendedAction.HUMAN_REVIEW,
            overall,
            f"High-risk field(s) changed ({fields}); never updated silently - "
            "routed to human confirmation.",
        )

    if dissent_high:
        a = dissent_high[0]
        return (
            RecommendedAction.HUMAN_REVIEW,
            overall,
            f"A reliable source reports {a.field}={a.dissent_value!r} while the record "
            f"still shows {a.current_value!r}; routed to human review before any update.",
        )

    risk = _max_risk(changed)
    threshold = policy.thresholds[risk]
    min_conf = min(a.confidence for a in changed)
    corroboration_ok = all(
        a.corroborating_classes >= policy.corroboration_min[a.risk_class] for a in changed
    )

    if min_conf >= threshold and corroboration_ok:
        fields = ", ".join(a.field for a in changed)
        return (
            RecommendedAction.AUTO_UPDATE,
            overall,
            f"Updated {fields} confirmed by independent reliable sources "
            f"(min confidence {min_conf:.2f} >= {threshold:.2f}).",
        )
    if min_conf >= policy.tau_low:
        reason = (
            f"Change detected but below the auto-update bar "
            f"(min confidence {min_conf:.2f} < {threshold:.2f}"
        )
        reason += "" if corroboration_ok else "; insufficient independent corroboration"
        reason += "); routed to human review."
        return (RecommendedAction.HUMAN_REVIEW, overall, reason)

    return (
        RecommendedAction.DISCARD,
        overall,
        f"Evidence too weak (min confidence {min_conf:.2f} < {policy.tau_low:.2f}); "
        "holding the record unchanged and re-queuing.",
    )


def build_recommendation(
    record: ProviderRecord,
    field_sources: dict[str, list[SourceValue]],
    field_current: dict[str, tuple[str | None, str | None]],
    *,
    policy: config.ScoringPolicy = config.DEFAULT_POLICY,
    as_of: date | None = None,
) -> tuple[Recommendation, list[FieldAssessment]]:
    """Score every field and assemble the brief-schema :class:`Recommendation`.

    ``field_current`` maps field → (normalized_current, raw_current).
    """
    assessments: list[FieldAssessment] = []
    for field, sources in field_sources.items():
        norm_current, raw_current = field_current.get(field, (None, None))
        assessment = assess_field(
            field, norm_current, raw_current, sources, policy=policy, as_of=as_of
        )
        if assessment is not None:
            assessments.append(assessment)

    action, overall, reason = decide(assessments, policy)

    changes = [
        FieldChange(
            field=a.field,
            old_value=a.raw_current,
            new_value=a.raw_proposed,
            confidence_score=round(a.confidence, 2),
            supporting_sources=a.supporting_sources,
        )
        for a in assessments
        if a.changed
    ]

    recommendation = Recommendation(
        provider_id=record.provider_id,
        npi=record.npi,
        change_detected=bool(changes),
        changes=changes,
        overall_confidence=overall,
        recommended_action=action,
        reason=reason,
    )
    return recommendation, assessments
