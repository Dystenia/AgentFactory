import tempfile
import unittest
from pathlib import Path
from project_access import validate_project_root

class ProjectAccessTests(unittest.TestCase):
    def test_specific_project_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            self.assertEqual(validate_project_root(project), project.resolve())
    def test_home_blocked(self):
        with self.assertRaises(ValueError):
            validate_project_root(Path.home())
    def test_root_blocked(self):
        with self.assertRaises(ValueError):
            validate_project_root(Path.home().anchor)

if __name__ == "__main__":
    unittest.main()
