@echo off
REM Opens the AMR dashboard in your browser. Close this window to stop it.
cd /d "%~dp0"
title AMR dashboard
where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install it from python.org and tick "Add to PATH".
    pause
    exit /b 1
)
echo Installing libraries if needed...
python -m pip install -q --disable-pip-version-check -r requirements.txt
echo Starting the dashboard at http://localhost:8501  (close this window to stop)
python -m streamlit run app\dashboard.py --server.headless false
pause
