@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0dist\ChronoView-1.1.0\ChronoView.exe" goto missing_program
start "" /D "%~dp0dist\ChronoView-1.1.0" "%~dp0dist\ChronoView-1.1.0\ChronoView.exe" %*
exit /b 0
:missing_program
echo Current V1.1.0 executable not found. Run scripts\build.ps1 first, or use run.cmd for source mode.
pause
exit /b 1
