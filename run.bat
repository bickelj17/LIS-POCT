@echo off
title POCT Result Analysis
cd /d "%~dp0"

:: Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python is not installed or not on your PATH.
    echo  Install Python from https://www.python.org/downloads/
    echo  During setup, check "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

:: Install dependencies using the SAME Python that will run the app
echo  Installing dependencies (Flask, etc.)...
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo  Failed to install dependencies. Check the message above.
    pause
    exit /b 1
)

:: Run the app (browser will open automatically)
echo  Starting POCT Result Analysis...
echo.
python app.py

pause
