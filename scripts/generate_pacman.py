#!/usr/bin/env python3
"""
Generate Pac-Man contribution grid animation SVGs for a GitHub profile.

Pac-Man travels row-by-row through the past year's contribution squares,
chomping each one as he passes.  Two files are produced (light + dark theme).

Usage:
    GITHUB_USER=Marguro GITHUB_TOKEN=<token> python scripts/generate_pacman.py
"""

import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

# ── Layout ────────────────────────────────────────────────────────────────────
CELL    = 11        # square side (px)
GAP     = 3         # gap between squares (px)
STEP    = CELL + GAP
PAC_R   = 7         # pac-man radius (px)
PADX    = 10
PADY    = 10
ANIM_S  = 20.0      # full-loop animation duration (seconds)
CHOMP_S = 0.35      # mouth chomp cycle (seconds)

# ── Colours ───────────────────────────────────────────────────────────────────
PALETTE = {
    "light": {"bg": "#ffffff", "empty": "#ebedf0", "pac": "#f5c518"},
    "dark":  {"bg": "#0d1117", "empty": "#161b22", "pac": "#f5c518"},
}


# ── GitHub GraphQL ─────────────────────────────────────────────────────────────
def fetch_weeks(username: str, token: str) -> list:
    now      = datetime.now(timezone.utc)
    one_year = now - timedelta(days=365)

    gql = (
        "query($l:String!,$f:DateTime!,$t:DateTime!){"
        "user(login:$l){contributionsCollection(from:$f,to:$t){"
        "contributionCalendar{weeks{contributionDays{contributionCount color}}}}}}"
    )
    payload = json.dumps({
        "query": gql,
        "variables": {
            "l": username,
            "f": one_year.strftime("%Y-%m-%dT00:00:00Z"),
            "t": now.strftime("%Y-%m-%dT23:59:59Z"),
        },
    }).encode()

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type":  "application/json",
            "User-Agent":    "pacman-contribution-grid/1.0",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    return (
        data["data"]["user"]["contributionsCollection"]
        ["contributionCalendar"]["weeks"]
    )


# ── Grid & path ───────────────────────────────────────────────────────────────
def build_grid(weeks: list):
    rows, cols = 7, len(weeks)
    grid = [[None] * cols for _ in range(rows)]
    for c, week in enumerate(weeks):
        for r, day in enumerate(week["contributionDays"]):
            if r < rows:
                grid[r][c] = day
    return grid, rows, cols


def boustrophedon(grid, rows: int, cols: int) -> list:
    """Serpentine path: row 0 left→right, row 1 right→left, …"""
    path = []
    for r in range(rows):
        col_range = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        for c in col_range:
            if grid[r][c] is not None:
                path.append((c, r))
    return path


# ── Pac-Man mouth path ────────────────────────────────────────────────────────
def pac_mouth(angle_deg: float) -> str:
    """
    SVG path for a Pac-Man circle facing right with the given mouth opening.
    Both open and closed share identical command structure (M L A Z) so that
    CSS d-property animation can interpolate smoothly between them.
    """
    a  = math.radians(angle_deg / 2)
    r  = PAC_R
    x1 = r * math.cos(a)
    y1 = -r * math.sin(a)   # top lip  (SVG y-axis is down)
    x2 = r * math.cos(a)
    y2 =  r * math.sin(a)   # bottom lip
    # Large counter-clockwise arc = the body of Pac-Man (not the mouth gap)
    return f"M 0 0 L {x1:.3f} {y1:.3f} A {r} {r} 0 1 0 {x2:.3f} {y2:.3f} Z"


MOUTH_OPEN   = pac_mouth(40)   # 40° opening
MOUTH_CLOSED = pac_mouth(4)    # near-closed (same path structure → smooth tween)


# ── SVG generator ─────────────────────────────────────────────────────────────
def generate(weeks: list, dark: bool = False) -> str:
    pal            = PALETTE["dark" if dark else "light"]
    grid, ROWS, COLS = build_grid(weeks)
    path           = boustrophedon(grid, ROWS, COLS)
    N              = len(path)
    step_of        = {pos: i for i, pos in enumerate(path)}

    W = PADX * 2 + COLS * STEP
    H = PADY * 2 + ROWS * STEP

    def cx(c): return PADX + c * STEP + CELL / 2
    def cy(r): return PADY + r * STEP + CELL / 2
    def rx(c): return PADX + c * STEP
    def ry(r): return PADY + r * STEP

    D = ANIM_S

    # ── CSS ───────────────────────────────────────────────────────────────────
    css_parts: list[str] = []

    # 1. Pac-Man position keyframes (one stop per grid step)
    pm_kf = []
    for i, (c, r) in enumerate(path):
        pct = i / N * 100
        pm_kf.append(f"{pct:.3f}%{{transform:translate({cx(c):.1f}px,{cy(r):.1f}px)}}")
    # close the loop at 100 %
    lc, lr = path[-1]
    pm_kf.append(f"100%{{transform:translate({cx(lc):.1f}px,{cy(lr):.1f}px)}}")
    css_parts.append("@keyframes pm{" + "".join(pm_kf) + "}")

    # 2. Mouth chomp keyframes (CSS d-property)
    css_parts.append(
        f"@keyframes ch{{"
        f"0%,100%{{d:path('{MOUTH_OPEN}')}}"
        f"50%{{d:path('{MOUTH_CLOSED}')}}"
        f"}}"
    )

    # 3. Per-cell eat keyframes
    for (c, r), idx in step_of.items():
        eat_t  = idx / N
        gone_t = min(eat_t + 0.4 / N, 0.9999)
        css_parts.append(
            f"@keyframes e{c}x{r}{{"
            f"0%,{eat_t*100:.3f}%{{opacity:1}}"
            f"{gone_t*100:.3f}%,100%{{opacity:0}}"
            f"}}"
        )

    style_block = "<style>" + "".join(css_parts) + "</style>"

    # ── Build SVG ─────────────────────────────────────────────────────────────
    out: list[str] = []
    a = out.append

    a(f'<svg xmlns="http://www.w3.org/2000/svg" '
      f'width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
    a(style_block)
    a(f'<rect width="{W}" height="{H}" fill="{pal["bg"]}"/>')

    # Contribution squares
    for r in range(ROWS):
        for c in range(COLS):
            cell = grid[r][c]
            if cell is None:
                continue
            color = cell["color"] if cell["contributionCount"] > 0 else pal["empty"]
            x, y  = rx(c), ry(r)
            idx   = step_of.get((c, r))

            if idx is not None:
                a(
                    f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{color}" '
                    f'style="animation:e{c}x{r} {D}s linear infinite"/>'
                )
            else:
                a(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{color}"/>')

    # Pac-Man (starts at first path position, CSS animates it)
    sx, sy = cx(path[0][0]), cy(path[0][1])
    a(f'<g style="animation:pm {D}s linear infinite;transform:translate({sx:.1f}px,{sy:.1f}px)">')
    a(
        f'  <path fill="{pal["pac"]}" '
        f'style="d:path(\'{MOUTH_OPEN}\');animation:ch {CHOMP_S}s linear infinite"/>'
    )
    a('</g>')

    a('</svg>')
    return "\n".join(out)


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    username = os.environ.get("GITHUB_USER") or (sys.argv[1] if len(sys.argv) > 1 else "")
    token    = os.environ.get("GITHUB_TOKEN", "")
    out_dir  = os.environ.get("OUTPUT_DIR", "dist")

    if not username:
        sys.exit("Error: set the GITHUB_USER environment variable")
    if not token:
        sys.exit("Error: set the GITHUB_TOKEN environment variable")

    print(f"Fetching contributions for {username}…")
    weeks = fetch_weeks(username, token)

    os.makedirs(out_dir, exist_ok=True)

    for dark, suffix in [(False, ""), (True, "-dark")]:
        out_path = os.path.join(out_dir, f"pacman-contribution-grid{suffix}.svg")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(generate(weeks, dark=dark))
        print(f"  → {out_path}")

    print("Done!")


if __name__ == "__main__":
    main()
