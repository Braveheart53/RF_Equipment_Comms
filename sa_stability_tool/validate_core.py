#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of stability_core.py against allantools and known noise slopes.

===============================================================================
 Title          : Stability Core Validation
 Filename       : validate_core.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : numpy, allantools (reference implementation)
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
Dev-time validation, not part of the delivered tool. Cross-checks
stability_core.py against allantools [1] and the expected power-law slopes
[2], [3]:

  TEST 1   OADEV / MDEV / OHDEV vs allantools (white FM)
  TEST 2   TDEV = tau / sqrt(3) * MDEV vs allantools
  TEST 3   non-overlapping ADEV consistent with OADEV
  TEST 4   noise type recovered from the ADEV slope (five noise types)
  TEST 5   Thêo1 unbiased vs OADEV at tau_eff = 0.75 m tau0 (white FM)
  TEST 6   ThêoH grid per Howe [4] eq. 7 and coverage to ~75 % of the record
  TEST 7   Thêo1 vs allantools.theo1 (same SP1065 eq. 30)                0.0.3
  TEST 8   parallel == serial (AVAR sweep, Thêo1, ThêoH); BLAS-free path  0.0.3
  TEST 9   frequency CSVs: len(t) == len(x), source column, f0           0.0.3
  TEST 10  linear frequency drift detected; Flicker-Walk FM not          0.0.3
  TEST 11  drift fit = np.polyfit; D = 2 a2 recovered                    0.0.3

Exit status 0 = all PASS, 1 = any FAIL. Run:  python validate_core.py
(or cell by cell in Spyder).

REFERENCES
----------
[1] "Allantools Documentation." https://allantools.readthedocs.io/
[2] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf
[3] IEEE Std 1139-2008, doi: 10.1109/IEEESTD.2008.4797525.
[4] D. A. Howe, "ThêoH: a hybrid, high-confidence statistic that improves
    on the Allan deviation," Metrologia, vol. 43, no. 4, pp. S322-S331,
    2006, doi: 10.1088/0026-1394/43/4/S20.

REVISION HISTORY
----------------
0.0.1  (baseline)  As received; imported from a fixed path.
0.0.2  2026-10-11  Imports from its own folder; full header; Spyder cells.
0.0.3  2026-10-11  PASS/FAIL recorded and returned as the exit status; TEST 4
                   and TEST 6 now assert; TESTS 7-11 added for the 0.0.3
                   fixes and the parallel engine.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import builtins
import math
import sys
import tempfile
import time
from pathlib import Path

import allantools
import numpy as np

_HERE = Path(globals().get("__file__") or "validate_core.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import stability_core as sc  # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TAU0 = 1.0
N = 20000
FAILURES = []


def check(ok: bool, label: str) -> bool:
    """Print and record one PASS/FAIL line."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)
    return ok


def rel(a: float, b: float) -> float:
    """Relative difference |a - b| / |b|."""
    return abs(a - b) / abs(b)


# %% ===========================================================================
#    TEST 1: OADEV / MDEV / OHDEV AGAINST ALLANTOOLS
# =============================================================================
print("=" * 70)
print("TEST 1: Cross-check OADEV/MDEV/OHDEV/TDEV against allantools")
print("=" * 70)
x = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=7)  # white FM
m_values = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
taus = [m * TAU0 for m in m_values]
rate = 1.0 / TAU0
_, at_oadev, _, _ = allantools.oadev(x, rate=rate, data_type="phase", taus=taus)
_, at_mdev, _, _ = allantools.mdev(x, rate=rate, data_type="phase", taus=taus)
_, at_ohdev, _, _ = allantools.ohdev(x, rate=rate, data_type="phase", taus=taus)
_, at_tdev, _, _ = allantools.tdev(x, rate=rate, data_type="phase", taus=taus)

print(f"{'m':>6} {'my_OADEV':>14} {'at_OADEV':>14} {'rel.err%':>10}   "
      f"{'my_MDEV':>14} {'at_MDEV':>14} {'rel.err%':>10}   "
      f"{'my_OHDEV':>14} {'at_OHDEV':>14} {'rel.err%':>10}")
max_rel_err = 0.0
for i, m in enumerate(m_values):
    my_oa, _ = sc.oadev(x, TAU0, m)
    my_md, _ = sc.mdev(x, TAU0, m)
    my_oh, _ = sc.ohdev(x, TAU0, m)
    re_oa = rel(my_oa, at_oadev[i]) * 100
    re_md = rel(my_md, at_mdev[i]) * 100
    re_oh = rel(my_oh, at_ohdev[i]) * 100
    max_rel_err = max(max_rel_err, re_oa, re_md, re_oh)
    print(f"{m:>6} {my_oa:>14.6e} {at_oadev[i]:>14.6e} {re_oa:>9.4f}%   "
          f"{my_md:>14.6e} {at_mdev[i]:>14.6e} {re_md:>9.4f}%   "
          f"{my_oh:>14.6e} {at_ohdev[i]:>14.6e} {re_oh:>9.4f}%")
print(f"\nMax relative error across all m, all estimators: {max_rel_err:.6f}%")
check(max_rel_err < 0.01, "OADEV/MDEV/OHDEV = allantools (< 0.01 %)")

# %% ===========================================================================
#    TEST 2: TDEV = tau / sqrt(3) * MDEV
# =============================================================================
print()
print("=" * 70)
print("TEST 2: TDEV formula check (TDEV = tau/sqrt(3) * MDEV)")
print("=" * 70)
max_rel_err_tdev = 0.0
for i, m in enumerate(m_values):
    my_md, _ = sc.mdev(x, TAU0, m)
    max_rel_err_tdev = max(max_rel_err_tdev, rel(sc.tdev_from_mdev(my_md, m * TAU0), at_tdev[i]) * 100)
print(f"Max relative error TDEV vs allantools: {max_rel_err_tdev:.6f}%")
check(max_rel_err_tdev < 0.01, "TDEV = allantools (< 0.01 %)")

# %% ===========================================================================
#    TEST 3: NON-OVERLAPPING ADEV VS OADEV
# =============================================================================
print()
print("=" * 70)
print("TEST 3: Non-overlapping ADEV sanity check (noisier but consistent with OADEV)")
print("=" * 70)
for m in [4, 16, 64]:
    a_val, a_n = sc.adev_nonoverlapping(x, TAU0, m)
    oa_val, oa_n = sc.oadev(x, TAU0, m)
    ratio = a_val / oa_val
    print(f"m={m:4d}  ADEV={a_val:.4e} (n={a_n:4d})  OADEV={oa_val:.4e} (n={oa_n:4d})  ratio={ratio:.3f}")
    check(0.9 < ratio < 1.1, f"ADEV/OADEV within 10 % at m={m}")

# %% ===========================================================================
#    TEST 4: NOISE TYPE FROM THE ADEV SLOPE
# =============================================================================
print()
print("=" * 70)
print("TEST 4: Noise-type slope vs injected noise type (tau = 8..16 octave)")
print("=" * 70)
noise_cases = [("White PM", 2), ("Flicker PM", 1), ("White FM", 0),
               ("Flicker FM", -1), ("Random Walk FM", -2)]
expected_mu = dict((n, mu) for n, _a, mu, _m in sc.NOISE_TABLE)
for label, alpha in noise_cases:
    xn = sc.generate_power_law_phase(N, TAU0, alpha=alpha, seed=99)
    pts = sc.compute_all_deviations(xn, TAU0, m_values=[2, 4, 8, 16, 32, 64, 128])
    log_t = [math.log10(p.tau) for p in pts]
    log_a = [math.log10(p.oadev) for p in pts]
    idx = 2  # tau = 8..16 octave, away from both ends
    slope = (log_a[idx + 1] - log_a[idx]) / (log_t[idx + 1] - log_t[idx])
    print(f"{label:>18}: expected ADEV slope mu={expected_mu[label]:+.2f}, measured mu={slope:+.2f}")
    check(abs(slope - expected_mu[label]) < 0.35, f"{label} ADEV slope within 0.35")

# %% ===========================================================================
#    TEST 5: THEO1 UNBIASED VS OADEV AT TAU_EFF (WHITE FM)
# =============================================================================
print()
print("=" * 70)
print("TEST 5: Thêo1 vs OADEV at the matched stride tau = 0.75 m tau0 (white FM)")
print("=" * 70)
xw = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=55)
for m in [20, 40, 80, 200]:
    tau_eff = sc.theo1_effective_tau(TAU0, m)
    oa_at_eff, _ = sc.oadev(xw, TAU0, int(round(tau_eff / TAU0)))
    th1_val, _ = sc.theo1(xw, TAU0, m)
    ratio = th1_val / oa_at_eff
    print(f"m={m:4d}  tau_eff={tau_eff:7.1f}s  OADEV(tau_eff)={oa_at_eff:.4e}  "
          f"THEO1(m)={th1_val:.4e}  ratio={ratio:.3f}")
    check(0.9 < ratio < 1.1, f"Thêo1/OADEV(tau_eff) within 10 % at m={m}")

# %% ===========================================================================
#    TEST 6: THEOH GRID (HOWE EQ. 7) AND TAU COVERAGE
# =============================================================================
print()
print("=" * 70)
print("TEST 6: ThêoH hybrid family - grid per Howe eq. 7 and coverage (white FM)")
print("=" * 70)
family = sc.compute_theoh_family(xw, TAU0, stitch_frac=0.1)
for tau, m, val, label in family:
    marker = "  <-- beyond OADEV's tau=N/2 limit" if tau > 0.5 * N * TAU0 else ""
    print(f"tau={tau:9.1f}s  m={m:6d}  {label:8s} dev={val:.4e}{marker}")
Nx = len(xw)                      # generate_power_law_phase(N) gives N + 1 points
k = int(0.1 * Nx)
avar_m = [m for _t, m, _v, s in family if s == "AVAR"]
theo_m = [m for _t, m, _v, s in family if s != "AVAR"]
coverage = family[-1][0] / ((Nx - 1) * TAU0)
print(f"Max tau reached: {family[-1][0]:.1f}s = {coverage * 100:.1f}% of record (OADEV: 50%).")
check(max(avar_m) < k, f"AVAR part uses m < k = {k}")
check(min(theo_m) >= math.ceil(k / 0.75) and all(m % 2 == 0 for m in theo_m),
      "ThêoBR part starts at m >= k/0.75 and uses even m")
check(max(theo_m) == (Nx - 1) - ((Nx - 1) % 2), "ThêoBR grid ends at the largest even m <= N-1")
check(coverage > 0.74, "ThêoH reaches ~75 % of the record")

# %% ===========================================================================
#    TEST 7: THEO1 AGAINST ALLANTOOLS.THEO1
# =============================================================================
print()
print("=" * 70)
print("TEST 7: Thêo1 vs allantools.theo1 (same SP1065 eq. 30, independent code)")
print("=" * 70)
xs = xw[:600]
t_at, d_at, _, _ = allantools.theo1(xs, rate=1.0, data_type="phase", taus=[10.0, 20.0, 50.0, 100.0])
worst = 0.0
for tau, d in zip(t_at, d_at):
    mine = sc.theo1(xs, 1.0, int(round(tau)))[0]
    worst = max(worst, rel(mine, d))
    print(f"m={int(round(tau)):4d}  allantools={d:.12e}  ours={mine:.12e}")
check(worst < 1e-12, f"Thêo1 = allantools.theo1 (worst rel. diff {worst:.1e})")

# %% ===========================================================================
#    TEST 8: PARALLEL == SERIAL; BLAS-FREE KERNEL
# =============================================================================
print()
print("=" * 70)
print("TEST 8: thread-pool results equal the serial ones (rounding only)")
print("=" * 70)
xl = sc.generate_power_law_phase(60000, 1.0, alpha=-1, seed=3)   # >= PARALLEL_MIN_N
t0 = time.perf_counter(); p1 = sc.compute_all_deviations(xl, 1.0, workers=1); t_s = time.perf_counter() - t0
t0 = time.perf_counter(); p2 = sc.compute_all_deviations(xl, 1.0, workers=4); t_p = time.perf_counter() - t0
same = all((a.oadev == b.oadev or (math.isnan(a.oadev) and math.isnan(b.oadev))) and
           (a.ohdev == b.ohdev or (math.isnan(a.ohdev) and math.isnan(b.ohdev))) for a, b in zip(p1, p2))
check(same, f"AVAR sweep identical (serial {t_s:.3f} s, 4 threads {t_p:.3f} s)")
t0 = time.perf_counter(); v1 = sc.theo1(xl, 1.0, 8000, workers=1)[0]; t_s = time.perf_counter() - t0
t0 = time.perf_counter(); v2 = sc.theo1(xl, 1.0, 8000, workers=4)[0]; t_p = time.perf_counter() - t0
check(rel(v2, v1) < 1e-12, f"Thêo1(m=8000) threaded = serial, rel {rel(v2, v1):.1e} "
                           f"(serial {t_s:.2f} s, 4 threads {t_p:.2f} s)")
t0 = time.perf_counter(); f1 = sc.compute_theoh_family(xl, 1.0, workers=1); t_s = time.perf_counter() - t0
t0 = time.perf_counter(); f2 = sc.compute_theoh_family(xl, 1.0, workers=4); t_p = time.perf_counter() - t0
check(len(f1) == len(f2) and max(rel(b[2], a[2]) for a, b in zip(f1, f2)) < 1e-12,
      f"ThêoH threaded = serial ({len(f1)} points; serial {t_s:.1f} s, 4 threads {t_p:.1f} s, "
      f"{sc.available_cpus()} CPU(s))")
saved = sc._threadpool_limits
sc._threadpool_limits = None                     # force the einsum kernel
try:
    v3 = sc.theo1(xl, 1.0, 8000, workers=2)[0]
finally:
    sc._threadpool_limits = saved
check(rel(v3, v1) < 1e-12, f"BLAS-free (einsum) kernel = BLAS kernel, rel {rel(v3, v1):.1e}")

# %% ===========================================================================
#    TEST 9: FREQUENCY CSVs LOAD WITH MATCHING LENGTHS
# =============================================================================
print()
print("=" * 70)
print("TEST 9: canonical CSV loader (phase_s, freq_hz, frac_freq)")
print("=" * 70)
tmp = Path(tempfile.mkdtemp(prefix="core_check_"))
f_hz = 10e6 + 1e-3 * np.sin(np.arange(50) / 3.0)
(tmp / "f.csv").write_text("﻿time_s,freq_hz\n" + "".join(
    f"{i},{repr(float(v))}\n" for i, v in enumerate(f_hz)), encoding="utf-8")
(tmp / "y.csv").write_text("time_s,frac_freq\n" + "".join(
    f"{i},{repr(float(v))}\n" for i, v in enumerate((f_hz - 10e6) / 10e6)))
(tmp / "x.csv").write_text("time_s,phase_s\n" + "".join(f"{i},{i * 1e-9}\n" for i in range(50)))
s_f = sc.load_canonical_series(str(tmp / "f.csv"))
s_y = sc.load_canonical_series(str(tmp / "y.csv"))
s_x = sc.load_canonical_series(str(tmp / "x.csv"))
check(len(s_f.t) == len(s_f.x) == 51 and s_f.source_column == "freq_hz",
      "freq_hz: 50 rows -> 51 phase points with 51 time tags (BOM header accepted)")
check(abs(s_f.f0_hz - float(np.median(f_hz))) < 1e-6, "freq_hz normalised by its median")
check(len(s_y.t) == len(s_y.x) == 51 and s_y.source_column == "frac_freq", "frac_freq lengths match")
check(len(s_x.t) == len(s_x.x) == 50 and s_x.source_column == "phase_s", "phase_s read unchanged")
t_c, x_c, k_c = sc.load_canonical_csv(str(tmp / "f.csv"))
check(k_c == "phase" and len(t_c) == len(x_c), "load_canonical_csv() keeps the 0.0.1 return form")
try:
    sc.fit_and_remove_drift(x_c, t_c, 1)
    check(True, "drift fit runs on a frequency CSV (failed in 0.0.1/0.0.2)")
except Exception as exc:  # noqa: BLE001
    check(False, f"drift fit on a frequency CSV: {exc}")

# %% ===========================================================================
#    TEST 10: LINEAR DRIFT VS FLICKER-WALK FM
# =============================================================================
print()
print("=" * 70)
print("TEST 10: noise table and drift detection")
print("=" * 70)
names = [row[0] for row in sc.NOISE_TABLE]
check(names[-1] == "Random Run FM" and sc.NOISE_TABLE[-1][1:] == (-4, 1.5, 1.5),
      "NOISE_TABLE last row is Random Run FM (alpha -4, slope +1.5)")
tt = np.arange(2 ** 15, dtype=float)
cls = sc.classify_noise(sc.compute_all_deviations(0.5 * 1e-9 * tt ** 2, 1.0, m_values=[4, 8, 16, 32]))
check(all(c.noise_type == sc.LINEAR_DRIFT_LABEL for c in cls), "pure linear drift -> Linear Freq. Drift")
xd = sc.generate_power_law_phase(2 ** 15, 1.0, 0, amp=1e-3, seed=4)[:2 ** 15] + 0.5 * 1e-7 * tt ** 2
cls = sc.classify_noise(sc.compute_all_deviations(xd, 1.0))
print("  white FM + drift:", [(int(c.tau), c.noise_type) for c in cls])
check(cls[0].noise_type == "White FM" and cls[-1].noise_type == sc.LINEAR_DRIFT_LABEL,
      "white FM at short tau, drift at long tau")
xf = sc.generate_power_law_phase(2 ** 15, 1.0, -3, seed=5)
cls = sc.classify_noise(sc.compute_all_deviations(xf, 1.0, m_values=[4, 8, 16, 32, 64, 128]))
check(all(c.noise_type == "Flicker Walk FM" for c in cls), "Flicker-Walk FM is not reported as drift")

# %% ===========================================================================
#    TEST 11: DRIFT FIT
# =============================================================================
print()
print("=" * 70)
print("TEST 11: drift fit on a scaled axis vs np.polyfit; D = 2 a2")
print("=" * 70)
t5 = np.arange(5000, dtype=float) + 1e6
D = 6e-12
x5 = sc.generate_power_law_phase(5000, 1.0, -1, amp=1e-13, seed=2)[:5000] + 0.5 * D * (t5 - t5[0]) ** 2
fit = sc.fit_and_remove_drift(x5, t5, 2)
ref = np.polyfit(t5, x5, 2)
print(f"  D = {fit.drift_rate:.6e} 1/s (injected {D:.1e}); np.polyfit 2*a2 = {2 * ref[0]:.6e}")
check(rel(fit.drift_rate, 2 * ref[0]) < 1e-6, "drift rate = np.polyfit (rel < 1e-6)")
check(rel(fit.drift_rate, D) < 0.05, "injected drift recovered within 5 %")

# %% ===========================================================================
#    SUMMARY
# =============================================================================
print("\n{0} failure(s)".format(len(FAILURES)))
for f in FAILURES:
    print("  FAIL:", f)
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
