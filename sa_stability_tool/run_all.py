#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Run every validate_*.py script in parallel and summarise the results.

===============================================================================
 Title          : Validation Suite Runner
 Filename       : run_all.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-11
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : the package's own requirements (each script imports its own)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Development tool (not part of the GUI)
===============================================================================

LICENCE
-------
This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. It is distributed WITHOUT ANY WARRANTY; see the GNU
General Public License (file LICENSE) for details.

DESCRIPTION
-----------
Starts each validate_*.py in its own Python process (isolated: python -I),
several at a time, keeps every log, and prints one table:

    script | result | seconds | last line

PASS = exit 0, FAIL = non-zero, SKIP = exit 2 from
validate_vszh5_in_veusz.py (Veusz not importable in that interpreter),
TIMEOUT = killed after --timeout seconds. The exit status is 0 when nothing
FAILed or timed out.

validate_vszh5_in_veusz.py needs a Python that can import Veusz; give it
with --veusz-python (for example the conda environment that has
conda-forge 'veusz'). Set TIME_STABILITY_VEUSZ to also test the Veusz
program render.

USAGE
-----
    python run_all.py [--jobs N] [--timeout S] [--python EXE]
                      [--veusz-python EXE] [--logs DIR] [--only NAME ...]

REVISION HISTORY
----------------
0.0.3  2026-10-11  First version (package 0.0.3).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND PATHS
# =============================================================================
from __future__ import annotations

import argparse
import builtins
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

_HERE = Path(globals().get("__file__") or "run_all.py").resolve().parent

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

#: Longest-running scripts first, so they start as early as possible.
PREFERRED_ORDER = ("validate_core.py", "validate_vszh5_in_veusz.py", "validate_gui.py",
                   "validate_phase_noise.py", "validate_veusz_export.py",
                   "validate_sa_convert.py", "validate_stable32_export.py")


# %% ===========================================================================
#    RUNNER
# =============================================================================
def _cpus() -> int:
    getter = getattr(os, "sched_getaffinity", None)
    if getter is not None:
        try:
            return max(1, len(getter(0)))
        except OSError:  # pragma: no cover
            pass
    return max(1, os.cpu_count() or 1)


def run_one(script: Path, python: str, timeout: float, log_dir: Path) -> Tuple[str, str, float, str]:
    """Run one script; return (name, result, seconds, last output line)."""
    log = log_dir / (script.stem + ".log")
    env = dict(os.environ)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.perf_counter()
    try:
        res = subprocess.run([python, "-I", str(script)], cwd=str(script.parent), env=env,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout)
        out = res.stdout + ("\n--- stderr ---\n" + res.stderr if res.stderr.strip() else "")
        code: Optional[int] = res.returncode
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        code = None
    seconds = time.perf_counter() - t0
    log.write_text(out, encoding="utf-8")
    lines = [ln for ln in (res.stdout if code is not None else out).splitlines() if ln.strip()]
    last = lines[-1].strip() if lines else ""
    if code is None:
        result = "TIMEOUT"
    elif code == 0:
        result = "PASS"
    elif code == 2 and script.name == "validate_vszh5_in_veusz.py":
        result = "SKIP"
    else:
        result = f"FAIL ({code})"
    return script.name, result, seconds, last


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the suite; return the exit status."""
    p = argparse.ArgumentParser(description="Run every validate_*.py of the package.")
    p.add_argument("--jobs", type=int, default=_cpus(), help="scripts at a time (default: CPUs)")
    p.add_argument("--timeout", type=float, default=1800.0, help="seconds per script")
    p.add_argument("--python", default=sys.executable, help="interpreter for the scripts")
    p.add_argument("--veusz-python", default="", help="interpreter for validate_vszh5_in_veusz.py")
    p.add_argument("--logs", default="", help="folder for the logs (default: a temporary one)")
    p.add_argument("--only", nargs="*", default=None, help="run only these script names")
    args = p.parse_args(argv)

    scripts = sorted(_HERE.glob("validate_*.py"),
                     key=lambda s: (PREFERRED_ORDER.index(s.name) if s.name in PREFERRED_ORDER else 99, s.name))
    if args.only:
        scripts = [s for s in scripts if s.name in args.only or s.stem in args.only]
    log_dir = Path(args.logs) if args.logs else Path(tempfile.mkdtemp(prefix="sa_stability_logs_"))
    log_dir.mkdir(parents=True, exist_ok=True)
    print(f"SA Time Stability Tools validation (run_all {__version__}): {len(scripts)} scripts, "
          f"{args.jobs} at a time, python {args.python}")

    def job(s: Path) -> Tuple[str, str, float, str]:
        py = args.veusz_python if (s.name == "validate_vszh5_in_veusz.py" and args.veusz_python) else args.python
        return run_one(s, py, args.timeout, log_dir)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        rows: List[Tuple[str, str, float, str]] = list(pool.map(job, scripts))
    width = max(len(r[0]) for r in rows) if rows else 10
    print(f"\n{'script':<{width}}  {'result':<9} {'s':>7}  last line")
    print("-" * (width + 60))
    for name, result, seconds, last in rows:
        print(f"{name:<{width}}  {result:<9} {seconds:7.1f}  {last[:70]}")
    bad = [r for r in rows if r[1].startswith(("FAIL", "TIMEOUT"))]
    print(f"\n{len(rows) - len(bad)} of {len(rows)} passed or skipped in "
          f"{time.perf_counter() - t0:.1f} s; logs in {log_dir}")
    return 1 if bad else 0


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    _status = main()
    if not getattr(builtins, "__IPYTHON__", False):
        sys.exit(_status)
