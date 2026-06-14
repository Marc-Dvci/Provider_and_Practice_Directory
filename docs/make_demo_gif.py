#!/usr/bin/env python
"""Render an animated terminal GIF of `directory-pipeline demo`.

Runs the real demo, captures its output, and paints it into a scrolling dark
terminal as an animated GIF (no external recorder needed).

Run:  python docs/make_demo_gif.py   ->  docs/demo.gif
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---- look & feel ---------------------------------------------------------- #
BG = (12, 14, 20)
TITLEBAR = (30, 33, 43)
DEFAULT = (203, 209, 219)
CYAN = (94, 200, 224)
GREEN = (104, 207, 142)
AMBER = (227, 173, 96)
GREY = (132, 140, 153)
MAGENTA = (205, 146, 214)
BLUE = (115, 174, 236)
PROMPT = (120, 205, 150)

FONT_SIZE = 15
LINE_H = 22
PAD = 26
TITLEBAR_H = 34
VIEWPORT_LINES = 32
WIDTH = 1180


def _font() -> ImageFont.FreeTypeFont:
    for name in ("consola.ttf", "DejaVuSansMono.ttf", "cour.ttf"):
        for base in (r"C:\Windows\Fonts", "/usr/share/fonts/truetype/dejavu", ""):
            try:
                return ImageFont.truetype(str(Path(base) / name), FONT_SIZE)
            except OSError:
                continue
    return ImageFont.load_default()


FONT = _font()


def color_for(line: str) -> tuple[int, int, int]:
    s = line.strip()
    if s.startswith("$ "):
        return PROMPT
    if (set(s) <= {"=", " "} and s) or (set(s) <= {"-", " "} and s):
        return GREY
    if line.startswith(" Provider & Practice") or "Agent Workflow" in line:
        return CYAN
    if s.startswith(("Verify queue", "Duplicate clusters", "Backtest report", "Audit log")):
        return CYAN
    if s.startswith("[+]"):
        return GREEN
    if s.startswith("[?]"):
        return AMBER
    if s.startswith(("[=]", "[.]")):
        return GREY
    if s.startswith("signal"):
        return MAGENTA
    if s.startswith("geocode"):
        return BLUE
    if s.startswith("action"):
        return DEFAULT
    if s.startswith("reason"):
        return GREY
    if "precision" in s or "recall" in s or "accuracy" in s:
        return GREEN
    if s.startswith("NOTE"):
        return AMBER
    return DEFAULT


def truncate(draw: ImageDraw.ImageDraw, text: str, max_w: int) -> str:
    if draw.textlength(text, font=FONT) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=FONT) > max_w:
        text = text[:-1]
    return text + "…"


def render_frame(visible: list[str]) -> Image.Image:
    h = TITLEBAR_H + 2 * PAD + VIEWPORT_LINES * LINE_H
    img = Image.new("RGB", (WIDTH, h), BG)
    d = ImageDraw.Draw(img)
    # title bar with traffic-light dots
    d.rectangle([0, 0, WIDTH, TITLEBAR_H], fill=TITLEBAR)
    for i, c in enumerate(((237, 106, 94), (245, 191, 79), (98, 197, 84))):
        d.ellipse([18 + i * 22, 11, 30 + i * 22, 23], fill=c)
    d.text(
        (WIDTH // 2, TITLEBAR_H // 2),
        "directory-pipeline — demo",
        font=FONT,
        fill=GREY,
        anchor="mm",
    )
    max_w = WIDTH - 2 * PAD
    y = TITLEBAR_H + PAD
    for line in visible[-VIEWPORT_LINES:]:
        d.text((PAD, y), truncate(d, line, max_w), font=FONT, fill=color_for(line))
        y += LINE_H
    return img


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "DIRPIPE_OFFLINE": "1"}
    proc = subprocess.run(
        [sys.executable, "-m", "directory_pipeline.cli", "demo"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=repo,
    )
    lines = [ln.rstrip() for ln in proc.stdout.splitlines()]

    prompt = "$ directory-pipeline demo"
    frames: list[Image.Image] = []
    durations: list[int] = []

    # 1) type the command
    for k in range(1, len(prompt) + 1):
        frames.append(render_frame([prompt[:k]]))
        durations.append(45)
    frames.append(render_frame([prompt]))
    durations.append(450)

    # 2) reveal output, scrolling
    shown = [prompt, ""]
    for line in lines:
        shown.append(line)
        frames.append(render_frame(shown))
        # linger on section breaks and record headers
        s = line.strip()
        if s.startswith(("[+]", "[?]", "[=]")) or s.startswith("Backtest report"):
            durations.append(260)
        elif set(s) <= {"-", " "} and s:
            durations.append(120)
        else:
            durations.append(70)

    # 3) hold the final screen
    durations[-1] = 3500

    out = repo / "docs" / "demo.gif"
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_mb = out.stat().st_size / 1e6
    print(f"wrote {out} ({len(frames)} frames, {size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
