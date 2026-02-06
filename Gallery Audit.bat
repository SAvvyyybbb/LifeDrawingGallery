@echo off
REM Change directory to the folder containing this script
cd /d "%~dp0"

REM Install Streamlit if not already installed
py -m pip show streamlit >nul 2>&1
IF ERRORLEVEL 1 (
    echo Streamlit not found. Installing...
    py -m pip install streamlit
)

REM Launch the Streamlit app
py -m streamlit run "Gallery UV Scanner.py"

pause
