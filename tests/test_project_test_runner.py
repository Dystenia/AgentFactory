"""Focused tests for the project test runner."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from subprocess import CompletedProcess, TimeoutExpired

from project_test_runner import run_project_tests


class TestRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".git").mkdir()
        (self.root / "tests").mkdir()

    @patch("project_test_runner.subprocess.run")
    def test_pass(self, run):
        run.return_value = CompletedProcess([], 0, "7 passed", "")
        result = run_project_tests(self.root)
        self.assertEqual(result["status"], "PASSED")
        self.assertEqual(result["exit_code"], 0)
        self.assertFalse(run.call_args.kwargs["shell"])

    @patch("project_test_runner.subprocess.run")
    def test_failure(self, run):
        run.return_value = CompletedProcess([], 1, "assert 1 == 2", "")
        self.assertEqual(run_project_tests(self.root)["status"], "FAILED")

    @patch("project_test_runner.subprocess.run", side_effect=TimeoutExpired("pytest", 3))
    def test_timeout(self, run):
        self.assertEqual(run_project_tests(self.root, timeout=3)["status"], "TIMEOUT")

    def test_missing_tests(self):
        (self.root / "tests").rmdir()
        self.assertEqual(run_project_tests(self.root)["status"], "NO_TESTS")

    def test_invalid_root(self):
        with self.assertRaises(ValueError):
            run_project_tests(self.root / "missing")


if __name__ == "__main__":
    unittest.main()
