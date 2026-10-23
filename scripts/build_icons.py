#!/usr/bin/env python3
"""Build the inline icon sprite from lucide (ISC, https://lucide.dev), the icon set VibeFarsi uses.

Each id the pages already reference (`<use href="#i-grid">`) maps to a lucide icon, so changing an icon
is one line in ICONS. The sprite is written between the ICONS markers in index.html and the panel
pages. Needs the network (unpkg) only when you run it; the pages themselves load nothing.

  python3 scripts/build_icons.py
"""
import re, sys, urllib.request
from pathlib import Path

VERSION = "0.469.0"
ROOT = Path(__file__).resolve().parent.parent
ICONS = {
    # navigation
    "i-grid": "layout-dashboard", "i-target": "target", "i-calendar": "calendar-days", "i-film": "clapperboard", "i-trend": "trending-up",
    "i-chart": "chart-column", "i-clock": "clock", "i-flask": "flask-conical", "i-bulb": "lightbulb", "i-trophy": "trophy", "i-users": "users",
    "i-check": "list-checks", "i-chat": "message-circle", "i-spark": "sparkles", "i-board": "kanban", "i-comment": "message-square-text",
    "i-settings": "sliders-horizontal", "i-shield": "shield-check",
    # top bar and menus
    "i-sun": "sun", "i-moon": "moon", "i-menu": "menu", "i-panel": "panel-right", "i-logout": "log-out", "i-bell": "bell", "i-print": "printer",
    "i-refresh": "refresh-cw", "i-plus": "plus", "i-x": "x", "i-chevron-down": "chevron-down",
    # KPI tiles
    "i-eye": "eye", "i-eye-off": "eye-off", "i-timer": "timer", "i-bookmark": "bookmark", "i-send": "send", "i-globe": "globe", "i-userplus": "user-plus", "i-heart": "heart",
    # actions and states
    "i-pen": "pen-line", "i-link": "link", "i-copy": "copy", "i-download": "download", "i-external": "external-link", "i-inbox": "inbox",
    "i-alert": "circle-alert", "i-up": "arrow-up-left", "i-down": "arrow-down-left", "i-search": "search",
    # the studio's agents
    "i-a-reel": "clapperboard", "i-a-caption": "pen-line", "i-a-carousel": "gallery-horizontal-end", "i-a-story": "circle-dashed",
    "i-a-viral": "search", "i-a-plan": "calendar-range", "i-a-audit": "stethoscope", "i-a-profile": "id-card", "i-a-human": "user-round-check",
    "i-a-comment": "message-circle", "i-a-reply": "reply", "i-a-dm": "mail", "i-a-repurpose": "recycle",
}
START, END = "<!--ICONS-->", "<!--/ICONS-->"


def fetch(name):
    url = f"https://unpkg.com/lucide-static@{VERSION}/icons/{name}.svg"
    svg = urllib.request.urlopen(url, timeout=30).read().decode()
    return re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1).strip()


def sprite(ids=None):
    body = []
    for sid, name in ICONS.items():
        if ids and sid not in ids:
            continue
        inner = re.sub(r"\s+", " ", fetch(name))
        body.append(f'<symbol id="{sid}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" '
                    f'stroke-linecap="round" stroke-linejoin="round">{inner}</symbol>')
    return (f'{START}<svg xmlns="http://www.w3.org/2000/svg" class="hidden" aria-hidden="true" style="display:none">'
            + "".join(body) + f"</svg>{END}")


def main():
    full = sprite()
    for page in [ROOT / "index.html"] + [ROOT / "panel" / n for n in ("settings.html", "admin.html", "login.html")]:
        s = page.read_text(encoding="utf-8")
        if START not in s:
            sys.exit(f"{page}: add {START}{END} where the sprite goes")
        s = re.sub(re.escape(START) + ".*?" + re.escape(END), lambda m: full, s, flags=re.S)
        page.write_text(s, encoding="utf-8")
        print("sprite →", page.relative_to(ROOT))


if __name__ == "__main__":
    main()
