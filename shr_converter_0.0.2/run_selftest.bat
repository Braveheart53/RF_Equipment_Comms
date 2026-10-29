@echo off
REM SHR Converter 0.0.2 - reader and engine self-tests, GUI smoke test, pytest
REM suites (the SM200C sample in tests\data is used automatically) and the
REM memory check. Optional: set SHR_REAL_FILE to Spike's sweep0v2.shr (from the
REM SM200C_SHR_reader_prep folder, extract sweep0v2.shr.7z) and VEUSZ_EXE to
REM veusz.exe for the real-file and render tests.
cd /d "%~dp0"
call mamba activate shr-converter
python shr_converter.py --selftest --gui-smoke
python -m pytest -q -rs tests
python tests\memory_check.py --sweeps 1500 --bins 65536 --workers 2 --ram-mb 256
REM Longer checks (about 1-3 min each on a desktop; ~1.5 GB of temporary files):
REM   python tests\long_capture_check.py --workers 8
REM   python tests\sm200c_rate_check.py --files 3 --minutes 10 --workers 8
pause
