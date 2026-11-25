#!/usr/bin/env python3
"""Shared helper: commits authored by a user in their private repositories.

Uses the REST API because GitHub's public contribution calendar does not
include private activity unless the profile setting is enabled. The token must
have access to the private repositories (`repo` scope or equivalent).
"""
from __future__ import annotations

import http.client
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime

API = "https://api.github.com"


def api_get(path: str, tok: str, attempts: int = 3):
    url = path if path.startswith("http") else API + path
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {tok}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "eliaselp-profile-activity",
        },
    )
    last_error = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                raw = response.read()
                return json.loads(raw), response.headers
        except (urllib.error.URLError, http.client.IncompleteRead, TimeoutError,
                ConnectionError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise last_error


def fetch_private_daily(user: str, tok: str, start: datetime, end: datetime):
    """Return ({'YYYY-MM-DD': commits}, number_of_private_repos)."""
    daily = defaultdict(int)
    seen: set[str] = set()
    repos, _ = api_get("/user/repos?affiliation=owner&per_page=100&sort=pushed", tok)
    private_repos = [repo for repo in repos if repo.get("private")]
    if not private_repos:
        print("warning: no private repositories visible to this token", file=sys.stderr)

    since = start.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = end.strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo in private_repos:
        url = (
            f"{API}/repos/{repo['full_name']}/commits"
            f"?author={user}&since={since}&until={until}&per_page=100"
        )
        while url:
            try:
                commits, headers = api_get(url, tok)
            except urllib.error.HTTPError as exc:
                if exc.code not in (404, 409):
                    print(f"warning: {repo['full_name']} commits: HTTP {exc.code}",
                          file=sys.stderr)
                break
            for commit in commits:
                sha = commit.get("sha")
                if sha in seen:
                    continue
                seen.add(sha)
                date = commit["commit"]["author"]["date"][:10]
                daily[date] += 1
            link = headers.get("Link", "")
            match = re.search(r'<([^>]+)>;\s*rel="next"', link)
            url = match.group(1) if match else None
    return daily, len(private_repos)
