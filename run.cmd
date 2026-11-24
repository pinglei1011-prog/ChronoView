@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py" %*
    exit /b 0
)
echo Please run scripts\setup.ps1 first to create the Python environment.
pause
exit /b 1
