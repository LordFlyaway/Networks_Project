@echo off
REM Runs the whole AMR project in order. Double-click this file.
setlocal
cd /d "%~dp0"
title Authenticated MAC Rotation - run all

where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install it from python.org and tick "Add to PATH".
    goto :end
)

echo ============================================================
echo  [1/6] Installing required libraries (skips if already there)
echo ============================================================
python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  [2/6] Running tests
echo ============================================================
python -m unittest discover tests
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  [3/6] Live demo
echo ============================================================
python demo.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  [4/6] Running experiments and drawing graphs (about 1 minute)
echo ============================================================
python run_experiments.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  [5/6] Creating Wireshark capture files
echo ============================================================
python make_pcap.py 2>nul
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  [6/6] Real security tests (attacks against the AMR code)
echo ============================================================
python security_tests.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  All done. Opening the results folder and the dashboard...
echo ============================================================
if not defined NO_OPEN start "" "%~dp0results"
REM The dashboard runs in its own window and opens in the browser.
REM Close that window to stop the website.
if not defined NO_OPEN start "AMR dashboard" cmd /k "cd /d "%~dp0" && python -m streamlit run app\dashboard.py"
echo  The website opens at http://localhost:8501 (give it a few seconds).
echo  Close the "AMR dashboard" window to stop it.
goto :end

:fail
echo.
echo Something failed above. Scroll up to see the error.

:end
echo.
if not defined NO_OPEN pause
