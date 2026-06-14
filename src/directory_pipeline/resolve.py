"""Identity / NPI resolution — the cold-start step (SOLUTION_PLAN §6.0).

A real directory has rows with missing, malformed, or wrong NPIs, plus practice
rows with no NPI at all. None of those can be keyed against NPPES until the
identity is *resolved* first, so this runs before Tier-0 reconciliation.

A passing NPI check-digit that maps to a *different* person is a data-entry error,
never a silent field update — it becomes a repair ticket.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from directory_pipeline.logging_config import get_logger
from directory_pipeline.models import ProviderRecord
from directory_pipeline.normalize import normalize_name

if TYPE_CHECKING:
    from directory_pipeline.sources.nppes import NppesProvider

log = get_logger("resolve")

_NPI_RE = re.compile(r"^\d{10}$")


def is_valid_npi(npi: str | None) -> bool:
    """Validate a 10-digit NPI via its Luhn check digit (CMS prefixes ``80840``).

    >>> is_valid_npi("1234567893")
    True
    >>> is_valid_npi("1234567890")  # the brief's placeholder fails the check digit
    False
    """
    if not npi or not _NPI_RE.match(npi):
        return False
    full = "80840" + npi  # 15 digits: prefix + 9-digit base + check digit
    total = 0
    for i, ch in enumerate(reversed(full)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


class ResolutionStatus(str, Enum):
    VALIDATED = "validated"  # NPI present, valid, and the record matches
    BAD_CHECKDIGIT = "bad_checkdigit"  # NPI fails Luhn but a match was found (proceed + flag)
    RESOLVED_BY_SEARCH = "resolved_by_search"  # NPI was missing; recovered via name/org search
    MISMATCH = "mismatch"  # NPI maps to a clearly different entity -> repair ticket
    UNRESOLVED = "unresolved"  # could not identify confidently -> quarantine


@dataclass(frozen=True)
class ResolutionResult:
    status: ResolutionStatus
    npi: str | None
    provider: NppesProvider | None
    confidence: float
    note: str

    @property
    def usable(self) -> bool:
        """Whether downstream reconciliation should proceed for this record."""
        return self.status in {
            ResolutionStatus.VALIDATED,
            ResolutionStatus.BAD_CHECKDIGIT,
            ResolutionStatus.RESOLVED_BY_SEARCH,
        }


class NppesLookup(Protocol):
    """The slice of the NPPES source that resolution needs."""

    def fetch(self, npi: str) -> NppesProvider | None: ...

    def search(
        self,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        organization_name: str | None = None,
        state: str | None = None,
        taxonomy_description: str | None = None,
    ) -> list[NppesProvider]: ...


def _name_agreement(record: ProviderRecord, provider: NppesProvider) -> float:
    """0..1 agreement between a record's name and an NPPES candidate's name."""
    rec_name = normalize_name(record.provider_name)
    cand_name = provider.normalized_name()
    if rec_name.canonical and cand_name.canonical:
        if rec_name.canonical == cand_name.canonical:
            return 1.0
        # family name match alone is partial corroboration
        if rec_name.family and rec_name.family.upper() == (cand_name.family or "").upper():
            return 0.6
        return 0.0
    # organization records: compare practice name to org name
    if record.practice_name and provider.organization_name:
        from directory_pipeline.normalize import normalize_practice_name

        a = normalize_practice_name(record.practice_name)
        b = normalize_practice_name(provider.organization_name)
        if a and b and (a == b or a in b or b in a):
            return 0.8
    return 0.0


# Accept a candidate found by search only above this name-agreement score.
_SEARCH_ACCEPT_THRESHOLD = 0.6


def resolve_identity(record: ProviderRecord, nppes: NppesLookup) -> ResolutionResult:
    """Resolve a record to an authoritative NPI before reconciliation."""
    npi = (record.npi or "").strip() or None

    if npi:
        valid = is_valid_npi(npi)
        provider = nppes.fetch(npi)
        if provider is None:
            return ResolutionResult(
                ResolutionStatus.UNRESOLVED,
                npi,
                None,
                0.0,
                f"NPI {npi} not found in NPPES.",
            )
        agreement = _name_agreement(record, provider)
        if agreement < 0.5:
            return ResolutionResult(
                ResolutionStatus.MISMATCH,
                npi,
                provider,
                agreement,
                f"NPI {npi} resolves to a different entity "
                f"({provider.display_name()!r}); routing to repair, not update.",
            )
        if not valid:
            log.warning(
                "NPI %s fails the check-digit test but matched a record "
                "(expected for the brief's placeholder); flagging for data-quality.",
                npi,
            )
            return ResolutionResult(
                ResolutionStatus.BAD_CHECKDIGIT,
                npi,
                provider,
                agreement,
                f"NPI {npi} fails its check digit; proceeding but flagged for repair.",
            )
        return ResolutionResult(
            ResolutionStatus.VALIDATED,
            npi,
            provider,
            agreement,
            f"NPI {npi} validated and matched.",
        )

    # --- cold start: no usable NPI on the record ---------------------------- #
    name = normalize_name(record.provider_name)
    state = _state_from_address(record.address)
    candidates: list[NppesProvider] = []
    if name.family:
        candidates = nppes.search(first_name=name.given, last_name=name.family, state=state)
    elif record.practice_name:
        candidates = nppes.search(organization_name=record.practice_name, state=state)

    scored = sorted(
        ((c, _name_agreement(record, c)) for c in candidates),
        key=lambda t: t[1],
        reverse=True,
    )
    if scored and scored[0][1] >= _SEARCH_ACCEPT_THRESHOLD:
        best, score = scored[0]
        # Reject ambiguous matches (a close runner-up means we can't be sure).
        if len(scored) > 1 and scored[1][1] >= score - 0.05:
            return ResolutionResult(
                ResolutionStatus.UNRESOLVED,
                None,
                None,
                score,
                "Multiple equally plausible NPPES matches; routing to human review.",
            )
        return ResolutionResult(
            ResolutionStatus.RESOLVED_BY_SEARCH,
            best.npi,
            best,
            score,
            f"NPI {best.npi} recovered by name/org search (agreement {score:.2f}).",
        )

    return ResolutionResult(
        ResolutionStatus.UNRESOLVED,
        None,
        None,
        0.0,
        "No confident NPPES match; record quarantined for human review.",
    )


def _state_from_address(address: str | None) -> str | None:
    if not address:
        return None
    m = re.search(r",\s*([A-Za-z]{2})\s*\d{5}", address)
    return m.group(1).upper() if m else None
