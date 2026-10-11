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
 Version        : 0.0.2  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.2
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
Writes synthetic generic, Keysight-style and R&S-style export files and a
batch of trace snapshots into a temporary folder, converts them, and
prints the detected kind (time series vs frequency trace) and the peak
values. The files are synthetic: confirm units against a real export
from your own instrument and firmware.

REVISION HISTORY
----------------
0.0.1  (baseline)  As received; fixed import path, files in /tmp.
0.0.2  2026-10-11  Imports from its own folder; files in a temporary
                   folder (works on Windows); full header; Spyder cells.
                   Tests unchanged.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

_HERE = Path(globals().get("__file__") or "validate_sa_convert.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import sa_convert as sac  # noqa: E402

__version__ = "0.0.2"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="sa_convert_check_"))
print("working folder:", TMP)

# %% ===========================================================================
#    1. GENERIC CSV TIME SERIES
# =============================================================================
with open(TMP / "generic_ts.csv", "w") as f:
    f.write("time_s,value\n")
    for i in range(20):
        f.write("{0},{1}\n".format(i * 1.0, 1e-9 * np.sin(i / 3.0)))
kind = sac.convert_to_canonical_csv(str(TMP / "generic_ts.csv"), str(TMP / "generic_ts_out.csv"), vendor="generic")
print("Generic time-series CSV -> kind detected:", kind, "(expect time_series)")
print(open(TMP / "generic_ts_out.csv").read()[:150])

# %% ===========================================================================
#    2. GENERIC CSV FREQUENCY (PHASE-NOISE) TRACE
# =============================================================================
freqs = np.logspace(0, 5, 30)  # 1 Hz to 100 kHz - large span_ratio > 1e3
lf = -20 * np.log10(freqs) - 60
with open(TMP / "generic_trace.csv", "w") as f:
    f.write("freq_hz,l_f\n")
    for a, b in zip(freqs, lf):
        f.write("{0},{1}\n".format(a, b))
kind2 = sac.convert_to_canonical_csv(str(TMP / "generic_trace.csv"), str(TMP / "generic_trace_out.csv"), vendor="generic")
print("\nGeneric freq-trace CSV -> kind detected:", kind2, "(expect freq_trace)")

# %% ===========================================================================
#    3. KEYSIGHT-STYLE EXPORT WITH METADATA HEADER
# =============================================================================
with open(TMP / "keysight_export.csv", "w") as f:
    f.write("Keysight PXA Phase Noise Measurement\n")
    f.write("Carrier Frequency: 10000000000 Hz\n")
    f.write("Frequency Offset (Hz),Phase Noise (dBc/Hz)\n")
    for a, b in zip(freqs, lf):
        f.write("{0},{1}\n".format(a, b))
kind3 = sac.convert_to_canonical_csv(str(TMP / "keysight_export.csv"), str(TMP / "keysight_out.csv"), vendor="keysight")
print("\nKeysight-style export -> kind detected:", kind3, "(expect freq_trace)")
print(open(TMP / "keysight_out.csv").read()[:150])

# %% ===========================================================================
#    4. R&S-STYLE SEMICOLON-DELIMITED EXPORT
# =============================================================================
with open(TMP / "rs_export.dat", "w") as f:
    f.write("Type;FSWP Phase Noise\n")
    f.write("Center Freq;10000000000 Hz\n")
    f.write("Values\n")
    for a, b in zip(freqs, lf):
        f.write("{0};{1}\n".format(a, b))
kind4 = sac.convert_to_canonical_csv(str(TMP / "rs_export.dat"), str(TMP / "rs_out.csv"), vendor="rs")
print("\nR&S-style export -> kind detected:", kind4, "(expect freq_trace)")
print(open(TMP / "rs_out.csv").read()[:150])

# %% ===========================================================================
#    5. BATCH MARKER EXTRACTION FROM SNAPSHOT FILES
# =============================================================================
paths = []
rng = np.random.default_rng(3)
for k in range(6):
    p = TMP / "snapshot_{0}.csv".format(k)
    freqs_k = np.linspace(9.999e9, 10.001e9, 50)
    amp_k = -50 - 20 * ((freqs_k - 1e10) ** 2) / 1e12 + rng.normal(0, 0.1, 50)
    with open(p, "w") as f:
        f.write("freq_hz,amp_dbm\n")
        for a, b in zip(freqs_k, amp_k):
            f.write("{0},{1}\n".format(a, b))
    paths.append(str(p))
t_idx, peak_vals = sac.batch_extract_marker_time_series(paths, vendor="generic", marker_index=0)
print("\nBatch marker extraction peak values (should hover near -50 dBm):", peak_vals)

print("\nALL sa_convert.py smoke tests completed without exceptions.")
