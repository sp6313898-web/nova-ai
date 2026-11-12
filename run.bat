@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install Python 3.8+ and tick Add to PATH. & pause & exit /b 1)
if not exist venv python -m venv venv
call venv\Scripts\activate.bat
pip install -q -r requirements.txt
python main.py
