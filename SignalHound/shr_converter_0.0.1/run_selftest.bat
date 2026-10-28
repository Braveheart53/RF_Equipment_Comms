@echo off
REM SHR Converter 0.0.1 - self-test, GUI smoke test and pytest suites
cd /d "%~dp0"
call mamba activate shr-converter
python shr_converter.py --selftest --gui-smoke
python -m pytest -q tests
python tests\memory_check.py --sweeps 1500 --bins 65536 --workers 2 --ram-mb 256
pause
