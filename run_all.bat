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
if defined NO_OPEN goto :end
REM Start the dashboard in its own window (close that window to stop the website)
start "AMR dashboard" /min cmd /k "cd /d "%~dp0" && python -m streamlit run app\dashboard.py --server.headless true --server.port 8501"
echo  Waiting for the dashboard to start...
set /a TRIES=0
:waitdash
curl -s http://localhost:8501/_stcore/health 2>nul | find "ok" >nul
if not errorlevel 1 goto opendash
set /a TRIES+=1
if %TRIES% geq 40 goto opendash
ping -n 2 127.0.0.1 >nul
goto waitdash
:opendash
start "" http://localhost:8501
echo  Dashboard open at http://localhost:8501  (close the "AMR dashboard" window to stop it)
goto :end

:fail
echo.
echo Something failed above. Scroll up to see the error.

:end
echo.
if not defined NO_OPEN pause
