@echo off
REM ===========================================================================
REM  run_batch_converter.bat - FSP Logger Batch Converter (stand-alone window)
REM  Version 0.0.1 (2026-10-29), logger bundle 0.10.0. Author: William W. Wallace
REM  Double-click to open the window, or drop CSV files / folders on this file.
REM  Uses the mamba environment "fsp-logger" when it exists, else python on PATH.
REM ===========================================================================
setlocal
cd /d "%~dp0"
set "ACT=%USERPROFILE%\miniforge3\Scripts\activate.bat"
if exist "%ACT%" (
    call "%ACT%" fsp-logger >nul 2>&1
)
python fsp_batch_convert.py %*
if errorlevel 1 pause
endlocal
