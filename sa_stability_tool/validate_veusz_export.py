"""Validation for veusz_export.py using the subprocess-isolated export path
with real synthetic data run through stability_core and phase_noise."""
from __future__ import annotations
import sys
sys.path.insert(0, "/home/user/workspace/maser_analysis/sa_stability_tool")
import numpy as np
import stability_core as sc
import phase_noise as pn
import veusz_export as ve

TAU0 = 1.0
N = 4096
x = sc.generate_power_law_phase(N, TAU0, alpha=-1, seed=5)  # flicker FM-like
t = np.arange(len(x)) * TAU0

drift = sc.fit_and_remove_drift(x, t, order=1)
x_resid = drift.residual_x

points = sc.compute_all_deviations(x, TAU0)
sigma_tau_series = {
    "OADEV": {"tau": [p.tau for p in points], "dev": [p.oadev for p in points]},
    "MDEV":  {"tau": [p.tau for p in points], "dev": [p.mdev for p in points]},
    "TDEV":  {"tau": [p.tau for p in points], "dev": [p.tdev for p in points]},
}

pn_res = pn.ssb_phase_noise_from_time_series(x, TAU0, 1e7, window="hann")

out_path = "/tmp/test_export.vszh5"
ve.export_all_plots_subprocess(
    out_path, t, x, x_resid, sigma_tau_series,
    phase_noise_freq=pn_res.freq_hz.tolist(), phase_noise_lf=pn_res.l_f_dbc_hz.tolist(),
    title="Validation Run",
)
import os
size = os.path.getsize(out_path)
print("Wrote {0} ({1} bytes)".format(out_path, size))
assert size > 1000, "Output file suspiciously small"
print("PASS - veusz_export subprocess path works end-to-end with real analysis data")
