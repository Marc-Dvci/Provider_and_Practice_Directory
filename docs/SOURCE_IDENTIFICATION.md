# Source Identification: Finding the Practice Website

This submission now treats the practice website as a discovered source, not an
assumed input.

Given only a provider name, NPI, and current or old address, the pipeline builds a
search packet:

- provider name and normalized variants
- NPI
- practice name from the internal record, CMS Doctors & Clinicians, or Type-2 NPPES
- old/current address and phone
- specialty and city/state hints

That packet is passed through `WebsiteCandidateProvider`, a small adapter seam for
licensed search providers such as a Google Places proxy, Bing Web Search proxy, or
another approved vendor. The production adapter returns candidate URLs and observed
page facts in a stable schema:

```json
{
  "candidates": [
    {
      "url": "https://practice.example.com",
      "source": "licensed_search_provider",
      "fields": {
        "practice_name": "ABC Heart Group",
        "provider_names": ["John Smith, MD"],
        "npi": "1234567890",
        "address": "250 Health Park Dr, Fort Myers, FL 33908",
        "phone": "239-555-9000",
        "page_text": "ABC Heart Group locations..."
      }
    }
  ]
}
```

The deterministic scorer then verifies the candidate before it can influence any
directory update:

- provider appears on the website roster
- practice name matches the internal/CMS/NPPES practice clue
- phone or address matches a known value
- NPI appears on the page when available
- page text contains provider/practice evidence
- aggregator and directory domains are penalized

Only `verified_official_site` or `probable_site` candidates are converted into
`practice_web` evidence. Ambiguous candidates are not trusted; they can be routed
to human review with the evidence breakdown.

This keeps NPPES in the right role: an identity/search seed, not the final source
of truth for current phone, address, or roster data.

## Local Demo

The offline demo uses `data/fixtures/web_discovery/*.json` instead of a paid API.
It exercises the same verification logic:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m directory_pipeline.cli discover-site --offline --record HL_001 --json
.\.venv\Scripts\python.exe -m pytest tests\test_sources.py -q
```

The production connection is configured through:

```text
DIRPIPE_WEBSITE_SEARCH_BASE_URL=https://internal-search-proxy.example.com/provider-sites
DIRPIPE_WEBSITE_SEARCH_API_KEY=...
DIRPIPE_WEBSITE_SEARCH_TOP_K=8
```

The proxy contract deliberately hides provider-specific details from the core
pipeline. A Google Places, Bing, or vendor-specific connector only has to return
candidate dictionaries in the schema above; the scoring, audit trail, and safe
update rules stay unchanged.
