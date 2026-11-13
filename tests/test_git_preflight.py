import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import subprocess

from git_preflight import git_preflight, format_preflight


@unittest.skipUnless(subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0, "Git fehlt")
class GitPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                        "commit", "--allow-empty", "-qm", "initial"], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_clean_and_dirty(self):
        clean = git_preflight(self.root)
        self.assertTrue(clean["clean"])
        self.assertEqual(clean["root"], str(self.root.resolve()))
        (self.root / "new.txt").write_text("test", encoding="utf-8")
        dirty = git_preflight(self.root)
        self.assertFalse(dirty["clean"])
        self.assertIn("new.txt", format_preflight(dirty))

    def test_reject_non_git_directory(self):
        other = self.root / "other"
        other.mkdir()
        with self.assertRaises(ValueError):
            git_preflight(other)

    def test_reject_nested_repository_path(self):
        nested = self.root / "nested"
        nested.mkdir()
        with self.assertRaises(ValueError):
            git_preflight(nested)


if __name__ == "__main__":
    unittest.main()
