"""Tests for bounded project context and multi-file review/application."""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from multi_file_development import project_source_context, review_changes, apply_changes


class MultiFileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Test"], check=True)
        (self.root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-qm", "initial"], check=True)
        self.commit = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "HEAD"], text=True).strip()

    def test_context_reads_existing_project(self):
        self.assertIn(("app.py", "VALUE = 1\n"), project_source_context(self.root))

    def test_diff_and_approved_apply(self):
        proposal = {"summary": "update", "files": [
            {"path": "app.py", "content": "VALUE = 2\n"},
            {"path": "tests/test_app.py", "content": "assert True\n"},
        ]}
        review = review_changes(self.root, proposal)
        self.assertIn("-VALUE = 1", review[0]["diff"])
        with self.assertRaises(ValueError):
            apply_changes(self.root, proposal, self.commit, review)
        paths = apply_changes(self.root, proposal, self.commit, review, approved=True)
        self.assertEqual(paths, ["app.py", "tests/test_app.py"])
        self.assertEqual((self.root / "app.py").read_text(), "VALUE = 2\n")

    def test_modified_file_blocks_stale_review(self):
        proposal = {"summary": "update", "files": [{"path": "app.py", "content": "VALUE = 2\n"}]}
        review = review_changes(self.root, proposal)
        (self.root / "app.py").write_text("VALUE = 3\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            apply_changes(self.root, proposal, self.commit, review, approved=True)


if __name__ == "__main__":
    unittest.main()
