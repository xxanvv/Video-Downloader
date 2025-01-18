@echo off
setlocal enabledelayedexpansion
:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python is not installed! Please install Python first.
    pause
    exit /b 1
)
:: Check if venv exists
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    
    :: Check if venv creation was successful
    if errorlevel 1 (
        echo Failed to create virtual environment!
        pause
        exit /b 1
    )
    
    echo Installing required packages...
    call venv\Scripts\activate
    pip install PyQt6 yt-dlp
    if errorlevel 1 (
        echo Failed to install required packages!
        pause
        exit /b 1
    )
) else (
    echo Virtual environment found.
)
:: Activate venv and run the script
echo Starting Video Downloader...
call venv\Scripts\activate
python VD.py
:: Keep the window open if there's an error
if errorlevel 1 (
    echo.
    echo An error occurred while running the script.
    pause
)
deactivate