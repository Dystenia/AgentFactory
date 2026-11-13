import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from controlled_edit import preview, apply, EditRejected


class ControlledEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        subprocess.run(['git','init','-q',str(self.root)], check=True)
        self.file = self.root / 'sample.txt'
        self.file.write_text('before', encoding='utf-8')
        subprocess.run(['git','-C',str(self.root),'add','sample.txt'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','initial'],check=True)
        self.sha = hashlib.sha256(b'before').hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def test_preview_does_not_write(self):
        self.assertEqual(preview(self.root,'sample.txt',self.sha,'after')['after_bytes'],5)
        self.assertEqual(self.file.read_text(),'before')

    def test_explicit_approval_required(self):
        with self.assertRaises(EditRejected): apply(self.root,'sample.txt',self.sha,'after')
        self.assertEqual(self.file.read_text(),'before')

    def test_approved_replacement(self):
        self.assertTrue(apply(self.root,'sample.txt',self.sha,'after',approved=True)['written'])
        self.assertEqual(self.file.read_text(),'after')

    def test_reject_wrong_hash(self):
        with self.assertRaises(EditRejected): apply(self.root,'sample.txt','0'*64,'after',approved=True)

    def test_reject_escape(self):
        with self.assertRaises(EditRejected): preview(self.root,'../outside.txt',self.sha,'after')

    def test_reject_dirty_worktree(self):
        self.file.write_text('modified')
        with self.assertRaises(EditRejected): preview(self.root,'sample.txt',self.sha,'after')

    def test_reject_symlink(self):
        link = self.root / "link.txt"

        try:
            link.symlink_to(self.file)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                self.skipTest(
                    "Windows erlaubt das Erstellen von Symlinks "
                    "ohne entsprechende Berechtigung nicht."
                )
            raise

        with self.assertRaises(EditRejected):
            preview(self.root, "link.txt", self.sha, "after")
if __name__ == '__main__': unittest.main()
