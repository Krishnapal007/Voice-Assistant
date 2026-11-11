@echo off
REM One-click setup for Windows (run from the project folder)
python -m venv venv
call venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup finished. Edit the .env file, then double-click run.bat
pause
