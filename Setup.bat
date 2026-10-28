@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title KeepSift setup
echo.
echo   KeepSift setup
echo   ==============
echo.

rem ---- 1. Find Python 3.11+ (install it if missing) ----
set "PY="
for %%C in ("py -3" "python") do (
    if not defined PY (
        %%~C -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=%%~C"
    )
)
if not defined PY (
    echo   Python 3.11+ not found. Installing Python 3.12 with winget...
    winget install --id Python.Python.3.12 -e --scope user --silent --accept-source-agreements --accept-package-agreements
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    if not exist "!PY!" (
        echo.
        echo   Could not install Python automatically.
        echo   Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^), then run Setup.bat again.
        pause
        exit /b 1
    )
)
echo   [1/4] Python: OK

rem ---- 2. Private environment for KeepSift ----
if not exist ".venv\Scripts\python.exe" (
    %PY% -m venv .venv || (echo   Could not create the environment. & pause & exit /b 1)
)
echo   [2/4] Environment: OK

rem ---- 3. Packages ----
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (
    echo   Package install failed ^(no internet?^). KeepSift still works, with a plainer look.
)
echo   [3/4] Packages: OK

rem ---- 4. Shortcuts ----
if not "%KEEPSIFT_NO_SHORTCUTS%"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$s = New-Object -ComObject WScript.Shell;" ^
      "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {" ^
      "  $l = $s.CreateShortcut((Join-Path $dir 'KeepSift.lnk'));" ^
      "  $l.TargetPath = (Resolve-Path '.venv\Scripts\pythonw.exe').Path;" ^
      "  $l.Arguments = '-m keepsift.gui';" ^
      "  $l.WorkingDirectory = (Get-Location).Path;" ^
      "  $l.IconLocation = (Resolve-Path 'assets\icon.ico').Path;" ^
      "  $l.Description = 'KeepSift - local-AI inbox cleanup';" ^
      "  $l.Save() }"
    echo   [4/4] Shortcuts on Desktop and Start menu: OK
)

echo.
echo   All done. Starting KeepSift...
if not "%KEEPSIFT_NO_LAUNCH%"=="1" start "" ".venv\Scripts\pythonw.exe" -m keepsift.gui
"%SystemRoot%\System32\timeout.exe" /t 3 /nobreak >nul
exit /b 0
