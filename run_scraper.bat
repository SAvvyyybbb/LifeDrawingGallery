@echo off
REM -------------------------------
REM Run Discord scraper relative to this .bat file
REM -------------------------------

REM Get the folder where this .bat file is located
SET "SCRIPT_DIR=%~dp0"

REM Change to the folder containing the script
cd /d "%SCRIPT_DIR%"

REM Run the Python script
python "discord_scraper.py"

REM Keep the console open after finishing
pause
