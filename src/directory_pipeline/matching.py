"""Matching / entity resolution (SOLUTION_PLAN §6.3).

A lightweight, dependency-free Fellegi–Sunter-style matcher used for duplicate
detection and movement detection. It blocks on NPI (a near-unique key) and on
``(soundex(family), zip5)`` so comparisons stay cheap, then scores candidate pairs
on normalized name / address / phone agreement.

In production this component is swapped for **Splink** (probabilistic record
linkage, scales to 100M+ with Spark) — the interface and the blocking strategy are
the same; only the backend changes. See SOLUTION_PLAN §6.3 / §8.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from itertools import combinations

from directory_pipeline.models import DuplicateCluster, ProviderRecord
from directory_pipeline.normalize import (
    normalize_address,
    normalize_name,
    normalize_phone,
)

DUPLICATE_THRESHOLD = 0.82

# Two geocoded locations within this distance count as the same practice location
# (SOLUTION_PLAN §6.3, practice-location matching via geocoded proximity).
SAME_LOCATION_KM = 0.15

Coord = tuple[float, float]


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(d))


def _geo_similarity(a: Coord | None, b: Coord | None) -> float | None:
    """1.0 if two geocoded points are co-located, decaying to 0 by ~2 km; None if
    either side has no coordinates (offline / un-geocoded)."""
    if a is None or b is None:
        return None
    km = haversine_km(a, b)
    if km <= SAME_LOCATION_KM:
        return 1.0
    return max(0.0, 1.0 - km / 2.0)


def soundex(value: str | None) -> str:
    """Classic Soundex code (used only for cheap blocking, not for scoring)."""
    if not value:
        return ""
    value = re.sub(r"[^A-Za-z]", "", value).upper()
    if not value:
        return ""
    codes = {
        **dict.fromkeys("BFPV", "1"),
        **dict.fromkeys("CGJKQSXZ", "2"),
        **dict.fromkeys("DT", "3"),
        "L": "4",
        **dict.fromkeys("MN", "5"),
        "R": "6",
    }
    first = value[0]
    encoded = first
    prev = codes.get(first, "")
    for ch in value[1:]:
        code = codes.get(ch, "")
        if code and code != prev:
            encoded += code
        if ch not in "HW":
            prev = code
        if len(encoded) >= 4:
            break
    return (encoded + "000")[:4]


def _trigram_similarity(a: str | None, b: str | None) -> float:
    """Jaccard similarity over character trigrams; robust to small typos."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0

    def grams(s: str) -> set[str]:
        s = f"  {s.lower()} "
        return {s[i : i + 3] for i in range(len(s) - 2)}

    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def record_match_score(
    a: ProviderRecord,
    b: ProviderRecord,
    *,
    coord_a: Coord | None = None,
    coord_b: Coord | None = None,
) -> tuple[float, str]:
    """Score whether two directory records are the same entity (0..1) + a reason.

    When both records carry Census-geocoded coordinates, geographic proximity
    replaces fuzzy string similarity for the address component (a far more reliable
    practice-location signal). With no coordinates the score is unchanged.
    """
    if a.npi and b.npi and a.npi == b.npi:
        return 1.0, f"identical NPI {a.npi}"

    name_a, name_b = normalize_name(a.provider_name), normalize_name(b.provider_name)
    name_sim = _trigram_similarity(name_a.canonical, name_b.canonical)
    addr_sim = _trigram_similarity(
        normalize_address(a.address).canonical, normalize_address(b.address).canonical
    )
    geo_sim = _geo_similarity(coord_a, coord_b)
    addr_component = geo_sim if geo_sim is not None else addr_sim
    phone_a = normalize_phone(a.phone).canonical
    phone_b = normalize_phone(b.phone).canonical
    phone_sim = 1.0 if phone_a and phone_a == phone_b else 0.0

    score = 0.55 * name_sim + 0.30 * addr_component + 0.15 * phone_sim
    addr_label = f"geo={geo_sim:.2f}" if geo_sim is not None else f"address={addr_sim:.2f}"
    reason = f"name={name_sim:.2f}, {addr_label}, phone={phone_sim:.2f}"
    return round(score, 4), reason


def _blocks(records: list[ProviderRecord]) -> dict[str, list[ProviderRecord]]:
    blocks: dict[str, list[ProviderRecord]] = defaultdict(list)
    for rec in records:
        if rec.npi:
            blocks[f"npi:{rec.npi}"].append(rec)
        name = normalize_name(rec.provider_name)
        zip5 = normalize_address(rec.address).zip5 or "?????"
        blocks[f"sx:{soundex(name.family)}:{zip5}"].append(rec)
    return blocks


def find_duplicate_clusters(
    records: list[ProviderRecord],
    threshold: float = DUPLICATE_THRESHOLD,
    *,
    coords: dict[str, Coord] | None = None,
) -> list[DuplicateCluster]:
    """Group records that refer to the same real-world entity.

    ``coords`` optionally maps provider_id -> (lat, lon) from the Census geocoder;
    when present for a pair, geographic proximity is used for the address signal.
    """
    coords = coords or {}
    parent: dict[str, str] = {r.provider_id: r.provider_id for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    pair_reason: dict[tuple[str, str], tuple[float, str]] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for block in _blocks(records).values():
        if len(block) < 2:
            continue
        for a, b in combinations(block, 2):
            lo, hi = sorted((a.provider_id, b.provider_id))
            key = (lo, hi)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            score, reason = record_match_score(
                a, b, coord_a=coords.get(a.provider_id), coord_b=coords.get(b.provider_id)
            )
            if score >= threshold:
                union(a.provider_id, b.provider_id)
                pair_reason[key] = (score, reason)

    groups: dict[str, list[str]] = defaultdict(list)
    for rec in records:
        groups[find(rec.provider_id)].append(rec.provider_id)

    by_id = {r.provider_id: r for r in records}
    clusters: list[DuplicateCluster] = []
    for i, (_, ids) in enumerate(sorted(groups.items())):
        if len(ids) < 2:
            continue
        scores = [pair_reason[k][0] for k in pair_reason if k[0] in ids and k[1] in ids]
        reasons = sorted({pair_reason[k][1] for k in pair_reason if k[0] in ids and k[1] in ids})
        npi = next((by_id[i].npi for i in ids if by_id[i].npi), None)
        clusters.append(
            DuplicateCluster(
                cluster_id=f"DUP_{i:03d}",
                provider_ids=sorted(ids),
                npi=npi,
                match_score=round(max(scores), 4) if scores else 1.0,
                reason="; ".join(reasons) or "blocked together",
            )
        )
    return clusters


def is_move(old_address: str | None, new_address: str | None) -> bool:
    """True when the street/city/zip core changed (a move, not reformatting)."""
    old_c = normalize_address(old_address).canonical if old_address else None
    new_c = normalize_address(new_address).canonical if new_address else None
    return bool(old_c and new_c and old_c != new_c)
