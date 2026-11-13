import json
import unittest
from project_proposal import parse_project_proposal, ProjectProposalError


class ProjectProposalTests(unittest.TestCase):
    def proposal(self, files):
        return json.dumps({"summary": "Demo", "files": files})

    def test_valid_two_files(self):
        data = parse_project_proposal(self.proposal([
            {"path": "main.py", "content": "print('hello')"},
            {"path": "README.md", "content": "Demo"},
        ]))
        self.assertEqual(len(data["files"]), 2)

    def test_reject_traversal(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([{"path": "../main.py", "content": "x"}]))

    def test_reject_windows_drive(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([{"path": "C:/temp/main.py", "content": "x"}]))

    def test_reject_duplicate_case_insensitive(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([
                {"path": "Main.py", "content": "a"},
                {"path": "main.py", "content": "b"},
            ]))

    def test_reject_executable_extension(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([{"path": "install.ps1", "content": "x"}]))

    def test_reject_too_many_files(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([
                {"path": f"file{i}.py", "content": "x"} for i in range(13)
            ]))

    def test_reject_reserved_windows_name(self):
        with self.assertRaises(ProjectProposalError):
            parse_project_proposal(self.proposal([{"path": "CON.txt", "content": "x"}]))


if __name__ == "__main__":
    unittest.main()
