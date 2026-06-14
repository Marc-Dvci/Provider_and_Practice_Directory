"""Provider & Practice Directory Update Pipeline.

A deterministic-first, cost-efficient pipeline that keeps a healthcare provider /
practice directory accurate by reconciling it against free authoritative U.S.
government data (NPPES, CMS), scoring each proposed change with a transparent
source-weighted formula, and routing only genuine conflicts to human review.

See ``SOLUTION_PLAN.md`` for the architecture this package implements.
"""

from __future__ import annotations

__version__ = "0.1.0"

from directory_pipeline.models import (
    FieldChange,
    ProviderRecord,
    Recommendation,
    RecommendedAction,
    RiskClass,
    SourceClass,
)

__all__ = [
    "FieldChange",
    "ProviderRecord",
    "Recommendation",
    "RecommendedAction",
    "RiskClass",
    "SourceClass",
    "__version__",
]
