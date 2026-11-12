"""Dependency-free, read-only scanner regression tests."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_inspector import inspect_project, report_text


class InspectorTests(unittest.TestCase):
    def test_inventory_and_dependency_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'main.py').write_text('print("test")\n', encoding='utf-8')
            (root / 'requirements.txt').write_text('PySide6>=6.6\n# comment\npytest\n', encoding='utf-8')
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_basic.py').write_text('pass\n', encoding='utf-8')
            (root / '.venv').mkdir()
            (root / '.venv' / 'hidden.py').write_text('pass\n', encoding='utf-8')
            result = inspect_project(root)
            self.assertEqual(result['file_count'], 3)
            self.assertEqual(result['tests_count'], 1)
            self.assertEqual(result['entrypoints'], ['main.py'])
            self.assertEqual(result['dependencies'], ['PySide6>=6.6', 'pytest'])
            self.assertIn('Projekt:', report_text(result))

    def test_nonexistent_folder(self):
        with self.assertRaises(FileNotFoundError):
            inspect_project(Path(tempfile.gettempdir()) / 'agentfactory_missing_987654321')


if __name__ == '__main__':
    unittest.main(verbosity=2)
