#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of phase_noise.py: L(f) slopes of synthetic power-law series.

===============================================================================
 Title          : Phase-Noise Validation
 Filename       : validate_phase_noise.py
 Version        : 0.0.2  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.2
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : numpy, scipy
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
Checks that phase_noise.py recovers the correct L(f) slope (dB/decade) for
synthetic power-law phase series with a known S_y(f) exponent, prints a
sample of the log-binned noise classification, and checks that
l_f_to_sy() returns finite positive values [1].

REFERENCES
----------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf

REVISION HISTORY
----------------
0.0.1  (baseline)  As received; imported from a fixed path.
0.0.2  2026-10-11  Imports from its own folder; full header; Spyder cells.
                   Tests unchanged.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(globals().get("__file__") or "validate_phase_noise.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import phase_noise as pn      # noqa: E402
import stability_core as sc   # noqa: E402

__version__ = "0.0.2"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TAU0 = 0.01   # 100 Hz sample rate SA long-time-measurement
N = 65536
F0 = 10e6     # 10 MHz reference

# %% ===========================================================================
#    L(f) SLOPE FOR THREE NOISE TYPES
# =============================================================================
# alpha is Sy(f) exponent; expected L(f) slope (dB/decade) for a few canonical types
cases = [
    ("White FM",   0, -20),
    ("Flicker FM", -1, -30),
    ("Random Walk FM", -2, -40),
]

for label, alpha, expected_lf_slope in cases:
    x = sc.generate_power_law_phase(N, TAU0, alpha=alpha, seed=17)
    res = pn.ssb_phase_noise_from_time_series(x, TAU0, F0, window="hann")
    # fit slope over a mid-band decade, away from DC and Nyquist edges
    f = res.freq_hz
    lf = res.l_f_dbc_hz
    lo = np.searchsorted(f, 1.0)
    hi = np.searchsorted(f, 10.0)
    if hi <= lo + 2:
        hi = lo + 5
    slope = np.polyfit(np.log10(f[lo:hi]), lf[lo:hi], 1)[0]
    print(f"{label:>16}: expected L(f) slope={expected_lf_slope:+d} dB/decade  measured={slope:+.2f}  "
          f"({'OK' if abs(slope - expected_lf_slope) < 2.0 else 'CHECK'})")

# %% ===========================================================================
#    LOG-BINNED NOISE CLASSIFICATION (WHITE FM)
# =============================================================================
print()
print("Noise-ID classification check (log-binned, White FM case):")
x = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=17)
res = pn.ssb_phase_noise_from_time_series(x, TAU0, F0, window="hann")
classes = pn.classify_freq_domain_noise(res, points_per_decade=8)
mid = len(classes) // 2
for c in classes[mid:mid + 5]:
    print(f"  f=[{c.f_lo_hz:.2f}, {c.f_hi_hz:.2f}] Hz  slope={c.slope_db_per_decade:+.2f} dB/dec  -> {c.noise_type}")

# %% ===========================================================================
#    L(f) -> S_y(f) CONVERSION
# =============================================================================
print()
print("l_f_to_sy round-trip sanity check:")
sy = pn.l_f_to_sy(res.l_f_dbc_hz, res.freq_hz, F0)
print(f"  Sy(f) range: {sy.min():.3e} to {sy.max():.3e} (should be positive, finite)")
