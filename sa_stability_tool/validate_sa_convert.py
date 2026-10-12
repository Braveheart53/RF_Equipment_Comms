#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of sa_convert.py with synthetic vendor-style export files.

===============================================================================
 Title          : SA Converter Validation
 Filename       : validate_sa_convert.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
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
Writes synthetic generic, Keysight-style, R&S-style (point and DECIMAL
COMMA), white-space-delimited files and a batch of trace snapshots into a
temporary folder, converts them and checks the detected kind, the values,
the full-precision round trip and the parallel batch. The files are
synthetic: confirm units against a real export from your own instrument
and firmware. Exit status 0 = all PASS, 1 = any FAIL.

REVISION HISTORY
----------------
0.0.1  (baseline)  As received; fixed import path, files in /tmp, no checks.
0.0.2  2026-10-11  Own folder, temporary folder, full header, Spyder cells.
0.0.3  2026-10-11  Every case asserts; new cases: decimal-comma R&S export,
                   white-space file, 10 GHz precision round trip, value
                   column check, parallel batch == serial; exit status.
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

_HERE = Path(globals().get("__file__") or "validate_sa_convert.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import sa_convert as sac  # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="sa_convert_check_"))
FAILURES = []
print("working folder:", TMP)


def check(ok: bool, label: str) -> bool:
    """Print and record one PASS/FAIL line."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)
    return ok


def read_back(path: Path) -> np.ndarray:
    """The two numeric columns of a canonical CSV."""
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)


freqs = np.logspace(0, 5, 30)  # 1 Hz to 100 kHz
lf = -20 * np.log10(freqs) - 60

# %% ===========================================================================
#    1. GENERIC CSV TIME SERIES AND TRACE
# =============================================================================
ts = 1e-9 * np.sin(np.arange(20) / 3.0)
(TMP / "generic_ts.csv").write_text("time_s,value\n" + "".join(
    f"{i * 1.0},{repr(float(v))}\n" for i, v in enumerate(ts)))
kind = sac.convert_to_canonical_csv(str(TMP / "generic_ts.csv"), str(TMP / "generic_ts_out.csv"))
back = read_back(TMP / "generic_ts_out.csv")
check(kind == "time_series" and np.array_equal(back[:, 1], ts), "generic time series: kind and exact values")
(TMP / "generic_trace.csv").write_text("freq_hz,l_f\n" + "".join(
    f"{a},{b}\n" for a, b in zip(freqs, lf)))
kind = sac.convert_to_canonical_csv(str(TMP / "generic_trace.csv"), str(TMP / "generic_trace_out.csv"))
check(kind == "freq_trace", "generic log-spaced trace -> freq_trace")

# %% ===========================================================================
#    2. KEYSIGHT-STYLE EXPORT WITH METADATA HEADER
# =============================================================================
(TMP / "keysight_export.csv").write_text(
    "Keysight PXA Phase Noise Measurement\nCarrier Frequency: 10000000000 Hz\n"
    "Frequency Offset (Hz),Phase Noise (dBc/Hz)\n" + "".join(f"{a},{b}\n" for a, b in zip(freqs, lf)))
kind = sac.convert_to_canonical_csv(str(TMP / "keysight_export.csv"), str(TMP / "keysight_out.csv"),
                                    vendor="keysight")
back = read_back(TMP / "keysight_out.csv")
check(kind == "freq_trace" and back.shape == (30, 2) and np.allclose(back[:, 1], lf, rtol=0, atol=1e-12),
      "Keysight-style export: 30 trace points read")

# %% ===========================================================================
#    3. R&S-STYLE SEMICOLON EXPORTS (DECIMAL POINT AND DECIMAL COMMA)
# =============================================================================
body = "".join(f"{a!r};{b!r};\n" for a, b in zip(map(float, freqs), map(float, lf)))
(TMP / "rs_export.dat").write_text("Type;FSWP Phase Noise;\nCenter Freq;10000000000;Hz\nValues;30;\n" + body)
kind = sac.convert_to_canonical_csv(str(TMP / "rs_export.dat"), str(TMP / "rs_out.csv"), vendor="rs")
back = read_back(TMP / "rs_out.csv")
check(kind == "freq_trace" and np.array_equal(back[:, 0], freqs), "R&S export (decimal point, trailing ';')")
(TMP / "rs_comma.dat").write_text("Type;FSWP Phase Noise;\nCenter Freq;10000000000;Hz\nValues;30;\n"
                                  + body.replace(".", ","))
kind = sac.convert_to_canonical_csv(str(TMP / "rs_comma.dat"), str(TMP / "rs_comma_out.csv"), vendor="rs")
back = read_back(TMP / "rs_comma_out.csv")
check(kind == "freq_trace" and back.shape == (30, 2) and np.array_equal(back[:, 0], freqs)
      and np.array_equal(back[:, 1], lf), "R&S export with DECIMAL COMMAS read exactly (0.0.1: no data)")

# %% ===========================================================================
#    4. WHITE-SPACE FILE, FULL PRECISION, VALUE COLUMN
# =============================================================================
f10 = 10e9 + np.array([0.0, 1.234e-3, 2.468e-3, 3.702e-3, 4.936e-3])
(TMP / "ws.txt").write_text("# counter log\n" + "".join(f"{i}   {v!r}\n" for i, v in enumerate(map(float, f10))))
kind = sac.convert_to_canonical_csv(str(TMP / "ws.txt"), str(TMP / "ws_out.csv"), value_column_name="freq_hz")
back = read_back(TMP / "ws_out.csv")
header = (TMP / "ws_out.csv").read_text().splitlines()[0]
check(kind == "time_series" and header == "time_s,freq_hz", "white-space file -> time_s,freq_hz")
check(np.array_equal(back[:, 1], f10), "10 GHz series round-trips bit-exact (0.0.1 lost 3.7 mHz)")
try:
    sac.convert_to_canonical_csv(str(TMP / "ws.txt"), str(TMP / "bad.csv"), value_column_name="volts")
    check(False, "unknown value column rejected")
except ValueError:
    check(True, "unknown value column rejected")

# %% ===========================================================================
#    5. BATCH MARKER EXTRACTION (SERIAL AND PARALLEL)
# =============================================================================
paths = []
rng = np.random.default_rng(3)
for k in range(12):
    p = TMP / "snapshot_{0:02d}.csv".format(k)
    freqs_k = np.linspace(9.999e9, 10.001e9, 50)
    amp_k = -50 - 20 * ((freqs_k - 1e10) ** 2) / 1e12 + rng.normal(0, 0.1, 50)
    p.write_text("freq_hz,amp_dbm\n" + "".join(f"{a},{b}\n" for a, b in zip(freqs_k, amp_k)))
    paths.append(str(p))
_, serial = sac.batch_extract_marker_time_series(paths[:6], vendor="generic")
_, parallel = sac.batch_extract_marker_time_series(paths, vendor="generic", workers=2)
print("peaks:", np.round(parallel, 3))
check(np.all(np.abs(serial + 50) < 1.0), "batch peaks near -50 dBm (6 files, serial)")
check(np.array_equal(parallel[:6], serial) and len(parallel) == 12, "12-file batch (parallel) = serial")

# %% ===========================================================================
#    SUMMARY
# =============================================================================
print("\n{0} failure(s)".format(len(FAILURES)))
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
