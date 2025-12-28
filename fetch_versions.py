#!/usr/bin/env python3
"""
Fetch all repos from the GitHub actions organization and their tags via the API,
and generate a versions.txt file with the latest vINTEGER tags.

No git cloning required - uses GitHub REST API only.

Repos known to have no vINTEGER tags are cached in unversioned.txt to skip
API calls on future runs.
"""

import json
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.resolve()
VERSIONS_FILE = SCRIPT_DIR / "versions.txt"
UNVERSIONED_FILE = SCRIPT_DIR / "unversioned.txt"
ORG_NAME = "actions"
GITHUB_API_URL = "https://api.github.com"


def load_unversioned() -> set[str]:
    """Load the set of repos known to have no vINTEGER tags."""
    if not UNVERSIONED_FILE.exists():
        return set()
    return set(line.strip() for line in UNVERSIONED_FILE.read_text().splitlines() if line.strip())


def save_unversioned(repos: set[str]) -> None:
    """Save the set of repos known to have no vINTEGER tags."""
    with open(UNVERSIONED_FILE, "w") as f:
        for repo_name in sorted(repos):
            f.write(f"{repo_name}\n")


def fetch_repos(org: str) -> list[dict]:
    """Fetch all repos for an organization using curl."""
    repos = []
    page = 1
    per_page = 100

    while True:
        url = f"{GITHUB_API_URL}/orgs/{org}/repos?per_page={per_page}&page={page}"
        result = subprocess.run(
            ["curl", "-s", "-H", "Accept: application/vnd.github+json", url],
            capture_output=True,
            text=True,
            check=True,
        )

        page_repos = json.loads(result.stdout)

        if not page_repos:
            break

        repos.extend(page_repos)

        if len(page_repos) < per_page:
            break

        page += 1

    return repos


def fetch_tags(org: str, repo_name: str) -> list[str]:
    """Fetch all tags for a repository using the GitHub API."""
    tags = []
    page = 1
    per_page = 100

    while True:
        url = f"{GITHUB_API_URL}/repos/{org}/{repo_name}/tags?per_page={per_page}&page={page}"
        result = subprocess.run(
            ["curl", "-s", "-H", "Accept: application/vnd.github+json", url],
            capture_output=True,
            text=True,
            check=True,
        )

        page_tags = json.loads(result.stdout)

        # Handle error responses (e.g., rate limiting)
        if isinstance(page_tags, dict) and "message" in page_tags:
            print(f"  API error for {repo_name}: {page_tags['message']}", file=sys.stderr)
            break

        if not page_tags:
            break

        tags.extend(tag["name"] for tag in page_tags)

        if len(page_tags) < per_page:
            break

        page += 1

    return tags


def get_latest_version_tag(tags: list[str]) -> str | None:
    """Get the latest vINTEGER tag from a list of tags."""
    # Filter to vINTEGER tags (e.g., v1, v2, v10)
    version_pattern = re.compile(r"^v(\d+)$")
    version_tags = []

    for tag in tags:
        match = version_pattern.match(tag.strip())
        if match:
            version_tags.append((int(match.group(1)), tag.strip()))

    if not version_tags:
        return None

    # Sort by version number descending and return the latest
    version_tags.sort(reverse=True, key=lambda x: x[0])
    return version_tags[0][1]


def main():
    """Main function to fetch repos, get tags via API, and generate versions.txt."""
    # Load cached unversioned repos
    unversioned = load_unversioned()
    if unversioned:
        print(f"Loaded {len(unversioned)} known unversioned repos from cache")

    print(f"Fetching repos for {ORG_NAME}...")
    repos = fetch_repos(ORG_NAME)
    print(f"Found {len(repos)} repos")

    versions = []
    new_unversioned = set()

    for repo in repos:
        repo_name = repo["name"]

        # Skip repos known to have no vINTEGER tags
        if repo_name in unversioned:
            print(f"Skipping {repo_name} (cached as unversioned)")
            new_unversioned.add(repo_name)
            continue

        print(f"Fetching tags for {repo_name}...", end=" ")
        tags = fetch_tags(ORG_NAME, repo_name)
        latest_tag = get_latest_version_tag(tags)

        if latest_tag:
            versions.append((repo_name, latest_tag))
            print(f"{latest_tag}")
        else:
            print("no vINTEGER tag")
            new_unversioned.add(repo_name)

    # Sort alphabetically by repo name
    versions.sort(key=lambda x: x[0].lower())

    # Write versions.txt
    with open(VERSIONS_FILE, "w") as f:
        for repo_name, tag in versions:
            f.write(f"{ORG_NAME}/{repo_name}@{tag}\n")

    # Update unversioned.txt
    save_unversioned(new_unversioned)

    print(f"\nWrote {len(versions)} versions to {VERSIONS_FILE}")
    print(f"Cached {len(new_unversioned)} unversioned repos to {UNVERSIONED_FILE}")


if __name__ == "__main__":
    main()
