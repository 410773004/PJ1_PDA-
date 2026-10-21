@echo off
rem Build PDA_Calc_LJ2.exe from pda_calc_gui.py (single-file, no console window).
rem Output: PDA_Calc_LJ2.exe next to this script. Needs: python + pip install pyinstaller
rem build\ holds PyInstaller work files and the generated .spec (git-ignored).
rem The GUI file embeds all logic on purpose: --onefile once missed the sibling CLI module
rem and the exe failed with ModuleNotFoundError.
setlocal
cd /d "%~dp0"

python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Run: pip install pyinstaller
    exit /b 1
)

python -m PyInstaller --noconfirm --onefile --windowed --name PDA_Calc_LJ2 ^
    --distpath "%~dp0." --workpath "%~dp0build" --specpath "%~dp0build" ^
    pda_calc_gui.py
if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

echo Done: %~dp0PDA_Calc_LJ2.exe
endlocal
