"""GitHub repository as a content source — for "repo know-how" reels.

Fetches metadata and README for a repo and reduces it to the facts a short
actually needs: what it is, how much traction it has, how fast it got there,
and what is actually inside it.

No auth required for public repos. Unauthenticated GitHub API allows 60
requests/hour per IP, which is ample for a few reels a day; set GITHUB_TOKEN
to raise it if the pipeline ever batches.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_API = "https://api.github.com/repos/{owner}/{repo}"
_RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"

# GitHub serves the API fine to default agents, but raw.githubusercontent can be
# fronted by protections that reject them — send a browser UA to both, same
# lesson as the Pexels Cloudflare 1010 block.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class GitHubRepoError(RuntimeError):
    """Raised when a repo cannot be read."""


@dataclass
class RepoFacts:
    """The reducible facts of a repository, ready for a script."""

    full_name: str
    description: str
    stars: int
    forks: int
    open_issues: int
    watchers: int
    created_at: str
    pushed_at: str
    topics: list[str] = field(default_factory=list)
    license: Optional[str] = None
    homepage: Optional[str] = None
    default_branch: str = "main"
    readme: str = ""
    categories: list[tuple[str, int]] = field(default_factory=list)
    total_entries: int = 0

    @property
    def age_days(self) -> int:
        created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        return max(1, (datetime.now(timezone.utc) - created).days)

    @property
    def stars_per_day(self) -> float:
        return round(self.stars / self.age_days, 1)

    def summary(self) -> str:
        """A compact brief for the intelligence layer.

        Deliberately facts-only. Any framing ("exploded", "took off") is the
        script writer's job, and inventing it here would launder opinion into
        something that reads like source data.
        """
        months = self.age_days / 30.44
        lines = [
            f"REPOSITORY: {self.full_name}",
            f"DESCRIPTION: {self.description}",
            f"STARS: {self.stars:,}",
            f"FORKS: {self.forks:,}",
            f"WATCHERS: {self.watchers:,}",
            f"OPEN ISSUES: {self.open_issues:,}",
            f"CREATED: {self.created_at[:10]}  ({self.age_days} days ago, ~{months:.1f} months)",
            f"LAST PUSH: {self.pushed_at[:10]}",
            f"AVERAGE STARS PER DAY SINCE CREATION: {self.stars_per_day}",
            f"LICENSE: {self.license or 'none declared'}",
            f"TOPICS: {', '.join(self.topics) if self.topics else 'none'}",
        ]
        if self.total_entries:
            lines.append(f"LINKED ENTRIES IN README: {self.total_entries}")
        if self.categories:
            lines.append("CATEGORIES (entries each):")
            for name, n in self.categories:
                lines.append(f"  - {name}: {n}")
        if self.readme:
            lines.append("\nREADME (truncated):\n" + self.readme[:6000])
        return "\n".join(lines)


def _get(url: str, *, accept: str = "application/vnd.github+json") -> bytes:
    headers = {"User-Agent": _UA, "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise GitHubRepoError(
                f"GitHub returned 403 for {url} — likely the 60/hour "
                f"unauthenticated rate limit. Set GITHUB_TOKEN to raise it."
            ) from exc
        raise GitHubRepoError(f"GitHub returned {exc.code} for {url}") from exc
    except urllib.error.URLError as exc:
        raise GitHubRepoError(f"cannot reach GitHub: {exc}") from exc


def parse_repo_url(url: str) -> tuple[str, str]:
    """Accept a full URL or an ``owner/repo`` shorthand."""
    m = re.search(r"github\.com/([^/\s]+)/([^/\s#?]+)", url)
    if m:
        return m.group(1), m.group(2).removesuffix(".git")
    parts = url.strip().strip("/").split("/")
    if len(parts) == 2 and all(parts):
        return parts[0], parts[1]
    raise GitHubRepoError(f"cannot parse a GitHub owner/repo from {url!r}")


def _readme_structure(readme: str) -> tuple[list[tuple[str, int]], int]:
    """Count linked list entries per '###' section.

    An awesome-list's real shape is its category sizes, and that is usually the
    most interesting fact about it — far more than the raw README length.
    """
    cats: list[tuple[str, int]] = []
    sections = re.split(r"^### ", readme, flags=re.M)
    for s in sections[1:]:
        name = s.split("\n", 1)[0].strip()
        body = s.split("\n##", 1)[0]
        n = len(re.findall(r"^\s*[-*]\s+\[", body, re.M))
        if n:
            cats.append((name, n))
    total = len(re.findall(r"^\s*[-*]\s+\[[^\]]+\]\([^)]+\)", readme, re.M))
    return cats, total


def fetch_repo(url: str, *, include_readme: bool = True) -> RepoFacts:
    """Fetch a repository's facts. Raises GitHubRepoError on failure."""
    owner, repo = parse_repo_url(url)
    logger.info("Fetching GitHub repo %s/%s", owner, repo)
    meta = json.loads(_get(_API.format(owner=owner, repo=repo)))

    lic = (meta.get("license") or {})
    facts = RepoFacts(
        full_name=meta["full_name"],
        description=meta.get("description") or "",
        stars=meta.get("stargazers_count", 0),
        forks=meta.get("forks_count", 0),
        open_issues=meta.get("open_issues_count", 0),
        watchers=meta.get("subscribers_count", 0),
        created_at=meta.get("created_at", ""),
        pushed_at=meta.get("pushed_at", ""),
        topics=meta.get("topics") or [],
        license=lic.get("spdx_id") if lic.get("spdx_id") != "NOASSERTION" else lic.get("name"),
        homepage=meta.get("homepage") or None,
        default_branch=meta.get("default_branch", "main"),
    )

    if include_readme:
        # The default branch is NOT always "main" — this repo is on "master",
        # and guessing wrong returns a 404 that looks like a missing README.
        try:
            raw = _get(
                _RAW.format(owner=owner, repo=repo, branch=facts.default_branch),
                accept="text/plain",
            )
            facts.readme = raw.decode("utf-8", "replace")
            facts.categories, facts.total_entries = _readme_structure(facts.readme)
        except GitHubRepoError as exc:
            logger.warning("README unavailable for %s: %s", facts.full_name, exc)

    logger.info(
        "%s: %d stars, %d forks, %d README entries across %d categories",
        facts.full_name, facts.stars, facts.forks,
        facts.total_entries, len(facts.categories),
    )
    return facts
