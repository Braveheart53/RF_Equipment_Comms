"""Validation: check phase_noise.py recovers the correct L(f) slope for
synthetic power-law phase series with known Sy(f) exponent."""
from __future__ import annotations
import sys
sys.path.insert(0, "/home/user/workspace/maser_analysis/sa_stability_tool")
import numpy as np
import stability_core as sc
import phase_noise as pn

TAU0 = 0.01   # 100 Hz sample rate SA long-time-measurement
N = 65536
F0 = 10e6     # 10 MHz reference

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

print()
print("Noise-ID classification check (log-binned, White FM case):")
x = sc.generate_power_law_phase(N, TAU0, alpha=0, seed=17)
res = pn.ssb_phase_noise_from_time_series(x, TAU0, F0, window="hann")
classes = pn.classify_freq_domain_noise(res, points_per_decade=8)
mid = len(classes) // 2
for c in classes[mid:mid + 5]:
    print(f"  f=[{c.f_lo_hz:.2f}, {c.f_hi_hz:.2f}] Hz  slope={c.slope_db_per_decade:+.2f} dB/dec  -> {c.noise_type}")

print()
print("l_f_to_sy round-trip sanity check:")
sy = pn.l_f_to_sy(res.l_f_dbc_hz, res.freq_hz, F0)
print(f"  Sy(f) range: {sy.min():.3e} to {sy.max():.3e} (should be positive, finite)")
