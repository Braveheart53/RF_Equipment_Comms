# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Run every check in this folder, in parallel, and print a summary table.

Part of the QuickSyn SCPI controller package, version 0.0.7.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Usage::

    python tests/run_all.py            # uses the running interpreter
    python tests/run_all.py --serial   # one check at a time, for debugging

The checks are independent processes, so they run concurrently
(``ThreadPoolExecutor`` is enough: each worker only waits on a subprocess).
Each runs with ``-I`` (isolated mode) so a stray ``PYTHONPATH`` or a file in
the current directory cannot change what is imported.
"""
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKS = ("check_release_metadata.py", "check_smoke.py", "check_reduction.py",
          "check_vszh5.py", "check_console.py")


def run_one(name: str) -> tuple[str, int, float, str]:
    """Run one check; return (name, exit status, seconds, combined output)."""
    t0 = time.perf_counter()
    # The checks set sys.dont_write_bytecode themselves (-I ignores PYTHON*
    # variables); PYTHONDONTWRITEBYTECODE covers the export script the GUI
    # check starts without -I, so no __pycache__ appears in the package.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    proc = subprocess.run(
        [sys.executable, "-I", str(HERE / name)],
        capture_output=True, text=True, timeout=900, env=env,
    )
    return name, proc.returncode, time.perf_counter() - t0, proc.stdout + proc.stderr


def main() -> int:
    """Run all checks and return 0 only if every one passed."""
    serial = "--serial" in sys.argv[1:]
    workers = 1 if serial else len(CHECKS)
    print(f"Python {sys.version.split()[0]}  ({sys.executable})")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(run_one, CHECKS))

    print(f"\n{'check':32s} {'status':8s} {'seconds':>8s}")
    print("-" * 52)
    for name, rc, secs, _ in outcomes:
        print(f"{name:32s} {'PASS' if rc == 0 else 'FAIL':8s} {secs:8.1f}")
    bad = [o for o in outcomes if o[1] != 0]
    for name, _, _, out in bad:
        print(f"\n===== {name} output =====\n{out}")
    print("\nALL PASSED" if not bad else f"\n{len(bad)} CHECK(S) FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
