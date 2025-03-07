@echo off
title OBS Stream Watchdog Launcher (WebSocket)
echo Starting OBS Stream Watchdog (WebSocket version)...
echo.

REM Check if Python is installed
python --version > nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Install required packages
echo Installing required packages...
python -m pip install websocket-client
if %ERRORLEVEL% NEQ 0 (
    echo Failed to install websocket-client package.
    echo Please install it manually with: pip install websocket-client
    echo.
    pause
    exit /b 1
)
echo Package installation complete.
echo.

REM Run the Python script
echo Starting watchdog script...
python obs-watchdog-websocket.py

pause 