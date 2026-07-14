# Production Cost Model

The proposal's cost table ([§9](PROPOSAL.md#9-cost-model--per-1000-records)) quotes
**$32–$54 per 1,000 records**. It should have been labeled explicitly as a
**prototype-stage marginal processing estimate**: what one more batch of 1,000
records costs once the platform and vendor access are in place and the funnel hits
its design targets. It is not a full production total-cost-of-ownership estimate.

This document is the full model. It separates the three costs that must not be
mixed, replaces single-point guesses with explicit low/base/stress scenarios,
projects them at directory scale, prices the fixed and one-time work around them,
and shows the specific mechanisms that bring unit cost back toward the original
range — together with the pilot measurements required before any of this becomes a
firm quote.

**Headline planning ranges (variable cost only):**

|Scenario|Variable cost / 1,000 records|Per record|
|-|-:|-:|
|Low (highly optimized funnel)|~$36|$0.036|
|**Base planning case**|**~$128**|**$0.128**|
|Stress (high escalation + review)|~$676|$0.676|
|Cost-down target after validated AI-assisted review, grouping, attestation|~$38–$55|$0.038–$0.055|

Human labor dominates every scenario. In the base case, review is **83.2%** of
variable cost; review plus limited provider outreach is **98.8%**. Model tokens are
a rounding error; human handling time is the business.

---

## 1. Three costs that must not be mixed

1. **Variable processing cost** — search, page acquisition, model tokens, human
review, and outreach caused by processing another 1,000 records.
2. **Recurring total cost of ownership** — variable cost **plus** cloud minimums,
monitoring, source licenses, source maintenance, engineering, QA leadership,
security, and vendor management.
3. **One-time implementation** — turning the prototype into a production service:
integration with the system of record, real-data validation, source contracts,
security/UAT review.

The proposal's table was intended to approximate item 1. Sections 3–4 below
re-estimate item 1 with explicit assumptions; sections 6–7 cover items 2 and 3.

## 2. What $32–$54 covers — and what it excludes

The submitted table:

|Stage|Records / 1,000|Subtotal|
|-|-:|-:|
|NPPES + CMS bulk reconcile (amortized)|1,000|~$0.50|
|Targeted NPPES API + Census geocode|~300|$0|
|Web fetch + LLM extraction (residual)|~100|$1–3|
|Human review (true conflicts)|~30–50|$30–50|

Its two structural assumptions — 10% web escalation and 3–5% human review — are
**design targets, not measured rates**. And its review line prices a review at ~$1.
At the BLS March 2026 private-industry median of **$34.78/hour loaded**, $1 buys
1.7 minutes. A realistic 4-minute review with 15% QA overhead costs **$2.67**, which
alone moves the review line from $30–50 to **$80–133 per 1,000**.

The estimate also excludes: licensed search and the work behind the discovery
adapter; page fetching/rendering and evidence retention; state-board or
primary-source licensing; provider outreach when sources disagree; reviewer QA,
supervision, and rework; cloud, observability, and security operations; production
engineering; and remediation of incorrect automatic updates. Those are priced below.

One honesty note on the repo's own benchmark: the synthetic 5,000-record backtest
validates code paths and calibration plumbing, **not funnel economics** — its
scenario mix routes ~18% of records to review *by construction*. The 3–5%
production review rate is a target the pilot in §10 must measure; nothing in the
repository proves it yet.

## 3. Variable-cost model

For `N = 1,000` processed records:

```text
C_variable = C_structured
           + N · web_rate · searches_per_escalation · search_price
           + N · web_rate · pages_per_escalation    · fetch_price
           + N · web_rate · llm_cost_per_escalation
           + N · review_rate   · review_min/60   · loaded_rate · QA_factor
           + N · outreach_rate · outreach_min/60 · loaded_rate · QA_factor
```

The formula deliberately exposes every rate a pilot must measure.

**Scenario assumptions:**

|Assumption|Low|Base|Stress|
|-|-:|-:|-:|
|Website escalation rate|5%|10%|25%|
|Search requests / escalation|1.0|1.5|3.0|
|Candidate pages fetched / escalation|1.5|2.5|5.0|
|Human-review rate|2%|4%|8%|
|Review handle time (min)|2.5|4.0|7.0|
|Loaded reviewer rate|$34.78/h|$34.78/h|$46.60/h|
|Review QA factor|1.10|1.15|1.20|
|Provider-outreach rate|0.1%|0.5%|2.0%|
|Outreach handle time (min)|5|6|8|

Shared prices (public rates, accessed 2026-07-14; sources in §11): structured
reconciliation allowance $0.50/1,000; search $0.005/request (Brave); managed fetch
$0.00083/page (Firecrawl Standard, fully utilized); LLM extraction
$0.00036/escalation (Gemini 2.5 Flash-Lite Batch, ~6,000 in + 300 out tokens).
Vendor plan minimums and commercial source licenses are excluded here and appear in
§5–6.

**Results per 1,000 records:**

|Component|Low|Base|Stress|
|-|-:|-:|-:|
|Structured reconcile|$0.50|$0.50|$0.50|
|Licensed search|$0.25|$0.75|$3.75|
|Managed page fetch|$0.06|$0.21|$1.04|
|LLM extraction|$0.02|$0.04|$0.09|
|Human review + QA (loaded)|$31.88|$106.66|$521.92|
|Provider outreach (limited)|$3.19|$20.00|$149.12|
|**Variable total / 1,000**|**$35.90**|**$128.15**|**$676.42**|

The original $32–$54 is reachable — it is essentially the low scenario. It is not a
defensible *central* forecast until the funnel rates are measured on real data.

**Sensitivity:** swapping the LLM barely moves the total; review rate and handle
time move it almost one-for-one. Every cost control in §8 therefore targets
reviewer minutes, not tokens.

## 4. At directory scale

HealthLynked's 2026 SEC filing reports ~**880,000 provider profiles**. With a
structured pass every 90 days (four passes/year, 3.52M record-passes):

|Variable scenario|One 880k cycle|Four cycles / year|
|-|-:|-:|
|Original submission ($32–54/1,000)|$28,160–$47,520|$112,640–$190,080|
|Low|$31,592|$126,368|
|**Base**|**$112,773**|**$451,090**|
|Stress|$595,247|$2,380,990|

Capacity matters as much as dollars. At the base 4% review rate:

```text
880,000 × 4% = 35,200 reviews/cycle × 4 min ≈ 2,347 reviewer-hours/cycle
four cycles ≈ 9,387 hours/year ≈ 4.5 review FTEs before QA and leave coverage
```

A 2–3 person *implementation* team does not describe the *operating* team — unless
the review-deflection design in §8 is validated.

A precision on the proposal's "flat in volume" claim: the **structured backbone**
is near-fixed (one national bulk file serves any volume, so its per-record cost
falls with scale), but search, fetching, review, outreach, and audit volume grow
linearly. The cost *curve* is favorable; total cost is not flat.

## 5. Choosing the paid sources

The discovery adapter (`docs/SOURCE_IDENTIFICATION.md`) is deliberately
vendor-neutral. The vendor choice changes both authority and price. At base-case
volume (~29,300 website escalations per average month):

* **Lean web path** — Brave Search ≈ 44,000 requests/month ≈ **$220/mo**;
Firecrawl Standard covers the ~73,000 pages/month at **$83/mo**; batch LLM
extraction ≈ **$11/mo**. Direct vendor cost is small next to labor.
* **Google Places path** — requesting `websiteUri` triggers the Text Search
Enterprise SKU: ≈ **$1,505/mo** at the same volume on the public price list.
Better local-business coverage, ~7× the search bill.
* **Primary-source / provider-attested path** — FSMB's Physician Data Center is an
authoritative source for **MD, DO, and PA licensure and disciplinary status**; it
does not establish NPI deactivation and does not cover every provider profession.
NPPES remains the applicable source for NPI deactivation, while other professions
require their own boards or primary-source services. For current rosters and
contacts, provider-attested feeds (e.g. CAQH) can beat both NPPES and the web.
Institutional FSMB and attested-data access are **priced by quote** and must appear
in any budget as a **TBD license line — not $0**. A suitable national service may
be cheaper than building and maintaining state/profession-board connectors (§7).

This is the direct answer to "finding the right source": NPPES/CMS serve as
identity, taxonomy, NPI-status, and search-seed layers; profession-specific
primary sources establish licensure and disciplinary status; and the
*current-truth* sources for rosters and contact data (official practice sites and
provider attestation) each carry a real acquisition cost that this model now
prices or explicitly flags as quote-required.

## 6. Recurring fixed operations

Planning envelopes, to be replaced by actual chargeback and staffing rates:

|Recurring item|Planning range / year|
|-|-:|
|Cloud platform, staging, logs, backups, secrets ($500–$3,000/month)|$6,000–$36,000|
|Data/platform engineering (0.5 × $180k to 1.0 × $215k loaded FTE)|$90,000–$215,000|
|Source-quality / operations lead (0.25 × $100k to 0.5 × $120k loaded FTE)|$25,000–$60,000|
|Security, legal, procurement, vendor management (planning allowance)|$10,000–$50,000|
|Commercial data licenses (FSMB, attested feeds)|**TBD — quote required**|
|**Known fixed subtotal**|**$131,000–$361,000**|

Adding the base variable case gives a **core recurring subtotal** of roughly
**$582,000–$812,000/year** plus source licenses — about **$0.66–$0.92 per directory
profile per year**, or $0.17–$0.23 per 90-day record-pass. This subtotal excludes
the risk-adjusted remediation cost modeled separately in §9 because its error rate
and cost per incident must be measured on production data.

## 7. One-time implementation

|One-time work|Planning range|
|-|-:|
|Core productionization (2–3 people × 12 weeks; ~$195k–$260k implied loaded FTE-year)|$90,000–$180,000|
|Integration, security, UAT, rollback (400–1,000 hours × $100–$160/hour)|$40,000–$160,000|
|Real gold set + source-cost pilot (200–500 hours × $50–$80/hour)|$10,000–$40,000|
|State/profession-board connectors (illustrative 50 × 40–80 hours × $50–$160/hour)|$100,000–$640,000|
|Commercial-source procurement & integration|TBD|
|Evidence-bound AI review workflow (§8; 200–600 hours × $100–$160/hour), if built from the start|$20,000–$96,000 (overlaps)|

An initial release without the full state-by-state connector estate is plausibly
**$140,000–$380,000**. The 50-connector case is illustrative, not a complete
multi-profession national inventory. A national primary-source service should be
quoted against the connector line before any board scraper is built.

## 8. The road back to ~$0.04/record

Since human labor is **98.8%** of base variable cost (review **83.2%**, outreach
**15.6%**), the credible cost-down lever is a **human-on-exception** design — not
cheaper labor and not "let an LLM decide":

1. **Deterministic decisions first.** Exact agreement, unchanged values, duplicates,
freshness and policy exclusions need no model and no human.
2. **Evidence-bound AI reviewer with an abstain option.** It reads a sealed evidence
packet (normalized values, source classes, timestamps, content hashes, cited text
spans), returns strict JSON with cited evidence IDs, and **every citation is
validated in code** — a claimed phone or NPI must literally exist in the cited
snapshot. No browsing, no write access. A second, adversarial pass tries to
disprove identity, authority, and freshness. Model agreement counts as one
analysis, never as two sources: an LLM interprets evidence, it is not evidence.
3. **Risk-scoped automation.** Low-risk contact fields (phone, website, suite) can
be AI-cleared after validation; address/affiliation only with independent
corroboration or attestation; the pipeline's existing `NEVER_AUTO_UPDATE` rule
for provider name, NPI, and active status stands — those stay human/primary-source
confirmed. Conflicts, missing evidence, novel layouts, and suspected prompt
injection abstain to quarantine.
4. **Practice-level grouping.** One verified practice location (domain, address,
phone, roster) covers many providers; one confirmed practice move resolves all
linked records in a single review.
5. **Structured provider attestation.** A signed, expiring link lets an authorized
practice user confirm or correct locations, phones, and roster in one action —
creating *new first-party evidence* instead of asking a model to arbitrate stale
sources. (CAQH's historical DirectAssure material reports 80% response to one
outreach email; vendor-reported, but worth testing as a first-class strategy.)

**Cost effect** (AI cost itself: two passes over each of the base case's 40 review
cases, each with ~8,000 input and 1,000 output tokens at Gemini 2.5 Flash standard
pricing, costs ≈ **$0.39 per 1,000 records**):

|Design|Human-work assumption|Variable / 1,000|Annual @ 3.52M passes|
|-|-|-:|-:|
|Base model (§3)|4% review × 4 min, manual outreach|$128.15|$451,090|
|AI-prepared human review|same queue, handle time → 2.5 min|$88.55|$311,681|
|Human on exception|AI clears 70%; 1.2% reviewed × 4 min; $1.00 audit allowance|$54.88|$193,183|
|+ grouping + attestation (mature)|+ 50% less search/fetch/extraction, 80% less outreach; audit retained|$38.39|$135,119|

Both AI-clear rows include **$1.00 per 1,000** for random audits. At the base loaded
rate, auditing 1–2% of the 28 AI-cleared cases costs approximately
**$0.75–$1.49 per 1,000**; the $1.00 value is a planning midpoint, not a vendor
charge. The mature row also retains the two-pass AI-review cost.

Validated 70% deflection saves ≈ **$258,000/year** at directory scale versus the
base case; the mature design ≈ **$316,000/year**.

**Release gates.** The 70% deflection rate is an optimization target under
non-negotiable quality controls, not a promise: predeclared precision targets by
field and risk class, a statistically justified lower confidence bound on a
time-split real gold set (selective-prediction / conformal calibration of the
abstention threshold), hard negatives for identity collisions, a continuous 1–2%
random human audit of AI-cleared cases, automatic pause on source-layout drift or
citation-validation failures, and revalidation of every model/prompt/policy change.
AI review reduces the cost of *interpreting* evidence; it cannot manufacture
evidence that sources don't contain.

## 9. The cost of being wrong

A cost model without quality economics is incomplete. For automatic updates:

```text
expected remediation = records × auto_update_rate × (1 − precision) × cost_per_bad_update
```

At 5% auto-update on 880,000 records and 99% precision, **~440 bad updates per
cycle** still ship. At $25–$100 each to investigate, correct, and audit, that is
**$11,000–$44,000 per cycle** before any lost-booking or reputational impact. This
is why the model keeps conservative thresholds and full audit-log reversibility,
and why the synthetic benchmark's 96.8% precision is treated as a code test, not a
production claim. The inverse error costs too — a stale phone number is a failed
booking — so the business case should price a *prevented* bad listing, not only the
cost of review.

The core recurring subtotal in §6 excludes this risk-adjusted line. Under the
illustrative assumptions above, four cycles add **$44,000–$176,000/year**, raising
the base recurring planning range to approximately **$626,000–$988,000/year plus
source licenses**. Until production precision and incident cost are measured, this
range should be reported separately rather than hidden inside reviewer overhead.

## 10. Pilot before quote

Every scenario above is a planning case. Before a firm unit price, a stratified
pilot of ≥5,000 real records (claimed/unclaimed, urban/rural, individual/group,
active/inactive, stale/fresh) must measure: the structured-diff change rate;
website-escalation rate; searches and pages per successful discovery; browser-render
rate; deterministic-extraction vs LLM-fallback rate; verified/probable/ambiguous
domain rates; review rate and reasons; review handle-time p50/p90; AI-review
deflection and abstention rates with precision by queue reason;
attestation-response rate; auto-update precision by field; and vendor minimums.
Bootstrap confidence intervals on those rates, fed through the §3 formula, produce
the quotable range. Until then, the responsible answer is the range above plus the
TBD license quotes — not one precise number.

## 11. Rates and sources used

Public rates and figures cited above, accessed 2026-07-14:

* CMS NPPES data dissemination (free access, file sizes): [cms.gov](https://www.cms.gov/medicare/regulations-guidance/administrative-simplification/data-dissemination) · [NPI files](https://download.cms.gov/nppes/NPI_Files.html)
* CMS Provider Data Catalog API: [data.cms.gov](https://data.cms.gov/provider-data/about) — US Census batch geocoder: [census.gov](https://www.census.gov/programs-surveys/geography/technical-documentation/complete-technical-documentation/census-geocoder.html)
* Brave Search API pricing: [brave.com/search/api](https://brave.com/search/api/)
* Google Maps Platform / Places pricing and `websiteUri` SKU: [pricing](https://developers.google.com/maps/billing-and-pricing/pricing) · [text search](https://developers.google.com/maps/documentation/places/web-service/text-search)
* Firecrawl plans: [firecrawl.dev/pricing](https://www.firecrawl.dev/pricing) — Gemini API pricing: [ai.google.dev](https://ai.google.dev/gemini-api/docs/pricing)
* BLS May 2025 occupational wages: [bls.gov](https://www.bls.gov/news.release/ocwage.t01.htm) — BLS March 2026 employer compensation: [bls.gov](https://www.bls.gov/news.release/ecec.nr0.htm)
* FSMB Physician Data Center (institutional pricing): [fsmb.org/pdc](https://www.fsmb.org/pdc/) · [data integration](https://www.fsmb.org/data-integration/)
* CAQH DirectAssure fact sheet (vendor-reported outreach results): [caqh.org](https://www.caqh.org/hubfs/43908627/drupal/solutions/fact-sheet-directassure.pdf)
* Conformal Risk Control (selective-prediction calibration): [arXiv:2208.02814](https://arxiv.org/abs/2208.02814)
* HealthLynked 2026 SEC filing (~880,000 provider profiles): [sec.gov](https://www.sec.gov/Archives/edgar/data/1680139/000121390026050297/ea0286031-s1a1_health.htm)
* Note: Microsoft retired the Bing Search APIs in August 2025 ([announcement](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement)), so Bing is not used as a pricing example here.
