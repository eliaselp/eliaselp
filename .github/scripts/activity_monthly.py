#!/usr/bin/env python3
"""Monthly contribution activity chart for eliaselp's GitHub profile.

Renders a stacked monthly bar chart:
  - public contributions from GitHub's contribution calendar
  - private commits from the user's private repositories (REST API)

The private layer exists because GitHub does not expose private contributions
in the public calendar unless the "Include private contributions on my profile"
setting is enabled. The chart deliberately labels the two layers separately:
"public contributions" and "private commits".

Usage:
    CONTRIB_TOKEN=... python3 activity_monthly.py --user eliaselp \
        --years 3 --theme dark --output dist/activity-monthly-dark.svg
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from github_private import fetch_private_daily

API = "https://api.github.com"
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]
MONTH_INITIALS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]

THEMES = {
    "light": dict(
        text="#1f2328", muted="#57606a", grid="#d8dee4", track="#eef1f4",
        public="#2da44e", private="#0969da", axis="#8c959f",
    ),
    "dark": dict(
        text="#e6edf3", muted="#8b949e", grid="#30363d", track="#161b22",
        public="#3fb950", private="#58a6ff", axis="#6e7681",
    ),
}


def token() -> str:
    for key in ("CONTRIB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    try:
        return subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=False
        ).stdout.strip()
    except FileNotFoundError:
        return ""


def graphql(query: str, variables: dict, tok: str) -> dict:
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
            "User-Agent": "eliaselp-profile-activity",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        data = json.load(response)
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def month_key(date: str) -> tuple[int, int]:
    year, month, _ = (int(part) for part in date.split("-"))
    return year, month


def month_range(start: datetime, end: datetime) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return months


def fetch_public(start: datetime, end: datetime, user: str, tok: str):
    query = """
    query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){
        contributionsCollection(from:$from,to:$to){
          restrictedContributionsCount
          contributionCalendar{
            totalContributions
            weeks{contributionDays{date contributionCount}}
          }
        }
      }
    }"""
    monthly = defaultdict(int)
    restricted = 0
    for year in range(start.year, end.year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = (end.strftime("%Y-%m-%dT%H:%M:%SZ")
              if year == end.year else f"{year}-12-31T23:59:59Z")
        data = graphql(query, {"login": user, "from": frm, "to": to}, tok)
        collection = data["user"]["contributionsCollection"]
        restricted += collection["restrictedContributionsCount"]
        for week in collection["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                monthly[month_key(day["date"])] += day["contributionCount"]
    return monthly, restricted


def fetch_private(start: datetime, end: datetime, user: str, tok: str):
    daily, repo_count = fetch_private_daily(user, tok, start, end)
    monthly = defaultdict(int)
    for date, count in daily.items():
        monthly[month_key(date)] += count
    return monthly, repo_count


def nice_max(value: int) -> int:
    if value <= 20:
        step = 5
    elif value <= 100:
        step = 10
    else:
        step = 40
    return max(step, math.ceil(value / step) * step)


def render(months, public, private, theme_name: str, user: str) -> str:
    t = THEMES[theme_name]
    width, height = 1100, 380
    left, right, top, bottom = 64, 28, 92, 64
    plot_w = width - left - right
    plot_h = height - top - bottom
    n = len(months)
    slot = plot_w / n
    bar_w = min(18.0, slot * 0.56)
    y_max = nice_max(max((public[m] + private[m] for m in months), default=1))

    def x_center(index: int) -> float:
        return left + index * slot + slot / 2

    def y_pos(value: float) -> float:
        return top + plot_h * (1 - value / y_max)

    base_y = top + plot_h
    total_public = sum(public.values())
    total_private = sum(private.values())
    total = total_public + total_private

    bars = []
    for index, month in enumerate(months):
        public_count = public[month]
        private_count = private[month]
        count = public_count + private_count
        x = x_center(index) - bar_w / 2
        public_h = plot_h * public_count / y_max
        private_h = plot_h * private_count / y_max
        label = f"{MONTHS[month[1] - 1]} {month[0]}: {public_count} public, {private_count} private"
        group = [
            f'<g class="bar" style="animation-delay:{index * 0.012:.3f}s">',
            f"<title>{html.escape(label)}</title>",
        ]
        if public_count:
            group.append(
                f'<rect x="{x:.2f}" y="{base_y - public_h:.2f}" width="{bar_w:.2f}" '
                f'height="{max(public_h, 1.5):.2f}" rx="2" fill="{t["public"]}"/>'
            )
        if private_count:
            group.append(
                f'<rect x="{x:.2f}" y="{base_y - public_h - private_h:.2f}" width="{bar_w:.2f}" '
                f'height="{max(private_h, 1.5):.2f}" rx="2" fill="{t["private"]}"/>'
            )
        group.append("</g>")
        bars.append("\n".join(group))

    grid = []
    for i in range(5):
        value = y_max * i / 4
        y = y_pos(value)
        grid.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width - right}" y2="{y:.2f}" '
            f'stroke="{t["grid"]}" stroke-width="1" stroke-dasharray="{3 if i else 0} {4 if i else 0}"/>'
        )
        grid.append(
            f'<text x="{left - 10}" y="{y + 3.5:.2f}" text-anchor="end" '
            f'class="axis">{int(value)}</text>'
        )

    year_marks = []
    year_labels = []
    year_start = 0
    for index, (year, _) in enumerate(months):
        if index == 0 or year != months[index - 1][0]:
            if index:
                x_line = left + index * slot
                year_marks.append(
                    f'<line x1="{x_line:.2f}" y1="{top - 6}" x2="{x_line:.2f}" '
                    f'y2="{base_y + 6}" stroke="{t["grid"]}" stroke-width="1" '
                    f'stroke-dasharray="3 4"/>'
                )
                prev_year = months[index - 1][0]
                year_labels.append(
                    f'<text x="{left + (year_start + index) / 2 * slot:.2f}" '
                    f'y="{base_y + 38}" text-anchor="middle" class="year">{prev_year}</text>'
                )
            year_start = index
    final_year = months[-1][0]
    year_labels.append(
        f'<text x="{left + (year_start + n) / 2 * slot:.2f}" y="{base_y + 38}" '
        f'text-anchor="middle" class="year">{final_year}</text>'
    )

    month_labels = []
    for index, (_, month) in enumerate(months):
        month_labels.append(
            f'<text x="{x_center(index):.2f}" y="{base_y + 18}" text-anchor="middle" '
            f'class="month">{MONTH_INITIALS[month - 1]}</text>'
        )

    # Legend at the top right.
    legend_x = width - right - 260
    legend = [
        f'<rect x="{legend_x}" y="62" width="10" height="10" rx="2" fill="{t["public"]}"/>',
        f'<text x="{legend_x + 16}" y="71" class="legend">Public contributions</text>',
        f'<rect x="{legend_x + 146}" y="62" width="10" height="10" rx="2" fill="{t["private"]}"/>',
        f'<text x="{legend_x + 162}" y="71" class="legend">Private commits</text>',
    ]

    title = "Monthly contribution activity"
    subtitle = (f"Monthly totals · {months[0][0]}–{months[-1][0]} · "
                f"public contributions + private commits")
    total_label = f"{total:,} total"
    root_title = f"{title} for {user}"
    root_desc = (f"Stacked monthly bars from {months[0][0]}-{months[0][1]:02d} to "
                 f"{months[-1][0]}-{months[-1][1]:02d}: public contributions and "
                 f"private commits.")

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="chart-title chart-desc">
  <title id="chart-title">{html.escape(root_title)}</title>
  <desc id="chart-desc">{html.escape(root_desc)}</desc>
  <style>
    text {{ font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .axis, .month, .year, .legend {{ font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }}
    .axis {{ font-size: 10px; fill: {t['muted']}; }}
    .month {{ font-size: 9px; fill: {t['axis']}; }}
    .year {{ font-size: 12px; fill: {t['text']}; font-weight: 600; }}
    .legend {{ font-size: 10px; fill: {t['muted']}; }}
    .title {{ font-size: 18px; fill: {t['text']}; font-weight: 700; }}
    .subtitle {{ font-size: 11px; fill: {t['muted']}; }}
    .total {{ font-size: 14px; fill: {t['text']}; font-weight: 600; }}
    .total-private {{ font-size: 11px; fill: {t['private']}; }}
    .bar {{ transform-box: fill-box; transform-origin: bottom; animation: grow .8s cubic-bezier(.2,.8,.2,1) both; }}
    @keyframes grow {{ from {{ transform: scaleY(0); }} to {{ transform: scaleY(1); }} }}
    @media (prefers-reduced-motion: reduce) {{ .bar {{ animation: none; }} }}
  </style>
  <text x="{left}" y="32" class="title">{html.escape(title)}</text>
  <text x="{left}" y="52" class="subtitle">{html.escape(subtitle)}</text>
  <text x="{width - right}" y="32" text-anchor="end" class="total">{html.escape(total_label)}</text>
  <text x="{width - right}" y="52" text-anchor="end" class="total-private">{total_private:,} private commits</text>
  {chr(10).join(legend)}
  {chr(10).join(grid)}
  {chr(10).join(year_marks)}
  {chr(10).join(bars)}
  {chr(10).join(month_labels)}
  {chr(10).join(year_labels)}
</svg>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Monthly contribution activity chart.")
    parser.add_argument("--user", default=os.environ.get("GH_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER"))
    parser.add_argument("--years", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--theme", choices=THEMES, default="dark")
    parser.add_argument("--output", default="dist/activity-monthly.svg")
    args = parser.parse_args()
    if not args.user:
        sys.exit("error: --user is required")

    tok = token()
    if not tok:
        sys.exit("error: no token found (CONTRIB_TOKEN / GH_TOKEN / GITHUB_TOKEN)")

    end = datetime.now(timezone.utc)
    start = datetime(end.year - args.years + 1, 1, 1, tzinfo=timezone.utc)
    public, restricted = fetch_public(start, end, args.user, tok)
    private, repo_count = fetch_private(start, end, args.user, tok)
    months = month_range(start, end)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(render(months, public, private, args.theme, args.user))
    print(
        f"wrote {args.output} — {len(months)} months, "
        f"{sum(public.values())} public, {sum(private.values())} private "
        f"({repo_count} private repos)"
    )
    if restricted:
        print(
            f"warning: GitHub reports {restricted} restricted contributions; "
            "private commits may overlap if the profile setting is enabled",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
