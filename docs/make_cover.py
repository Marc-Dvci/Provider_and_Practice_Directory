#!/usr/bin/env python
"""Generate the Kaggle writeup cover image (SVG + PNG via headless Chrome).

Run:  python docs/make_cover.py   ->  docs/cover.png  (1600x900, 2x)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

W, H = 1600, 900

GREEN = "#1f9d63"
GREEN2 = "#178a55"
AMBER = "#d98324"
BLUE = "#2563a8"
INK = "#0f172a"
SLATE = "#475569"
MUTE = "#64748b"
FUNNEL_BG = "#eef2f7"

p: list[str] = []


def text(x, y, s, size, fill=INK, weight=400, anchor="start", spacing=None, opacity=None):
    extra = f' letter-spacing="{spacing}"' if spacing else ""
    extra += f' opacity="{opacity}"' if opacity else ""
    p.append(
        f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
        f'text-anchor="{anchor}"{extra}>{escape(s)}</text>'
    )


def chip(x, y, label, color, bg):
    w = len(label) * 8.0 + 38
    p.append(
        f'<rect x="{x}" y="{y}" width="{w:.0f}" height="36" rx="18" fill="{bg}" '
        f'stroke="{color}" stroke-width="1.5"/>'
    )
    p.append(
        f'<circle cx="{x + 19}" cy="{y + 18}" r="4.5" fill="{color}"/>'
        f'<text x="{x + 33}" y="{y + 23}" font-size="15.5" font-weight="600" fill="{INK}">'
        f"{escape(label)}</text>"
    )
    return w


def band(cx, y, w, h, label, color):
    p.append(
        f'<rect x="{cx - w / 2:.0f}" y="{y}" width="{w:.0f}" height="{h}" rx="9" fill="{color}"/>'
    )
    p.append(
        f'<text x="{cx}" y="{y + h / 2 + 6}" font-size="18.5" font-weight="700" fill="white" '
        f'text-anchor="middle">{escape(label)}</text>'
    )


# ---- background ----
p.append(f'<rect width="{W}" height="{H}" fill="white"/>')
p.append(f'<rect width="{W}" height="8" fill="url(#bar)"/>')
p.append(f'<rect x="0" y="8" width="{W}" height="{H - 8}" fill="url(#wash)"/>')

# ---- left: text column ----
LX = 96
text(
    LX,
    196,
    "HEALTHLYNKED  ·  PROVIDER & PRACTICE DIRECTORY CHALLENGE",
    17,
    GREEN,
    700,
    spacing="1.5",
)
text(LX, 270, "Provider & Practice", 58, INK, 800)
text(LX, 338, "Directory Update Pipeline", 58, INK, 800)
text(LX, 396, "A repeatable, cost-efficient pipeline that keeps a healthcare", 23, SLATE, 400)
text(LX, 428, "directory accurate — and measures its own accuracy.", 23, SLATE, 400)

# thesis line
text(LX, 486, "Deterministic-first, LLM-last.", 20, GREEN2, 700)
text(LX, 516, "Most updates already sit in free U.S. government data, so the bulk", 20, SLATE, 400)
text(
    LX, 544, "resolves at ~$0 — only the residual reaches an LLM, scrape, or human.", 20, SLATE, 400
)

# stat chips (two rows)
c1 = chip(LX, 588, "≈ $0 per record on the hot path", GREEN, "#e8f7ef")
chip(LX + c1 + 14, 588, "0 paid APIs — free NPPES + CMS data", AMBER, "#fcf1e2")
c3 = chip(LX, 636, "≈ 97% auto-update precision, measured", BLUE, "#e7f0fb")
chip(LX + c3 + 14, 636, "transparent confidence + full audit trail", SLATE, "#eef1f5")

# footer
text(LX, 792, "Hybrid submission — runnable prototype + production architecture.", 18, MUTE, 500)

# ---- right: funnel ----
CXR = 1235
y0, y1 = 232, 602
top_w, bot_w = 520, 196


def fwidth(y: float) -> float:
    return top_w - (top_w - bot_w) * (y - y0) / (y1 - y0)


# funnel silhouette
p.append(
    f'<path d="M {CXR - top_w / 2} {y0} H {CXR + top_w / 2} '
    f'L {CXR + bot_w / 2} {y1} H {CXR - bot_w / 2} Z" '
    f'fill="{FUNNEL_BG}"/>'
)
text(CXR, y0 - 16, "every directory record", 16, MUTE, 600, anchor="middle")

bands = [
    (250, "Structured reconcile · NPPES + CMS", GREEN),
    (335, "Confidence + safe-update rules", GREEN2),
    (420, "Gated web / LLM extraction", AMBER),
    (505, "Human review", BLUE),
]
for by, label, color in bands:
    bw = fwidth(by + 30) - 28
    band(CXR, by, bw, 60, label, color)

# volume tags to the left of the funnel
for ty, tag in ((280, "100% — free"), (450, "~10% residual"), (535, "≈3–5%")):
    text(CXR - top_w / 2 - 22, ty, tag, 15.5, MUTE, 600, anchor="end")

text(
    CXR,
    y1 + 34,
    "route each record only as far down the cost gradient as it needs to go",
    16,
    SLATE,
    500,
    anchor="middle",
)

svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"
     font-family="'Segoe UI', Helvetica, Arial, sans-serif">
  <defs>
    <linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{GREEN}"/>
      <stop offset="60%" stop-color="{GREEN}"/>
      <stop offset="80%" stop-color="{AMBER}"/>
      <stop offset="100%" stop-color="{BLUE}"/>
    </linearGradient>
    <linearGradient id="wash" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="100%" stop-color="#f6f9fc"/>
    </linearGradient>
  </defs>
  {"".join(p)}
</svg>
"""

DOCS = Path(__file__).resolve().parent
(DOCS / "cover.svg").write_text(svg, encoding="utf-8")
print(f"wrote {DOCS / 'cover.svg'}")


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


chrome = _find_chrome()
if chrome:
    wrapper = DOCS / "_cover.html"
    wrapper.write_text(
        f"<!doctype html><meta charset='utf-8'><style>html,body{{margin:0}}</style>{svg}",
        encoding="utf-8",
    )
    png = DOCS / "cover.png"
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
else:
    print("Chrome/Edge not found; wrote cover.svg only.")
