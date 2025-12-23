@echo off
REM Local Windows startup script for Disciplined Trader
REM This script sets up environment variables for local development

echo Starting Disciplined Trader (Local Development)...
echo.

REM Set environment variables for local development
set HOST=127.0.0.1
set PORT=5000
set DEBUG=true
set ENVIRONMENT=dev

REM Activate virtual environment if it exists
if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Run the application
echo Starting application...
python main.py

pause

