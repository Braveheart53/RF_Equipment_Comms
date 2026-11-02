@echo off
REM ===========================================================================
REM  run_fsp_logger.bat - R and S FSP Trace Logger
REM  Version 0.10.0 (2026-10-29). Author: William W. Wallace
REM  Double-click to open the logger. Add --demo for the simulated analyzer.
REM  Uses the mamba environment "fsp-logger" when it exists, else python on PATH.
REM ===========================================================================
setlocal
cd /d "%~dp0"
set "ACT=%USERPROFILE%\miniforge3\Scripts\activate.bat"
if exist "%ACT%" (
    call "%ACT%" fsp-logger >nul 2>&1
)
python rs_fsp_logger.py %*
if errorlevel 1 pause
endlocal
