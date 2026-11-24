$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (Get-Command uv -ErrorAction SilentlyContinue) {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        uv venv --python 3.12 .venv
        if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment.' }
    }
    & .venv\Scripts\python.exe -c 'import sys; assert (3, 12) <= sys.version_info[:2] < (3, 14), "Python 3.12 or 3.13 required"'
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
    uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
} else {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            py -3.12 -m venv .venv
        } else {
            python -m venv .venv
        }
    }
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        throw 'Python 3.12+ is required. Install Python or uv and retry.'
    }
    & .venv\Scripts\python.exe -c 'import sys; assert (3, 12) <= sys.version_info[:2] < (3, 14), "Python 3.12 or 3.13 required"'
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python version.' }
    & .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
Write-Host 'Ready. Double-click run.cmd to start ChronoView.'
