#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of stable32_export.py: format, gaps, atomic write, round trip.

===============================================================================
 Title          : Stable32 Export Validation
 Filename       : validate_stable32_export.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-11
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : numpy
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Development validation script (not part of the GUI)
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
The 0.0.1 README said the Stable32 writer had been round-tripped, but no
script for it was shipped. This one checks: phase and frequency files read
back (16 significant digits), the gap = 0 convention with a gap count, the
rejection of a first/last-point gap BEFORE anything is written (no file,
no .part, an existing file untouched), the value-only layout
(timetags=False), the header file name, and the sigma-tau table (NaN rows
skipped). Reading the files in Stable32 itself was not possible here.
Exit status 0 = all PASS, 1 = any FAIL.

REVISION HISTORY
----------------
0.0.3  2026-10-11  First version (package 0.0.3).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import builtins
import sys
import tempfile
from pathlib import Path

import numpy as np

_HERE = Path(globals().get("__file__") or "validate_stable32_export.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import stable32_export as s32  # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="stable32_check_"))
FAILURES = []


def check(ok: bool, label: str) -> bool:
    """Print and record one PASS/FAIL line."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)
    return ok


def data_lines(path: Path) -> list:
    """Non-comment lines of a written file."""
    return [ln for ln in path.read_text().splitlines() if ln and not ln.startswith("#")]


# %% ===========================================================================
#    1. PHASE AND FREQUENCY FILES READ BACK
# =============================================================================
t = np.arange(1000, dtype=float)
x = 1e-9 * np.sin(t / 37.0) + 3e-12 * t
s32.write_stable32_phase_file(str(TMP / "p.PHD"), t, x, title="phase test")
back = np.loadtxt(TMP / "p.PHD", comments="#")
check(back.shape == (1000, 2), "phase file: 1000 rows of timetag + value")
check(np.allclose(back[:, 1], x, rtol=1e-15, atol=0), "phase values to 16 significant digits")
check(np.array_equal(back[:, 0], t), "time tags read back")
head = (TMP / "p.PHD").read_text().splitlines()[:6]
check(head[0] == "# File: p.PHD" and "# Title: phase test" in head, "header names the file and title")
y = np.diff(x)
s32.write_stable32_freq_file(str(TMP / "f.FRD"), t[:-1], y)
check(np.allclose(np.loadtxt(TMP / "f.FRD", comments="#")[:, 1], y, rtol=1e-15, atol=0),
      "frequency file read back")
s32.write_stable32_phase_file(str(TMP / "v.PHD"), t, x, timetags=False)
check(np.loadtxt(TMP / "v.PHD", comments="#").ndim == 1, "timetags=False writes the value column only")

# %% ===========================================================================
#    2. GAPS
# =============================================================================
xg = x.copy()
xg[[10, 11, 500]] = np.nan
s32.write_stable32_phase_file(str(TMP / "g.PHD"), t, xg)
rows = np.loadtxt(TMP / "g.PHD", comments="#")
check(np.all(rows[[10, 11, 500], 1] == 0.0), "interior gaps written as 0")
check("# Gaps written as 0: 3" in (TMP / "g.PHD").read_text(), "gap count in the header")

(TMP / "keep.PHD").write_text("previous content\n")
for idx, name in ((0, "first"), (-1, "last")):
    bad = x.copy()
    bad[idx] = np.nan
    try:
        s32.write_stable32_phase_file(str(TMP / "keep.PHD"), t, bad)
        check(False, f"{name}-point gap rejected")
    except ValueError:
        check(True, f"{name}-point gap rejected")
check((TMP / "keep.PHD").read_text() == "previous content\n",
      "rejected write leaves the existing file untouched (0.0.1 truncated it)")
check(not (TMP / "keep.PHD.part").exists(), "no .part file left behind")
try:
    s32.write_stable32_phase_file(str(TMP / "new.PHD"), t, np.r_[x[:-1], np.nan])
except ValueError:
    pass
check(not (TMP / "new.PHD").exists(), "rejected write creates no file (0.0.1 left a partial one)")

# %% ===========================================================================
#    3. SIGMA-TAU TABLE
# =============================================================================
rows_in = [(1.0, 1, 999, 1.2e-11), (2.0, 2, 997, float("nan")), (4.0, 4, 993, 6.1e-12)]
s32.write_stable32_sigma_tau_table(str(TMP / "t.DAT"), rows_in, columns=("tau_s", "m", "n", "adev"))
lines = data_lines(TMP / "t.DAT")
check(len(lines) == 2 and lines[0].split("\t")[1] == "1", "table: NaN row skipped, integers kept")
check("# Rows skipped (non-finite value): 1" in (TMP / "t.DAT").read_text(), "skipped rows counted")
try:
    s32.write_stable32_sigma_tau_table(str(TMP / "t9.DAT"), [], columns=tuple("abcdefghi"))
    check(False, "more than 8 columns rejected")
except ValueError:
    check(True, "more than 8 columns rejected")

# %% ===========================================================================
#    SUMMARY
# =============================================================================
print("\n{0} failure(s)".format(len(FAILURES)))
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
