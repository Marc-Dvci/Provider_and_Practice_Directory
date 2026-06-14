"""Deterministic normalization (SOLUTION_PLAN §6.2).

Every value is reduced to a canonical form *before* comparison so that cosmetic
differences ("100 Main St" vs "100 Main Street, Ste 2", "(239) 555-1234" vs
"+12395551234", "Cardiology" vs taxonomy code ``207RC0000X``) never masquerade as
real changes. Comparison everywhere downstream is plain equality on these forms.

The address parser prefers :mod:`usaddress` (CRF-based) and falls back to a small
regex parser when it is not installed, so the package works on a bare install.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from functools import lru_cache

import phonenumbers

from directory_pipeline import config
from directory_pipeline.logging_config import get_logger

log = get_logger("normalize")

try:  # optional dependency; the regex fallback covers the common cases
    import usaddress

    _HAS_USADDRESS = True
except Exception:  # pragma: no cover - exercised only when usaddress is absent
    _HAS_USADDRESS = False


# --------------------------------------------------------------------------- #
# Specialty <-> NUCC taxonomy crosswalk
# --------------------------------------------------------------------------- #
# A small inline seed guarantees the package works even with no data files. The
# bundled CSV (data/taxonomy_crosswalk.csv) extends it; production points
# DIRPIPE_TAXONOMY_CSV at the full official NUCC release. Both are loaded lazily.
_TAXONOMY_SEED: dict[str, str] = {
    "207RC0000X": "Cardiology",
    "207R00000X": "Internal Medicine",
    "207Q00000X": "Family Medicine",
    "363L00000X": "Nurse Practitioner",
    "208000000X": "Pediatrics",
    "207V00000X": "Obstetrics & Gynecology",
}


@lru_cache(maxsize=1)
def taxonomy_to_specialty() -> dict[str, str]:
    """Code -> specialty label, seed merged with the bundled/configured CSV."""
    mapping = dict(_TAXONOMY_SEED)
    path = config.TAXONOMY_CSV
    try:
        if path.exists():
            with path.open(encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    code = (row.get("code") or "").strip().upper()
                    label = (row.get("specialty") or "").strip()
                    if code and label:
                        mapping[code] = label
    except OSError as exc:  # a missing/locked file just leaves us with the seed
        log.warning("taxonomy crosswalk load failed (%s); using inline seed", exc)
    return mapping


@lru_cache(maxsize=1)
def specialty_to_taxonomy() -> dict[str, str]:
    """Specialty label (lowercased) -> first code that uses it."""
    out: dict[str, str] = {}
    for code, label in taxonomy_to_specialty().items():
        out.setdefault(label.lower(), code)
    return out


# USPS street-suffix and directional standardization (subset of Pub. 28).
_SUFFIX_MAP = {
    "street": "ST",
    "st": "ST",
    "avenue": "AVE",
    "ave": "AVE",
    "boulevard": "BLVD",
    "blvd": "BLVD",
    "drive": "DR",
    "dr": "DR",
    "road": "RD",
    "rd": "RD",
    "lane": "LN",
    "ln": "LN",
    "court": "CT",
    "ct": "CT",
    "place": "PL",
    "pl": "PL",
    "parkway": "PKWY",
    "pkwy": "PKWY",
    "circle": "CIR",
    "cir": "CIR",
    "suite": "STE",
    "ste": "STE",
    "highway": "HWY",
    "hwy": "HWY",
    "way": "WAY",
    "terrace": "TER",
    "trail": "TRL",
}
_DIRECTIONAL_MAP = {
    "north": "N",
    "south": "S",
    "east": "E",
    "west": "W",
    "northeast": "NE",
    "northwest": "NW",
    "southeast": "SE",
    "southwest": "SW",
}


def _std_token(token: str) -> str:
    low = token.lower().strip(".,")
    if low in _SUFFIX_MAP:
        return _SUFFIX_MAP[low]
    if low in _DIRECTIONAL_MAP:
        return _DIRECTIONAL_MAP[low]
    return token.upper()


# --------------------------------------------------------------------------- #
# Phone
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NormalizedPhone:
    e164: str | None
    extension: str | None

    @property
    def canonical(self) -> str | None:
        return self.e164


def normalize_phone(raw: str | None, region: str = "US") -> NormalizedPhone:
    """Parse a phone number to E.164, splitting any extension into its own field."""
    if not raw or not raw.strip():
        return NormalizedPhone(None, None)
    extension = None
    work = raw
    ext_match = re.search(r"(?:ext\.?|x|#)\s*(\d{1,6})\s*$", work, flags=re.IGNORECASE)
    if ext_match:
        extension = ext_match.group(1)
        work = work[: ext_match.start()]
    try:
        parsed = phonenumbers.parse(work, region)
        if not phonenumbers.is_valid_number(parsed):
            return NormalizedPhone(None, extension)
        if parsed.extension:
            extension = parsed.extension
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        return NormalizedPhone(e164, extension)
    except phonenumbers.NumberParseException:
        return NormalizedPhone(None, extension)


# --------------------------------------------------------------------------- #
# Address
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NormalizedAddress:
    street: str | None = None
    suite: str | None = None
    city: str | None = None
    state: str | None = None
    zip5: str | None = None
    components: dict[str, str] = field(default_factory=dict)

    @property
    def canonical(self) -> str | None:
        """Comparison key: street core + city + state + ZIP5 (suite excluded).

        Suite/unit churn is a low-risk field handled separately, so a move is
        detected on the street/city/zip core, not on a changed suite number.
        """
        locality = " ".join(p for p in (self.state, self.zip5) if p)
        parts = [p for p in (self.street, self.city, locality) if p]
        return ", ".join(parts) if parts else None


def _normalize_zip(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    return digits[:5] if len(digits) >= 5 else (digits or None)


def _canonical_street(text: str) -> str:
    return " ".join(_std_token(t) for t in text.split() if t)


def _parse_with_usaddress(raw: str) -> NormalizedAddress | None:
    try:
        tagged, _ = usaddress.tag(raw)
    except Exception:  # usaddress raises on ambiguous input
        return None
    street_keys = [
        "AddressNumber",
        "StreetNamePreDirectional",
        "StreetName",
        "StreetNamePostType",
        "StreetNamePostDirectional",
    ]
    street = " ".join(tagged[k] for k in street_keys if k in tagged)
    suite = " ".join(tagged[k] for k in ("OccupancyType", "OccupancyIdentifier") if k in tagged)
    return NormalizedAddress(
        street=_canonical_street(street) or None,
        suite=_canonical_street(suite) or None,
        city=(tagged.get("PlaceName") or "").upper() or None,
        state=(tagged.get("StateName") or "").upper()[:2] or None,
        zip5=_normalize_zip(tagged.get("ZipCode")),
        components=dict(tagged),
    )


_REGEX_ADDR = re.compile(
    r"^\s*(?P<street>.*?)\s*,\s*(?P<city>[^,]+?)\s*,\s*"
    r"(?P<state>[A-Za-z]{2})\s*(?P<zip>\d{5}(?:-\d{4})?)?\s*$"
)


def _parse_with_regex(raw: str) -> NormalizedAddress:
    m = _REGEX_ADDR.match(raw)
    if not m:
        return NormalizedAddress(street=_canonical_street(raw) or None, components={"raw": raw})
    street_raw = m.group("street")
    suite = None
    suite_match = re.search(r"\b(ste|suite|unit|apt|#)\b\.?\s*([\w-]+)", street_raw, re.IGNORECASE)
    if suite_match:
        suite = _canonical_street(suite_match.group(0))
        street_raw = street_raw[: suite_match.start()].strip(" ,")
    return NormalizedAddress(
        street=_canonical_street(street_raw) or None,
        suite=suite,
        city=m.group("city").upper(),
        state=m.group("state").upper(),
        zip5=_normalize_zip(m.group("zip")),
        components={"raw": raw},
    )


def normalize_address(
    raw: str | None = None,
    *,
    street: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip_code: str | None = None,
) -> NormalizedAddress:
    """Normalize either a single address string or pre-split components."""
    if raw is None and any((street, city, state, zip_code)):
        return NormalizedAddress(
            street=_canonical_street(street or "") or None,
            city=(city or "").upper() or None,
            state=(state or "").upper()[:2] or None,
            zip5=_normalize_zip(zip_code),
            components={"street": street or "", "city": city or "", "state": state or ""},
        )
    if not raw or not raw.strip():
        return NormalizedAddress()
    if _HAS_USADDRESS:
        parsed = _parse_with_usaddress(raw)
        if parsed is not None:
            return parsed
    return _parse_with_regex(raw)


# --------------------------------------------------------------------------- #
# Specialty
# --------------------------------------------------------------------------- #
def normalize_specialty(text: str | None = None, *, taxonomy_code: str | None = None) -> str | None:
    """Map a specialty label or NUCC taxonomy code to a canonical taxonomy code."""
    if taxonomy_code:
        return taxonomy_code.upper()  # a valid code is already canonical
    if not text:
        return None
    return specialty_to_taxonomy().get(text.strip().lower())


def specialty_label(taxonomy_code: str | None) -> str | None:
    """Human-readable specialty for a taxonomy code (for display)."""
    if not taxonomy_code:
        return None
    return taxonomy_to_specialty().get(taxonomy_code.upper(), taxonomy_code.upper())


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NormalizedName:
    given: str | None = None
    middle: str | None = None
    family: str | None = None
    suffix: str | None = None
    credentials: tuple[str, ...] = ()

    @property
    def canonical(self) -> str | None:
        """Comparison key: ``FAMILY|GIVEN`` (credentials kept structured, not compared)."""
        if not self.family and not self.given:
            return None
        return f"{(self.family or '').upper()}|{(self.given or '').upper()}"


_CREDENTIALS = {
    "MD",
    "DO",
    "NP",
    "PA",
    "DPM",
    "DDS",
    "DMD",
    "PHD",
    "RN",
    "APRN",
    "FACC",
    "FACP",
}


def normalize_name(raw: str | None) -> NormalizedName:
    """Parse a provider name into structured parts; pull credentials out of the name."""
    if not raw or not raw.strip():
        return NormalizedName()

    def _as_credential(token: str) -> str:
        return re.sub(r"[.\s]", "", token).upper()

    creds: list[str] = []
    work = raw
    if "," in work:
        head, tail = work.split(",", 1)
        for tok in re.split(r"[,\s]+", tail):
            cred = _as_credential(tok)
            if cred in _CREDENTIALS:
                creds.append(cred)
        work = head
    tokens = [t for t in re.split(r"\s+", work.strip()) if t]
    # strip any trailing credential tokens that weren't comma-separated
    while tokens and _as_credential(tokens[-1]) in _CREDENTIALS:
        creds.append(_as_credential(tokens.pop()))
    given = tokens[0] if tokens else None
    family = tokens[-1] if len(tokens) > 1 else None
    middle = " ".join(tokens[1:-1]) if len(tokens) > 2 else None
    return NormalizedName(
        given=given,
        middle=middle,
        family=family,
        credentials=tuple(dict.fromkeys(creds)),  # de-dup, preserve order
    )


# --------------------------------------------------------------------------- #
# Misc
# --------------------------------------------------------------------------- #
def normalize_active(value: object) -> str | None:
    """Canonicalize an active/inactive signal to ``"active"`` / ``"inactive"``."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "active" if value else "inactive"
    text = str(value).strip().lower()
    if text in {"a", "active", "true", "1", "yes"}:
        return "active"
    if text in {"i", "inactive", "deactivated", "false", "0", "no", "retired"}:
        return "inactive"
    return None


def normalize_practice_name(raw: str | None) -> str | None:
    """Canonicalize a practice / organization name for comparison."""
    if not raw or not raw.strip():
        return None
    text = raw.upper()
    text = re.sub(r"[.,]", " ", text)
    text = re.sub(r"\b(LLC|PA|PC|INC|LLP|GROUP|ASSOCIATES|ASSOC)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None
