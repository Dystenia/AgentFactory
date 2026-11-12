import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from prompt_context import collect_context, build_request, ContextError
from model_router import generate, ModelError

class PromptStudioTests(unittest.TestCase):
    def test_collect_context_and_redact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'main.py').write_text('api_key = abc123\nprint("ok")', encoding='utf-8')
            (root / '.env').write_text('secret=VERYSECRET', encoding='utf-8')
            report = {'root': str(root.resolve()), 'file_count': 2, 'entrypoints': ['main.py'], 'dependencies': [], 'sample_files': ['main.py', '.env']}
            result = collect_context(str(root), report)
            self.assertIn('print("ok")', result)
            self.assertNotIn('abc123', result)
            self.assertNotIn('VERYSECRET', result)
    def test_no_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {'root': str(root.resolve()), 'file_count': 1, 'entrypoints': ['../secrets.txt'], 'dependencies': [], 'sample_files': []}
            self.assertNotIn('secrets.txt (', collect_context(str(root), report))
    def test_empty_task(self):
        with self.assertRaises(ContextError):
            build_request(' ', 'x')
    def test_no_key_no_network(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(ModelError):
                generate('OpenAI', 'gpt-4.1-mini', 'system', 'user')
    def test_invalid_provider(self):
        with self.assertRaises(ModelError):
            generate('unknown', 'model', 'system', 'user')

if __name__ == '__main__':
    unittest.main()
