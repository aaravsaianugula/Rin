@echo off
:: Rin Agent Startup Script
:: This script starts the Rin agent backend which includes:
::   - API Server (port 8000)
::   - Discord Service
::   - Voice Service
::   - VLM Manager (on-demand)

:: Set working directory to Rin project folder
cd /d "%~dp0"

:: Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

:: Start the agent in background (minimized, with logging)
echo Starting Rin Agent...
start /min "" pythonw main.py

echo Rin Agent started. Check logs folder for output.
exit
