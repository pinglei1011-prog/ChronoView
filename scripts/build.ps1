$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
& .venv\Scripts\python.exe -m PyInstaller --noconfirm packaging\ChronoView.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -LiteralPath packaging\portable-readme.txt -Destination dist\ChronoView\使用说明.txt
if (Test-Path -LiteralPath 'VALIDATION.md') {
    Copy-Item -LiteralPath VALIDATION.md -Destination dist\ChronoView\VALIDATION.md
}
Write-Host 'Portable application: dist\ChronoView\ChronoView.exe'
