"""Static, read-only inventory of local Python projects; never executes project code."""
import json
from pathlib import Path

SKIP = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', '.tox', '.mypy_cache', '.pytest_cache', 'dist', 'build'}
MAX_FILES = 12000
MAX_DEPTH = 16


def inspect_project(directory):
    root = Path(directory).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Bitte einen Projektordner auswählen.')
    counts = {}
    files = []
    truncated = False
    pending = [(root, 0)]
    while pending:
        current, depth = pending.pop()
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            continue
        for child in children:
            if child.is_symlink():
                continue  # Never follow links outside the selected tree
            if child.is_dir():
                if child.name not in SKIP and depth < MAX_DEPTH:
                    pending.append((child, depth + 1))
            elif child.is_file():
                suffix = child.suffix.lower() or '[ohne Endung]'
                counts[suffix] = counts.get(suffix, 0) + 1
                if len(files) < MAX_FILES:
                    files.append(child.relative_to(root).as_posix())
                else:
                    truncated = True
        if truncated:
            break
    config = [p for p in ('pyproject.toml', 'requirements.txt', 'setup.py', 'Pipfile', 'poetry.lock', 'README.md', 'pytest.ini', 'tox.ini', '.gitignore') if p in files]
    tests = [p for p in files if p.startswith('tests/') or p.startswith('test_') or '/test_' in p]
    entrypoints = [p for p in ('main.py', 'app.py', 'run.py', '__main__.py', 'manage.py') if p in files]
    frameworks = []
    # Read only a small, bounded amount of dependency metadata; never import or execute it.
    depfile = root / 'requirements.txt'
    if depfile.is_file() and not depfile.is_symlink() and depfile.stat().st_size <= 256_000:
        try:
            lines = depfile.read_text(encoding='utf-8-sig').splitlines()
            frameworks = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith('#')][:80]
        except (UnicodeError, OSError):
            pass
    return {'root': str(root), 'file_count': sum(counts.values()), 'extensions': counts,
            'configs': config, 'tests_count': len(tests), 'entrypoints': entrypoints,
            'dependencies': frameworks, 'sample_files': files[:60], 'truncated': truncated,
            'git_present': (root / '.git').exists()}


def report_text(data):
    return ('Projekt: {root}\nDateien: {file_count}{limit}\nGit vorhanden: {git}\n'
            'Einstiegspunkte: {entry}\nKonfiguration: {configs}\nTestdateien: {tests_count}\n'
            'Dateitypen: {extensions}\n\nAbhängigkeiten (requirements.txt):\n{deps}\n\n'
            'Dateiauswahl:\n{files}\n\n'
            'Hinweis: rein statische Bestandsaufnahme, keine Qualitäts- oder Laufzeitprüfung.').format(
                root=data['root'], file_count=data['file_count'], extensions=data['extensions'], tests_count=data['tests_count'],
                limit=' (Scan begrenzt)' if data['truncated'] else '',
                git='Ja' if data['git_present'] else 'Nein',
                entry=', '.join(data['entrypoints']) or 'Nicht erkannt',
                configs=', '.join(data['configs']) or 'Keine erkannt',
                deps='\n'.join(data['dependencies']) or 'Keine erkannt',
                files='\n'.join(data['sample_files']) or 'Keine Dateien')
