@echo off
REM ----------------------------------------
REM Batch file to launch Streamlit Booter using python -m
REM ----------------------------------------

REM Change directory to the folder containing Streamlit_booter.py
cd /d %~dp0

REM Use python -m to run streamlit
python -m streamlit run Streamlit_booter.py

pause
