@echo off
REM SHR Converter 0.0.2 - create the mamba environment "shr-converter" (once)
cd /d "%~dp0"
call mamba env create -f environment.yml || call mamba env update -f environment.yml --prune
echo.
echo Optional: mamba install -n shr-converter -c conda-forge veusz
pause
