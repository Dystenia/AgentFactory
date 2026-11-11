$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonw = Join-Path $project '.venv\Scripts\pythonw.exe'
$main = Join-Path $project 'main.py'
$icon = Join-Path $project 'assets\dystenia_agent_factory.ico'
if (-not (Test-Path $pythonw)) { throw "Virtuelle Umgebung fehlt: $pythonw" }
if (-not (Test-Path $main)) { throw "main.py fehlt: $main" }
if (-not (Test-Path $icon)) { throw "Icon fehlt: $icon" }
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
if (-not (Test-Path $desktop)) { throw 'Desktop-Ordner nicht gefunden' }
$shortcut = Join-Path $desktop 'Dystenia Agent Factory.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $pythonw
$link.Arguments = '"' + $main + '"'
$link.WorkingDirectory = $project
$link.IconLocation = $icon + ',0'
$link.Description = 'Dystenia Agent Factory - lokale Auftragsverwaltung'
$link.Save()
Write-Host "Desktopverknuepfung erstellt: $shortcut"
