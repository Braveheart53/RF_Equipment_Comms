#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of phase_noise.py: L(f) slopes and noise identification.

===============================================================================
 Title          : Phase-Noise Validation
 Filename       : validate_phase_noise.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
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
  1. L(f) slope over 1-10 Hz for white, flicker and random-walk FM, each
     averaged over three INDEPENDENT seeds. (0.0.1 used one seed for all
     three noise types, so all three slopes shared the same -0.8 dB/decade
     realisation error.)
  2. Noise identification on five noise types x three seeds in the
     0.05-20 Hz band: fraction of segments named correctly (>= 90 %
     required; 0.0.2's two-bin method reached 67 % on the same records).
  3. l_f_to_sy(): S_y = (f/f0)^2 * 2 * 10^(L/10) checked at three points.
Exit status 0 = all PASS, 1 = any FAIL.

REFERENCES
----------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf
[2] IEEE Std 1139-2008, doi: 10.1109/IEEESTD.2008.4797525.

REVISION HISTORY
----------------
0.0.1  (baseline)  As received; imported from a fixed path.
0.0.2  2026-10-11  Imports from its own folder; full header; Spyder cells.
0.0.3  2026-10-11  Independent seeds; classification accuracy test for the
                   windowed slope fit; l_f_to_sy() checked against the
                   formula; PASS/FAIL exit status.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import builtins
import sys
from pathlib import Path

import numpy as np

_HERE = Path(globals().get("__file__") or "validate_phase_noise.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import phase_noise as pn      # noqa: E402
import stability_core as sc   # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TAU0 = 0.01   # 100 Hz sample rate SA long-time-measurement
N = 65536
F0 = 10e6     # 10 MHz reference
FAILURES = []


def check(ok: bool, label: str) -> bool:
    """Print and record one PASS/FAIL line."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)
    return ok


# %% ===========================================================================
#    1. L(f) SLOPE FOR THREE NOISE TYPES (INDEPENDENT SEEDS)
# =============================================================================
cases = [("White FM", 0, -20), ("Flicker FM", -1, -30), ("Random Walk FM", -2, -40)]
for label, alpha, expected in cases:
    slopes = []
    for seed in (101 + 10 * alpha, 202 + 10 * alpha, 303 + 10 * alpha):
        x = sc.generate_power_law_phase(N, TAU0, alpha=alpha, seed=seed)
        res = pn.ssb_phase_noise_from_time_series(x, TAU0, F0, window="hann")
        lo, hi = np.searchsorted(res.freq_hz, 1.0), np.searchsorted(res.freq_hz, 10.0)
        slopes.append(np.polyfit(np.log10(res.freq_hz[lo:hi]), res.l_f_dbc_hz[lo:hi], 1)[0])
    mean = float(np.mean(slopes))
    print(f"{label:>16}: expected {expected:+d} dB/decade, measured "
          f"{', '.join(f'{v:+.2f}' for v in slopes)} (mean {mean:+.2f})")
    check(abs(mean - expected) < 1.5, f"{label} mean L(f) slope within 1.5 dB/decade")

# %% ===========================================================================
#    2. NOISE IDENTIFICATION ACCURACY
# =============================================================================
print()
correct, total = 0, 0
for label, alpha in [("White PM", 2), ("Flicker PM", 1), ("White FM", 0),
                     ("Flicker FM", -1), ("Random Walk FM", -2)]:
    for seed in (17, 18, 19):
        x = sc.generate_power_law_phase(N, TAU0, alpha=alpha, seed=seed)
        res = pn.ssb_phase_noise_from_time_series(x, TAU0, F0)
        mid = [c for c in pn.classify_freq_domain_noise(res)
               if 0.05 <= c.f_lo_hz and c.f_hi_hz <= 20.0]
        correct += sum(c.noise_type == label for c in mid)
        total += len(mid)
frac = correct / total
print(f"Segments named correctly: {correct}/{total} = {frac * 100:.0f} % "
      f"(0.0.2 two-bin method: 67 % on the same records)")
check(frac >= 0.90, "noise identification >= 90 % on synthetic power-law noise")

# %% ===========================================================================
#    3. L(f) -> S_y(f) CONVERSION
# =============================================================================
print()
f = np.array([1.0, 10.0, 100.0])
lf = np.array([-100.0, -120.0, -140.0])
sy = pn.l_f_to_sy(lf, f, F0)
expect = (f / F0) ** 2 * 2.0 * 10.0 ** (lf / 10.0)
print("S_y(f):", sy)
check(np.allclose(sy, expect, rtol=1e-15, atol=0) and np.all(sy > 0), "l_f_to_sy() = IEEE 1139 formula")

# %% ===========================================================================
#    SUMMARY
# =============================================================================
print("\n{0} failure(s)".format(len(FAILURES)))
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
