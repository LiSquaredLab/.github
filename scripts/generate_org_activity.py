#!/usr/bin/env python3
"""Generate a 365-day organization activity chart from the GitHub REST API."""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ORG = os.environ.get("GITHUB_ORG", "LiSquaredLab")
TOKEN = os.environ["ORG_ACTIVITY_TOKEN"]
DAYS = 365
API = "https://api.github.com"


def get(path: str, params: dict[str, str] | None = None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {TOKEN}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "LiSquaredLab-org-activity",
    })
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response), response.headers


def pages(path: str, params: dict[str, str]):
    page = 1
    while True:
        data, _ = get(path, {**params, "page": str(page), "per_page": "100"})
        if not data:
            return
        yield from data
        if len(data) < 100:
            return
        page += 1


def main() -> None:
    today = dt.date.today()
    start = today - dt.timedelta(days=DAYS - 1)
    dates = [start + dt.timedelta(days=i) for i in range(DAYS)]
    commits, prs, issues = Counter(), Counter(), Counter()

    repos = pages(f"/orgs/{ORG}/repos", {"type": "all", "sort": "full_name"})
    for repo in repos:
        full_name = repo["full_name"]
        for commit in pages(f"/repos/{full_name}/commits", {"since": f"{start}T00:00:00Z"}):
            stamp = (commit.get("commit", {}).get("author", {}).get("date") or "")[:10]
            if stamp:
                commits[stamp] += 1
        for pr in pages(f"/repos/{full_name}/pulls", {"state": "all", "sort": "created", "direction": "asc"}):
            stamp = (pr.get("created_at") or "")[:10]
            if stamp >= str(start):
                prs[stamp] += 1
        for issue in pages(f"/repos/{full_name}/issues", {"state": "all", "sort": "created", "direction": "asc"}):
            if "pull_request" in issue:
                continue
            stamp = (issue.get("created_at") or "")[:10]
            if stamp >= str(start):
                issues[stamp] += 1

    values = [{"date": str(day), "commits": commits[str(day)], "prs": prs[str(day)], "issues": issues[str(day)]} for day in dates]
    Path("assets/org-activity.json").write_text(json.dumps(values, indent=2) + "\n")
    make_svg(values, Path("assets/org-activity.svg"))


def make_svg(values: list[dict[str, int]], output: Path) -> None:
    width, height, pad = 1000, 300, 36
    total = [v["commits"] + v["prs"] + v["issues"] for v in values]
    maximum = max(total, default=1) or 1
    def points(series):
        return " ".join(f"{pad + i * (width - 2 * pad) / (len(series) - 1):.1f},{height-pad - n / maximum * (height-2*pad):.1f}" for i, n in enumerate(series))
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img">',
             '<title>LiSquaredLab contribution history (last 365 days)</title>',
             '<rect width="100%" height="100%" rx="18" fill="#fff7fb"/>',
             '<text x="36" y="28" font-family="sans-serif" font-size="16" font-weight="600" fill="#6d28d9">LiSquaredLab · contribution history</text>']
    for color, key in (("#8b5cf6", "commits"), ("#f472b6", "prs"), ("#fb7185", "issues")):
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="{points([v[key] for v in values])}"/>')
    lines += ['<text x="36" y="286" font-family="sans-serif" font-size="12" fill="#6b7280">365 days</text>',
              '<text x="720" y="286" font-family="sans-serif" font-size="12" fill="#8b5cf6">● commits</text>',
              '<text x="810" y="286" font-family="sans-serif" font-size="12" fill="#f472b6">● PRs</text>',
              '<text x="870" y="286" font-family="sans-serif" font-size="12" fill="#fb7185">● issues</text>', '</svg>']
    output.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
