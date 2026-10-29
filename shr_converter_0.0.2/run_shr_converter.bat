@echo off
REM SHR Converter 0.0.2 - start the GUI (files may be dropped on this .bat)
cd /d "%~dp0"
call mamba activate shr-converter
python shr_converter.py %*
