@echo off
rem Start KeepSift (runs Setup.bat first if needed). With arguments, runs the command line tool instead:
rem   KeepSift.bat run --live      KeepSift.bat log -n 20      KeepSift.bat --help
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call Setup.bat & exit /b
if "%~1"=="" (
    start "" ".venv\Scripts\pythonw.exe" -m keepsift.gui
) else (
    ".venv\Scripts\python.exe" -m keepsift %*
)
