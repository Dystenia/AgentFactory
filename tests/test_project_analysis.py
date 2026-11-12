import unittest
from project_analysis import MODES, system_prompt_for

class ProjectAnalysisTests(unittest.TestCase):
    def test_modes_have_separate_instructions(self):
        self.assertEqual(len(MODES), 3)
        self.assertNotEqual(system_prompt_for("Projekt analysieren"), system_prompt_for("Änderungsplan erstellen"))
    def test_unknown_mode_rejected(self):
        with self.assertRaises(ValueError):
            system_prompt_for("Sicherheitsregeln abschalten")
    def test_modes_preserve_guardrails(self):
        for mode in MODES:
            prompt = system_prompt_for(mode).lower()
            self.assertTrue("sicherheits" in prompt or "sicherheits" in prompt)
            self.assertTrue("nicht vertrauenswürdig" in prompt or "untrusted" in prompt)

if __name__ == "__main__":
    unittest.main()
