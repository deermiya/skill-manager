@echo off
cd /d "%~dp0"
where pythonw >nul 2>&1
if %errorlevel%==0 (
  start "" pythonw "%~dp0skill_manager.py"
  exit /b 0
)
python "%~dp0skill_manager.py"
if errorlevel 1 pause
