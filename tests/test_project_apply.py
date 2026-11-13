import json
import subprocess

import pytest

from project_apply import apply_project_proposal


def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c",
                    "user.email=test@example.com", "commit", "-q", "--allow-empty", "-m", "initial"], check=True)
    return subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()


def proposal(*files):
    return {"summary": "test", "files": [{"path": p, "content": c} for p, c in files]}


def test_new_files_written_only_with_approval(tmp_path):
    sha = repo(tmp_path)
    data = proposal(("main.py", "print('ok')\n"), ("tests/test_app.py", "def test_ok(): assert True\n"))
    with pytest.raises(ValueError, match="Freigabe"):
        apply_project_proposal(str(tmp_path), data, sha)
    assert not (tmp_path / "main.py").exists()
    written = apply_project_proposal(str(tmp_path), data, sha, approved=True)
    assert written == ["main.py", "tests/test_app.py"]
    assert (tmp_path / "main.py").read_text() == "print('ok')\n"


def test_existing_file_not_overwritten(tmp_path):
    sha = repo(tmp_path)
    (tmp_path / "main.py").write_text("existing")
    with pytest.raises(ValueError):
        apply_project_proposal(str(tmp_path), proposal(("main.py", "new")), sha, approved=True)
    assert (tmp_path / "main.py").read_text() == "existing"


def test_invalid_path_rejected(tmp_path):
    sha = repo(tmp_path)
    with pytest.raises(ValueError):
        apply_project_proposal(str(tmp_path), proposal(("../outside.py", "oops")), sha, approved=True)
    assert not (tmp_path.parent / "outside.py").exists()


def test_stale_commit_rejected(tmp_path):
    sha = repo(tmp_path)
    with pytest.raises(ValueError, match="Git-Stand"):
        apply_project_proposal(str(tmp_path), proposal(("main.py", "ok")), "0" * 40, approved=True)
