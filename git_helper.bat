@echo off
REM Open Git Helper in a new terminal window

REM Check if python is in PATH
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found. Please install Python and add it to your PATH.
    pause
    exit /b
)

REM Run the Python script
python "%~dp0git_helper.py"

REM Keep the terminal open after the script finishes
pause
