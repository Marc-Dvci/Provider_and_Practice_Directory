#!/usr/bin/env python
"""Build a *real* historical backtest from two NPPES snapshots (SOLUTION_PLAN §8.5).

The synthetic `directory-pipeline backtest --scale` proves the method at scale; this
script proves it on real data. CMS keeps no NPPES history, but NBER mirrors every
monthly/weekly file (https://data.nber.org/npi/ , 2017->present). Given two monthly
snapshots T and T+Δ this script:

  1. reads NPI -> (address, phone, status) from each snapshot CSV,
  2. treats snapshot **T** as "the directory" (what HealthLynked held back then),
  3. treats the diff to snapshot **T+Δ** as ground truth (what really changed),
  4. writes the later snapshot as offline fixtures, so the existing harness can
     replay it deterministically:

        directory-pipeline backtest --cases <out>/cases.json   # with DIRPIPE fixtures

This is intentionally NOT imported by the package and NOT run in CI (the files are
~1 GB). It is the reproducibility bridge between "trust me" and "here is the curve
on real provider moves/closures." Run it once, locally, to regenerate real numbers.

Usage:
    python scripts/fetch_nppes_snapshots.py \
        --from data/snapshots/npidata_2025-01.csv \
        --to   data/snapshots/npidata_2025-04.csv \
        --out  data/snapshots/backtest_2025Q1 \
        --limit 20000

(Download the CSVs from the NBER mirror first, or pass --download with --from-month
/--to-month like 2025-01 to fetch them automatically.)
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from urllib.request import urlretrieve

NBER_BASE = "https://data.nber.org/npi"

# Actual NPPES data-dissemination CSV headers (practice LOCATION address).
COL_NPI = "NPI"
COL_ENTITY = "Entity Type Code"  # 1 = individual, 2 = organization
COL_ADDR = "Provider First Line Business Practice Location Address"
COL_CITY = "Provider Business Practice Location Address City Name"
COL_STATE = "Provider Business Practice Location Address State Name"
COL_ZIP = "Provider Business Practice Location Address Postal Code"
COL_PHONE = "Provider Business Practice Location Address Telephone Number"
COL_DEACT = "NPI Deactivation Date"
COL_FIRST = "Provider First Name"
COL_LAST = "Provider Last Name (Legal Name)"
COL_ORG = "Provider Organization Name (Legal Business Name)"


def _zip5(z: str) -> str:
    digits = "".join(c for c in z if c.isdigit())
    return digits[:5]


def _address(row: dict[str, str]) -> str:
    parts = [row.get(COL_ADDR, "").strip(), row.get(COL_CITY, "").strip()]
    tail = " ".join(p for p in (row.get(COL_STATE, "").strip(), _zip5(row.get(COL_ZIP, ""))) if p)
    line = ", ".join(p for p in parts if p)
    return ", ".join(p for p in (line, tail) if p)


def load_snapshot(path: Path, limit: int | None = None) -> dict[str, dict[str, str]]:
    """NPI -> {address, phone, status, name, ...} from an NPPES CSV."""
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            npi = (row.get(COL_NPI) or "").strip()
            if not npi:
                continue
            out[npi] = {
                "address": _address(row),
                "phone": (row.get(COL_PHONE) or "").strip(),
                "status": "I" if (row.get(COL_DEACT) or "").strip() else "A",
                "entity": (row.get(COL_ENTITY) or "1").strip(),
                "first": (row.get(COL_FIRST) or "").strip().title(),
                "last": (row.get(COL_LAST) or "").strip().title(),
                "org": (row.get(COL_ORG) or "").strip(),
            }
    return out


def build_cases(snap_from: dict, snap_to: dict, limit: int) -> dict:
    """Directory = snapshot T; truth = the fields that changed by T+Δ."""
    directory: list[dict] = []
    truth: dict[str, dict] = {}
    changed = 0
    for npi, old in snap_from.items():
        new = snap_to.get(npi)
        if new is None:
            continue
        changes: dict[str, str] = {}
        if old["address"] != new["address"] and new["address"]:
            changes["address"] = new["address"]
        if old["phone"] != new["phone"] and new["phone"]:
            changes["phone"] = new["phone"]
        if old["status"] == "A" and new["status"] == "I":
            changes["active"] = "Inactive"
        is_org = old["entity"] == "2"
        directory.append(
            {
                "provider_id": f"NPI_{npi}",
                "provider_name": None if is_org else f"{old['first']} {old['last']}, MD",
                "npi": npi,
                "practice_name": old["org"] or f"{old['last']} Practice",
                "address": old["address"],
                "phone": old["phone"],
                "active": old["status"] == "A",
            }
        )
        expected = "no_change"
        if "active" in changes:
            expected = "human_review"
        elif changes:
            expected = "auto_update"
        truth[f"NPI_{npi}"] = {"changes": changes, "expected_action": expected}
        if changes:
            changed += 1
        if changed >= limit:
            break
    return {"directory": directory, "truth": truth}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from", dest="frm", help="snapshot T CSV path")
    p.add_argument("--to", dest="to", help="snapshot T+Δ CSV path")
    p.add_argument("--from-month", help="e.g. 2025-01 (with --download)")
    p.add_argument("--to-month", help="e.g. 2025-04 (with --download)")
    p.add_argument("--download", action="store_true", help="fetch CSVs from the NBER mirror")
    p.add_argument("--out", required=True, help="output directory for cases.json")
    p.add_argument("--limit", type=int, default=20000, help="cap records (memory/time)")
    args = p.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.download:
        if not (args.from_month and args.to_month):
            p.error("--download requires --from-month and --to-month")
        frm = out_dir / f"npidata_{args.from_month}.csv"
        to = out_dir / f"npidata_{args.to_month}.csv"
        for month, dest in ((args.from_month, frm), (args.to_month, to)):
            year = month.split("-")[0]
            url = f"{NBER_BASE}/{year}/npidata_{month}.csv"  # adjust to the mirror's layout
            print(f"downloading {url} -> {dest}")
            urlretrieve(url, dest)
    else:
        if not (args.frm and args.to):
            p.error("pass --from/--to CSV paths, or --download with --from-month/--to-month")
        frm, to = Path(args.frm), Path(args.to)

    print("loading snapshots...")
    snap_from = load_snapshot(frm, args.limit)
    snap_to = load_snapshot(to, args.limit)
    cases = build_cases(snap_from, snap_to, args.limit)
    cases_path = out_dir / "cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    n_changed = sum(1 for t in cases["truth"].values() if t["changes"])
    print(f"wrote {cases_path}: {len(cases['directory'])} records, {n_changed} with real changes")
    print("next: generate fixtures from the later snapshot, then `directory-pipeline backtest`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
