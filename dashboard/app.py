"""Human-review dashboard (SOLUTION_PLAN §6.6).

A lean Streamlit screen over the pipeline's review queue: one card per record that
needs a human, showing each proposed change side-by-side with its confidence,
supporting sources, and conflict flag. Every approve/reject click is appended to a
decisions log — those become the training labels that tune thresholds over time.

Run with:
    pip install -e ".[dashboard]"
    directory-pipeline demo          # populate audit_log.jsonl
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import html
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from directory_pipeline.audit import AuditLog
from directory_pipeline.models import AuditEvent

st.set_page_config(page_title="Directory Review Queue", page_icon="🩺", layout="wide")

DECISIONS_PATH = Path("review_decisions.jsonl")

# --------------------------------------------------------------------------- #
# Styling — a small, self-contained stylesheet so the screen reads as a real
# review console rather than a default Streamlit page (no external assets).
# --------------------------------------------------------------------------- #
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; max-width: 1180px; }
      .rev-card { border: 1px solid #e2e8f0; border-radius: 14px; padding: 18px 20px 6px;
                  margin-bottom: 6px; background: #ffffff;
                  box-shadow: 0 1px 3px rgba(15,23,42,.06); }
      .rev-head { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
      .rev-title { font-size: 1.18rem; font-weight: 700; color: #0f172a; }
      .rev-npi { color: #64748b; font-weight: 500; font-size: .95rem; }
      .rev-reason { color: #475569; font-size: .92rem; margin: 8px 0 14px; }
      .badge { font-size: .72rem; font-weight: 800; letter-spacing: .03em;
               padding: 3px 9px; border-radius: 999px; text-transform: uppercase; }
      .b-high { background: #fde8e8; color: #b42318; border: 1px solid #f4b9b3; }
      .b-medium { background: #fcf1e2; color: #b45309; border: 1px solid #f0cf9b; }
      .b-low { background: #e8f7ef; color: #15803d; border: 1px solid #a7e0c0; }
      .b-conflict { background: #fde8e8; color: #b42318; border: 1px solid #f4b9b3; }
      .frow { display: grid; grid-template-columns: 120px 1fr 168px; gap: 14px;
              align-items: center; padding: 10px 0; border-top: 1px solid #eef2f7; }
      .fname { font-weight: 700; color: #0f172a; text-transform: capitalize; }
      .fval-old { color: #94a3b8; text-decoration: line-through; }
      .fval-arrow { color: #94a3b8; margin: 0 8px; }
      .fval-new { color: #0f172a; font-weight: 700; }
      .pill { display: inline-block; font-size: .72rem; background: #eef2f7; color: #334155;
              border: 1px solid #dbe3ec; border-radius: 999px; padding: 2px 8px;
              margin: 2px 4px 0 0; }
      .pill-conflict { background: #fde8e8; color: #b42318; border-color: #f4b9b3; }
      .conf-wrap { }
      .conf-bar { height: 8px; border-radius: 6px; background: #eef2f7; overflow: hidden; }
      .conf-fill { height: 100%; border-radius: 6px; }
      .conf-num { font-size: .8rem; font-weight: 700; margin-bottom: 3px; }
      .metric-card { border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 16px;
                     background: #fff; }
      .metric-num { font-size: 1.7rem; font-weight: 800; color: #0f172a; line-height: 1; }
      .metric-lab { font-size: .8rem; color: #64748b; margin-top: 4px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def record_decision(provider_id: str, decision: str, fields: list[str], note: str = "") -> None:
    """Append a reviewer decision (a training label) to the decisions log."""
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DECISIONS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "provider_id": provider_id,
                    "decision": decision,
                    "fields": fields,
                    "note": note,
                    "reviewer": "demo-reviewer",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            + "\n"
        )


def decided_ids() -> set[str]:
    if not DECISIONS_PATH.exists():
        return set()
    out: set[str] = set()
    with DECISIONS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.add(json.loads(line)["provider_id"])
    return out


def group_queue(events: list[AuditEvent]) -> dict[str, list[AuditEvent]]:
    grouped: dict[str, list[AuditEvent]] = defaultdict(list)
    for event in events:
        grouped[event.provider_id].append(event)
    return grouped


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
        f'<div class="conf-wrap"><div class="conf-num" style="color:{color}">{conf:.2f}</div>'
        f'<div class="conf-bar"><div class="conf-fill" '
        f'style="width:{pct}%;background:{color}"></div></div></div>'
    )


def _field_row(event: AuditEvent) -> str:
    old = html.escape(str(event.old_value)) if event.old_value not in (None, "") else "—"
    new = html.escape(str(event.new_value)) if event.new_value not in (None, "") else "—"
    pills = "".join(f'<span class="pill">{html.escape(s.label)}</span>' for s in event.sources)
    if event.conflict:
        pills += '<span class="pill pill-conflict">⚠ conflict</span>'
    conf = event.field_confidence or 0.0
    return (
        '<div class="frow">'
        f'<div class="fname">{html.escape(event.field or "—")}</div>'
        f'<div><span class="fval-old">{old}</span>'
        f'<span class="fval-arrow">→</span><span class="fval-new">{new}</span>'
        f"<div>{pills}</div></div>"
        f"{_conf_cell(conf)}"
        "</div>"
    )


def _risk_badge(risk: str) -> str:
    cls = {"high": "b-high", "medium": "b-medium", "low": "b-low"}.get(risk, "b-low")
    return f'<span class="badge {cls}">{html.escape(risk)} risk</span>'


# --------------------------------------------------------------------------- #
st.title("🩺 Provider Directory — Human Review Queue")
st.caption(
    "Only the records the pipeline could not (or should not) auto-update reach this "
    "screen. Every approve / reject is logged as a label that tunes the scoring "
    "thresholds over time, so the system grows more autonomous as it earns trust."
)

audit_path = st.sidebar.text_input("Audit log path", value="audit_log.jsonl")
hide_decided = st.sidebar.checkbox("Hide already-reviewed", value=True)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Confidence legend**\n\n🟩 ≥ 0.85 strong  \n🟧 0.60–0.85 mid  \n🟥 < 0.60 weak / conflict"
)

audit = AuditLog(audit_path)
if not Path(audit_path).exists():
    st.warning(f"No audit log at `{audit_path}`. Run `directory-pipeline demo` first.")
    st.stop()

queue = group_queue(audit.review_queue())
done = decided_ids() if hide_decided else set()
pending = {pid: evs for pid, evs in queue.items() if pid not in done}

# Sort the most dangerous records to the top: high-risk and conflicts first.
_risk_rank = {"high": 0, "medium": 1, "low": 2}


def _sort_key(item: tuple[str, list[AuditEvent]]) -> tuple[int, int]:
    _, evs = item
    risk = min(
        (_risk_rank.get((e.risk_class.value if e.risk_class else "low"), 2) for e in evs), default=2
    )
    conflict = 0 if any(e.conflict for e in evs) else 1
    return (risk, conflict)


pending = dict(sorted(pending.items(), key=_sort_key))

m1, m2, m3 = st.columns(3)
for col, num, lab in (
    (m1, len(queue), "In review queue"),
    (m2, len(pending), "Pending your review"),
    (m3, len(done), "Reviewed this session"),
):
    col.markdown(
        f'<div class="metric-card"><div class="metric-num">{num}</div>'
        f'<div class="metric-lab">{lab}</div></div>',
        unsafe_allow_html=True,
    )

st.write("")

if not pending:
    st.success("Review queue is clear. ✅")
    st.stop()

for provider_id, events in pending.items():
    npi = next((e.npi for e in events if e.npi), None)
    risk = next((e.risk_class.value for e in events if e.risk_class), "low")
    has_conflict = any(e.conflict for e in events)
    rows = [e for e in events if e.field]

    head = (
        '<div class="rev-card"><div class="rev-head">'
        f'<span class="rev-title">{html.escape(provider_id)}</span>'
        + (f'<span class="rev-npi">NPI {html.escape(npi)}</span>' if npi else "")
        + _risk_badge(risk)
        + ('<span class="badge b-conflict">⚠ source conflict</span>' if has_conflict else "")
        + "</div>"
        + f'<div class="rev-reason">{html.escape(events[0].reason)}</div>'
    )
    body = (
        "".join(_field_row(e) for e in rows)
        if rows
        else (
            '<div class="rev-reason">No field-level changes — flagged for identity / '
            "data-quality review.</div>"
        )
    )
    st.markdown(head + body + "</div>", unsafe_allow_html=True)

    fields = [e.field for e in rows if e.field]
    note = st.text_input(
        "Reviewer note",
        key=f"note_{provider_id}",
        label_visibility="collapsed",
        placeholder="Reviewer note (optional)…",
    )
    b1, b2, b3, _ = st.columns([1, 1, 1, 4])
    if b1.button("✓ Approve", key=f"approve_{provider_id}", use_container_width=True):
        record_decision(provider_id, "approved", fields, note)
        st.rerun()
    if b2.button("✗ Reject", key=f"reject_{provider_id}", use_container_width=True):
        record_decision(provider_id, "rejected", fields, note)
        st.rerun()
    if b3.button("Snooze", key=f"snooze_{provider_id}", use_container_width=True):
        record_decision(provider_id, "snoozed", fields, note)
        st.rerun()
    st.write("")
