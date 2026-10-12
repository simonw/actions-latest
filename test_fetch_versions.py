#!/usr/bin/env python3
"""
Unit tests for fetch_versions.py
"""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import fetch_versions


def api_response(data):
    return io.BytesIO(json.dumps(data).encode())


class TestFetchPage(unittest.TestCase):
    def setUp(self):
        self.url = "https://api.github.com/repos/actions/checkout/tags"
        self.enterContext(patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": ""}))

    @patch("fetch_versions.urlopen")
    def test_authentication(self, mock_open):
        for env, expected_token in [
            ({"GITHUB_TOKEN": "github-token", "GH_TOKEN": "gh-token"}, "github-token"),
            ({"GITHUB_TOKEN": "", "GH_TOKEN": "gh-token"}, "gh-token"),
            ({"GITHUB_TOKEN": "", "GH_TOKEN": ""}, None),
        ]:
            with self.subTest(env=env), patch.dict(os.environ, env):
                mock_open.return_value = api_response([{"name": "v1"}])
                self.assertEqual(fetch_versions.fetch_page(self.url), [{"name": "v1"}])
                request = mock_open.call_args.args[0]
                self.assertEqual(request.full_url, self.url)
                self.assertEqual(request.get_header("Accept"), "application/vnd.github+json")
                self.assertEqual(
                    request.get_header("Authorization"),
                    f"Bearer {expected_token}" if expected_token else None,
                )

    @patch("fetch_versions.urlopen")
    def test_http_and_network_errors_propagate(self, mock_open):
        errors = [HTTPError(self.url, status, "API failure", {}, None) for status in (403, 429, 500)]
        for error in errors:
            self.addCleanup(error.close)
        errors.extend([URLError("Connection failed"), TimeoutError("Timed out")])
        for error in errors:
            with self.subTest(error=error):
                mock_open.side_effect = error
                with self.assertRaises(type(error)):
                    fetch_versions.fetch_page(self.url)

    @patch("fetch_versions.urlopen")
    def test_unexpected_response_is_an_error(self, mock_open):
        for data in [{"message": "API rate limit exceeded"}, None, "oops", [{}], [{"name": None}], ["v1"]]:
            with self.subTest(data=data):
                mock_open.return_value = api_response(data)
                with self.assertRaises(ValueError):
                    fetch_versions.fetch_page(self.url)

    @patch("fetch_versions.urlopen")
    def test_invalid_json_is_an_error(self, mock_open):
        mock_open.return_value = io.BytesIO(b"<html>Service unavailable</html>")
        with self.assertRaises(ValueError):
            fetch_versions.fetch_page(self.url)


class TestFetchRepos(unittest.TestCase):
    @patch("fetch_versions.urlopen")
    def test_fetch_repos_single_page(self, mock_open):
        repos = [{"name": "setup-python"}, {"name": "setup-node"}]
        mock_open.return_value = api_response(repos)
        self.assertEqual(fetch_versions.fetch_repos("actions"), repos)

    @patch("fetch_versions.urlopen")
    def test_fetch_repos_multiple_pages(self, mock_open):
        first_page = [{"name": f"repo-{i}"} for i in range(100)]
        second_page = [{"name": "repo-100"}]
        mock_open.side_effect = [api_response(first_page), api_response(second_page)]
        self.assertEqual(fetch_versions.fetch_repos("actions"), first_page + second_page)
        self.assertEqual(
            [call.args[0].full_url for call in mock_open.call_args_list],
            [f"https://api.github.com/orgs/actions/repos?per_page=100&page={page}" for page in (1, 2)],
        )

    @patch("fetch_versions.urlopen")
    def test_fetch_repos_empty(self, mock_open):
        mock_open.return_value = api_response([])
        self.assertEqual(fetch_versions.fetch_repos("empty-org"), [])


class TestFetchTags(unittest.TestCase):
    @patch("fetch_versions.urlopen")
    def test_fetch_tags_single_page(self, mock_open):
        mock_open.return_value = api_response([{"name": tag} for tag in ("v1", "v2", "v3")])
        self.assertEqual(fetch_versions.fetch_tags("actions", "setup-python"), ["v1", "v2", "v3"])

    @patch("fetch_versions.urlopen")
    def test_fetch_tags_multiple_pages(self, mock_open):
        mock_open.side_effect = [
            api_response([{"name": f"v{i}"} for i in range(100)]),
            api_response([{"name": "v100"}]),
        ]
        self.assertEqual(fetch_versions.fetch_tags("actions", "big-repo"), [f"v{i}" for i in range(101)])
        self.assertEqual(
            [call.args[0].full_url for call in mock_open.call_args_list],
            [f"https://api.github.com/repos/actions/big-repo/tags?per_page=100&page={page}" for page in (1, 2)],
        )

    @patch("fetch_versions.urlopen")
    def test_fetch_tags_empty(self, mock_open):
        mock_open.return_value = api_response([])
        self.assertEqual(fetch_versions.fetch_tags("actions", "no-tags-repo"), [])


class TestUnversionedReport(unittest.TestCase):
    def test_save_unversioned(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            unversioned_file = Path(tmpdir) / "unversioned.txt"
            with patch.object(fetch_versions, "UNVERSIONED_FILE", unversioned_file):
                fetch_versions.save_unversioned({"zebra", "alpha", "mango"})
            self.assertEqual(unversioned_file.read_text(), "alpha\nmango\nzebra\n")


class TestUpdateReadme(unittest.TestCase):
    """Tests for updating the README versions block."""

    def test_update_readme_replaces_only_marked_section(self):
        """Test replacing the generated block while preserving surrounding text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_file = Path(tmpdir) / "README.md"
            readme_file.write_text(
                "Intro text\n\n"
                f"{fetch_versions.README_START_MARKER}\n"
                "## Latest versions\n\n"
                "```\n"
                "actions/checkout@v5\n"
                "```\n"
                f"{fetch_versions.README_END_MARKER}\n\n"
                "Footer text\n"
            )

            with patch.object(fetch_versions, "README_FILE", readme_file):
                fetch_versions.update_readme(
                    "actions/checkout@v6\n"
                    "actions/upload-artifact@v7\n"
                )

            self.assertEqual(
                readme_file.read_text(),
                "Intro text\n\n"
                f"{fetch_versions.README_START_MARKER}\n"
                "## Latest versions\n\n"
                "```\n"
                "actions/checkout@v6\n"
                "actions/upload-artifact@v7\n"
                "```\n"
                f"{fetch_versions.README_END_MARKER}\n\n"
                "Footer text\n"
            )

    def test_update_readme_appends_section_when_markers_are_missing(self):
        """Test adding the generated block to a README without markers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            readme_file = Path(tmpdir) / "README.md"
            readme_file.write_text("Intro text\n")

            with patch.object(fetch_versions, "README_FILE", readme_file):
                fetch_versions.update_readme("actions/checkout@v6\n")

            self.assertEqual(
                readme_file.read_text(),
                "Intro text\n\n"
                f"{fetch_versions.README_START_MARKER}\n"
                "## Latest versions\n\n"
                "```\n"
                "actions/checkout@v6\n"
                "```\n"
                f"{fetch_versions.README_END_MARKER}\n"
            )


class TestGetLatestVersionTag(unittest.TestCase):
    """Tests for the get_latest_version_tag function."""

    def test_get_latest_version_tag(self):
        """Test getting the latest vINTEGER tag."""
        tags = ["v1", "v2", "v3", "v10", "v2.1.0"]
        result = fetch_versions.get_latest_version_tag(tags)

        self.assertEqual(result, "v10")

    def test_get_latest_version_tag_no_vinteger(self):
        """Test when repo has no vINTEGER tags."""
        tags = ["v1.0.0", "v2.0.0", "release-1"]
        result = fetch_versions.get_latest_version_tag(tags)

        self.assertIsNone(result)

    def test_get_latest_version_tag_empty(self):
        """Test when repo has no tags at all."""
        tags = []
        result = fetch_versions.get_latest_version_tag(tags)

        self.assertIsNone(result)

    def test_version_ordering(self):
        """Test that version ordering is numeric, not lexicographic."""
        tags = ["v9", "v10", "v2", "v1"]
        result = fetch_versions.get_latest_version_tag(tags)

        # v10 should be latest, not v9 (which would be latest lexicographically)
        self.assertEqual(result, "v10")


class TestMain(unittest.TestCase):
    """Exercise real fetching and file writes with only HTTP responses mocked."""

    def setUp(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.versions = directory / "versions.txt"
        self.readme = directory / "README.md"
        self.unversioned = directory / "unversioned.txt"
        self.versions.write_text("actions/setup-python@v5\n")
        self.readme.write_text(
            "Intro\n\n<!-- VERSIONS_START -->\n"
            "## Latest versions\n\n```\nactions/setup-python@v5\n```\n"
            "<!-- VERSIONS_END -->\n"
        )
        # Reproduce a poisoned cache that previously prevented recovery.
        self.unversioned.write_text("setup-python\nsetup-node\nno-tags-repo\n")
        for name, path in [
            ("VERSIONS_FILE", self.versions),
            ("README_FILE", self.readme),
            ("UNVERSIONED_FILE", self.unversioned),
        ]:
            self.enterContext(patch.object(fetch_versions, name, path))
        self.enterContext(patch("sys.stdout", new=io.StringIO()))
        self.before = self.output_contents()

    def output_contents(self):
        return [path.read_bytes() for path in (self.versions, self.readme, self.unversioned)]

    @patch("fetch_versions.urlopen")
    def test_main_recovers_cached_repos_and_updates_all_outputs(self, mock_open):
        mock_open.side_effect = [
            api_response([{"name": "setup-python"}, {"name": "setup-node"}, {"name": "no-tags-repo"}]),
            api_response([{"name": "v5"}, {"name": "v6"}]),
            api_response([{"name": "v4"}]),
            api_response([]),
        ]
        fetch_versions.main()
        content = "actions/setup-node@v4\nactions/setup-python@v6\n"
        self.assertEqual(self.versions.read_text(), content)
        self.assertIn(f"```\n{content}```", self.readme.read_text())
        self.assertTrue(self.readme.read_text().startswith("Intro\n"))
        self.assertEqual(self.unversioned.read_text(), "no-tags-repo\n")
        self.assertEqual(mock_open.call_count, 4)

    @patch("fetch_versions.urlopen")
    def test_empty_results_preserve_all_outputs(self, mock_open):
        for pages in [[], [{"name": "checkout"}]]:
            with self.subTest(repos=pages):
                mock_open.side_effect = [api_response(pages), api_response([])]
                with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                    fetch_versions.main()
                self.assertEqual(self.output_contents(), self.before)

    @patch("fetch_versions.urlopen")
    def test_api_failures_preserve_all_outputs(self, mock_open):
        prefixes = [
            [],  # Repository listing fails immediately.
            [[{"name": f"repo-{i}"} for i in range(100)]],  # Second repository page fails.
            [[{"name": "checkout"}]],  # First tags request fails.
            [
                [{"name": "checkout"}, {"name": "setup-python"}],
                [{"name": "v6"}],
                [{"name": f"v{i}"} for i in range(100)],
            ],  # Tags pagination fails after finding usable versions.
        ]
        for prefix in prefixes:
            with self.subTest(prefix=prefix):
                error = HTTPError("https://api.github.com", 403, "API rate limit exceeded", {}, None)
                self.addCleanup(error.close)
                mock_open.side_effect = [api_response(page) for page in prefix] + [error]
                with self.assertRaises(HTTPError):
                    fetch_versions.main()
                self.assertEqual(self.output_contents(), self.before)

    @patch("fetch_versions.urlopen")
    def test_malformed_response_preserves_all_outputs(self, mock_open):
        mock_open.side_effect = [
            api_response([{"name": "checkout"}, {"name": "setup-python"}]),
            api_response([{"name": "v6"}]),
            api_response({"message": "API rate limit exceeded"}),
        ]
        with self.assertRaisesRegex(ValueError, "API rate limit exceeded"):
            fetch_versions.main()
        self.assertEqual(self.output_contents(), self.before)


class TestVersionPatternMatching(unittest.TestCase):
    """Tests for the version tag pattern matching."""

    def test_valid_version_tags(self):
        """Test that valid vINTEGER tags are matched."""
        import re

        pattern = re.compile(r"^v(\d+)$")

        valid_tags = ["v1", "v2", "v10", "v100", "v999"]
        for tag in valid_tags:
            self.assertIsNotNone(pattern.match(tag), f"{tag} should match")

    def test_invalid_version_tags(self):
        """Test that invalid tags are not matched."""
        import re

        pattern = re.compile(r"^v(\d+)$")

        invalid_tags = [
            "v1.0",
            "v1.0.0",
            "v1-beta",
            "1.0",
            "release-1",
            "v",
            "v1a",
            "V1",  # uppercase
            " v1",  # leading space
            "v1 ",  # trailing space
        ]
        for tag in invalid_tags:
            self.assertIsNone(pattern.match(tag), f"{tag} should not match")


if __name__ == "__main__":
    unittest.main()
