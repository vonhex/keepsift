@echo off
rem Build a standalone dist\KeepSift.exe (no Python needed to run it). Used by the GitHub release workflow too.
cd /d "%~dp0"
if not exist ".build-venv\Scripts\python.exe" python -m venv .build-venv
".build-venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q pyinstaller==6.16.0 -r requirements.txt || exit /b 1
".build-venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name KeepSift ^
    --icon assets\icon.ico --add-data "assets;assets" --add-data "samples;samples" ^
    --collect-data sv_ttk keepsift_app.py || exit /b 1
echo Built dist\KeepSift.exe
