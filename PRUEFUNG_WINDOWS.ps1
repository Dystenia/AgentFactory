$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Python-Umgebung .venv fehlt.' }
& $python -m pip show PySide6
if ($LASTEXITCODE -ne 0) { throw 'PySide6 fehlt.' }
& $python -m compileall -q main.py project_inspector.py model_router.py prompt_context.py project_analysis.py project_access.py
if ($LASTEXITCODE -ne 0) { throw 'Syntaxpruefung fehlgeschlagen.' }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests fehlgeschlagen.' }
Write-Host 'Statische Abnahme OK. GUI bitte manuell starten.'
