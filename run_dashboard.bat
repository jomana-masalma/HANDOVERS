@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Setup] Creating virtual environment...
    py -m venv .venv
)

echo [Setup] Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo [Setup] Installing requirements...
python -m pip install -r requirements.txt

REM Choice 1 opens the Stage 1 dashboard. Choice 2 opens the comments and reply-network dashboard.
echo.
echo 1  Stage 1: videos, channels, and search
echo 2  Comments and reply network
echo.
set /p CHOICE=Choose 1 or 2: 

if "%CHOICE%"=="1" (
    streamlit run youtube_dashboard_streamlit.py
) else if "%CHOICE%"=="2" (
    streamlit run final_video_ids_visualization.py
) else (
    echo Choose 1 or 2.
)

echo.
echo Dashboard ended. Press any key to close.
pause >nul
