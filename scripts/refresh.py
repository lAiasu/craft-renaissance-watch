#!/usr/bin/env python3
"""Refresh a curated Craft GitHub watchlist and discover potential new projects.

No external dependencies; meant to run in GitHub Actions each day.
"""
import datetime as dt
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.datetime.now(dt.timezone.utc)
DATE = TODAY.strftime("%Y-%m-%d")
HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "craft-renaissance-watch/1.0",
    "X-GitHub-Api-Version": "2022-11-28",
}
if os.environ.get("GITHUB_TOKEN"):
    HEADERS["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]

GROUPS = [
    "Creative applications",
    "Office, CAD and audio",
    "Core project and infrastructure",
    "Independent creative experiments",
    "Community ecosystem",
    "Separate game-crossover wave",
]
ORDER = {"High": 0, "Medium": 1, "Low": 2}


def api(path, params=None):
    url = "https://api.github.com/" + path.lstrip("/")
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers=HEADERS)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError) as exc:
            if attempt == 2 or (isinstance(exc, HTTPError) and exc.code in (401, 403, 404, 422)):
                raise RuntimeError(f"{url}: {exc}") from exc
            time.sleep(2 * (attempt + 1))


def load(path, default):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path, text):
    (ROOT / path).write_text(text, encoding="utf-8")


def safe(s):
    return str(s or "").replace("|", r"\|").replace("\n", " ").strip()


def date(s):
    return (s or "")[:10] or "—"


def week_delta(old, now, cutoff):
    eligible = [x for x in old if x.get("date", "") <= cutoff]
    if not eligible:
        return "—"
    baseline = eligible[-1]["stars"]
    delta = now - baseline
    return f"+{delta}" if delta >= 0 else str(delta)


def refresh():
    catalog = load("projects.json", [])
    history = load("history.json", {})
    results = []
    errors = []
    cutoff = (TODAY - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    for entry in catalog:
        try:
            data = api("repos/" + entry["repo"])
            if data.get("fork") or data.get("archived"):
                errors.append(entry["repo"] + ": is fork or archived; review manually")
            stars = data["stargazers_count"]
            trail = history.get(entry["repo"], [])
            growth = week_delta(trail, stars, cutoff)
            if not trail or trail[-1]["date"] != DATE:
                trail.append({"date": DATE, "stars": stars})
            else:
                trail[-1]["stars"] = stars
            history[entry["repo"]] = [
                item for item in trail
                if item["date"] >= (TODAY - dt.timedelta(days=40)).strftime("%Y-%m-%d")
            ]
            results.append({**entry, "stars": stars, "forks": data["forks_count"],
                            "pushed": date(data["pushed_at"]), "created": date(data["created_at"]),
                            "growth": growth})
        except Exception as exc:
            errors.append(entry["repo"] + ": " + str(exc))
            results.append({**entry, "stars": None, "forks": None,
                            "pushed": "unavailable", "created": "—", "growth": "—"})

    lines = [
        "# Craft Renaissance — GitHub Watchlist",
        "",
        f"**{len(catalog)} curated projects · {len(GROUPS)} categories · Updated {TODAY.strftime('%Y-%m-%d %H:%M')} UTC**",
        "",
        "A private, categorized tracker for the sudden wave of *-Craft applications and adjacent experiments.",
        "This list **does not star, fork or subscribe to** any of the tracked repositories.",
        "",
        "> **Editorial criteria:** Original and non-trivial implementation, meaningful documented scope,",
        "> and evidence of recent activity. Excludes straightforward forks, empty/zero-star uploads,",
        "> lookalike download sites and unrelated Minecraft projects. Projects are **not audited**;",
        "> feature lists are developer claims, not independent validation.",
        "",
        "### Jump to a category",
        "",
    ]
    for group in GROUPS:
        slug = re.sub(r"[^a-z0-9 -]", "", group.lower()).replace(" ", "-")
        lines.append(f"- [{group}](#{slug})")
    lines += [
        "",
        "### Reading the tracker",
        "",
        "**Priority:** High = most worth following; Medium = credible early implementation;",
        "Low = supporting or speculative project. The **7d stars** column becomes useful",
        "after seven days of automated snapshots. **Last push** is GitHub repository activity,",
        "not proof of feature completeness or code quality.",
        "",
    ]
    for group in GROUPS:
        subset = [r for r in results if r["group"] == group]
        subset.sort(key=lambda r: (ORDER.get(r["priority"], 3), -(r["stars"] or 0), r["repo"].lower()))
        lines += [f"## {group}", "", "| Repository | What it is | Priority | Stars | 7d stars | Last push | Why track |",
                  "|---|---|:---:|---:|---:|:---:|---|"]
        for r in subset:
            label = r["repo"].split("/", 1)[1]
            stars = f'{r["stars"]:,}' if r["stars"] is not None else "—"
            lines.append(
                f'| [{safe(label)}](https://github.com/{r["repo"]}) | {safe(r["target"])} '
                f'| {r["priority"]} | {stars} | {r["growth"]} | {r["pushed"]} '
                f'| {safe(r["watch"])} |'
            )
        lines.append("")
    lines += [
        "## Continuing coverage",
        "",
        "- [New discoveries awaiting manual review](CANDIDATES.md) — automatically searched, **not endorsed**.",
        "- [Catalog and priority labels](projects.json) — edit this file to curate/add/remove projects.",
        "- [Historical star snapshots](history.json) — 40-day rolling history.",
        "- [Update workflow](.github/workflows/refresh.yml) — runs daily and can be run manually.",
        "",
        "For additional searching, see [recent original Craft-named repositories](https://github.com/search?q=craft+in%3Aname+created%3A%3E%3D2026-09-29+fork%3Afalse&type=repositories).",
        "A private repository README is available only when signed in to the GitHub account with access.",
        "",
        f"*Last refresh: {TODAY.isoformat(timespec='seconds')}.*",
        "",
    ]
    if errors:
        lines += ["### Refresh warnings", "", *("- " + safe(err) for err in errors), ""]
    write("README.md", "\n".join(lines))
    write("history.json", json.dumps(history, indent=2, sort_keys=True) + "\n")
    print(f"Updated {len(results)} tracked repos; {len(errors)} fetch warnings")
    discover(catalog)


def discover(catalog):
    known = {p["repo"].lower() for p in catalog}
    try:
        result = api("search/repositories", {
            "q": "craft in:name created:>=2026-09-29 stars:>=3 fork:false",
            "sort": "updated", "order": "desc", "per_page": 100,
        })
    except Exception as exc:
        print("Discovery skipped:", exc)
        return

    pattern = re.compile(
        r"artcraft|craft apps|crafting apps|photoshop|illustrator|after effects|"
        r"adobe animate|premiere|lightroom|acrobat|creative app|office suite|"
        r"word processor|spreadsheet|powerpoint|cad editor|"
        r"photo editor|vector editor|material editor|animation editor|"
        r"minecraft.+(?:skyrim|fallout|sekiro|gta|team fortress|half.life|"
        r"zomboid|portal|mario|peak)|(?:skyrim|fallout|sekiro|gta|"
        r"team fortress|half.life|zomboid|portal|mario|peak).+minecraft",
        re.IGNORECASE,
    )
    matches = []
    tracked_names = {p["repo"].split("/")[-1].lower() for p in catalog}
    spam = re.compile(
        r"official free download|download:|cracked|keygen|serial key|"
        r"artcraft photoshop download|photocraft v[0-9]+.*local zip",
        re.IGNORECASE,
    )
    for repo in result.get("items", []):
        name = repo["full_name"]
        short_name = name.split("/")[-1].lower()
        if (name.lower() in known or repo.get("fork") or repo.get("archived")
                or short_name in tracked_names):
            continue
        desc = repo.get("description") or ""
        if spam.search(desc) or not pattern.search(desc):
            continue
        matches.append(repo)
    matches.sort(key=lambda r: (-r["stargazers_count"], r["full_name"].lower()))
    rows = [
        "# Possible New Craft Projects — Unreviewed",
        "",
        f"Discovery scan: **{TODAY.strftime('%Y-%m-%d %H:%M')} UTC**.",
        "",
        "Automated search for newly created, non-fork, Craft-named repositories with **3+ stars**",
        "and a relevant description. **These are discovery leads, not recommendations.**",
        "A project belongs in [the main tracker](README.md) only after checking that it has",
        "substantial original source code, meaningful documentation and recent development.",
        "Search only inspects GitHub's 100 most recently updated matching results;",
        "some projects will be missed. Never run unofficial binaries solely because they appear here.",
        "",
        "| Candidate | Stars | Created | Description |",
        "|---|---:|:---:|---|",
    ]
    for r in matches[:35]:
        rows.append(
            f'| [{r["full_name"]}](https://github.com/{r["full_name"]}) '
            f'| {r["stargazers_count"]:,} | {date(r["created_at"])} '
            f'| {safe(r.get("description"))} |'
        )
    if not matches:
        rows.append("| No new matches in this scan | — | — | — |")
    rows += ["", f"*Search returned {len(result.get('items', []))} repositories; {len(matches)} matched the descriptive filter.*", ""]
    write("CANDIDATES.md", "\n".join(rows))


if __name__ == "__main__":
    refresh()
