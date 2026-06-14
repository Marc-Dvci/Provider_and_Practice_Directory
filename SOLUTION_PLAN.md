# HealthLynked — Provider & Practice Directory Update Pipeline
## Research notes + the optimal solution to build, and how to win the $5,000 challenge

*Prepared 2026-06-13. Solo submission. Voice = "I".*

---

## 0. TL;DR — what to submit and why

**Submit Option C (Hybrid): a Technical Architecture Proposal + a small working prototype.**

The prize is not just $5,000 — the winner is hired as a consultant for 3 months to actually build this. That changes the optimal strategy: the judges are choosing a person they will trust to ship a production system, not just grading a document. A clean working MVP that runs on the example record (`HL_001`, Naples FL) and emits the exact JSON schema they specified is the single highest-leverage thing I can show. It de-risks me in their eyes and sweeps most of the bonus-point list.

**The winning thesis in one sentence:** *Most provider/practice updates are already sitting in free, authoritative, structured U.S. government datasets (NPPES + CMS), so the optimal pipeline is a deterministic-first funnel that resolves the bulk of records at ~$0 marginal cost and reserves LLMs, web scraping, and human reviewers for only the small residual where structured sources are silent or in conflict.*

Everything below is engineered around that thesis because it is exactly what their evaluation criteria reward: accuracy (authoritative sources), cost efficiency (free data does the heavy lifting), explainability (transparent source-weighted scoring), and practicality (a lean team can build it).

**Two things separate this from the proposals they'll see most often:**
1. **I measure accuracy, I don't just claim it.** Because the government sources are versioned monthly, I can *backtest* the whole pipeline on real historical provider moves/closures and report measured precision + a calibration curve (§8.5) — for free, before HealthLynked spends a dollar. "Here's the curve" beats "trust me," and it's exactly what wins a *consulting* hire over a document.
2. **The timing is now a legal mandate, not a nice-to-have.** The **REAL Health Providers Act became law on 2026-02-03**, requiring Medicare Advantage plans to *measure and publicly report* directory accuracy from PY2028 (§1). A pipeline that emits a defensible, auditable accuracy score is the compliance product HealthLynked's payer customers will be *required* to buy.

---

## 1. Who HealthLynked is (and why it shapes the answer)

- HealthLynked Corp. (OTCQB: **HLYK**), Naples, FL. Cloud platform connecting patients & providers; runs a consumer **Provider Directory** and a **Practice Directory** (18,000+ OBGYN offices, 30,000+ primary-care listings).
- They are now selling directory/data value to **insurers, TPAs, pharma, ACOs** (hlykgroup.com). That means **directory accuracy is a sellable product feature**, and their buyers (payers) are legally bound by the **No Surprises Act** to verify provider directories every 90 days and apply corrections within 2 business days. → My proposal should explicitly frame accuracy as a compliance/revenue asset, not just hygiene.
- **Regulatory tailwind just became law (use this — it's the strongest "why now").** The **REAL Health Providers Act** (Requiring Enhanced & Accurate Lists of Health Providers) was **signed into law on 2026-02-03** inside the Consolidated Appropriations Act, 2026. Starting **plan year 2028**, Medicare Advantage organizations must: verify every directory field at least every 90 days, **remove a provider within 5 days** of learning they left the network, and — for the first time ever — **run an annual accuracy analysis and publicly report an accuracy score.** Congress has now legislated a national mandate to *measure and disclose* directory accuracy. That reframes this whole project: a pipeline that not only fixes records but **emits a defensible, auditable accuracy score** is exactly the compliance product HealthLynked's payer customers will be forced to buy. I will make "we measure accuracy, not just chase it" a headline.
- It's a small-cap company → **lean engineering team, real cost sensitivity.** A baroque multi-agent architecture loses; a pragmatic, mostly-free pipeline wins.

The example record being a Naples cardiologist is not random — that's their backyard. The prototype should use that exact record.

---

## 2. The challenge, decoded into what actually scores

The brief lists 9 evaluation criteria + a long bonus list. Mapping each to the design decision that earns it:

| Criterion | What earns the points |
|---|---|
| **Accuracy** | Anchor on authoritative structured sources (NPPES/CMS) before ever touching an LLM or a scrape; never auto-update on a single weak source. **And prove it**: a historical-snapshot **backtest** (§8.5) measures real precision/recall instead of just asserting a number — most submissions will only assert. |
| **Scalability** | Batch reconciliation against national bulk files is embarrassingly parallel; Splink dedups millions on a laptop. State concrete numbers (8–9M NPIs, ~1 GB file). |
| **Cost Efficiency** | Deterministic free funnel resolves ~85–95% of records; LLM/scrape/human only on the residual. Give a per-1,000-record cost table. |
| **Practicality** | Mostly free OSS + free gov APIs; no exotic infra; a 2–3 person team can run it. Phased roadmap. |
| **Explainability** | Every recommendation carries the scoring math + the source snapshots that drove it. |
| **Data Quality** | libpostal + Census geocoder (address), libphonenumber (phone), NPI taxonomy crosswalk (specialty), canonical name parsing. |
| **Source Reliability** | Explicit per-source, per-field reliability weights; conflict handling baked into the confidence formula. |
| **Human Review Design** | Risk-tiered routing so only true conflicts/low-confidence reach a human; a sketched review dashboard. |
| **Audit Trail** | Append-only event store; every change links to source evidence + the confidence computation that approved it. |

**Bonus checklist I will explicitly hit:** working prototype · agent workflow diagram · cost per 1,000 records · confidence-scoring formula · human-review dashboard · duplicate detection · address normalization · NPI validation · practice-location matching · provider-movement detection · inactive/retired detection · change history/audit log · safe auto-update rules · implementation roadmap. **That is all 14 bonus items.**

---

## 3. The core insight: a deterministic-first funnel, LLM last

Naive solutions burn money by treating this as "web-search + LLM every record." The optimal design recognizes a **cost/authority gradient** and routes each record only as far down it as needed:

```
TIER 0 — Authoritative structured reconciliation         cost ≈ $0/record, highest authority
  Diff the directory against NPPES + CMS bulk/API.
  Resolves identity, NPI, specialty/taxonomy, primary
  practice address & phone for the large majority.
        │  (only records still uncertain/conflicting fall through)
        ▼
TIER 1 — Deterministic normalization & matching          cost ≈ $0/record
  libpostal/Census (address), libphonenumber (phone),
  taxonomy crosswalk (specialty), Splink (entity res /
  dedup / movement detection).
        │  (residual: structured sources silent or disagree)
        ▼
TIER 2 — Confidence scoring + decision gate              cost ≈ $0/record
  Source-weighted formula → auto_update / human_review /
  no_change, with safe-update rules per field class.
        │  (only records that NEED fresh evidence)
        ▼
TIER 3 — Agentic web/LLM enrichment                      cost = the only $$ tier; gated
  Fetch practice website / state board, LLM-extract,
  re-score. Budget-capped, batched, cached.
        │
        ▼
TIER 4 — Human review (smallest slice)                   most expensive per item; minimized by design
```

The economic point I will hammer in the proposal: **the expensive tiers (3 and 4) only ever see the records the free tiers couldn't resolve.** That single architectural choice is what makes the cost curve flat as volume grows.

---

## 4. Data sources & reliability tiers (free first)

I researched and confirmed these are free, legal, and authoritative:

| Source | What it's authoritative for | Access | Cost | Per-field reliability |
|---|---|---|---|---|
| **NPPES NPI Registry** (CMS) | Covers **both halves of the brief**: Type-1 NPIs = individual **providers**; Type-2 NPIs = **organizations/practices** (legal business name, DBA, former names, org address & phone). NPI validity, legal/provider name, taxonomy→specialty, practice & mailing address, phone, sole-proprietor, **deactivation**. | Free **API** (`npiregistry.cms.hhs.gov/api/`, v2.1, no key, refreshed daily) — supports **lookup by NPI** *and* **search by name / org-name / taxonomy with trailing wildcards** (this is what powers cold-start NPI resolution, §6.0). Free **bulk** (monthly full-replacement ~1 GB zip, weekly incremental, monthly deactivation file; **use the V2 file format — V1 was retired 2026-03-03**). | $0 | Identity/NPI/specialty: **very high**. Address/phone: **high but self-reported (can lag)**. |
| **Historical NPPES & CMS snapshots** | Time-series of every monthly file → lets me replay "the directory N months ago" vs "ground truth now". **The backbone of the §8.5 backtest.** | CMS does *not* keep history, but **NBER mirrors monthly/weekly NPPES files 2017→2026** (`data.nber.org/npi/YYYY/`), and CMS keeps **archived Doctors & Clinicians snapshots** (`data.cms.gov/provider-data/archived-data/doctors-clinicians`). | $0 | Ground-truth for validation: **high** (it's the same authoritative data, just time-stamped). |
| **CMS Doctors & Clinicians National Downloadable File** (Provider Data Catalog, dataset `mj5m-pzi6`, ~2.5M rows) | Medicare-enrolled clinicians, **group/practice affiliation** (PAC ID/org), **multiple practice locations**, phone, active Medicare enrollment | Free **API** (`data.cms.gov/provider-data/api/1/datastore/query/mj5m-pzi6/0`, offset/limit paging) + bulk CSV, ~monthly | $0 | Affiliation & practice location: **high**. Confirms "provider works here now." |
| **CMS PECOS / Medicare enrollment & Order-and-Referring file** | Active enrollment / eligibility status | Free bulk | $0 | Active/inactive corroboration: **high**. |
| **State medical board license lookups** | License status (active/inactive/disciplinary), credential | Per-state; some APIs/bulk, many require scraping | $0 (scrape cost) | License/active status: **high**; access effort: **variable**. |
| **Practice website** | Current phone, address, suite, provider roster | Scrape + LLM extract (Tier 3 only) | $ (scrape+LLM) | **Low structured reliability**, but strong corroborator when it agrees. |
| **US Census Geocoder** | Address canonicalization/validation, geocode | Free API, no key | $0 | Address standardization: **high**. |
| **USPS Address APIs** | Address standardization (allowed-use only) | Free API | $0 | ⚠️ TOS forbids using it to *source/derive* directory addresses — use only to validate/standardize addresses we already hold. (Flagging this shows compliance awareness; default to Census for canonicalization.) |

Deliberately **avoided** paid APIs (Google Places, Melissa, commercial provider-data vendors) in the default path — they're the easy way to blow the cost budget and the brief explicitly penalizes "unnecessary paid APIs."

---

## 5. System architecture (the agent workflow diagram)

Seven cooperating components. I'll render this as a clean diagram in the submission; ASCII version here:

```
                 ┌─────────────────────────────────────────────┐
                 │   HealthLynked Provider/Practice Directory    │
                 │            (system of record)                 │
                 └───────────────┬───────────────────────────────┘
                                 │ snapshot
                                 ▼
   (1) TRIAGE / RISK AGENT  ── scores staleness & risk, builds the verify queue
        • days since last_verified_date (NSA 90-day cadence)
        • field-volatility priors (phone>address>name)
        • signal hits: NPI in deactivation file, NPPES monthly diff, returned mail
                                 │ prioritized records
                                 ▼
   (2) SOURCE HARVEST  ── pulls candidate values per record
        Tier 0/1 (free, always):  NPPES API/bulk · CMS Doctors&Clinicians · PECOS
        Tier 3 (gated, residual):  practice website · state board   →  (6) EXTRACTION AGENT (LLM)
                                 │ raw candidate values + source provenance
                                 ▼
   (3) NORMALIZATION ENGINE  ── deterministic canonicalization
        address(libpostal+Census) · phone(libphonenumber/E.164) · specialty(taxonomy crosswalk) · name(parse+casefold)
                                 │ normalized values
                                 ▼
   (4) MATCHING / ENTITY-RESOLUTION ENGINE  (Splink, Fellegi–Sunter)
        record↔record dedup · provider↔practice-location match · movement detection · inactive detection
                                 │ matched & linked entities + field-level value sets
                                 ▼
   (5) CONFIDENCE & DECISION ENGINE  ── source-weighted formula + safe-update rules
                                 │
         ┌───────────────┬───────┴───────────┬───────────────────┐
         ▼               ▼                   ▼                   ▼
     NO CHANGE      AUTO-UPDATE         HUMAN REVIEW         DISCARD/HOLD
   (confirmed)   (high conf + safe)  (conflict/mid conf)   (too weak)
         │               │                   │                   │
         └───────────────┴─────────┬─────────┴───────────────────┘
                                    ▼
   (7) AUDIT/PROVENANCE STORE (append-only)  →  writes back to Directory
        every event: old→new, sources+snapshots, score math, decision, actor, timestamp
   (8) HUMAN-REVIEW DASHBOARD reads the review queue; approvals/rejections feed back as labels
```

Naming the boxes "agents" earns the *agent workflow diagram* bonus; keeping most of them deterministic earns the *cost efficiency* and *practicality* points. (Note: only boxes 1, 2-harvest, and 6 are "agentic"; 3/4/5 are plain deterministic code. That honesty is a selling point — judges have seen too many "10 LLM agents" proposals.)

---

## 6. Component deep-dives

### 6.0 Identity / NPI resolution — *the cold-start step the brief's clean example hides*
The example record `HL_001` arrives with a valid NPI, so Tier-0 reconciliation is a trivial keyed lookup. Real directories aren't that tidy: a meaningful slice of rows have a **missing, malformed, or wrong NPI**, or are **practice records with no NPI at all**. Those rows can't be keyed against NPPES until I *resolve* them first, so this is step zero of the funnel:

- **Has a plausible NPI →** validate the **Luhn check-digit** (NPIs are 10 digits with a built-in checksum, prefix `80840`), then confirm the returned name/taxonomy actually matches the record. A passing checksum that maps to a different person = data-entry error → repair ticket, *never* a silent field update.
- **No / bad NPI, individual →** NPPES API **search by name + state (+ taxonomy)** with trailing wildcards, then run the §6.3 entity-resolution scorer over the candidates to accept a match only above threshold (else → human review). 
- **Practice record →** NPPES **organization-name search (Type-2 NPI)** + CMS affiliation to attach the practice to its org NPI and its locations.
- This step is **free (NPPES API)**, cached, and gates everything downstream — a record whose identity I can't resolve confidently is quarantined rather than guessed at.

### 6.1 Triage / risk selection — *don't re-verify everything*
The cheapest verification is the one you skip. Each record gets a **risk score**:

```
risk = w1·staleness(days_since_verified)          # NSA 90-day cadence sets the clock
     + w2·field_volatility_prior                  # phone & suite churn > name
     + w3·hard_signal                             # NPI deactivation-file hit, NPPES monthly diff, bounce-back
     + w4·directory_importance                    # high-traffic / sold-to-payer records first
```
Only the top of the queue gets actively harvested each cycle; everything else rides the free monthly batch diff. This is the biggest single cost lever and directly answers "Identify provider and practice records that may be outdated."

### 6.2 Normalization (Data Quality bonus)
- **Address:** parse with `libpostal` → standardize/validate via **Census Geocoder** → canonical components (street, suite, city, state, ZIP+4, lat/lng). Compare on canonical form, not raw strings, so "100 Main St" == "100 Main Street, Ste 2".
- **Phone:** `libphonenumber` → E.164; strip extensions to a separate field. Avoids false diffs from formatting.
- **Specialty:** map free-text/credential strings to the **NUCC Healthcare Provider Taxonomy** code via NPPES, then to HealthLynked's specialty vocabulary through a crosswalk table. Cardiology ↔ `207RC0000X`.
- **Name:** parse to {prefix, given, middle, family, suffix, credentials}; case-fold; keep credentials (MD/DO/NP) as structured flags, not name noise.

### 6.3 Matching / entity resolution (Splink) — dedup, movement, inactive
**Splink** (probabilistic Fellegi–Sunter record linkage, free, scales to 100M+ with Spark, ~1M/min on a laptop) is the workhorse for:
- **Duplicate detection:** block on NPI / soundex(name)+ZIP; match on normalized name, address, phone, taxonomy with term-frequency adjustments. NPI is a near-unique key, so blocking is cheap and precise.
- **Practice-location matching:** link a provider to the right practice location using the CMS multi-location records + geocoded address proximity.
- **Practice-entity reconciliation (the "practice directory" half):** resolve each practice to its **Type-2 org NPI** and CMS group (PAC ID). Detect **practice close/merge/rebrand** as structured signals, not guesses: org NPI in the deactivation file → likely **closed**; the practice's providers en-masse re-affiliating to a new group PAC ID → **merge/acquisition**; same org NPI + same address but a new legal-business-name/DBA → **rebrand** (update the name, don't spawn a duplicate).
- **Provider-movement detection:** when a provider's authoritative practice address in NPPES/CMS shifts across monthly snapshots (or appears at a new group PAC ID), flag a **move**, not a data error.
- **Inactive/retired detection:** NPI present in the **deactivation file**, or dropped from active Medicare enrollment, or license lapsed at the state board → propose `active=false` (high-risk class → corroboration required, see rules).

### 6.4 Confidence scoring formula (explicit — bonus)
For a changed field `f` with candidate new value `v`, let `S` be the sources that assert a value for `f`. Each source `s` carries a **per-field reliability weight** `w(s,f) ∈ [0,1]` (Table §4) and a **freshness factor** `φ(s) = decay(age_of_source_data)`.

```
              Σ_{s∈S : value(s)=v}  w(s,f)·φ(s)
field_conf(f,v) = ─────────────────────────────────────      ∈ [0,1]
                      Σ_{s∈S}  w(s,f)·φ(s)
```

- Sources **agreeing** on `v` push the numerator up; sources asserting a **different** value stay in the denominator only → genuine conflict mechanically drags confidence toward the ambiguous middle. (The `HL_001` conflict example — website vs NPI Registry disagree → ~0.61 → human_review — falls straight out of this.)
- **Corroboration gate — and what "independent" actually means:** for medium/high-risk fields, require **≥2 sources from ≥2 distinct independence classes** asserting `v` (one strong source alone never auto-updates a name or active-status). This guards against a trap most naive scorers fall into: **NPPES and CMS are *not* independent** — both are ultimately self-reported by the provider to CMS, so they often agree *because they share an origin, not because the value is true.* I define four independence classes — **(a)** provider-self-reported government (NPPES), **(b)** claims/enrollment-derived government (CMS PECOS, Doctors & Clinicians), **(c)** the practice's own web presence, **(d)** regulatory/board (state license). Corroboration must span ≥2 classes; agreeing sources *within* one class are down-weighted by a correlation factor `ρ` so they can't masquerade as independent confirmation.

Record-level number reported two ways:
- `overall_confidence` (for the human, an aggregate) = weighted mean of changed-field confidences.
- **Decision uses the *minimum* changed-field confidence** (conservative — one shaky field shouldn't ride in on a confident one).

Weights & thresholds are **config, learned and tuned from human-review outcomes over time** (the dashboard's approve/reject decisions are labels) — so the system gets more autonomous as it earns trust. I'll ship sensible defaults and show the tuning loop.

### 6.5 Decision + safe auto-update rules (bonus)
Field **risk classes** govern thresholds:

| Class | Fields | Rule |
|---|---|---|
| **Low** | phone, suite/unit, website, address formatting | auto-update if `field_conf ≥ 0.85` and no active conflict |
| **Medium** | full practice address (move), specialty, affiliation | auto-update if `field_conf ≥ 0.90` **and ≥2 independent sources** |
| **High** | provider name, **NPI**, active/inactive status, practice merge/close | **never silent**: require `≥0.95` + ≥2 strong sources *and still* route to human for confirmation |

```
if no field differs from canonical → NO_CHANGE
elif any changed field has active conflict → HUMAN_REVIEW
elif min(field_conf) ≥ class_threshold and corroboration_met → AUTO_UPDATE
elif min(field_conf) ≥ τ_low → HUMAN_REVIEW
else → DISCARD/HOLD (don't touch the directory; re-queue later)
```

Special **NPI rule:** the NPI itself should essentially never change for a real provider. An NPI mismatch means a data-entry error or a merged duplicate, **never** an auto-update — it's a high-priority dedup/repair ticket. (Calling this out shows domain depth.)

### 6.6 Human-review dashboard (sketch — bonus)
A lean web UI (Streamlit/React) showing one record per card:

```
┌─ Review: John Smith, MD  (NPI 1234567890)            risk: HIGH ─┐
│ Field    | Current            | Proposed              | Conf | Sources        │
│ address  | 100 Main St,Naples | 250 Health Park Dr,FM | 0.61 | Web≠NPPES ⚠   │
│ phone    | 239-555-1234       | 239-555-9000          | 0.88 | Web+NPPES ✓   │
│                                                                                │
│  [side-by-side source snapshots]   [map: old ⟶ new pin]                        │
│  [✓ Approve all]  [✗ Reject]  [Approve phone only]  [Snooze]  notes:[____]     │
└────────────────────────────────────────────────────────────────────────────────┘
```
Every click is logged as a training label. Queue is sorted by risk × directory importance so reviewer time goes to what matters. Target: a single reviewer clears the daily residual in under an hour.

### 6.7 Audit trail / provenance (bonus)
**Append-only event store** (e.g., Postgres table or event log). Every proposed/applied change writes one immutable event:
```json
{ "event_id","provider_id","npi","field","old_value","new_value",
  "decision":"auto_update|human_review|no_change",
  "field_confidence","overall_confidence",
  "sources":[{"name","url","retrieved_at","snapshot_hash","asserted_value","weight"}],
  "score_breakdown":{...the formula inputs...},
  "actor":"pipeline|reviewer_id","timestamp","pipeline_version" }
```
Source **snapshots are content-hashed and stored**, so an update is reproducible and defensible months later — exactly what "trace every update back to sources and confidence logic" asks for, and what a payer's compliance auditor will want.

---

## 7. Cost model — per 1,000 provider records (bonus)

Assumes the deterministic funnel resolves the bulk and only the residual hits paid tiers. Conservative numbers:

| Stage | Records touched / 1,000 | Unit cost | Subtotal |
|---|---|---|---|
| Tier 0/1 batch reconcile (NPPES+CMS bulk, compute, amortized) | 1,000 | ~$0.0005 | **$0.50** |
| NPPES API + Census geocode (targeted) | ~300 | $0 (free APIs) | **$0** |
| Tier 3 web fetch + LLM extraction (residual only) | ~100 (10%) | ~$0.01–0.03 | **$1–3** |
| Human review (true conflicts only) | ~30–50 (3–5%) | ~$1.00/review | **$30–50** |
| **Total** | | | **≈ $32–54 / 1,000 records ≈ $0.03–0.05 per record** |

The cost is **dominated by human review**, which the entire architecture exists to minimize, and is **flat in volume** because Tiers 0–1 are batch/free. Doubling the directory roughly doubles only a near-zero line. *That* is the cost story judges want.

(Contrast: a "LLM-every-record + paid address API" approach lands around $0.30–1.00+/record — 10–20× more — and is less accurate. I'll show this comparison.)

---

## 8. Scalability

- NPPES national file ≈ **8–9M NPIs, ~1 GB zipped** — trivially ingested monthly; full-directory reconciliation is **embarrassingly parallel** (partition by state/ZIP).
- **Splink** dedups millions on a single machine, 100M+ on Spark/Athena — covers HealthLynked far past current size.
- Stateless workers behind a queue; horizontal scale by adding workers. No paid-API rate limits gate the hot path because the hot path is free bulk data.
- Periodic cadence: **monthly** full reconcile (free), **weekly** NPPES incremental + deactivation diff, **event-driven** triage feeding Tier 3. Orchestrate with Prefect/Dagster/Airflow (or plain cron + queue for the MVP).

---

## 8.5 Validation, backtesting & calibration — *how I prove the accuracy claims*

This is the section most competing proposals will not have, and it's the one that wins a *consulting* engagement: anyone can assert "99% precision"; I can **measure** it on real data, for free, before HealthLynked spends a dollar. It also produces exactly the accuracy score the REAL Health Providers Act now makes mandatory (§1).

**The trick — time-travel with historical snapshots (no hand-labeling needed).** The authoritative sources are themselves versioned monthly (NBER's NPPES mirror 2017→2026; CMS's archived Doctors & Clinicians, §4). So I can run a true **backtest**:

```
  Take the authoritative snapshot at month T          →  treat as "the directory" (with known staleness injected)
  Run the full pipeline using only sources as-of T
  Compare its proposed changes against snapshot T+Δ    →  the change that actually happened = ground truth
```

Because the *future* snapshot tells me what really changed (a real move, a real deactivation, a real rebrand), I get labels **for free, at national scale**, and can measure:

| Metric | Why it's the one that matters |
|---|---|
| **Auto-update precision** (1 − wrong-silent-change rate) | The cardinal sin is silently writing a *wrong* value. This is the KPI I commit to (≥99%) and the one the backtest is built to bound. |
| **Recall of real changes** | Of the moves/closures/deactivations that genuinely happened, how many did the pipeline catch (vs leave stale)? |
| **Routing correctness** | Were the records sent to `human_review` actually the ambiguous ones, and the `auto_update`s actually safe? Drives the cost model. |
| **Per-field-class breakdown** | Precision/recall split by low/med/high-risk class (§6.5), so thresholds are tuned per class, not globally. |

**Confidence calibration.** A score of `0.90` should mean *~90% of such updates are correct* — otherwise the thresholds in §6.5 are arbitrary. I fit a **reliability curve** (isotonic / Platt scaling) on backtest outcomes so the published confidence is calibrated, not just monotonic. Calibrated scores are what make the audit trail and the mandated public accuracy score *defensible to a payer's compliance auditor*.

**Honest about the one thing snapshots can't tell me.** Backtesting measures agreement with the authoritative record, and NPPES address/phone is self-reported and can lag the real world (§4, §12). So for the fields where ground truth lives *off* the government grid — current suite, working phone — I hold out a **small hand-labeled gold set** (a few hundred records verified by phone/web) to measure real-world precision and to keep the Tier-3 enrichment honest. The backtest covers identity/taxonomy/affiliation/deactivation at scale; the gold set covers on-the-ground contact accuracy in depth.

**Why this is cheap and credible:** the data is free and already downloaded for Tier 0/1, the labels are automatic, and the same harness runs every cycle as a **regression test** — so a threshold change or a new source can never silently degrade precision without the backtest catching it. This is the difference between "trust me" and "here's the curve."

## 9. MVP prototype scope (what I'll actually build) + stack

Keep it lean, runnable, and mapped to the exact brief schema. Python.

**Pipeline (`pipeline/`):**
1. `ingest.py` — load sample directory (incl. the brief's `HL_001`).
2. `resolve.py` — NPI resolution / cold-start (§6.0): Luhn check-digit validation + NPPES name/org-name search for rows with missing or bad NPIs.
3. `harvest_nppes.py` — query NPPES API v2.1 by NPI (free, no key) → authoritative candidate values.
4. `harvest_cms.py` — query CMS Doctors & Clinicians (`mj5m-pzi6`) for affiliation/locations.
5. `normalize.py` — libpostal/`usaddress` + Census geocoder, `phonenumbers`, taxonomy crosswalk.
6. `match.py` — Splink demo on a small synthetic set to show dedup + movement.
7. `score.py` — the §6.4 formula + §6.5 decision rules → emits the **exact JSON** from the brief.
8. `audit.py` — append-only JSONL/SQLite event log.
9. `dashboard.py` — Streamlit human-review screen (§6.6).
10. `backtest.py` — the §8.5 harness: replay two NPPES snapshots (NBER mirror) and print a precision/recall + calibration report. *This is the credibility module — most submissions won't have one.*

**Stack:** Python 3.11 · requests/httpx · pandas · `usaddress`/libpostal · `phonenumbers` · `splink` · `scikit-learn` (calibration) · pydantic (schema) · SQLite + JSONL (audit) · Streamlit (dashboard). All free/OSS.

**Demo script:** run on `HL_001` → show (a) a confirmed no-change field, (b) an auto-update (phone, 2 sources agree), (c) a conflict → human_review (the address case from the brief), all emitting the specified JSON, all logged to the audit store, all surfaced in the dashboard. Then (d) a 60-second **backtest flex**: point `backtest.py` at two real consecutive NPPES snapshots and print measured auto-update precision + a calibration curve on actual historical provider moves/deactivations — proof, not assertion. One command, ~30 seconds for (a)–(c). That demo touches *every* evaluation criterion.

---

## 10. Output schema (matches the brief exactly)

Reuse the brief's structure verbatim so judges see instant compliance:
```json
{ "provider_id","npi","change_detected",
  "changes":[{"field","old_value","new_value","confidence_score","supporting_sources":[...]}],
  "overall_confidence","recommended_action":"no_change|auto_update|human_review","reason" }
```
The prototype's pydantic models enforce this; the proposal shows the auto-update, the conflict→human_review, and the no_change variants.

---

## 11. Implementation roadmap (bonus — also the 3-month consulting plan)

| Phase | Weeks | Deliverable |
|---|---|---|
| **0 — MVP (this submission)** | — | Runnable funnel on sample data; NPPES live; schema-compliant output; audit log; dashboard. |
| **1 — Structured backbone + backtest** | 1–4 | Bulk NPPES + CMS ingestion; full-directory monthly batch reconcile; normalization at scale; baseline scoring; **§8.5 backtest harness stood up on historical snapshots so every later change is measured against precision/recall from day one.** |
| **2 — Matching & triage** | 4–8 | Splink dedup/movement/inactive in production; risk-based triage queue; weekly incremental + deactivation diffs. |
| **3 — Residual enrichment** | 8–12 | Gated Tier-3 agent (practice site/state board) with budget caps & caching; human-review dashboard live; threshold tuning loop from reviewer labels. |
| **Ongoing** | — | Monitor precision (bad auto-updates), review volume, cost/1k; ratchet thresholds as trust accrues. |

KPIs to commit to — and **measured continuously via the §8.5 backtest, not asserted**: **auto-update precision ≥ 99%** (almost no wrong silent changes), **human-review rate ≤ 5%**, **cost ≤ $0.05/record**, **directory freshness within the 90-day window** (NSA today, REAL Act for MA from PY2028), plus a **published, calibrated accuracy score** that satisfies the REAL Act's new public-reporting mandate.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| NPPES address is self-reported & can lag reality | Treat NPPES as strong-but-not-sole for address; require corroboration for moves; Tier-3 confirms. |
| State-board scraping is brittle / 50 different sites | Build incrementally, highest-volume states first; degrade gracefully (board is a bonus corroborator, not a hard dependency). |
| LLM extraction hallucinates a value | LLM only *extracts* from fetched page text (never invents); extracted value must still clear the scoring + corroboration gate; store the source snapshot. |
| Over-aggressive auto-update damages trust | Conservative thresholds, min-field-confidence decision, high-risk classes always human-confirmed, full reversibility via audit log. |
| Conflicting sources | Built into the formula (conflict → mid score → human_review), not an afterthought. |

---

## 13. Submission deliverables checklist

- [ ] **Architecture proposal** (PDF/Markdown) — sections 3–8, **8.5**, 11–12 above, polished.
- [ ] **Agent workflow diagram** — clean rendered version of §5.
- [ ] **Working prototype** — repo per §9, one-command demo on `HL_001`.
- [ ] **Cost-per-1,000 table** (§7) + the "10–20× cheaper than naive" comparison.
- [ ] **Confidence formula** (§6.4) written out, incl. the source-independence classes.
- [ ] **Validation / backtest report** (§8.5) — measured precision/recall + a calibration curve on real historical snapshots. *The differentiator; lead with it.*
- [ ] **Human-review dashboard** — live Streamlit screenshot/GIF.
- [ ] **Coverage of all 8 MVP fields** (name, NPI, specialty, practice, address, phone, website, active/inactive).
- [ ] **Bonus sweep** — confirm all 14 bonus items are explicitly present.
- [ ] **One-page exec summary** opening the proposal (§0 thesis + cost story).
- [ ] **README** with run instructions + a 60–90s demo video/GIF.

---

## 14. Sources (verified during research)

- [NPPES NPI Registry API (CMS/HHS)](https://npiregistry.cms.hhs.gov/api-page) · [API help](https://npiregistry.cms.hhs.gov/registry/help-api) · [NPI bulk files](https://download.cms.gov/nppes/NPI_Files.html) · [CMS Data Dissemination](https://www.cms.gov/medicare/regulations-guidance/administrative-simplification/data-dissemination)
- [CMS Doctors & Clinicians — Provider Data Catalog](https://data.cms.gov/provider-data/topics/doctors-clinicians) · [National Downloadable File dataset mj5m-pzi6](https://data.cms.gov/provider-data/dataset/mj5m-pzi6) · [PDC API docs](https://data.cms.gov/provider-data/docs) · [DOC Data Dictionary](https://data.cms.gov/provider-data/sites/default/files/data_dictionaries/physician/DOC_Data_Dictionary.pdf) · [Doctors & Clinicians archived snapshots (backtest ground truth)](https://data.cms.gov/provider-data/archived-data/doctors-clinicians)
- Historical NPPES snapshots for backtesting (CMS keeps no history): [NBER NPI/NPPES monthly+weekly mirror 2017–2026](https://www.nber.org/research/data/national-plan-and-provider-enumeration-system-nppesnpi) (`https://data.nber.org/npi/YYYY/`) · note: NPPES bulk **V1 file format retired 2026-03-03, use V2**
- [libpostal (address normalization)](https://github.com/openvenues/libpostal) · [USPS Address APIs (allowed-use caveat)](https://www.usps.com/business/web-tools-apis/address-information-api.htm)
- [Splink — probabilistic record linkage](https://moj-analytical-services.github.io/splink/index.html) · [Splink GitHub](https://github.com/moj-analytical-services/splink) · [Deduplicating 7M records in 2 min](https://medium.com/data-science-collective/deduplicating-7-million-records-in-two-minutes-with-splink-4b1a87035a85)
- No Surprises Act directory rules (90-day verification, 2-business-day update): [AJMC — persistence of directory inaccuracies](https://www.ajmc.com/view/persistence-of-provider-directory-inaccuracies-after-the-no-surprises-act) · [Quest Analytics](https://questanalytics.com/news/no-surprises-act-protecting-patients-and-improving-provider-directory-accuracy/)
- **REAL Health Providers Act** (signed 2026-02-03 in the Consolidated Appropriations Act, 2026; PY2028 effective; 90-day verify, 5-day removal, mandatory annual accuracy analysis + public accuracy score): [S.3750 text, Congress.gov](https://www.congress.gov/bill/119th-congress/senate-bill/3750/text) · [Quest Analytics explainer](https://questanalytics.com/news/requiring-enhanced-accurate-lists-of-health-providers-act/) · [Kyruus Health — data accuracy implications](https://kyruushealth.com/real-health-providers-act-data-accuracy/)
- HealthLynked context: [Upgraded Provider Directory launch (2025)](https://www.globenewswire.com/news-release/2025/07/28/3122372/0/en/HealthLynked-Launches-New-Enterprise-Healthcare-Solutions-Website-and-Upgraded-Provider-Directory-to-Expand-Strategic-Value-Across-the-Healthcare-Market.html) · [Practice Directory (OTCQB:HLYK)](https://www.proactiveinvestors.com/companies/news/989016/healthlynked-makes-upgrades-to-its-cloud-based-platform-including-adding-a-practice-directory-989016.html)
