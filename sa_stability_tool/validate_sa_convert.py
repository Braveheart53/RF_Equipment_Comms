"""Validation for sa_convert.py using synthetic vendor-style export files."""
from __future__ import annotations
import sys
sys.path.insert(0, "/home/user/workspace/maser_analysis/sa_stability_tool")
import numpy as np
import sa_convert as sac

# --- 1. Generic CSV time series ---
with open("/tmp/generic_ts.csv", "w") as f:
    f.write("time_s,value\n")
    for i in range(20):
        f.write("{0},{1}\n".format(i * 1.0, 1e-9 * np.sin(i / 3.0)))
kind = sac.convert_to_canonical_csv("/tmp/generic_ts.csv", "/tmp/generic_ts_out.csv", vendor="generic")
print("Generic time-series CSV -> kind detected:", kind, "(expect time_series)")
print(open("/tmp/generic_ts_out.csv").read()[:150])

# --- 2. Generic CSV frequency (phase-noise) trace, log-spaced offsets ---
freqs = np.logspace(0, 5, 30)  # 1 Hz to 100 kHz - large span_ratio > 1e3
lf = -20 * np.log10(freqs) - 60
with open("/tmp/generic_trace.csv", "w") as f:
    f.write("freq_hz,l_f\n")
    for a, b in zip(freqs, lf):
        f.write("{0},{1}\n".format(a, b))
kind2 = sac.convert_to_canonical_csv("/tmp/generic_trace.csv", "/tmp/generic_trace_out.csv", vendor="generic")
print("\nGeneric freq-trace CSV -> kind detected:", kind2, "(expect freq_trace)")

# --- 3. Keysight-style export with metadata header ---
with open("/tmp/keysight_export.csv", "w") as f:
    f.write("Keysight PXA Phase Noise Measurement\n")
    f.write("Carrier Frequency: 10000000000 Hz\n")
    f.write("Frequency Offset (Hz),Phase Noise (dBc/Hz)\n")
    for a, b in zip(freqs, lf):
        f.write("{0},{1}\n".format(a, b))
kind3 = sac.convert_to_canonical_csv("/tmp/keysight_export.csv", "/tmp/keysight_out.csv", vendor="keysight")
print("\nKeysight-style export -> kind detected:", kind3, "(expect freq_trace)")
print(open("/tmp/keysight_out.csv").read()[:150])

# --- 4. R&S-style semicolon-delimited export ---
with open("/tmp/rs_export.dat", "w") as f:
    f.write("Type;FSWP Phase Noise\n")
    f.write("Center Freq;10000000000 Hz\n")
    f.write("Values\n")
    for a, b in zip(freqs, lf):
        f.write("{0};{1}\n".format(a, b))
kind4 = sac.convert_to_canonical_csv("/tmp/rs_export.dat", "/tmp/rs_out.csv", vendor="rs")
print("\nR&S-style export -> kind detected:", kind4, "(expect freq_trace)")
print(open("/tmp/rs_out.csv").read()[:150])

# --- 5. Batch marker extraction from multiple snapshot files ---
paths = []
rng = np.random.default_rng(3)
for k in range(6):
    p = "/tmp/snapshot_{0}.csv".format(k)
    freqs_k = np.linspace(9.999e9, 10.001e9, 50)
    amp_k = -50 - 20 * ((freqs_k - 1e10) ** 2) / 1e12 + rng.normal(0, 0.1, 50)
    with open(p, "w") as f:
        f.write("freq_hz,amp_dbm\n")
        for a, b in zip(freqs_k, amp_k):
            f.write("{0},{1}\n".format(a, b))
    paths.append(p)
t_idx, peak_vals = sac.batch_extract_marker_time_series(paths, vendor="generic", marker_index=0)
print("\nBatch marker extraction peak values (should hover near -50 dBm):", peak_vals)

print("\nALL sa_convert.py smoke tests completed without exceptions.")
