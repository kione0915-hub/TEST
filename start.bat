@echo off
cd /d "%~dp0"
echo ============================================
echo  Starting auto-trading dashboard...
echo  (First run installs packages - please wait)
echo ============================================

py --version >nul 2>nul
if not errorlevel 1 goto haspy
python --version >nul 2>nul
if not errorlevel 1 goto haspython
goto nopython

:haspy
py updater.py
py -m pip install -r requirements.txt --quiet
py webapp.py
goto end

:haspython
python updater.py
python -m pip install -r requirements.txt --quiet
python webapp.py
goto end

:nopython
echo.
echo [ERROR] Python is not installed on this computer.
echo.
echo   1. Open https://python.org/downloads and install Python
echo   2. IMPORTANT: check the box "Add python.exe to PATH"
echo   3. Run this file (start.bat) again
echo.

:end
pause
