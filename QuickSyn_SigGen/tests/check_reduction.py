# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Reduction maths checks.

Part of the QuickSyn SCPI controller package, version 0.0.7.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_reduction.py``) or through ``tests/run_all.py``.
Needs no instrument, no display and no Veusz.

What it checks
---------------
Achieved rate, interval jitter and the overlapping Allan deviation against a
direct O(Nm) summation, and the moving statistics against numpy.convolve.
The Veusz output is checked separately, by check_vszh5.py. (Up to 0.0.3
this file also drove a mock of the embedded Veusz interface; 0.0.4 writes
the .vszh5 directly, so that mock no longer tests anything real.)
"""

import sys
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree
import numpy as np

import quicksyn_veusz_export_v0_0_7 as red

# ---- build a synthetic session ------------------------------------------
n = 600
rec = np.zeros(n, dtype=red.TELEMETRY_DTYPE)
rec["idx"] = np.arange(n)
rec["t_mono"] = np.arange(n) * 0.1
rec["t_unix"] = 1.9e9 + rec["t_mono"]
rec["freq_hz"] = 1.0e10 + np.random.default_rng(7).normal(0, 2.0, n)
rec["power_dbm"] = -4.2
rec["temp_c"] = 30 + 8 * (1 - np.exp(-rec["t_mono"] / 90))
rec["status"] = 0xA8
rec["modmask"] = 0x10
rec["latency_s"] = 0.004
rec["rate_hz"] = 10.0

stats = red.reduce_session(rec, "synthetic",
                           {"sampler": {"rate_hz": 10.0}}, use_gpu=False)
assert stats.n_samples == n
assert abs(stats.achieved_rate_hz - 10.0) < 1e-6, stats.achieved_rate_hz
assert stats.adev and len(stats.adev) == len(stats.adev_tau_s)
assert all(d > 0 for d in stats.adev), stats.adev
print(f"reduction ........................ OK  {stats.n_samples} samples, "
      f"{stats.achieved_rate_hz:.4f} Hz, {len(stats.adev)} ADEV points")
print(f"                                   ADEV tau = "
      f"{[round(t,2) for t in stats.adev_tau_s]} s")
print(f"                                   ADEV     = "
      f"{['%.2e' % d for d in stats.adev]}")

# ---- ADEV cross-check against a direct O(N*m) implementation ------------
y = (rec["freq_hz"] - np.median(rec["freq_hz"])) / np.median(rec["freq_hz"])
tau0 = stats.interval_mean_s
def adev_reference(y, tau0, m):
    """Textbook overlapping ADEV, equation (2), evaluated directly."""
    N = y.size
    x = np.concatenate(([0.0], np.cumsum(y) * tau0))
    total, count = 0.0, N - 2 * m + 1
    for k in range(count):
        total += (x[k + 2 * m] - 2 * x[k + m] + x[k]) ** 2
    return np.sqrt(total / (2 * count * (m * tau0) ** 2))
for i, m in enumerate([1, 2, 4, 8]):
    ref = adev_reference(y, tau0, m)
    got = stats.adev[i]
    assert abs(ref - got) / ref < 1e-9, (m, ref, got)
print(f"ADEV vs direct summation ......... OK  4 averaging factors agree "
      f"to <1e-9 relative")

# ---- moving statistics cross-check --------------------------------------
mean, std = red.moving_statistics(rec["temp_c"].astype(float), 50)
ref_mean = np.convolve(rec["temp_c"].astype(float), np.ones(50) / 50, "valid")
assert np.allclose(mean, ref_mean, atol=1e-9)
assert mean.size == n - 50 + 1 and std.size == mean.size
print("moving statistics ................ OK  matches np.convolve")

print("\nALL REDUCTION CHECKS PASSED")
