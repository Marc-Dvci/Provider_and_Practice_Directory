#!/usr/bin/env python
"""Render docs/PROPOSAL.md to a polished PDF via headless Chrome.

Run:  python docs/make_pdf.py
Produces docs/PROPOSAL.html (intermediate) and prints docs/Proposal.pdf with Chrome.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", Helvetica, Arial, sans-serif; color: #1f2733;
       font-size: 10.6pt; line-height: 1.5; max-width: 820px; margin: 0 auto; }
h1 { font-size: 22pt; color: #0f2d4a; margin: 0 0 2px; line-height: 1.15; }
h1 + p { color: #475569; font-weight: 600; margin-top: 0; }
h2 { font-size: 14pt; color: #14507e; border-bottom: 2px solid #d8e3ef;
     padding-bottom: 4px; margin: 22px 0 10px; page-break-after: avoid; }
h3 { font-size: 11.5pt; color: #1f2733; margin: 14px 0 6px; page-break-after: avoid; }
p, li { orphans: 2; widows: 2; }
strong { color: #102a43; }
code, pre { font-family: Consolas, "Courier New", monospace; }
code { background: #eef2f7; padding: 1px 4px; border-radius: 3px; font-size: 9.2pt; }
pre { background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
      font-size: 8.8pt; line-height: 1.4; overflow-x: auto; page-break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.4pt;
        page-break-inside: avoid; }
th, td { border: 1px solid #cdd9e5; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #eef3f9; color: #102a43; }
tr:nth-child(even) td { background: #f8fafc; }
img { max-width: 100%; display: block; margin: 14px auto; border: 1px solid #e2e8f0;
      border-radius: 6px; page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #e2e8f0; margin: 18px 0; }
a { color: #14507e; }
h2 { page-break-before: auto; }
"""


def main() -> int:
    md = (DOCS / "PROPOSAL.md").read_text(encoding="utf-8")
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists", "attr_list"])
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Provider &amp; Practice Directory Update Pipeline — Proposal</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )
    html_path = DOCS / "PROPOSAL.html"
    html_path.write_text(html, encoding="utf-8")

    chrome = _find_chrome()
    if not chrome:
        print("Chrome not found; wrote PROPOSAL.html — print it to PDF manually.")
        return 0
    pdf_path = DOCS / "Proposal.pdf"
    url = html_path.as_uri()
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            f"--user-data-dir={DOCS / '_chrome'}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            url,
        ],
        check=False,
    )
    if pdf_path.exists():
        print(f"wrote {pdf_path} ({pdf_path.stat().st_size / 1e6:.2f} MB)")
        shutil.rmtree(DOCS / "_chrome", ignore_errors=True)
    return 0


def _find_chrome() -> str | None:
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if c and Path(c).exists():
            return c
    return None


if __name__ == "__main__":
    raise SystemExit(main())
