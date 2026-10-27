@echo off
REM Opens the AMR dashboard in your browser.
cd /d "%~dp0"
title AMR dashboard launcher
where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install it from python.org and tick "Add to PATH".
    pause
    exit /b 1
)
echo Installing libraries if needed...
python -m pip install -q --disable-pip-version-check -r requirements.txt
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
ping -n 4 127.0.0.1 >nul
