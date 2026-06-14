<!--
  KAGGLE WRITEUP — copy/paste guide
  =================================
  • TITLE    -> Provider & Practice Directory Update Pipeline
  • SUBTITLE -> Deterministic-first, LLM-last: fixing a healthcare directory at ~$0/record — and measuring its own accuracy
  • COVER    -> upload docs/cover.png in the Kaggle cover-image slot

  IMAGES: the inline images below load from the repo's raw GitHub URLs, which only
  resolve once the repo is PUBLIC. Two options:
    (a) Make the repo public (recommended — judges need to see the code anyway), then
        the URLs render as-is; or
    (b) Keep it private and UPLOAD these files from docs/ directly into the Kaggle editor:
        cover.png, architecture.png, dashboard.png (and demo.gif if wanted), replacing
        each image URL with the uploaded one.

  The body below is ready to paste into Kaggle's writeup editor. Solo entry, "I" voice.
-->

![Provider & Practice Directory Update Pipeline](https://raw.githubusercontent.com/Marc-Dvci/Provider_and_Practice_Directory/main/docs/cover.png)

## The problem, and the one idea that solves it

Healthcare provider data decays constantly — clinicians move, practices merge or rebrand, phones and suites change, providers retire. Maintaining a directory by hand is expensive and doesn't scale, and the tempting shortcut — *"web-search + an LLM on every record"* — is both costly and inaccurate.

**My thesis:** most provider and practice updates already sit in **free, authoritative U.S. government datasets** (NPPES + CMS). So the optimal design is a **deterministic-first funnel** that resolves the bulk of records at ≈$0 marginal cost and reserves web scraping, LLMs, and human reviewers for the small residual where structured sources are silent or in conflict.

That single architectural choice is what keeps the cost curve flat as volume grows: **the expensive tiers only ever see the records the free tiers couldn't resolve.**

![Architecture](https://raw.githubusercontent.com/Marc-Dvci/Provider_and_Practice_Directory/main/docs/architecture.png)

## What makes this more than a proposal

1. **It runs.** One command reconciles the brief's exact `HL_001` example, emits the brief's exact JSON schema, and exercises every evaluation criterion end-to-end — fully offline, no API keys.
2. **Accuracy is measured, not claimed.** Because the government sources are versioned monthly, I replay a past snapshot against a later one and score the pipeline's proposed changes against what *actually* changed — labels for free, at national scale. A representative 5,000-record backtest: **≈98% recall, ≈97% auto-update precision, 100% routing accuracy, Brier ≈ 0.05.**
3. **Independence-aware confidence.** NPPES and CMS are **not** independent — both are ultimately self-reported by the provider to CMS — so corroboration has to span **≥2 distinct independence classes**, not just "two sources agree." Most naive scorers miss this and over-trust correlated feeds.
4. **The timing is now law.** The **REAL Health Providers Act** (signed 2026-02-03) will require Medicare Advantage plans to verify every directory field every 90 days and **publicly report an accuracy score** from PY2028. A pipeline that emits a defensible, auditable accuracy score is the compliance product payers will be *required* to buy.

## How a record flows

```
resolve identity  →  harvest free sources  →  normalize  →  match  →  score & decide  →  audit
  NPI Luhn +         NPPES + CMS (+ gated     address+geo   dedup +    source-weighted   append-only,
  cold-start search  web/board on residual)   phone, NUCC   geocoded   + safe-update     content-hashed
```

For a field `f` with candidate value `v` asserted by sources `S`:

```
field_conf(f, v) = R(v) · A(v)
    A(v) = Σ_{s:val=v} w(s,f)·φ(s) / Σ_{s∈S} w(s,f)·φ(s)     # agreement share — conflict drags it to the middle
    R(v) = 1 − Π_{s:val=v} (1 − w(s,f)·φ(s))                  # noisy-OR — independent confirmations add strength
```

Field **risk classes** then set the bar: low-risk fields (phone, suite) auto-update at high confidence; medium-risk (address move, specialty) need ≥2 independent classes; **high-risk fields (name, NPI, active status) are never updated silently.** An NPI that maps to a different entity becomes a repair ticket, never a silent write — and a credible *inactive/closure* signal is never quietly left stale.

The pipeline also emits lifecycle signals — **provider movement, practice relocation, closure, rebrand, NPI repair** — and detects duplicates via blocking + geocoded practice-location proximity.

## Only the residual reaches a human

The records the pipeline can't (or shouldn't) auto-update land in a review queue, **highest-risk and conflicting first** — each field shown side-by-side with its calibrated confidence, supporting sources, and conflict flag. Every approve/reject is logged as a **training label** that tunes the thresholds over time, so the system grows more autonomous as it earns trust.

![Human-review dashboard](https://raw.githubusercontent.com/Marc-Dvci/Provider_and_Practice_Directory/main/docs/dashboard.png)

## Cost & scale

| Stage (per 1,000 records) | Touched | Subtotal |
|---|---|---|
| Tier 0/1 batch reconcile (NPPES + CMS bulk) | 1,000 | ~$0.50 |
| NPPES API + Census geocode (free) | ~300 | $0 |
| Tier 3 web fetch + LLM extraction (residual) | ~100 | $1–3 |
| Human review (true conflicts only) | ~30–50 | $30–50 |
| **Total** | | **≈ $0.03–0.05 / record** |

Cost is **dominated by human review** — which the whole architecture exists to minimize — and is **flat in volume** because the hot path is free bulk data. The national NPPES file (~8–9M NPIs, ~1 GB) reconciles embarrassingly parallel by state/ZIP; matching blocks so it never goes quadratic and swaps to **Splink** for 100M+. A naive "LLM-every-record + paid address API" approach lands 10–20× higher and is less accurate.

## Try it (≈30 seconds, offline)

```bash
pip install -e ".[dev,calibration]"
directory-pipeline demo                    # end-to-end showcase on the sample directory
directory-pipeline backtest --scale 5000   # the measured accuracy + calibration curve
streamlit run dashboard/app.py             # the human-review dashboard
```

**Code (MIT, 50 tests, CI, ruff/mypy clean) + the full architecture proposal PDF:**
👉 **[github.com/Marc-Dvci/Provider_and_Practice_Directory](https://github.com/Marc-Dvci/Provider_and_Practice_Directory)**

This is a **hybrid submission** — a runnable prototype *and* a production architecture proposal — built so a lean team can ship it: free OSS, free government data, no exotic infrastructure, and an accuracy number you can hold the system to.
