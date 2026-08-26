#!/usr/bin/env python3
"""Render preview.png and preview.gif from synthetic fixture data.

The preview must never contain a live fleet screenshot: real panels carry
internal hostnames, agent working titles, and client project paths. This
generator draws the panel layout from tests/fixtures/fleet_demo.json, which
ships only neutral synthetic data, so anyone can reproduce the assets with:

    python3 scripts/make_preview.py

Requires ImageMagick (magick) and ffmpeg. Writes preview.png (first frame)
and preview.gif (animated walk-through) at the repo root.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fleet_demo.json"
W, H = 520, 700
SCALE = 2

BG = "#16161d"
PANEL = "#1b1b27"
BORDER = "#363a4f"
FG = "#cad3f5"
MUTED = "#8087a2"
ACCENT = "#8aadf4"
OK = "#a6da95"
WARN = "#eed49f"
BAD = "#ed8796"
STALE = "#f5a97f"
ROW_SEL = "#24243a"

HEALTH = {"online": OK, "degraded": WARN, "offline": BAD}
STATUS = {"working": OK, "blocked": BAD, "idle": MUTED, "waiting": WARN, "done": ACCENT}

FONT = "DejaVu Sans Mono"
FONT_ICON = "BitstromWera Nerd Font"  # private-use glyphs DejaVu lacks


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text(x, y, s, fill=FG, size=12, weight="normal", anchor=None):
    a = f' text-anchor="{anchor}"' if anchor else ""
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-family="{FONT}" '
        f'font-size="{size}" font-weight="{weight}"{a}>{esc(s)}</text>'
    )


def est_w(s: str, size: float) -> float:
    return len(s) * size * 0.62  # monospace estimate, conservative


def fit(s: str, max_w: float, size: float) -> str:
    """Truncate with an ellipsis so the string cannot exceed max_w."""
    if est_w(s, size) <= max_w:
        return s
    keep = max(1, int(max_w / (size * 0.62)) - 1)
    return s[:keep].rstrip() + "…"


def rect(x, y, w, h, fill, rx: float = 0, opacity: float | None = None):
    o = f' opacity="{opacity}"' if opacity else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"{o}/>'


def load_demo() -> dict:
    return json.loads(FIXTURE.read_text())


def summarize(connectors):
    online = sum(1 for c in connectors if c["health"] == "online")
    agents = [a for c in connectors if c.get("herdr") for a in (c["herdr"] or {}).get("agents", [])]
    working = sum(1 for a in agents if a["status"] == "working")
    blocked = sum(1 for a in agents if a["status"] == "blocked")
    reqs = sum((c.get("omp") or {}).get("overall", {}).get("totalRequests", 0) for c in connectors)
    cost = sum((c.get("omp") or {}).get("overall", {}).get("totalCost", 0) for c in connectors)
    return online, working, blocked, reqs, cost


def frame(conns: list, view: str = "overview", cursor: int = 0, query: str = "", note: str = "") -> str:
    online, working, blocked, reqs, cost = summarize(conns)
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    s.append(rect(0, 0, W, H, BG))

    # shell chrome
    s.append(rect(10, 10, W - 20, H - 20, PANEL, rx=10))
    s.append(
        f'<rect x="10" y="10" width="{W-20}" height="{H-20}" rx="10" fill="none" '
        f'stroke="{BORDER}" stroke-width="1"/>'
    )
    s.append(f'<text x="26" y="38" fill="{FG}" font-family="{FONT_ICON}" font-size="15">󰳆</text>')
    s.append(text(50, 38, fit("Fleet Shepherd", 300, 14), size=14, weight="bold"))
    s.append(text(W - 26, 38, fit(note or "2m ago · Ctrl+R", 170, 11), fill=MUTED, size=11, anchor="end"))
    s.append(f'<line x1="10" y1="50" x2="{W-10}" y2="50" stroke="{BORDER}"/>')

    # view tabs
    tabs = [("1", "Overview", "overview"), ("2", "Attention", "attention"),
            ("3", "Agents", "agents"), ("4", "Usage", "usage")]
    tx = 26
    for num, label, vid in tabs:
        active = vid == view
        if active:
            s.append(rect(tx - 8, 58, 14 + 7.2 * len(label), 22, "#2a2a45", rx=6))
        s.append(text(tx, 73, f"{num} {label}", fill=ACCENT if active else MUTED, size=11))
        tx += 24 + 7.2 * len(label)

    # filter field
    fy = 92
    s.append(rect(26, fy, W - 52, 26, "#131320", rx=6))
    s.append(f'<rect x="26" y="{fy}" width="{W-52}" height="26" rx="6" fill="none" stroke="{BORDER}"/>')
    if query:
        s.append(text(36, fy + 17, query, fill=FG, size=11))
        s.append(text(36 + est_w(query, 11) + 3, fy + 17, "|", fill=ACCENT, size=11))
    else:
        s.append(text(36, fy + 17, "Filter connectors, agents, projects, models", fill=MUTED, size=10))

    # summary strip
    sy = 132
    sx = 26
    for label, val, color in (("online", online, OK), ("working", working, OK),
                              ("blocked", blocked, BAD if blocked else MUTED),
                              (f"reqs {reqs:,}", None, MUTED)):
        piece = label if val is None else f"{label} {val}"
        s.append(text(sx, sy, fit(piece, 96, 11), fill=color, size=11))
        sx += est_w(piece, 11) + 18
    s.append(text(W - 26, sy, fit(f"${cost:,.2f}", 90, 11), fill=MUTED, size=11, anchor="end"))
    s.append(f'<line x1="26" y1="{sy+10}" x2="{W-26}" y2="{sy+10}" stroke="{BORDER}" opacity="0.6"/>')

    def visible(c):
        if query:
            hay = json.dumps(c).lower()
            return query.lower() in hay
        if view == "attention":
            return bool(c.get("herdr") and any(a["status"] == "blocked" for a in (c["herdr"] or {}).get("agents", [])))
        return True

    rows = [c for c in conns if visible(c)]
    y = sy + 30
    for i, c in enumerate(rows):
        agents = (c.get("herdr") or {}).get("agents", []) or []
        h = 36 + 16 * min(len(agents[:3]), 3) if view != "usage" else 58
        if i == cursor and not query:
            s.append(rect(20, y - 4, W - 40, h, ROW_SEL, rx=6))
            s.append(rect(20, y - 4, 3, h, ACCENT, rx=1.5))
        dot = HEALTH.get(c["health"], MUTED)
        s.append(f'<circle cx="34" cy="{y+6}" r="4" fill="{dot}"/>')
        lat = f'{c["health"]} · {c["latencyMs"]}ms' if c["health"] != "offline" else c.get("error", "offline")[:24]
        lat_w = est_w(lat, 10) + 14
        s.append(text(46, y + 10, fit(c["label"], W - 46 - 26 - lat_w, 13), size=13))
        s.append(text(W - 26, y + 10, lat, fill=MUTED, size=10, anchor="end"))
        y += 22  # keep the label's em-box clear of the first agent line
        if view == "usage" and c.get("omp"):
            y += 6
            for m in (c["omp"] or {}).get("byModel", [])[:3]:
                s.append(rect(46, y - 8, 3, 12, ACCENT, rx=1.5))
                s.append(text(56, y + 2, fit(f'{m["model"]} · {m.get("provider","")} · ${m["totalCost"]:.2f}', W - 56 - 26, 10), fill=MUTED, size=10))
                y += 16
            y += 6
            continue
        for a in agents[:3]:
            if view == "attention" and a["status"] != "blocked":
                continue
            s.append(rect(48, y - 8, 3, 12, STATUS.get(a["status"], MUTED), rx=1.5))
            left = fit(f'{a["agent"]} · {a["status"]}', 150, 11)
            right = fit(a.get("activity", a.get("cwd", "")), W - 26 - 58 - est_w(left, 11) - 24, 10)
            s.append(text(58, y + 2, left, size=11))
            s.append(text(W - 26, y + 2, right, fill=MUTED, size=10, anchor="end"))
            y += 16
        y += 14

    if not rows:
        s.append(text(W // 2, y + 20, "no connectors match", fill=MUTED, size=12, anchor="middle"))

    # footer hint
    s.append(f'<text x="26" y="{H-24}" fill="{MUTED}" font-family="{FONT_ICON}" font-size="11">󰅂 󰁅</text>')
    s.append(text(62, H - 24, "navigate · Return raise terminal · Esc close", fill=MUTED, size=10))
    s.append("</svg>")
    return "".join(s)


def main() -> None:
    demo = load_demo()
    conns = demo["connectors"]
    seq = [
        {"conns": conns, "view": "overview", "cursor": 0},
        {"conns": conns, "view": "overview", "cursor": 1},
        {"conns": conns, "view": "overview", "cursor": 2},
        {"conns": conns, "view": "attention", "cursor": 0, "note": "1 blocked · attention"},
        {"conns": conns, "view": "agents", "cursor": 1},
        {"conns": conns, "view": "usage", "cursor": 0, "note": "usage by model"},
        {"conns": conns, "view": "overview", "cursor": 0, "query": "api", "note": "filter: api"},
    ]
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for i, spec in enumerate(seq):
            svg = tdp / f"f{i}.svg"
            svg.write_text(frame(**spec))
            # -density rasterizes the SVG at 2x directly; the previous
            # 1x-then-upscale was the source of the blur
            subprocess.run(
                ["magick", "-background", "none", "-density", "192", str(svg),
                 "-resize", f"{W*SCALE}x{H*SCALE}", str(tdp / f"f{i}.png")],
                check=True, capture_output=True)
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", "0.8", "-i", str(tdp / "f%d.png"),
             "-vf", "split[a][b];[a]palettegen=stats_mode=single[p];[b][p]paletteuse=dither=bayer:bayer_scale=3",
             str(ROOT / "preview.gif")],
            check=True, capture_output=True)
        subprocess.run(
            ["magick", str(tdp / "f0.png"), str(ROOT / "preview.png")],
            check=True, capture_output=True)
    print("wrote preview.png and preview.gif")


if __name__ == "__main__":
    main()
