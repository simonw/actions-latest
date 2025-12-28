#!/usr/bin/env python3
"""
Unit tests for fetch_versions.py
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import fetch_versions


class TestFetchRepos(unittest.TestCase):
    """Tests for the fetch_repos function."""

    @patch("fetch_versions.subprocess.run")
    def test_fetch_repos_single_page(self, mock_run):
        """Test fetching repos when all fit on one page."""
        mock_repos = [
            {"name": "setup-python", "clone_url": "https://github.com/actions/setup-python.git"},
            {"name": "setup-node", "clone_url": "https://github.com/actions/setup-node.git"},
        ]

        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_repos),
            returncode=0,
        )

        repos = fetch_versions.fetch_repos("actions")

        self.assertEqual(len(repos), 2)
        self.assertEqual(repos[0]["name"], "setup-python")
        self.assertEqual(repos[1]["name"], "setup-node")

    @patch("fetch_versions.subprocess.run")
    def test_fetch_repos_multiple_pages(self, mock_run):
        """Test fetching repos when pagination is needed."""
        # First page - full page of 100 repos
        first_page = [{"name": f"repo-{i}", "clone_url": f"https://github.com/actions/repo-{i}.git"} for i in range(100)]
        # Second page - partial page (last page)
        second_page = [{"name": "repo-100", "clone_url": "https://github.com/actions/repo-100.git"}]

        mock_run.side_effect = [
            MagicMock(stdout=json.dumps(first_page), returncode=0),
            MagicMock(stdout=json.dumps(second_page), returncode=0),
        ]

        repos = fetch_versions.fetch_repos("actions")

        self.assertEqual(len(repos), 101)
        self.assertEqual(mock_run.call_count, 2)

    @patch("fetch_versions.subprocess.run")
    def test_fetch_repos_empty(self, mock_run):
        """Test fetching repos when org has no repos."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps([]),
            returncode=0,
        )

        repos = fetch_versions.fetch_repos("empty-org")

        self.assertEqual(len(repos), 0)


class TestFetchTags(unittest.TestCase):
    """Tests for the fetch_tags function."""

    @patch("fetch_versions.subprocess.run")
    def test_fetch_tags_single_page(self, mock_run):
        """Test fetching tags when all fit on one page."""
        mock_tags = [
            {"name": "v1"},
            {"name": "v2"},
            {"name": "v3"},
        ]

        mock_run.return_value = MagicMock(
            stdout=json.dumps(mock_tags),
            returncode=0,
        )

        tags = fetch_versions.fetch_tags("actions", "setup-python")

        self.assertEqual(len(tags), 3)
        self.assertEqual(tags, ["v1", "v2", "v3"])

    @patch("fetch_versions.subprocess.run")
    def test_fetch_tags_multiple_pages(self, mock_run):
        """Test fetching tags when pagination is needed."""
        # First page - full page of 100 tags
        first_page = [{"name": f"v{i}"} for i in range(100)]
        # Second page - partial page (last page)
        second_page = [{"name": "v100"}]

        mock_run.side_effect = [
            MagicMock(stdout=json.dumps(first_page), returncode=0),
            MagicMock(stdout=json.dumps(second_page), returncode=0),
        ]

        tags = fetch_versions.fetch_tags("actions", "big-repo")

        self.assertEqual(len(tags), 101)
        self.assertEqual(mock_run.call_count, 2)

    @patch("fetch_versions.subprocess.run")
    def test_fetch_tags_empty(self, mock_run):
        """Test fetching tags when repo has no tags."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps([]),
            returncode=0,
        )

        tags = fetch_versions.fetch_tags("actions", "no-tags-repo")

        self.assertEqual(len(tags), 0)

    @patch("fetch_versions.subprocess.run")
    def test_fetch_tags_api_error(self, mock_run):
        """Test handling API error response."""
        mock_run.return_value = MagicMock(
            stdout=json.dumps({"message": "API rate limit exceeded"}),
            returncode=0,
        )

        tags = fetch_versions.fetch_tags("actions", "some-repo")

        self.assertEqual(len(tags), 0)


class TestUnversionedCache(unittest.TestCase):
    """Tests for the unversioned repos caching functions."""

    def test_load_unversioned_file_not_exists(self):
        """Test loading when unversioned.txt doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(fetch_versions, "UNVERSIONED_FILE", Path(tmpdir) / "unversioned.txt"):
                result = fetch_versions.load_unversioned()
                self.assertEqual(result, set())

    def test_load_unversioned_with_repos(self):
        """Test loading unversioned repos from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unversioned_file = Path(tmpdir) / "unversioned.txt"
            unversioned_file.write_text("repo1\nrepo2\nrepo3\n")

            with patch.object(fetch_versions, "UNVERSIONED_FILE", unversioned_file):
                result = fetch_versions.load_unversioned()
                self.assertEqual(result, {"repo1", "repo2", "repo3"})

    def test_save_unversioned(self):
        """Test saving unversioned repos to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            unversioned_file = Path(tmpdir) / "unversioned.txt"

            with patch.object(fetch_versions, "UNVERSIONED_FILE", unversioned_file):
                fetch_versions.save_unversioned({"zebra", "alpha", "mango"})

                content = unversioned_file.read_text()
                lines = content.strip().split("\n")
                # Should be sorted alphabetically
                self.assertEqual(lines, ["alpha", "mango", "zebra"])


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
    """Integration tests for the main function."""

    @patch("fetch_versions.save_unversioned")
    @patch("fetch_versions.load_unversioned")
    @patch("fetch_versions.VERSIONS_FILE")
    @patch("fetch_versions.get_latest_version_tag")
    @patch("fetch_versions.fetch_tags")
    @patch("fetch_versions.fetch_repos")
    def test_main_integration(
        self,
        mock_fetch_repos,
        mock_fetch_tags,
        mock_get_tag,
        mock_versions_file,
        mock_load_unversioned,
        mock_save_unversioned,
    ):
        """Test the main function with mocked dependencies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            versions_file = tmppath / "versions.txt"
            mock_versions_file.__str__ = lambda self: str(versions_file)
            mock_versions_file.__fspath__ = lambda self: str(versions_file)

            # No cached unversioned repos
            mock_load_unversioned.return_value = set()

            # Mock fetch_repos to return test data
            mock_fetch_repos.return_value = [
                {"name": "setup-python"},
                {"name": "setup-node"},
                {"name": "no-tags-repo"},
            ]

            # Mock fetch_tags to return tags for each repo
            def fetch_tags_side_effect(org, repo_name):
                if repo_name == "setup-python":
                    return ["v1", "v2", "v5"]
                elif repo_name == "setup-node":
                    return ["v1", "v2", "v3", "v4"]
                else:
                    return []  # no-tags-repo has no tags

            mock_fetch_tags.side_effect = fetch_tags_side_effect

            # Mock get_latest_version_tag to return versions for some repos
            def get_tag_side_effect(tags):
                if "v5" in tags:
                    return "v5"
                elif "v4" in tags:
                    return "v4"
                else:
                    return None

            mock_get_tag.side_effect = get_tag_side_effect

            # Patch open() to write to our temp file
            original_open = open

            def patched_open(path, *args, **kwargs):
                if "versions.txt" in str(path):
                    return original_open(versions_file, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=patched_open):
                fetch_versions.main()

            # Verify the versions file was written correctly
            content = versions_file.read_text()
            lines = content.strip().split("\n")

            self.assertEqual(len(lines), 2)
            self.assertIn("actions/setup-node@v4", lines)
            self.assertIn("actions/setup-python@v5", lines)

            # Verify alphabetical ordering (setup-node before setup-python)
            self.assertEqual(lines[0], "actions/setup-node@v4")
            self.assertEqual(lines[1], "actions/setup-python@v5")

            # Verify unversioned repos were saved
            mock_save_unversioned.assert_called_once()
            saved_unversioned = mock_save_unversioned.call_args[0][0]
            self.assertIn("no-tags-repo", saved_unversioned)

    @patch("fetch_versions.save_unversioned")
    @patch("fetch_versions.load_unversioned")
    @patch("fetch_versions.VERSIONS_FILE")
    @patch("fetch_versions.get_latest_version_tag")
    @patch("fetch_versions.fetch_tags")
    @patch("fetch_versions.fetch_repos")
    def test_main_skips_cached_unversioned(
        self,
        mock_fetch_repos,
        mock_fetch_tags,
        mock_get_tag,
        mock_versions_file,
        mock_load_unversioned,
        mock_save_unversioned,
    ):
        """Test that cached unversioned repos are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            versions_file = tmppath / "versions.txt"
            mock_versions_file.__str__ = lambda self: str(versions_file)
            mock_versions_file.__fspath__ = lambda self: str(versions_file)

            # Cached unversioned repos
            mock_load_unversioned.return_value = {"cached-no-tags"}

            # Mock fetch_repos to return test data including cached repo
            mock_fetch_repos.return_value = [
                {"name": "setup-python"},
                {"name": "cached-no-tags"},
            ]

            # Mock fetch_tags - should only be called for setup-python
            mock_fetch_tags.return_value = ["v1", "v5"]
            mock_get_tag.return_value = "v5"

            # Patch open() to write to our temp file
            original_open = open

            def patched_open(path, *args, **kwargs):
                if "versions.txt" in str(path):
                    return original_open(versions_file, *args, **kwargs)
                return original_open(path, *args, **kwargs)

            with patch("builtins.open", side_effect=patched_open):
                fetch_versions.main()

            # fetch_tags should only be called once (for setup-python, not cached-no-tags)
            self.assertEqual(mock_fetch_tags.call_count, 1)
            mock_fetch_tags.assert_called_with("actions", "setup-python")


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
