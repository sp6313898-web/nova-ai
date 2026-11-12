@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/6] Checking Python
where python >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.8+ from python.org and tick "Add python.exe to PATH".
  pause & exit /b 1
)

echo [2/6] Creating virtual environment
if not exist venv python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [3/6] Installing dependencies
pip install -r requirements.txt
if errorlevel 1 goto fail

echo [4/6] Optional modules (offline speech Vosk, local llama DLL mode)
set "OPT=--collect-all vosk"
pip install vosk
if errorlevel 1 goto fail
pip install llama-cpp-python --only-binary :all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if not errorlevel 1 set "OPT=%OPT% --collect-all llama_cpp"

echo [5/6] Building NovaAgent.exe (the program)
pyinstaller --noconfirm --clean --onefile --noconsole --name NovaAgent ^
  --icon assets\icon.ico --add-data "assets\icon.ico;assets" ^
  --collect-all sounddevice --collect-data speech_recognition --collect-all edge_tts ^
  --hidden-import win32com.client --hidden-import pythoncom --hidden-import pystray._win32 ^
  --collect-submodules psutil %OPT% main.py
if errorlevel 1 goto fail

echo [6/6] Building NovaAgentSetup.exe (the installer)
if not exist installer\payload mkdir installer\payload
copy /Y dist\NovaAgent.exe installer\payload\NovaAgent.exe >nul
pyinstaller --noconfirm --clean --onefile --noconsole --name NovaAgentSetup ^
  --icon assets\icon.ico --add-data "assets\icon.ico;assets" ^
  --add-data "installer\payload\NovaAgent.exe;payload" installer\installer.py
if errorlevel 1 goto fail

if not exist release mkdir release
copy /Y dist\NovaAgent.exe release\ >nul
copy /Y dist\NovaAgentSetup.exe release\ >nul
echo.
echo Done. Files are in the "release" folder: NovaAgentSetup.exe and NovaAgent.exe
explorer release
pause
exit /b 0

:fail
echo.
echo Build failed. See messages above.
pause
exit /b 1
