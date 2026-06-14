#!/usr/bin/env python
"""Render a screenshot of the human-review dashboard for the proposal/README.

The live screen is the Streamlit app in ``dashboard/app.py``; this script renders
the *same* design (identical CSS) populated with the *same* real data from
``audit_log.jsonl`` to a standalone HTML page, then screenshots it with headless
Chrome. That keeps the artifact reproducible and faithful without depending on a
running Streamlit server / browser-driver timing.

Run:
    directory-pipeline demo            # populate audit_log.jsonl
    python docs/make_dashboard_shot.py # -> docs/dashboard.png
"""

from __future__ import annotations

import html
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

DOCS = Path(__file__).resolve().parent
REPO = DOCS.parent
sys.path.insert(0, str(REPO / "src"))

from directory_pipeline.audit import AuditLog  # noqa: E402
from directory_pipeline.models import AuditEvent  # noqa: E402

CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; background: #f4f6fa; font-family: "Segoe UI", Helvetica, Arial, sans-serif;
         color: #0f172a; }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 30px 28px 36px; }
  .app-title { font-size: 1.9rem; font-weight: 800; margin: 0 0 6px; }
  .app-cap { color: #475569; font-size: .95rem; max-width: 860px; margin: 0 0 20px;
             line-height: 1.5; }
  .metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 22px; }
  .metric-card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 14px 18px;
                 background:#fff; box-shadow: 0 1px 3px rgba(15,23,42,.05); }
  .metric-num { font-size: 1.9rem; font-weight: 800; line-height: 1; }
  .metric-lab { font-size: .82rem; color: #64748b; margin-top: 6px; }
  .rev-card { border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px 22px 16px;
              margin-bottom: 16px; background: #fff; box-shadow: 0 1px 3px rgba(15,23,42,.06); }
  .rev-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
  .rev-title { font-size: 1.18rem; font-weight: 700; }
  .rev-npi { color: #64748b; font-weight: 500; font-size: .95rem; }
  .rev-reason { color: #475569; font-size: .92rem; margin: 10px 0 4px; line-height: 1.45; }
  .badge { font-size: .72rem; font-weight: 800; letter-spacing: .03em; padding: 3px 9px;
           border-radius: 999px; text-transform: uppercase; }
  .b-high { background:#fde8e8; color:#b42318; border:1px solid #f4b9b3; }
  .b-medium { background:#fcf1e2; color:#b45309; border:1px solid #f0cf9b; }
  .b-low { background:#e8f7ef; color:#15803d; border:1px solid #a7e0c0; }
  .b-conflict { background:#fde8e8; color:#b42318; border:1px solid #f4b9b3; }
  .frow { display:grid; grid-template-columns:120px 1fr 170px; gap:16px; align-items:center;
          padding:11px 0; border-top:1px solid #eef2f7; }
  .fname { font-weight:700; text-transform:capitalize; }
  .fval-old { color:#94a3b8; text-decoration:line-through; }
  .fval-arrow { color:#94a3b8; margin:0 8px; }
  .fval-new { font-weight:700; }
  .pill { display:inline-block; font-size:.72rem; background:#eef2f7; color:#334155;
          border:1px solid #dbe3ec; border-radius:999px; padding:2px 8px; margin:4px 4px 0 0; }
  .pill-conflict { background:#fde8e8; color:#b42318; border-color:#f4b9b3; }
  .conf-num { font-size:.82rem; font-weight:700; margin-bottom:4px; }
  .conf-bar { height:8px; border-radius:6px; background:#eef2f7; overflow:hidden; }
  .conf-fill { height:100%; border-radius:6px; }
  .actions { display:flex; gap:10px; margin-top:14px; }
  .btn { font-size:.85rem; font-weight:600; padding:7px 16px; border-radius:8px; border:1px solid;
         background:#fff; }
  .btn-approve { color:#15803d; border-color:#a7e0c0; }
  .btn-reject { color:#b42318; border-color:#f4b9b3; }
  .btn-snooze { color:#475569; border-color:#cbd5e1; }
"""

_RISK_RANK = {"high": 0, "medium": 1, "low": 2}


def _conf_color(conf: float) -> str:
    if conf >= 0.85:
        return "#1f9d63"
    if conf >= 0.60:
        return "#d98324"
    return "#b42318"


def _conf_cell(conf: float) -> str:
    pct = max(0, min(100, round(conf * 100)))
    color = _conf_color(conf)
    return (
        f'<div><div class="conf-num" style="color:{color}">{conf:.2f}</div>'
        f'<div class="conf-bar"><div class="conf-fill" style="width:{pct}%;background:{color}">'
        "</div></div></div>"
    )


def _field_row(e: AuditEvent) -> str:
    old = html.escape(str(e.old_value)) if e.old_value not in (None, "") else "—"
    new = html.escape(str(e.new_value)) if e.new_value not in (None, "") else "—"
    pills = "".join(f'<span class="pill">{html.escape(s.label)}</span>' for s in e.sources)
    if e.conflict:
        pills += '<span class="pill pill-conflict">⚠ conflict</span>'
    return (
        '<div class="frow">'
        f'<div class="fname">{html.escape(e.field or "—")}</div>'
        f'<div><span class="fval-old">{old}</span><span class="fval-arrow">→</span>'
        f'<span class="fval-new">{new}</span><div>{pills}</div></div>'
        f"{_conf_cell(e.field_confidence or 0.0)}</div>"
    )


def _risk_badge(risk: str) -> str:
    cls = {"high": "b-high", "medium": "b-medium", "low": "b-low"}.get(risk, "b-low")
    return f'<span class="badge {cls}">{html.escape(risk)} risk</span>'


def build_html(audit_path: Path) -> str:
    audit = AuditLog(audit_path)
    grouped: dict[str, list[AuditEvent]] = defaultdict(list)
    for ev in audit.review_queue():
        grouped[ev.provider_id].append(ev)

    def sort_key(item: tuple[str, list[AuditEvent]]) -> tuple[int, int]:
        _, evs = item
        risk = min(
            (_RISK_RANK.get(e.risk_class.value if e.risk_class else "low", 2) for e in evs),
            default=2,
        )
        return (risk, 0 if any(e.conflict for e in evs) else 1)

    ordered = sorted(grouped.items(), key=sort_key)

    cards: list[str] = []
    for pid, events in ordered:
        npi = next((e.npi for e in events if e.npi), None)
        risk = next((e.risk_class.value for e in events if e.risk_class), "low")
        conflict = any(e.conflict for e in events)
        rows = [e for e in events if e.field]
        head = (
            '<div class="rev-card"><div class="rev-head">'
            f'<span class="rev-title">{html.escape(pid)}</span>'
            + (f'<span class="rev-npi">NPI {html.escape(npi)}</span>' if npi else "")
            + _risk_badge(risk)
            + ('<span class="badge b-conflict">⚠ source conflict</span>' if conflict else "")
            + "</div>"
            + f'<div class="rev-reason">{html.escape(events[0].reason)}</div>'
        )
        body = "".join(_field_row(e) for e in rows) or (
            '<div class="rev-reason">No field-level changes — flagged for identity / '
            "data-quality review.</div>"
        )
        actions = (
            '<div class="actions"><span class="btn btn-approve">✓ Approve</span>'
            '<span class="btn btn-reject">✗ Reject</span>'
            '<span class="btn btn-snooze">Snooze</span></div>'
        )
        cards.append(head + body + actions + "</div>")

    total = len(ordered)
    metrics = (
        '<div class="metrics">'
        f'<div class="metric-card"><div class="metric-num">{total}</div>'
        '<div class="metric-lab">In review queue</div></div>'
        f'<div class="metric-card"><div class="metric-num">{total}</div>'
        '<div class="metric-lab">Pending your review</div></div>'
        '<div class="metric-card"><div class="metric-num">0</div>'
        '<div class="metric-lab">Reviewed this session</div></div></div>'
    )
    return (
        f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
        '<div class="wrap">'
        '<div class="app-title">🩺 Provider Directory — Human Review Queue</div>'
        '<div class="app-cap">Only the records the pipeline could not (or should not) '
        "auto-update reach this screen. Every approve / reject is logged as a label that tunes "
        "the scoring thresholds over time, so the system grows more autonomous as it earns "
        "trust.</div>"
        f"{metrics}{''.join(cards)}</div></body></html>"
    )


def _find_chrome() -> str | None:
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if c and Path(c).exists():
            return c
    return None


def main() -> int:
    audit_path = REPO / "audit_log.jsonl"
    if not audit_path.exists():
        print("No audit_log.jsonl — run `directory-pipeline demo` first.")
        return 1
    html_doc = build_html(audit_path)
    html_path = DOCS / "_dashboard.html"
    html_path.write_text(html_doc, encoding="utf-8")

    chrome = _find_chrome()
    if not chrome:
        print(f"Chrome/Edge not found; wrote {html_path} — screenshot it manually.")
        return 0
    png = DOCS / "dashboard.png"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--user-data-dir={DOCS / '_chrome'}",
            "--window-size=1180,1118",
            f"--screenshot={png}",
            html_path.as_uri(),
        ],
        check=False,
    )
    html_path.unlink(missing_ok=True)
    shutil.rmtree(DOCS / "_chrome", ignore_errors=True)
    if png.exists():
        print(f"wrote {png} ({png.stat().st_size / 1e3:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
