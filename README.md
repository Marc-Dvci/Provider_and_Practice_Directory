# Provider & Practice Directory Update Pipeline

A repeatable, cost-efficient pipeline that keeps a healthcare **provider & practice
directory** accurate by reconciling it against free, authoritative U.S. government
data (NPPES, CMS), scoring every proposed change with a transparent
source-weighted formula, and routing only genuine conflicts to a human.

> **Design thesis — deterministic-first, LLM last.** Most provider/practice
> updates already sit in free, structured government datasets, so the pipeline
> resolves the bulk of records at ~$0 marginal cost and reserves web scraping,
> LLMs, and human reviewers for the small residual where structured sources are
> silent or in conflict. See [`SOLUTION_PLAN.md`](SOLUTION_PLAN.md) for the full
> architecture, cost model, and validation strategy this code implements.

It runs **fully offline** against bundled fixtures (no API keys, no network), so
the demo, tests, and CI are deterministic; flip one flag to hit the live APIs.

![Demo](docs/demo.gif)

> **Submission artifacts** (in [`docs/`](docs/)): the polished
> **[proposal PDF](docs/Proposal.pdf)**, the
> **[architecture diagram](docs/architecture.svg)**, the
> **[human-review dashboard](docs/dashboard.png)**, and the demo recording above.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev,calibration]"

directory-pipeline demo          # end-to-end offline showcase (~seconds)
```

The demo reconciles the sample directory, prints a recommendation per record,
writes an append-only audit log, detects duplicates, and finishes with a
**measured** backtest report (precision / recall / calibration).

### Other commands

```bash
# Reconcile a directory and emit the brief's exact JSON schema
directory-pipeline run --offline --json --output recommendations.json

# Process a single record
directory-pipeline run --offline --record HL_001

# Triage: rank records by re-verification risk (the cost lever)
directory-pipeline triage

# Validation harness: measured precision/recall + confidence calibration
directory-pipeline backtest                 # fast offline stand-in (small)
directory-pipeline backtest --scale 5000    # synthetic at scale -> the real curve

# Human-review dashboard (needs the [dashboard] extra)
pip install -e ".[dashboard]"
streamlit run dashboard/app.py
```

Run against the **live** government APIs by dropping `--offline` (or setting
`DIRPIPE_OFFLINE=0`). NPPES and the CMS Provider Data Catalog need no API key.

The dashboard surfaces only the records that need a human, highest-risk and
conflicting first, each field with its calibrated confidence, sources, and conflict
flag:

![Human-review dashboard](docs/dashboard.png)

---

## Architecture

![Agent workflow](docs/architecture.png)

## What it does

First, **triage** (`triage.py`) ranks the directory by re-verification risk
(staleness vs the 90-day cadence, field volatility, hard signals, importance) so a
cycle only actively harvests the records most likely to be wrong.

Then, for each record the pipeline runs the deterministic-first funnel:

1. **Resolve identity** (`resolve.py`) — validate the NPI's Luhn check digit; if
   the NPI is missing or wrong, recover it via an NPPES name / organization search.
   An NPI that maps to a *different* entity becomes a repair ticket, never a silent
   update.
2. **Harvest** free authoritative sources (`sources/`) — NPPES (identity, taxonomy,
   address, phone, deactivation; Type-1 providers **and** Type-2 practices) and CMS
   Doctors & Clinicians (affiliation, practice locations). The gated practice-website
   / state-board corroborator is consulted only for the residual.
3. **Normalize** (`normalize.py`) — addresses → canonical components (suite handled
   separately), phones → E.164, specialties → NUCC taxonomy codes, names → structured
   parts. Comparison is equality on canonical forms, so formatting never looks like a
   change.
4. **Geocode** (`sources/census.py`) — the effective address is validated/standardized
   against the free US Census geocoder; coordinates feed the audit trail and
   practice-location matching.
5. **Score & decide** (`scoring.py`) — a source-weighted confidence per field, with
   independence-aware corroboration, conflict detection, and a high-risk *dissent*
   safety net (a credible inactive/closure signal is never silently left stale), then
   safe-update rules by field risk class.
6. **Audit** (`audit.py`) — every proposal writes an immutable, content-hashed event
   linking old→new, the supporting source snapshots, geocode, and the scoring math.

The pipeline also emits **lifecycle signals** — provider movement / practice
relocation, closure, rebrand, NPI-repair — and `matching.py` adds duplicate
detection with geocoded practice-location proximity across the directory.

### Decision logic (`scoring.py`)

For a field `f` and candidate value `v` asserted by sources `S`:

```
field_conf(f, v) = R(v) · A(v)
    A(v) = Σ_{s:val=v} w(s,f)·φ(s) / Σ_{s∈S} w(s,f)·φ(s)   # agreement share
    R(v) = 1 − Π_{s:val=v} (1 − w(s,f)·φ(s))               # noisy-OR corroboration
```

`A` collapses confidence toward the middle when sources disagree; `R` rewards
multiple *independent* confirmations. Crucially, NPPES and CMS are **not**
independent (both are provider-self-reported to CMS), so same-class sources are
de-correlated before scoring and the corroboration gate requires agreement across
**≥2 distinct independence classes**. Field risk classes (low / medium / high) set
the auto-update thresholds; high-risk fields (name, NPI, active status) are never
updated silently. All weights and thresholds live in `config.py`.

### Output schema

`run --json` emits exactly the brief's structure. Here is the real `HL_001`
output — the practice website and CMS show a new address while NPPES still shows the
old one, so the address conflict drags that field's confidence down and the record
is correctly routed to a human (the phone, agreed by two sources, is high):

```json
{
  "provider_id": "HL_001",
  "npi": "1234567890",
  "change_detected": true,
  "changes": [
    {"field": "address", "old_value": "100 Main St, Naples, FL 34102",
     "new_value": "250 Health Park Dr, Fort Myers, FL 33908",
     "confidence_score": 0.58, "supporting_sources": ["Practice Website", "CMS Doctors & Clinicians"]},
    {"field": "phone", "old_value": "239-555-1234", "new_value": "239-555-9000",
     "confidence_score": 0.88, "supporting_sources": ["NPI Registry", "Practice Website"]}
  ],
  "overall_confidence": 0.73,
  "recommended_action": "human_review",
  "reason": "... Practice Website, CMS Doctors & Clinicians and NPI Registry disagree on address; manual verification recommended."
}
```

---

## Validation / backtesting

Because the authoritative sources are versioned monthly, accuracy is **measured**,
not asserted (`backtest.py`, SOLUTION_PLAN §8.5): a past directory snapshot is
replayed and the pipeline's proposed changes are scored against a later snapshot as
ground truth. The harness reports auto-update precision, recall, routing accuracy,
a Brier score, and a calibration curve — and doubles as a regression test.

Three fidelity levels, same metric code:

| Command | What it runs on | Use |
|---|---|---|
| `directory-pipeline backtest` | 6-record bundled stand-in | fast offline demo / CI regression |
| `directory-pipeline backtest --scale 5000` | synthetic two-snapshot world at scale, with a fraction of stale/wrong sources | the **statistically meaningful** precision + calibration curve |
| `scripts/fetch_nppes_snapshots.py` | two real consecutive NPPES snapshots (NBER mirror) | reproduce the numbers on real provider moves/closures |

A representative `--scale 5000` run: **recall ≈ 98%, auto-update precision ≈ 97%,
routing accuracy 100%**, calibrated (Brier ≈ 0.05). The small bundled set prints a
note instead of a noisy curve — calibration needs ≥30 scored changes to mean
anything.

## Scalability

The hot path is free bulk data, so cost is flat in volume: Tier-0/1 reconciliation
against the national NPPES file (≈8–9M NPIs, ~1 GB) is **embarrassingly parallel**
(partition by state/ZIP) and `pipeline.run` is a pure per-record map — drop it
behind a process pool or a queue of stateless workers with no code change. The
matcher blocks on NPI and `(soundex(name), ZIP)` so dedup never goes quadratic, and
swaps to **Splink** (100M+ on Spark) behind the same blocking strategy. Live calls
are retried with backoff and cached on disk, so re-runs and the 90-day re-verify
cadence don't re-hit the network. See SOLUTION_PLAN §8.

---

## Project layout

```
src/directory_pipeline/
  models.py        Pydantic schemas (brief output + internal provenance)
  config.py        Settings + scoring policy (weights, thresholds, risk classes)
  normalize.py     Address / phone / specialty / name canonicalization
  resolve.py       NPI Luhn validation + cold-start identity resolution
  sources/         NPPES, CMS, web/board, Census harvesters (live + offline)
  scoring.py       Confidence formula + safe-update decision engine
  matching.py      Duplicate detection + geocoded practice-location matching
  triage.py        Risk-ranked re-verification queue (the cost lever)
  audit.py         Append-only, content-hashed event store
  pipeline.py      Orchestration of the full funnel
  backtest.py      Measured precision/recall + calibration (incl. synthetic scale)
  cli.py           `directory-pipeline` entry point
dashboard/app.py   Streamlit human-review screen
scripts/           Real NPPES-snapshot backtest builder (NBER mirror)
data/              Sample directory + offline fixtures + NUCC crosswalk
tests/             Pytest suite
```

## Configuration

All settings are optional (see [`.env.example`](.env.example)); the pipeline runs
offline with zero configuration. Key knobs: `DIRPIPE_OFFLINE`, the source base URLs,
`DIRPIPE_HTTP_TIMEOUT`, `DIRPIPE_HTTP_RETRIES`, `DIRPIPE_HTTP_CACHE`,
`DIRPIPE_TAXONOMY_CSV` (point at the full NUCC release), `DIRPIPE_AUDIT_PATH`,
`DIRPIPE_LOG_LEVEL`.

## Development

```bash
pip install -e ".[dev]"
pytest                 # tests
ruff check . && ruff format --check .
mypy
```

## Production notes

The MVP makes deliberate, documented swaps for a lean, installable repo:

- **Matching** uses a dependency-free Fellegi–Sunter matcher; production swaps in
  **Splink** behind the same blocking strategy for 100M+ scale.
- **Address parsing** prefers [`usaddress`](https://pypi.org/project/usaddress/)
  (install the `address` extra) and falls back to a regex parser; production can
  upgrade to **libpostal**. The **Census geocoder** (`sources/census.py`) is wired
  into the pipeline today — offline it echoes the canonical form; live it attaches
  coordinates used for the audit trail and practice-location proximity matching.
- **Specialty crosswalk** ships a curated NUCC subset (`data/taxonomy_crosswalk.csv`)
  loaded lazily; point `DIRPIPE_TAXONOMY_CSV` at the full official release in prod.
- **Tier-3 enrichment** (practice website / state board) is fixture-driven here;
  production dispatches a gated, budget-capped scrape + LLM-extraction agent that
  only *extracts* from fetched text and must still clear the scoring gate.
- **Live API calls** retry with exponential backoff and cache on disk
  (`DIRPIPE_HTTP_*`), so re-runs and the re-verify cadence stay cheap.

## Data sources

NPPES NPI Registry (API + bulk), CMS Doctors & Clinicians (`mj5m-pzi6`), US Census
geocoder — all free and authoritative. See SOLUTION_PLAN §4 and §14 for the full
list, reliability tiers, and the regulatory context (No Surprises Act; REAL Health
Providers Act).

## License

MIT — see [`LICENSE`](LICENSE).
