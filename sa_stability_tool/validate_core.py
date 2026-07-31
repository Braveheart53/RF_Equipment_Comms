"""Validation script (dev-time only, not part of the delivered tool):
cross-checks stability_core.py against allantools and against expected
power-law noise slopes. Run with: python3.12 validate_core.py
"""
from __future__ import annotations
import sys
import numpy as np
import allantools

sys.path.insert(0, "/home/user/workspace/maser_analysis/sa_stability_tool")
import stability_core as sc

TAU0 = 1.0
N = 20000

print("=" * 70)
print("TEST 1: Cross-check OADEV/MDEV/OHDEV/TDEV against allantools")
print("=" * 70)
x = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=7)  # white FM
m_values = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]

rate = 1.0 / TAU0
_, at_oadev, at_oadev_err, _ = allantools.oadev(x, rate=rate, data_type="phase", taus=[m * TAU0 for m in m_values])
_, at_mdev, at_mdev_err, _ = allantools.mdev(x, rate=rate, data_type="phase", taus=[m * TAU0 for m in m_values])
_, at_ohdev, at_ohdev_err, _ = allantools.ohdev(x, rate=rate, data_type="phase", taus=[m * TAU0 for m in m_values])
_, at_tdev, at_tdev_err, _ = allantools.tdev(x, rate=rate, data_type="phase", taus=[m * TAU0 for m in m_values])

print(f"{'m':>6} {'my_OADEV':>14} {'at_OADEV':>14} {'rel.err%':>10}   "
      f"{'my_MDEV':>14} {'at_MDEV':>14} {'rel.err%':>10}   "
      f"{'my_OHDEV':>14} {'at_OHDEV':>14} {'rel.err%':>10}")
max_rel_err = 0.0
for i, m in enumerate(m_values):
    my_oa, _ = sc.oadev(x, TAU0, m)
    my_md, _ = sc.mdev(x, TAU0, m)
    my_oh, _ = sc.ohdev(x, TAU0, m)
    my_td = sc.tdev_from_mdev(my_md, m * TAU0)
    re_oa = abs(my_oa - at_oadev[i]) / at_oadev[i] * 100
    re_md = abs(my_md - at_mdev[i]) / at_mdev[i] * 100
    re_oh = abs(my_oh - at_ohdev[i]) / at_ohdev[i] * 100
    max_rel_err = max(max_rel_err, re_oa, re_md, re_oh)
    print(f"{m:>6} {my_oa:>14.6e} {at_oadev[i]:>14.6e} {re_oa:>9.4f}%   "
          f"{my_md:>14.6e} {at_mdev[i]:>14.6e} {re_md:>9.4f}%   "
          f"{my_oh:>14.6e} {at_ohdev[i]:>14.6e} {re_oh:>9.4f}%")
print(f"\nMax relative error across all m, all estimators: {max_rel_err:.6f}%")
print("PASS" if max_rel_err < 0.01 else "FAIL -- investigate formula mismatch")

print()
print("=" * 70)
print("TEST 2: TDEV formula check (TDEV = tau/sqrt(3) * MDEV)")
print("=" * 70)
max_rel_err_tdev = 0.0
for i, m in enumerate(m_values):
    my_md, _ = sc.mdev(x, TAU0, m)
    my_td = sc.tdev_from_mdev(my_md, m * TAU0)
    re = abs(my_td - at_tdev[i]) / at_tdev[i] * 100
    max_rel_err_tdev = max(max_rel_err_tdev, re)
print(f"Max relative error TDEV vs allantools: {max_rel_err_tdev:.6f}%")
print("PASS" if max_rel_err_tdev < 0.01 else "FAIL")

print()
print("=" * 70)
print("TEST 3: Non-overlapping ADEV sanity check (should be noisier but")
print("         statistically consistent with OADEV, same order of mag.)")
print("=" * 70)
for m in [4, 16, 64]:
    a_val, a_n = sc.adev_nonoverlapping(x, TAU0, m)
    oa_val, oa_n = sc.oadev(x, TAU0, m)
    ratio = a_val / oa_val
    print(f"m={m:4d}  ADEV={a_val:.4e} (n={a_n:4d})  OADEV={oa_val:.4e} (n={oa_n:4d})  ratio={ratio:.3f}")

print()
print("=" * 70)
print("TEST 4: Noise-type slope classification vs known injected noise type")
print("=" * 70)
noise_cases = [
    ("White PM", 2), ("Flicker PM", 1), ("White FM", 0),
    ("Flicker FM", -1), ("Random Walk FM", -2),
]
for label, alpha in noise_cases:
    xn = sc.generate_power_law_phase(N, TAU0, alpha=alpha, seed=99)
    pts = sc.compute_all_deviations(xn, TAU0, m_values=[2, 4, 8, 16, 32, 64, 128], include_theo=False)
    # use a mid-range octave pair for the slope estimate (avoid edge/DC-injection artifacts)
    import math
    log_t = [math.log10(p.tau) for p in pts]
    log_a = [math.log10(p.oadev) for p in pts]
    idx = 2  # tau = 8..16 octave, away from both ends
    slope = (log_a[idx + 1] - log_a[idx]) / (log_t[idx + 1] - log_t[idx])
    expected = dict((n, mu) for n, _a, mu, _m in sc.NOISE_TABLE)[label]
    print(f"{label:>18}: expected ADEV slope mu={expected:+.2f}, measured mu={slope:+.2f}  "
          f"({'OK' if abs(slope-expected) < 0.35 else 'CHECK'})")

print()
print("=" * 70)
print("TEST 5: Thêo1 unbiasedness vs OADEV at MATCHED effective tau=0.75*m*tau0")
print("        (white FM -- Thêo1 should be ~unbiased per NIST SP1065/Ref.[7])")
print("=" * 70)
xw = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=55)
for m in [20, 40, 80, 200]:
    tau_eff = sc.theo1_effective_tau(TAU0, m)
    oa_at_eff, _ = sc.oadev(xw, TAU0, int(round(tau_eff / TAU0)))
    th1_val, _ = sc.theo1(xw, TAU0, m)
    ratio = th1_val / oa_at_eff
    print(f"m={m:4d}  tau_eff={tau_eff:7.1f}s  OADEV(tau_eff)={oa_at_eff:.4e}  "
          f"THEO1(m)={th1_val:.4e}  ratio={ratio:.3f}  "
          f"({'OK (~1.0)' if 0.9 < ratio < 1.1 else 'CHECK'})")

print()
print("=" * 70)
print("TEST 6: ThêoH hybrid family -- continuity check at AVAR/ThêoBR splice,")
print("        and extended tau coverage beyond N/2 (white FM)")
print("=" * 70)
family = sc.compute_theoh_family(xw, TAU0, stitch_frac=0.1)
for tau, m, val, label in family:
    marker = "  <-- beyond OADEV's tau=N/2 limit" if tau > 0.5 * N * TAU0 else ""
    print(f"tau={tau:9.1f}s  m={m:6d}  {label:8s} dev={val:.4e}{marker}")
print(f"Max tau reached: {family[-1][0]:.1f}s = {family[-1][0]/(N*TAU0)*100:.1f}% of record "
      f"(N*tau0={N*TAU0:.0f}s); OADEV alone maxes out at 50%.")
