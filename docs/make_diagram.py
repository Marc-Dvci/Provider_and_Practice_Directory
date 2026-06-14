#!/usr/bin/env python
"""Generate the agent-workflow architecture diagram (SVG, and PNG via headless Chrome).

Run:  python docs/make_diagram.py
Produces docs/architecture.svg and, when Chrome/Edge is present, docs/architecture.png.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1240, 1180
CX = 560  # centre of the main column (right margin reserved for the LLM box + feedback rail)

# palette
GREEN = "#1f9d63"  # free / deterministic
GREEN_BG = "#e8f7ef"
AMBER = "#d98324"  # gated LLM / scrape (the only $$ tier)
AMBER_BG = "#fcf1e2"
BLUE = "#2563a8"  # storage / UI / system of record
BLUE_BG = "#e7f0fb"
SLATE = "#475569"
SLATE_BG = "#eef1f5"
INK = "#0f172a"

parts: list[str] = []


def box(x, y, w, h, title, subtitle=None, stroke=GREEN, fill=GREEN_BG, badge=None, rx=12):
    parts.append(
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2" filter="url(#sh)"/>'
    )
    ty = y + (h / 2 if not subtitle else h / 2 - 9)
    parts.append(
        f'<text x="{x + w / 2}" y="{ty}" text-anchor="middle" '
        f'font-size="17" font-weight="700" fill="{INK}" dominant-baseline="middle">'
        f"{escape(title)}</text>"
    )
    if subtitle:
        parts.append(
            f'<text x="{x + w / 2}" y="{y + h / 2 + 14}" text-anchor="middle" '
            f'font-size="12.5" fill="{SLATE}" dominant-baseline="middle">{escape(subtitle)}</text>'
        )
    if badge:
        parts.append(
            f'<circle cx="{x + 24}" cy="{y + 22}" r="13" fill="{stroke}"/>'
            f'<text x="{x + 24}" y="{y + 22}" text-anchor="middle" dominant-baseline="central" '
            f'font-size="14" font-weight="700" fill="white">{badge}</text>'
        )


def arrow(x1, y1, x2, y2, label=None, color=SLATE, dash=False):
    da = ' stroke-dasharray="5 4"' if dash else ""
    parts.append(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
        f'stroke-width="2"{da} marker-end="url(#arrow)"/>'
    )
    if label:
        parts.append(
            f'<text x="{(x1 + x2) / 2 + 9}" y="{(y1 + y2) / 2}" font-size="11.5" '
            f'fill="{SLATE}" dominant-baseline="middle">{escape(label)}</text>'
        )


def line(x1, y1, x2, y2, color=SLATE, width=2):
    parts.append(
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}"/>'
    )


bw, bx = 720, CX - 360  # main column geometry  (bx=200, bx+bw=920)

# --- system of record ------------------------------------------------------- #
box(
    bx,
    70,
    bw,
    52,
    "HealthLynked Provider / Practice Directory",
    "system of record",
    stroke=BLUE,
    fill=BLUE_BG,
    rx=10,
)
arrow(CX, 122, CX, 150, "snapshot")

# --- 1 triage --------------------------------------------------------------- #
box(
    bx,
    150,
    bw,
    64,
    "Triage / Risk Agent",
    "staleness vs 90-day cadence · field volatility · hard signals  →  verify queue",
    badge="1",
)
arrow(CX, 214, CX, 242, "prioritized records")

# --- 2 harvest (+ 6 LLM extraction to the right) ---------------------------- #
box(bx, 242, bw, 92, "", None, badge="2")
parts.append(
    f'<text x="{CX}" y="270" text-anchor="middle" font-size="17" font-weight="700" '
    f'fill="{INK}">Source Harvest</text>'
)
parts.append(
    f'<text x="{CX}" y="296" text-anchor="middle" font-size="12.5" fill="{GREEN}" '
    f'font-weight="700">Tier 0/1 (free, always): NPPES · CMS Doctors '
    f"&amp; Clinicians · PECOS</text>"
)
parts.append(
    f'<text x="{CX}" y="316" text-anchor="middle" font-size="12.5" fill="{AMBER}" '
    f'font-weight="700">Tier 3 (gated, residual only): practice website · state board</text>'
)
lx, lw = 944, 158
parts.append(
    f'<rect x="{lx}" y="256" width="{lw}" height="74" rx="12" fill="{AMBER_BG}" '
    f'stroke="{AMBER}" stroke-width="2" filter="url(#sh)"/>'
)
parts.append(  # badge centred on the top border, clear of the title
    f'<circle cx="{lx + lw / 2}" cy="256" r="13" fill="{AMBER}"/>'
    f'<text x="{lx + lw / 2}" y="256" text-anchor="middle" dominant-baseline="central" '
    f'font-size="14" font-weight="700" fill="white">6</text>'
)
parts.append(
    f'<text x="{lx + lw / 2}" y="288" text-anchor="middle" font-size="16" font-weight="700" '
    f'fill="{INK}">LLM Extraction</text>'
)
parts.append(
    f'<text x="{lx + lw / 2}" y="308" text-anchor="middle" font-size="12.5" fill="{SLATE}">'
    f"extracts text; never invents</text>"
)
# double-headed link between harvest and the gated extractor
parts.append(
    f'<line x1="{lx}" y1="293" x2="{bx + bw}" y2="293" stroke="{AMBER}" stroke-width="2" '
    f'marker-start="url(#arrowA)" marker-end="url(#arrowA)"/>'
)
arrow(CX, 334, CX, 362, "candidate values + provenance")

# --- 3 normalise ------------------------------------------------------------ #
box(
    bx,
    362,
    bw,
    64,
    "Normalization Engine",
    "address + Census geocode · phone E.164 · NUCC taxonomy · structured name",
    badge="3",
)
arrow(CX, 426, CX, 454, "normalized values")

# --- 4 matching ------------------------------------------------------------- #
box(
    bx,
    454,
    bw,
    64,
    "Matching / Entity Resolution",
    "dedup · provider movement · practice relocation · geocoded location match",
    badge="4",
)
arrow(CX, 518, CX, 546, "linked entities + value sets")

# --- 5 decision ------------------------------------------------------------- #
box(
    bx,
    546,
    bw,
    66,
    "Confidence & Decision Engine",
    "source-weighted score · independence-class corroboration · safe-update rules",
    badge="5",
)

# --- decision fan-out (clean: drop to a distributor bus, then parallel arrows) #
labels = [
    ("NO CHANGE", "confirmed", BLUE, BLUE_BG),
    ("AUTO-UPDATE", "high conf + safe", GREEN, GREEN_BG),
    ("HUMAN REVIEW", "conflict / mid conf", AMBER, AMBER_BG),
    ("DISCARD / HOLD", "too weak", SLATE, SLATE_BG),
]
dw, gap = 236, 16
total = 4 * dw + 3 * gap
sx = CX - total // 2
centres = [sx + i * (dw + gap) + dw / 2 for i in range(4)]
bus_y = 642
out_y = 672
line(CX, 612, CX, bus_y)  # decision -> distributor bus
line(centres[0], bus_y, centres[-1], bus_y)  # the distributor bus
for cxi in centres:
    arrow(cxi, bus_y, cxi, out_y)  # parallel branches, no crossings
for (t, s, st, fl), cxi in zip(labels, centres, strict=True):
    box(cxi - dw / 2, out_y, dw, 60, t, s, stroke=st, fill=fl, rx=10)

# --- converge to audit (clean: collector bus, single arrow in) -------------- #
coll_y = 758
for cxi in centres:
    line(cxi, out_y + 60, cxi, coll_y)
line(centres[0], coll_y, centres[-1], coll_y)
arrow(CX, coll_y, CX, 786)

# --- 7 audit ---------------------------------------------------------------- #
box(
    bx,
    786,
    bw,
    64,
    "Audit / Provenance Store   (append-only, content-hashed)",
    "old → new · sources + snapshots · score math · decision · actor · timestamp",
    stroke=BLUE,
    fill=BLUE_BG,
    badge="7",
)
# write-back loop up the left rail to the directory
parts.append(
    f'<path d="M {bx} 818 H 96 V 96 H {bx}" fill="none" stroke="{BLUE}" '
    f'stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrow)"/>'
)
parts.append(
    f'<text x="86" y="460" font-size="12" fill="{BLUE}" font-weight="700" '
    f'transform="rotate(-90 86 460)" text-anchor="middle">write back approved updates</text>'
)
arrow(CX, 850, CX, 878)

# --- 8 dashboard ------------------------------------------------------------ #
box(
    bx,
    878,
    bw,
    64,
    "Human-Review Dashboard",
    "reviews the residual; every approve / reject is logged as a training label",
    stroke=BLUE,
    fill=BLUE_BG,
    badge="8",
)
# feedback loop up the right rail to the decision engine
parts.append(
    f'<path d="M {bx + bw} 910 H {W - 54} V 579 H {bx + bw}" fill="none" stroke="{AMBER}" '
    f'stroke-width="2" stroke-dasharray="5 4" marker-end="url(#arrow)"/>'
)
parts.append(
    f'<text x="{W - 42}" y="745" font-size="12" fill="{AMBER}" font-weight="700" '
    f'transform="rotate(-90 {W - 42} 745)" text-anchor="middle">labels tune thresholds</text>'
)

# --- cost / authority gradient rail (the thesis, visualised) ---------------- #
rail_x, rail_top, rail_bot = 44, 156, 606
parts.append(
    f'<rect x="{rail_x}" y="{rail_top}" width="10" height="{rail_bot - rail_top}" rx="5" '
    f'fill="url(#grad)"/>'
)
parts.append(
    f'<text x="{rail_x + 26}" y="{(rail_top + rail_bot) / 2}" font-size="12.5" '
    f'fill="{SLATE}" font-weight="700" transform="rotate(-90 {rail_x + 26} '
    f'{(rail_top + rail_bot) / 2})" text-anchor="middle">'
    f"cost / authority gradient — route each record only as far as it needs to go</text>"
)

# --- legend ----------------------------------------------------------------- #
ly = 1000
parts.append(f'<text x="{bx}" y="{ly}" font-size="13" font-weight="700" fill="{INK}">Legend</text>')
legend = [
    (GREEN, GREEN_BG, "free / deterministic  (≈ $0 per record — Tiers 0–2)"),
    (AMBER, AMBER_BG, "gated LLM / scrape — the only paid tier, residual only (Tier 3)"),
    (BLUE, BLUE_BG, "storage / UI / system of record"),
]
for i, (st, fl, txt) in enumerate(legend):
    yy = ly + 20 + i * 26
    parts.append(
        f'<rect x="{bx}" y="{yy - 12}" width="22" height="16" rx="4" fill="{fl}" '
        f'stroke="{st}" stroke-width="2"/>'
    )
    parts.append(f'<text x="{bx + 32}" y="{yy}" font-size="13" fill="{SLATE}">{escape(txt)}</text>')

parts.append(
    f'<text x="{bx + bw}" y="{ly}" text-anchor="end" font-size="12" fill="{SLATE}">'
    f"Agentic: 1 (triage) · 2 (gated harvest) · 6 (LLM extraction).  "
    f"3 / 4 / 5 / 7 / 8 are deterministic, testable code.</text>"
)

title = (
    f'<text x="{CX}" y="42" text-anchor="middle" font-size="22" font-weight="800" '
    f'fill="{INK}">Provider &amp; Practice Directory Update Pipeline — Agent Workflow</text>'
)

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"
     font-family="'Segoe UI', Helvetica, Arial, sans-serif">
  <defs>
    <marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"
            markerUnits="strokeWidth">
      <path d="M0,0 L8,3 L0,6 Z" fill="{SLATE}"/>
    </marker>
    <marker id="arrowA" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"
            markerUnits="strokeWidth">
      <path d="M0,0 L7,3 L0,6 Z" fill="{AMBER}"/>
    </marker>
    <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{GREEN}"/>
      <stop offset="70%" stop-color="{GREEN}"/>
      <stop offset="100%" stop-color="{AMBER}"/>
    </linearGradient>
    <filter id="sh" x="-2%" y="-2%" width="104%" height="112%">
      <feDropShadow dx="0" dy="1.5" stdDeviation="1.6" flood-color="#0f172a" flood-opacity="0.10"/>
    </filter>
  </defs>
  <rect width="{W}" height="{H}" fill="white"/>
  {title}
  {"".join(parts)}
</svg>
"""

DOCS = Path(__file__).resolve().parent
out = DOCS / "architecture.svg"
out.write_text(svg, encoding="utf-8")
print(f"wrote {out}")


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


def _render_png(chrome: str) -> None:
    """Screenshot the SVG to a crisp 2x PNG via headless Chrome."""
    wrapper = DOCS / "_diagram.html"
    wrapper.write_text(
        f"<!doctype html><meta charset='utf-8'><style>html,body{{margin:0;padding:0}}</style>{svg}",
        encoding="utf-8",
    )
    png = DOCS / "architecture.png"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--user-data-dir={DOCS / '_chrome'}",
            f"--window-size={W},{H}",
            f"--screenshot={png}",
            wrapper.as_uri(),
        ],
        check=False,
    )
    wrapper.unlink(missing_ok=True)
    shutil.rmtree(DOCS / "_chrome", ignore_errors=True)
    if png.exists():
        print(f"wrote {png} ({png.stat().st_size / 1e3:.0f} KB)")


_chrome = _find_chrome()
if _chrome:
    _render_png(_chrome)
else:
    print("Chrome/Edge not found; wrote SVG only — render architecture.png manually.")
