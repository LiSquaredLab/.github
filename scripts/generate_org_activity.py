
#!/usr/bin/env python3
"""Generate 30/90/365-day LiSquaredLab organization activity charts."""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ORG = os.environ.get("GITHUB_ORG", "LiSquaredLab")
TOKEN = os.environ["ORG_ACTIVITY_TOKEN"]

HISTORY_DAYS = 365
CHART_WINDOWS = (30, 90, 365)
API = "https://api.github.com"

ASSETS = Path("assets")

# White-background, mathematical / GitHub-style palette
COLORS = {
    "background": "#ffffff",
    "title": "#111827",
    "text": "#6b7280",
    "grid": "#e5e7eb",
    "commits": "#2563eb",
    "prs": "#10b981",
    "issues": "#f59e0b",
}

SERIES = (
    ("commits", "Commits"),
    ("prs", "PRs"),
    ("issues", "Issues"),
)


def get(path: str, params: dict[str, str] | None = None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LiSquaredLab-org-activity",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"GitHub API error {exc.code} for {path}: {detail}"
        ) from exc


def pages(
    path: str,
    params: dict[str, str] | None = None,
):
    """Iterate through paginated GitHub REST API results."""
    page = 1
    params = params or {}

    while True:
        data = get(
            path,
            {
                **params,
                "page": str(page),
                "per_page": "100",
            },
        )

        if not isinstance(data, list):
            raise RuntimeError(f"Expected a list from {path}")

        if not data:
            return

        yield from data

        if len(data) < 100:
            return

        page += 1


def count_created_events(
    path: str,
    counter: Counter,
    start: dt.date,
    end: dt.date,
    *,
    skip_pull_requests: bool = False,
):
    """Count Issues or PRs using descending creation dates."""

    for item in pages(
        path,
        {
            "state": "all",
            "sort": "created",
            "direction": "desc",
        },
    ):
        stamp = (item.get("created_at") or "")[:10]

        if not stamp:
            continue

        day = dt.date.fromisoformat(stamp)

        # Items are sorted newest first.
        if day < start:
            break

        if day > end:
            continue

        # The Issues endpoint also returns Pull Requests.
        if skip_pull_requests and "pull_request" in item:
            continue

        counter[stamp] += 1


def collect_activity():
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=HISTORY_DAYS - 1)
    tomorrow = today + dt.timedelta(days=1)

    dates = [
        start + dt.timedelta(days=i)
        for i in range(HISTORY_DAYS)
    ]

    commits = Counter()
    prs = Counter()
    issues = Counter()

    repo_count = 0

    for repo in pages(
        f"/orgs/{ORG}/repos",
        {
            "type": "all",
            "sort": "full_name",
        },
    ):
        repo_count += 1
        full_name = repo["full_name"]

        # Avoid counting the auto-generated chart commits.
        # Remove this condition if you want to count them.
        if repo["name"] == ".github":
            print(f"Skipping automation repository: {full_name}")
            continue

        print(f"Collecting activity: {full_name}", flush=True)

        # Commits reachable from the repository's default branch.
        # 'since' filters by commit timestamp on the GitHub API.
        for commit in pages(
            f"/repos/{full_name}/commits",
            {
                "since": f"{start}T00:00:00Z",
                "until": f"{tomorrow}T00:00:00Z",
            },
        ):
            info = commit.get("commit", {})
            stamp = (
                (info.get("author") or {}).get("date")
                or (info.get("committer") or {}).get("date")
                or ""
            )[:10]

            if stamp and str(start) <= stamp <= str(today):
                commits[stamp] += 1

        count_created_events(
            f"/repos/{full_name}/pulls",
            prs,
            start,
            today,
        )

        count_created_events(
            f"/repos/{full_name}/issues",
            issues,
            start,
            today,
            skip_pull_requests=True,
        )

    if repo_count == 0:
        raise RuntimeError(
            f"No accessible repositories found in {ORG}. "
            "Check your GitHub token permissions."
        )

    values = [
        {
            "date": str(day),
            "commits": commits[str(day)],
            "prs": prs[str(day)],
            "issues": issues[str(day)],
        }
        for day in dates
    ]

    return values


def make_svg(
    values: list[dict],
    output: Path,
) -> None:
    """Render a standalone GitHub-compatible SVG line chart."""

    if len(values) < 2:
        raise ValueError("At least two days are required")

    width = 1000
    height = 340

    left = 60
    right = 35
    top = 70
    bottom = 78

    plot_width = width - left - right
    plot_height = height - top - bottom
    days = len(values)

    maximum = max(
        (
            value[key]
            for value in values
            for key, _ in SERIES
        ),
        default=0,
    )

    # Choose convenient integer tick intervals.
    import math

    raw_step = max(maximum, 1) / 4
    magnitude = 10 ** math.floor(math.log10(raw_step))
    tick_step = next(
        step * magnitude
        for step in (1, 2, 5, 10)
        if step * magnitude >= raw_step
    )

    y_max = max(
        tick_step * 4,
        math.ceil(maximum / tick_step) * tick_step,
    )

    def x_pos(index: int) -> float:
        return left + index * plot_width / (days - 1)

    def y_pos(value: float) -> float:
        return top + plot_height * (1 - value / y_max)

    def points(key: str) -> str:
        return " ".join(
            f"{x_pos(i):.2f},{y_pos(item[key]):.2f}"
            for i, item in enumerate(values)
        )

    start_date = values[0]["date"]
    end_date = values[-1]["date"]
    start_label = dt.date.fromisoformat(start_date).strftime("%b %d")
    end_label = dt.date.fromisoformat(end_date).strftime("%b %d")

    title = f"{ORG} · Contribution Activity"
    subtitle = (
        f"Last {days} days  ·  "
        f"{start_date} to {end_date}"
    )

    svg = [
        (
            '<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {width} {height}" '
            'role="img" aria-labelledby="chart-title chart-desc">'
        ),
        (
            f'<title id="chart-title">'
            f'{html.escape(title)}</title>'
        ),
        (
            f'<desc id="chart-desc">'
            f'Daily commits, pull requests, and issues '
            f'for the last {days} days.</desc>'
        ),
        (
            f'<rect width="{width}" height="{height}" '
            'rx="12" '
            f'fill="{COLORS["background"]}"/>'
        ),
        (
            f'<text x="{left}" y="32" '
            'font-family="Arial, sans-serif" '
            'font-size="19" font-weight="600" '
            f'fill="{COLORS["title"]}">'
            f'{html.escape(title)}</text>'
        ),
        (
            f'<text x="{left}" y="53" '
            'font-family="Arial, sans-serif" '
            'font-size="12" '
            f'fill="{COLORS["text"]}">'
            f'{html.escape(subtitle)}</text>'
        ),
    ]

    # Horizontal grid and Y-axis labels.
    for index in range(5):
        value = index * tick_step
        y = y_pos(value)

        svg.append(
            f'<line x1="{left}" y1="{y:.2f}" '
            f'x2="{width - right}" y2="{y:.2f}" '
            f'stroke="{COLORS["grid"]}" stroke-width="1"/>'
        )

        svg.append(
            f'<text x="{left - 12}" y="{y + 4:.2f}" '
            'text-anchor="end" '
            'font-family="Arial, sans-serif" '
            'font-size="11" '
            f'fill="{COLORS["text"]}">'
            f'{int(value) if value == int(value) else value:g}'
            '</text>'
        )

    # Plot each activity type.
    for key, label in SERIES:
        svg.append(
            '<polyline fill="none" '
            f'stroke="{COLORS[key]}" '
            'stroke-width="2.7" '
            'stroke-linecap="round" '
            'stroke-linejoin="round" '
            f'points="{points(key)}"/>'
        )

    # X-axis: five date labels.
    for index in range(5):
        data_index = round(index * (days - 1) / 4)
        date = dt.date.fromisoformat(
            values[data_index]["date"]
        )
        label = date.strftime("%b %d")
        x = x_pos(data_index)

        svg.append(
            f'<text x="{x:.2f}" y="{height - 48}" '
            'text-anchor="middle" '
            'font-family="Arial, sans-serif" '
            'font-size="11" '
            f'fill="{COLORS["text"]}">'
            f'{html.escape(label)}</text>'
        )

    # Legend.
    legend_y = height - 17
    legend_positions = (330, 465, 575)

    for (key, label), x in zip(SERIES, legend_positions):
        svg.append(
            f'<line x1="{x}" y1="{legend_y - 4}" '
            f'x2="{x + 23}" y2="{legend_y - 4}" '
            f'stroke="{COLORS[key]}" '
            'stroke-width="3" stroke-linecap="round"/>'
        )
        svg.append(
            f'<text x="{x + 31}" y="{legend_y}" '
            'font-family="Arial, sans-serif" '
            'font-size="12" '
            f'fill="{COLORS["text"]}">'
            f'{html.escape(label)}</text>'
        )

    svg.append("</svg>")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(svg) + "\n",
        encoding="utf-8",
    )

    print(f"Generated {output} ({days} days)")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)

    values = collect_activity()

    # Retain the full history for future interactive charts.
    json_path = ASSETS / "org-activity.json"
    json_path.write_text(
        json.dumps(values, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Generate three SVGs without additional API calls.
    for days in CHART_WINDOWS:
        make_svg(
            values[-days:],
            ASSETS / f"org-activity-{days}d.svg",
        )

    print("Activity chart generation completed.")


if __name__ == "__main__":
    main()
