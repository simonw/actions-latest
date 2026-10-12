#!/usr/bin/env python3
"""
Fetch all repos from the GitHub actions organization and their tags via the API,
and generate a versions.txt file with the latest vINTEGER tags.

No git cloning required - uses GitHub REST API only.

Repos with no vINTEGER tags are recorded in unversioned.txt and checked again on every run.
"""

import json
import os
import re
from pathlib import Path
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).parent.resolve()
VERSIONS_FILE = SCRIPT_DIR / "versions.txt"
UNVERSIONED_FILE = SCRIPT_DIR / "unversioned.txt"
README_FILE = SCRIPT_DIR / "README.md"

# Markers for the README section
README_START_MARKER = "<!-- VERSIONS_START -->"
README_END_MARKER = "<!-- VERSIONS_END -->"
ORG_NAME = "actions"
GITHUB_API_URL = "https://api.github.com"


def save_unversioned(repos: set[str]) -> None:
    """Save the set of repos known to have no vINTEGER tags."""
    with open(UNVERSIONED_FILE, "w") as f:
        for repo_name in sorted(repos):
            f.write(f"{repo_name}\n")


def update_readme(versions_content: str) -> None:
    """Update the README.md with the latest versions in a fenced code block."""
    if not README_FILE.exists():
        print(f"Warning: {README_FILE} not found, skipping README update")
        return

    readme_text = README_FILE.read_text()

    # Build the new section content
    new_section = f"""{README_START_MARKER}
## Latest versions

```
{versions_content}```
{README_END_MARKER}"""

    # Check if markers already exist
    if README_START_MARKER in readme_text and README_END_MARKER in readme_text:
        # Replace existing section
        pattern = re.compile(
            re.escape(README_START_MARKER) + r".*?" + re.escape(README_END_MARKER),
            re.DOTALL
        )
        new_readme = pattern.sub(new_section, readme_text)
    else:
        # Append to end of file
        new_readme = readme_text.rstrip() + "\n\n" + new_section + "\n"

    README_FILE.write_text(new_readme)
    print(f"Updated {README_FILE} with latest versions")


def fetch_page(url: str) -> list[dict]:
    """Fetch an API page, raising on HTTP errors or unexpected responses."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError(f"Expected a list from {url}, got: {data!r}")
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise ValueError(f"Invalid item from {url}: {item!r}")
    return data


def fetch_repos(org: str) -> list[dict]:
    """Fetch all repos for an organization using the GitHub API."""
    repos = []
    page = 1
    per_page = 100

    while True:
        url = f"{GITHUB_API_URL}/orgs/{org}/repos?per_page={per_page}&page={page}"
        page_repos = fetch_page(url)

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
        page_tags = fetch_page(url)

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
    print(f"Fetching repos for {ORG_NAME}...")
    repos = fetch_repos(ORG_NAME)
    print(f"Found {len(repos)} repos")

    versions = []
    new_unversioned = set()

    for repo in repos:
        repo_name = repo["name"]

        print(f"Fetching tags for {repo_name}...", end=" ")
        tags = fetch_tags(ORG_NAME, repo_name)
        latest_tag = get_latest_version_tag(tags)

        if latest_tag:
            versions.append((repo_name, latest_tag))
            print(f"{latest_tag}")
        else:
            print("no vINTEGER tag")
            new_unversioned.add(repo_name)

    # Preserve all existing output files if the API yields no usable versions.
    if not versions:
        raise ValueError("No version tags found; refusing to overwrite existing files")

    # Sort alphabetically by repo name
    versions.sort(key=lambda x: x[0].lower())

    # Build versions content
    versions_content = "\n".join(
        f"{ORG_NAME}/{repo_name}@{tag}" for repo_name, tag in versions
    ) + "\n"

    # Write versions.txt
    with open(VERSIONS_FILE, "w") as f:
        f.write(versions_content)

    # Update README.md with the versions
    update_readme(versions_content)

    # Update unversioned.txt
    save_unversioned(new_unversioned)

    print(f"\nWrote {len(versions)} versions to {VERSIONS_FILE}")
    print(f"Recorded {len(new_unversioned)} unversioned repos to {UNVERSIONED_FILE}")


if __name__ == "__main__":
    main()
