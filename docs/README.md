# Submission artifacts

| File | What it is |
|---|---|
| [`Proposal.pdf`](Proposal.pdf) | The polished proposal (Option C) for judges. |
| [`PROPOSAL.md`](PROPOSAL.md) | Markdown source of the proposal. |
| [`architecture.svg`](architecture.svg) / [`architecture.png`](architecture.png) | Agent-workflow diagram. |
| [`dashboard.png`](dashboard.png) | Human-review dashboard screen (used in the PDF). |
| [`demo.gif`](demo.gif) | Animated terminal recording of `directory-pipeline demo`. |
| [`demo_screenshot.png`](demo_screenshot.png) | Static capture of the same run (used in the PDF). |

These are reproducible — regenerate them from the repo with:

```bash
pip install -e ".[docs,dashboard]"   # pillow + markdown (+ streamlit for the live screen)
directory-pipeline demo              # writes audit_log.jsonl (feeds the dashboard shot)
python docs/make_diagram.py          # architecture.svg + architecture.png
python docs/make_dashboard_shot.py   # dashboard.png  (renders the review screen from the audit log)
python docs/make_demo_gif.py         # demo.gif + demo_screenshot.png
python docs/make_pdf.py              # Proposal.pdf
```

The diagram, dashboard shot, and PDF are produced with headless Chrome/Edge (already
present on most machines); the scripts find it automatically or fall back to writing the
HTML/SVG for manual export. `dashboard.png` renders the *same* design as the live
Streamlit screen (`dashboard/app.py`) populated with the real audit-log data, so it stays
reproducible without depending on a running server. No paid tools are used.
