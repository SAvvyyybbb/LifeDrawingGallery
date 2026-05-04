@echo off
REM ----------------------------------------
REM Batch file to launch Streamlit Booter using python -m
REM ----------------------------------------

REM Change directory to the folder containing Home.py
cd /d %~dp0

REM Use python -m to run streamlit
python -m streamlit run Home.py

pause
