$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git ist nicht installiert oder nicht im PATH.' }
if (-not (Test-Path '.git')) { git init -b main; if ($LASTEXITCODE -ne 0) { throw 'git init fehlgeschlagen' } }
$remote = git remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0) {
    git remote add origin 'https://github.com/Dystenia/AgentFactory.git'
} elseif ($remote -ne 'https://github.com/Dystenia/AgentFactory.git' -and $remote -ne 'git@github.com:Dystenia/AgentFactory.git') {
    throw "Unbekannter origin-Remote: $remote. Kein automatischer Push."
}
git add -- main.py requirements.txt README.md .gitignore desktop_verknuepfung.ps1 DESKTOP_STARTEN.cmd GIT_ERSTCOMMIT.ps1 assets/dystenia_agent_factory.ico assets/dystenia_agent_factory.png
if ($LASTEXITCODE -ne 0) { throw 'git add fehlgeschlagen' }
git diff --cached --check
if ($LASTEXITCODE -ne 0) { throw 'Whitespace-Pruefung fehlgeschlagen' }
git status --short
Write-Host 'Dateien sind fuer den Commit vorgemerkt.'
Write-Host 'Pruefe die Liste. Danach manuell ausfuehren:'
Write-Host 'git commit -m "feat: initial Agent Factory MVP with desktop shortcut"'
Write-Host 'git push -u origin main'
