$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$releaseVersion = & .venv\Scripts\python.exe -c 'from app import __version__; print(__version__)'
if ($releaseVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version.' }
$releasePath = Join-Path dist ('ChronoView-' + $releaseVersion)
& .venv\Scripts\python.exe scripts\prepare_libmpv.py
if ($LASTEXITCODE -ne 0) { throw 'Native playback runtime verification failed.' }
& .venv\Scripts\python.exe scripts\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
& .venv\Scripts\python.exe scripts\collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm packaging\ChronoView.spec
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -LiteralPath packaging\portable-readme.txt -Destination (Join-Path $releasePath 'README.txt')
Copy-Item -LiteralPath packaging\compatible-playback.cmd -Destination (Join-Path $releasePath '兼容播放.cmd')
if (Test-Path -LiteralPath 'VALIDATION.md') {
    Copy-Item -LiteralPath VALIDATION.md -Destination (Join-Path $releasePath 'VALIDATION.md')
}
if (Test-Path -LiteralPath 'STABILITY_REPORT.md') {
    Copy-Item -LiteralPath STABILITY_REPORT.md -Destination (Join-Path $releasePath 'STABILITY_REPORT.md')
}
Copy-Item -LiteralPath assets\licenses -Destination (Join-Path $releasePath 'licenses') -Recurse -Force
Write-Host ('Portable application: ' + (Join-Path $releasePath 'ChronoView.exe'))
