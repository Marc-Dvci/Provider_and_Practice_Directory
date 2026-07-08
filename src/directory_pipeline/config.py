"""Configuration: runtime settings and the scoring policy.

Everything tunable lives here so that the rest of the codebase reads as plain
logic. The scoring constants are the defaults described in SOLUTION_PLAN §6.4–6.5;
in production they are *learned and ratcheted* from human-review outcomes, but the
shape of the policy stays the same.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from directory_pipeline.models import RiskClass, SourceClass

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
DATA_DIR = REPO_ROOT / "data"
FIXTURES_DIR = DATA_DIR / "fixtures"
SAMPLE_DIRECTORY = DATA_DIR / "sample_directory.json"

# NUCC taxonomy -> specialty crosswalk. The bundled CSV is a curated subset; in
# production point DIRPIPE_TAXONOMY_CSV at the full official NUCC release.
_DEFAULT_TAXONOMY_CSV = DATA_DIR / "taxonomy_crosswalk.csv"
TAXONOMY_CSV = Path(os.environ.get("DIRPIPE_TAXONOMY_CSV", str(_DEFAULT_TAXONOMY_CSV)))


# --------------------------------------------------------------------------- #
# Runtime settings (env-overridable, sensible offline-first defaults)
# --------------------------------------------------------------------------- #
def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Process-wide settings, populated from the environment with safe defaults."""

    offline: bool = False
    nppes_base_url: str = "https://npiregistry.cms.hhs.gov/api/"
    cms_base_url: str = "https://data.cms.gov/provider-data/api/1/datastore/query/"
    census_base_url: str = "https://geocoding.geo.census.gov/geocoder/"
    cms_doctors_dataset: str = "mj5m-pzi6"
    http_timeout: float = 15.0
    http_retries: int = 3  # transient-error retries (429/5xx) with exponential backoff
    http_cache: bool = True  # cache live API responses on disk (cost lever, SOLUTION_PLAN §7)
    http_cache_ttl: float = 86400.0  # seconds a cached response stays fresh (default 24h)
    cache_dir: Path = DATA_DIR / "cache"
    audit_path: Path = Path("audit_log.jsonl")
    fixtures_dir: Path = FIXTURES_DIR
    website_search_base_url: str | None = None
    website_search_api_key: str | None = None
    website_search_top_k: int = 8

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            offline=_env_bool("DIRPIPE_OFFLINE", False),
            nppes_base_url=os.environ.get("DIRPIPE_NPPES_BASE_URL", cls.nppes_base_url),
            cms_base_url=os.environ.get("DIRPIPE_CMS_BASE_URL", cls.cms_base_url),
            census_base_url=os.environ.get("DIRPIPE_CENSUS_BASE_URL", cls.census_base_url),
            http_timeout=float(os.environ.get("DIRPIPE_HTTP_TIMEOUT", cls.http_timeout)),
            http_retries=int(os.environ.get("DIRPIPE_HTTP_RETRIES", cls.http_retries)),
            http_cache=_env_bool("DIRPIPE_HTTP_CACHE", cls.http_cache),
            http_cache_ttl=float(os.environ.get("DIRPIPE_HTTP_CACHE_TTL", cls.http_cache_ttl)),
            audit_path=Path(os.environ.get("DIRPIPE_AUDIT_PATH", str(cls.audit_path))),
            website_search_base_url=os.environ.get("DIRPIPE_WEBSITE_SEARCH_BASE_URL") or None,
            website_search_api_key=os.environ.get("DIRPIPE_WEBSITE_SEARCH_API_KEY") or None,
            website_search_top_k=int(
                os.environ.get("DIRPIPE_WEBSITE_SEARCH_TOP_K", cls.website_search_top_k)
            ),
        )


# --------------------------------------------------------------------------- #
# Scoring policy (SOLUTION_PLAN §6.4–6.5)
# --------------------------------------------------------------------------- #

# Which risk class each field belongs to. Governs the auto-update threshold and
# how many independent source-classes must corroborate before a silent write.
FIELD_RISK_CLASS: dict[str, RiskClass] = {
    "phone": RiskClass.LOW,
    "website": RiskClass.LOW,
    "suite": RiskClass.LOW,
    "address": RiskClass.MEDIUM,
    "specialty": RiskClass.MEDIUM,
    "practice_name": RiskClass.MEDIUM,
    "affiliation": RiskClass.MEDIUM,
    "provider_name": RiskClass.HIGH,
    "npi": RiskClass.HIGH,
    "active": RiskClass.HIGH,
}

# Auto-update confidence threshold per risk class.
RISK_THRESHOLDS: dict[RiskClass, float] = {
    RiskClass.LOW: 0.85,
    RiskClass.MEDIUM: 0.90,
    RiskClass.HIGH: 0.95,
}

# Minimum number of *distinct* independence classes that must assert the new
# value before it may auto-update (corroboration gate).
CORROBORATION_MIN_CLASSES: dict[RiskClass, int] = {
    RiskClass.LOW: 1,
    RiskClass.MEDIUM: 2,
    RiskClass.HIGH: 2,
}

# High-risk fields are *never* updated silently, even at high confidence.
NEVER_AUTO_UPDATE: frozenset[str] = frozenset({"provider_name", "npi", "active"})

# Below this confidence we don't even bother a human — hold and re-queue later.
TAU_LOW: float = 0.50

# A competing value holding at least this share of total source weight, asserted
# by a *different* class than the leading value, is treated as an active conflict.
CONFLICT_MIN_SHARE: float = 0.25

# Correlation discount applied to additional same-class sources (the 2nd, 3rd...
# NPPES-class source contributes only (1 - RHO) of its weight). SOLUTION_PLAN §6.4.
RHO: float = 0.5

# Freshness decay: a source's weight is multiplied by 0.5 ** (age / HALFLIFE),
# clamped to FRESHNESS_FLOOR so old-but-authoritative data still counts.
FRESHNESS_HALFLIFE_DAYS: float = 540.0
FRESHNESS_FLOOR: float = 0.3

# Per-(field, source-class) reliability weight w(s, f) in [0, 1].
# Rows are fields; columns are independence classes. Absent entries default to 0
# (that class is not considered authoritative for that field).
_W = SourceClass
SOURCE_FIELD_WEIGHTS: dict[str, dict[SourceClass, float]] = {
    "provider_name": {
        _W.GOV_SELF_REPORTED: 0.95,
        _W.GOV_CLAIMS: 0.80,
        _W.REGULATORY_BOARD: 0.85,
        _W.PRACTICE_WEB: 0.50,
    },
    "npi": {
        _W.GOV_SELF_REPORTED: 0.99,
        _W.GOV_CLAIMS: 0.85,
    },
    "specialty": {
        _W.GOV_SELF_REPORTED: 0.92,
        _W.GOV_CLAIMS: 0.82,
        _W.REGULATORY_BOARD: 0.70,
        _W.PRACTICE_WEB: 0.40,
    },
    "practice_name": {
        _W.GOV_SELF_REPORTED: 0.88,
        _W.GOV_CLAIMS: 0.80,
        _W.PRACTICE_WEB: 0.55,
    },
    "address": {
        _W.GOV_SELF_REPORTED: 0.66,  # self-reported, can lag reality
        _W.GOV_CLAIMS: 0.62,
        _W.PRACTICE_WEB: 0.68,
        _W.REGULATORY_BOARD: 0.50,
    },
    "phone": {
        _W.GOV_SELF_REPORTED: 0.66,
        _W.GOV_CLAIMS: 0.62,
        _W.PRACTICE_WEB: 0.66,
        _W.REGULATORY_BOARD: 0.40,
    },
    "website": {
        _W.PRACTICE_WEB: 0.80,
        _W.GOV_SELF_REPORTED: 0.40,
    },
    "active": {
        _W.GOV_SELF_REPORTED: 0.95,  # NPPES deactivation file
        _W.GOV_CLAIMS: 0.85,  # dropped from Medicare enrollment
        _W.REGULATORY_BOARD: 0.90,  # license lapsed
        _W.PRACTICE_WEB: 0.30,
    },
}

DEFAULT_WEIGHT = 0.40  # fallback for any (field, class) not enumerated above


def weight_for(field_name: str, source_class: SourceClass) -> float:
    """Reliability weight w(s, f) for a source class on a given field."""
    return SOURCE_FIELD_WEIGHTS.get(field_name, {}).get(source_class, DEFAULT_WEIGHT)


def risk_class_for(field_name: str) -> RiskClass:
    """Risk class of a field (defaults to MEDIUM for unknown fields)."""
    return FIELD_RISK_CLASS.get(field_name, RiskClass.MEDIUM)


@dataclass(frozen=True)
class ScoringPolicy:
    """Bundle of scoring knobs, so tests/backtests can sweep alternatives."""

    thresholds: dict[RiskClass, float] = field(default_factory=lambda: dict(RISK_THRESHOLDS))
    corroboration_min: dict[RiskClass, int] = field(
        default_factory=lambda: dict(CORROBORATION_MIN_CLASSES)
    )
    never_auto: frozenset[str] = NEVER_AUTO_UPDATE
    tau_low: float = TAU_LOW
    conflict_min_share: float = CONFLICT_MIN_SHARE
    rho: float = RHO
    halflife_days: float = FRESHNESS_HALFLIFE_DAYS
    freshness_floor: float = FRESHNESS_FLOOR


DEFAULT_POLICY = ScoringPolicy()
