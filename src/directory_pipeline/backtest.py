"""Validation / backtesting harness (SOLUTION_PLAN §8.5).

Because the authoritative sources are versioned monthly, accuracy can be *measured*
rather than asserted: treat a past directory snapshot as the input and a later
snapshot as ground truth, run the pipeline, and check whether it proposed the
changes that really happened (recall), avoided wrong ones (auto-update precision),
and routed records correctly. The same harness doubles as a regression test and as
the accuracy score the REAL Health Providers Act now mandates.

In production the ground truth is the *next* real NPPES snapshot (NBER mirror). For
an offline, runnable demo this ships a small labeled case set as a stand-in; the
metric code is identical either way.
"""

from __future__ import annotations

import json
import random
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from directory_pipeline import config
from directory_pipeline.ingest import load_directory
from directory_pipeline.models import ProviderRecord, RecommendedAction
from directory_pipeline.normalize import (
    normalize_active,
    normalize_address,
    normalize_name,
    normalize_phone,
    normalize_practice_name,
    normalize_specialty,
)
from directory_pipeline.pipeline import Pipeline
from directory_pipeline.resolve import is_valid_npi

_DEFAULT_CASES = config.FIXTURES_DIR / "snapshots" / "backtest_cases.json"


def _norm_field(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if field_name == "phone":
        return normalize_phone(value).canonical
    if field_name == "address":
        return normalize_address(value).canonical
    if field_name == "specialty":
        return normalize_specialty(text=value)
    if field_name == "provider_name":
        return normalize_name(value).canonical
    if field_name == "practice_name":
        return normalize_practice_name(value)
    if field_name == "active":
        return normalize_active(value)
    return str(value).strip().lower()


@dataclass
class CalibrationBin:
    lo: float
    hi: float
    count: int
    mean_confidence: float
    empirical_accuracy: float


@dataclass
class BacktestReport:
    records: int
    true_changes: int
    detected_changes: int
    correct_detections: int
    auto_updates: int
    correct_auto_updates: int
    routing_correct: int
    routing_total: int
    brier: float
    ece: float
    calibration: list[CalibrationBin] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.correct_detections / self.true_changes if self.true_changes else 1.0

    @property
    def detection_precision(self) -> float:
        return self.correct_detections / self.detected_changes if self.detected_changes else 1.0

    @property
    def auto_update_precision(self) -> float:
        return self.correct_auto_updates / self.auto_updates if self.auto_updates else 1.0

    @property
    def routing_accuracy(self) -> float:
        return self.routing_correct / self.routing_total if self.routing_total else 1.0

    # Below this many scored changes a calibration curve is statistical noise; the
    # offline 6-record stand-in is well under it, so we annotate rather than mislead.
    MIN_CALIBRATION_SAMPLES = 30

    def render(self) -> str:
        small = self.detected_changes < self.MIN_CALIBRATION_SAMPLES
        lines = [
            "Backtest report (historical-snapshot replay)",
            "=" * 52,
            f"  records evaluated        : {self.records}",
            f"  true field changes       : {self.true_changes}",
            f"  detected (correct/all)   : {self.correct_detections}/{self.detected_changes}",
            "",
            f"  recall                   : {self.recall:6.1%}",
            f"  detection precision      : {self.detection_precision:6.1%}",
            f"  AUTO-UPDATE precision    : {self.auto_update_precision:6.1%}  "
            f"({self.correct_auto_updates}/{self.auto_updates})",
            f"  routing accuracy         : {self.routing_accuracy:6.1%}  "
            f"({self.routing_correct}/{self.routing_total})",
            "",
            f"  Brier score (lower=better): {self.brier:.4f}",
            f"  expected calib. error     : {self.ece:.4f}",
        ]
        if small:
            lines += [
                "",
                f"  NOTE: only {self.detected_changes} scored changes — too few for a stable",
                "        calibration curve. Run `directory-pipeline backtest --scale 5000`",
                "        for the statistically meaningful curve (isotonic in production).",
            ]
        else:
            lines += [
                "",
                "  confidence calibration (predicted vs empirical):",
                "    bucket        n   mean_conf   empirical",
            ]
            for b in self.calibration:
                if b.count == 0:
                    continue
                lines.append(
                    f"    {b.lo:.1f}-{b.hi:.1f}   {b.count:4d}    {b.mean_confidence:6.2f}     "
                    f"{b.empirical_accuracy:6.2f}"
                )
        return "\n".join(lines)


def _calibration(
    samples: list[tuple[float, bool]], n_bins: int = 5
) -> tuple[list[CalibrationBin], float, float]:
    """Reliability bins + Brier score + expected calibration error.

    sklearn's IsotonicRegression is the production calibrator; these
    dependency-free metrics summarize calibration quality for the report.
    """
    if not samples:
        return [], 0.0, 0.0
    brier = sum((conf - (1.0 if ok else 0.0)) ** 2 for conf, ok in samples) / len(samples)
    bins: list[CalibrationBin] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        in_bin = [(c, ok) for c, ok in samples if (lo <= c < hi) or (i == n_bins - 1 and c == 1.0)]
        if in_bin:
            mean_conf = sum(c for c, _ in in_bin) / len(in_bin)
            acc = sum(1 for _, ok in in_bin if ok) / len(in_bin)
            ece += (len(in_bin) / len(samples)) * abs(mean_conf - acc)
            bins.append(CalibrationBin(lo, hi, len(in_bin), mean_conf, acc))
        else:
            bins.append(CalibrationBin(lo, hi, 0, 0.0, 0.0))
    return bins, brier, ece


def run_backtest(
    cases_path: Path | str | None = None,
    *,
    settings: config.Settings | None = None,
    policy: config.ScoringPolicy = config.DEFAULT_POLICY,
) -> BacktestReport:
    """Replay a directory snapshot against labeled ground truth and score it."""
    cases_path = Path(cases_path) if cases_path else _DEFAULT_CASES
    cases = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    truth: dict[str, dict] = cases.get("truth", {})

    if cases.get("directory"):
        records = [ProviderRecord.model_validate(r) for r in cases["directory"]]
    else:
        records = load_directory()

    # Force offline so the backtest is deterministic and needs no network.
    settings = settings or config.Settings.from_env()
    settings = config.Settings(
        offline=True,
        nppes_base_url=settings.nppes_base_url,
        cms_base_url=settings.cms_base_url,
        census_base_url=settings.census_base_url,
        http_timeout=settings.http_timeout,
        fixtures_dir=settings.fixtures_dir,
    )
    pipeline = Pipeline(settings, policy=policy)
    results = pipeline.run(records)

    true_changes = detected = correct_detections = 0
    auto_updates = correct_auto = 0
    routing_correct = routing_total = 0
    calib: list[tuple[float, bool]] = []

    for result in results:
        pid = result.record.provider_id
        case = truth.get(pid, {})
        truth_changes: dict[str, str] = case.get("changes", {})
        true_changes += len(truth_changes)

        expected_action = case.get("expected_action")
        if expected_action:
            routing_total += 1
            if result.recommendation.recommended_action.value == expected_action:
                routing_correct += 1

        is_auto = result.recommendation.recommended_action == RecommendedAction.AUTO_UPDATE
        for change in result.recommendation.changes:
            detected += 1
            expected_val = truth_changes.get(change.field)
            correct = expected_val is not None and _norm_field(
                change.field, change.new_value
            ) == _norm_field(change.field, expected_val)
            if correct:
                correct_detections += 1
            calib.append((change.confidence_score, bool(correct)))
            if is_auto:
                auto_updates += 1
                if correct:
                    correct_auto += 1

    bins, brier, ece = _calibration(calib)
    return BacktestReport(
        records=len(results),
        true_changes=true_changes,
        detected_changes=detected,
        correct_detections=correct_detections,
        auto_updates=auto_updates,
        correct_auto_updates=correct_auto,
        routing_correct=routing_correct,
        routing_total=routing_total,
        brier=round(brier, 4),
        ece=round(ece, 4),
        calibration=bins,
    )


# --------------------------------------------------------------------------- #
# Synthetic scale backtest
# --------------------------------------------------------------------------- #
# The bundled 6-record case set proves the *method* but is far too small for a
# meaningful precision/calibration estimate. This generator fabricates a
# statistically realistic two-snapshot world at arbitrary scale — with known
# ground truth and a small fraction of *stale/wrong sources* (noise) — and runs it
# end-to-end through the real pipeline. In production the very same harness points
# at two consecutive real NPPES snapshots (see scripts/fetch_nppes_snapshots.py);
# here it lets anyone reproduce the headline accuracy numbers with one command.

_CITIES = [
    ("NAPLES", "FL", "34102"),
    ("FORT MYERS", "FL", "33901"),
    ("CAPE CORAL", "FL", "33904"),
    ("BONITA SPRINGS", "FL", "34134"),
    ("ESTERO", "FL", "33928"),
    ("MARCO ISLAND", "FL", "34145"),
]
_STREETS = ["MAIN ST", "PINE RIDGE RD", "BAY RD", "HEALTH PARK DR", "1ST AVE N", "GULF BLVD"]
_TAXONOMIES = [
    ("207RC0000X", "Cardiology"),
    ("207Q00000X", "Family Medicine"),
    ("207R00000X", "Internal Medicine"),
    ("208000000X", "Pediatrics"),
    ("207V00000X", "Obstetrics & Gynecology"),
]


def _make_npi(rng: random.Random) -> str:
    """A random, checksum-valid 10-digit NPI."""
    base = "1" + "".join(str(rng.randint(0, 9)) for _ in range(8))
    for c in range(10):
        cand = base + str(c)
        if is_valid_npi(cand):
            return cand
    return base + "0"  # pragma: no cover - a valid check digit always exists


def _addr(rng: random.Random) -> tuple[str, str]:
    """Return (raw_address_string, '<num> <street>') for a random FL location."""
    num = rng.randint(50, 9999)
    street = rng.choice(_STREETS)
    city, st, zp = rng.choice(_CITIES)
    return f"{num} {street}, {city.title()}, {st} {zp}", f"{num} {street}"


def _phone(rng: random.Random) -> str:
    return f"239-555-{rng.randint(1000, 9999)}"


def _nppes_indiv(
    npi: str, first: str, last: str, taxo: tuple[str, str], addr: str, phone: str, status: str
) -> dict:
    parts = addr.split(", ")
    street = parts[0]
    city = parts[1].upper()
    st, zp = parts[2].split(" ")
    return {
        "result_count": 1,
        "results": [
            {
                "number": npi,
                "enumeration_type": "NPI-1",
                "basic": {
                    "first_name": first,
                    "last_name": last,
                    "credential": "M.D.",
                    "status": status,
                },
                "taxonomies": [{"code": taxo[0], "desc": taxo[1], "primary": True}],
                "addresses": [
                    {
                        "address_purpose": "LOCATION",
                        "address_1": street.upper(),
                        "city": city,
                        "state": st,
                        "postal_code": zp,
                        "telephone_number": phone,
                    }
                ],
            }
        ],
    }


def _cms_row(npi: str, facility: str, addr: str, phone: str) -> dict:
    parts = addr.split(", ")
    st, zp = parts[2].split(" ")
    return {
        "results": [
            {
                "NPI": npi,
                "Facility Name": facility,
                "org_pac_id": "9" + npi[1:],
                "adr_ln_1": parts[0],
                "City/Town": parts[1],
                "State": st,
                "ZIP Code": zp,
                "Telephone Number": phone,
            }
        ]
    }


def _web_fixture(pid: str, fields: dict[str, str]) -> dict:
    return {
        "provider_id": pid,
        "sources": [
            {
                "source_name": "practice_web",
                "source_label": "Practice Website",
                "source_class": "practice_web",
                "url": f"https://example.com/{pid}",
                "fields": {k: {"value": v} for k, v in fields.items()},
            }
        ],
    }


def generate_synthetic_snapshot(n: int, seed: int, out_dir: Path) -> Path:
    """Write a synthetic directory + matching NPPES/CMS/web fixtures + a labeled
    cases file into ``out_dir``. Returns the path to the cases file."""
    rng = random.Random(seed)
    fixtures = out_dir / "fixtures"
    for sub in ("nppes", "cms", "web"):
        (fixtures / sub).mkdir(parents=True, exist_ok=True)

    directory: list[dict] = []
    truth: dict[str, dict] = {}

    # Scenario mix (sums to 1.0) and the rate at which the *sources* are themselves
    # stale/wrong (so a confident auto-update is occasionally incorrect — realism).
    scenarios = ["no_change", "phone", "move", "deactivation", "conflict"]
    weights = [0.50, 0.18, 0.14, 0.08, 0.10]
    noise_rate = 0.04

    for i in range(n):
        pid = f"SYN_{i:05d}"
        npi = _make_npi(rng)
        first, last = f"First{i}", f"Last{i}"
        taxo = rng.choice(_TAXONOMIES)
        cur_addr, _ = _addr(rng)
        cur_phone = _phone(rng)
        facility = f"{last} {taxo[1]} Group"
        verified = (date(2026, 6, 1) - timedelta(days=rng.randint(10, 1500))).isoformat()
        directory.append(
            {
                "provider_id": pid,
                "provider_name": f"{first} {last}, MD",
                "npi": npi,
                "specialty": taxo[1],
                "practice_name": facility,
                "address": cur_addr,
                "phone": cur_phone,
                "website": None,
                "active": True,
                "last_verified_date": verified,
            }
        )

        scenario = rng.choices(scenarios, weights)[0]
        status = "A"
        nppes_addr, nppes_phone = cur_addr, cur_phone
        cms_addr, cms_phone = cur_addr, cur_phone
        web_fields: dict[str, str] = {}
        case_changes: dict[str, str] = {}
        expected = "no_change"

        def _truth(field_name: str, source_val: str) -> str:
            # With prob noise_rate the *real* next-snapshot value differs from what
            # the sources reported (sources were stale) -> a wrong silent update.
            if rng.random() < noise_rate:
                return _phone(rng) if field_name == "phone" else _addr(rng)[0]
            return source_val

        if scenario == "phone":
            new_phone = _phone(rng)
            nppes_phone = cms_phone = new_phone
            web_fields["phone"] = new_phone
            case_changes["phone"] = _truth("phone", new_phone)
            expected = "auto_update"
        elif scenario == "move":
            new_addr, _ = _addr(rng)
            new_phone = _phone(rng)
            nppes_addr = cms_addr = new_addr
            nppes_phone = cms_phone = new_phone
            web_fields = {"address": new_addr, "phone": new_phone}
            case_changes = {
                "address": _truth("address", new_addr),
                "phone": _truth("phone", new_phone),
            }
            expected = "auto_update"
        elif scenario == "deactivation":
            status = "I"
            case_changes["active"] = "Inactive"
            expected = "human_review"
        elif scenario == "conflict":
            new_addr, _ = _addr(rng)
            # NPPES still shows the old address; CMS + web show the new one.
            cms_addr = new_addr
            web_fields["address"] = new_addr
            case_changes["address"] = new_addr
            expected = "human_review"

        npi_path = fixtures / "nppes" / f"{npi}.json"
        npi_path.write_text(
            json.dumps(_nppes_indiv(npi, first, last, taxo, nppes_addr, nppes_phone, status)),
            encoding="utf-8",
        )
        (fixtures / "cms" / f"{npi}.json").write_text(
            json.dumps(_cms_row(npi, facility, cms_addr, cms_phone)), encoding="utf-8"
        )
        if web_fields:
            (fixtures / "web" / f"{pid}.json").write_text(
                json.dumps(_web_fixture(pid, web_fields)), encoding="utf-8"
            )
        truth[pid] = {"changes": case_changes, "expected_action": expected}

    cases_path = out_dir / "cases.json"
    cases_path.write_text(json.dumps({"directory": directory, "truth": truth}), encoding="utf-8")
    return cases_path


def run_scale_backtest(
    n: int = 5000,
    *,
    seed: int = 0,
    policy: config.ScoringPolicy = config.DEFAULT_POLICY,
) -> BacktestReport:
    """Generate an n-record synthetic two-snapshot world and backtest the pipeline
    on it end-to-end (resolve → harvest → normalize → score → decide)."""
    with tempfile.TemporaryDirectory(prefix="dirpipe_backtest_") as tmp:
        out_dir = Path(tmp)
        cases_path = generate_synthetic_snapshot(n, seed, out_dir)
        settings = config.Settings(offline=True, fixtures_dir=out_dir / "fixtures")
        return run_backtest(cases_path, settings=settings, policy=policy)
