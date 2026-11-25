param([string]$Compiler = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $Compiler) {
    $candidates = @(
        (Join-Path $projectRoot 'work\release-1.1\tools\InnoSetup\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    )
    $Compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Compiler) { throw 'Install Inno Setup 6 or 7, or provide -Compiler <ISCC.exe>.' }
& $Compiler packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
