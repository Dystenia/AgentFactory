import sqlite3
import unittest
import job_workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE TABLE jobs (id TEXT PRIMARY KEY)")
        self.db.execute("INSERT INTO jobs VALUES ('job-1')")
        job_workflow.migrate(self.db)

    def tearDown(self):
        self.db.close()

    def test_full_approval_and_restart(self):
        job_workflow.ensure(self.db, "job-1", "original")
        job_workflow.save_questions(self.db, "job-1", "original", "Welche Version?")
        job_workflow.save_answers(self.db, "job-1", "Version 1")
        job_workflow.save_final(self.db, "job-1", "Implementiere Version 1")
        with self.assertRaises(ValueError):
            job_workflow.approve(self.db, "job-1", "unapproved edit")
        job_workflow.approve(self.db, "job-1", "Implementiere Version 1")
        self.assertEqual(job_workflow.get(self.db, "job-1")["status"], "READY")

    def test_original_change_revokes_approval(self):
        job_workflow.ensure(self.db, "job-1", "original")
        job_workflow.save_questions(self.db, "job-1", "original", "Keine Rückfragen")
        job_workflow.save_answers(self.db, "job-1", "Keine Rückfragen")
        job_workflow.save_final(self.db, "job-1", "Final")
        job_workflow.approve(self.db, "job-1", "Final")
        state = job_workflow.ensure(self.db, "job-1", "changed")
        self.assertEqual(state["status"], "DRAFT")
        self.assertEqual(state["final_prompt"], "")
        self.assertIsNone(state["approved_at"])

    def test_cannot_approve_before_clarification(self):
        job_workflow.ensure(self.db, "job-1", "original")
        with self.assertRaises(ValueError):
            job_workflow.save_final(self.db, "job-1", "Final")
        with self.assertRaises(ValueError):
            job_workflow.approve(self.db, "job-1", "Final")

    def test_binding_project_revokes_ready_without_losing_final(self):
        self.db.execute("ALTER TABLE jobs ADD COLUMN project_root TEXT")
        self.db.execute("CREATE TABLE imported_projects (root TEXT PRIMARY KEY)")
        self.db.execute("INSERT INTO imported_projects VALUES ('project-A')")
        job_workflow.ensure(self.db, "job-1", "original")
        job_workflow.save_questions(self.db, "job-1", "original", "Keine Rückfragen")
        job_workflow.save_answers(self.db, "job-1", "Keine Rückfragen")
        job_workflow.save_final(self.db, "job-1", "Final")
        job_workflow.approve(self.db, "job-1", "Final")
        self.assertTrue(job_workflow.bind_project(self.db, "job-1", "project-A"))
        state = job_workflow.get(self.db, "job-1")
        self.assertEqual(state["status"], "FINAL_REVIEW")
        self.assertEqual(state["final_prompt"], "Final")
        self.assertIsNone(state["approved_at"])
        self.assertFalse(job_workflow.bind_project(self.db, "job-1", "project-A"))
        with self.assertRaises(ValueError):
            job_workflow.bind_project(self.db, "job-1", "missing")

    def test_missing_job_rejected(self):
        with self.assertRaises(ValueError):
            job_workflow.ensure(self.db, "unknown", "original")


if __name__ == "__main__":
    unittest.main()
