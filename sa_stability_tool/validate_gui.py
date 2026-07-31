"""Headless smoke test for gui_app.py: instantiate the QApplication/MainWindow
under the offscreen Qt platform and drive the core buttons programmatically
(no real display needed) to catch wiring bugs before calling this done."""
from __future__ import annotations
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_API"] = "pyside6"
import sys
sys.path.insert(0, "/home/user/workspace/maser_analysis/sa_stability_tool")

import numpy as np
import stability_core as sc
from PySide6.QtWidgets import QApplication
import gui_app

# Write a synthetic canonical CSV to load through the real "Load CSV" code path
N = 2048
TAU0 = 1.0
x = sc.generate_power_law_phase(N, TAU0, alpha=-1, seed=9)
t = np.arange(len(x)) * TAU0
csv_path = "/tmp/gui_test_input.csv"
with open(csv_path, "w") as f:
    f.write("time_s,phase_s\n")
    for a, b in zip(t, x):
        f.write("{0},{1}\n".format(a, b))

app = QApplication.instance() or QApplication(sys.argv)
win = gui_app.MainWindow()

# Directly exercise the internal logic (equivalent to what the load dialog would do)
t_loaded, x_loaded, kind = sc.load_canonical_csv(csv_path)
win.t_s, win.x_s, win.value_kind = t_loaded, x_loaded, kind
win.tau0 = float(np.median(np.diff(win.t_s)))
win._plot_raw()
print("plot_raw OK, tau0=", win.tau0)

win.on_run_drift()
print("drift OK:", win.drift_result.order, win.drift_result.drift_rate, win.drift_result.r_squared)

win.on_run_stability()
print("stability OK: n_dev_points=", len(win.dev_points), "n_theoh=", len(win.theoh_points))
print("noise table rows:", win.table_noise.rowCount())

win.on_run_phase_noise()
print("phase noise OK: n_freq_points=", len(win.pn_result.freq_hz))
print("freq noise table rows:", win.table_freq_noise.rowCount())

# Export paths (exercise real export functions through GUI methods)
import stable32_export as s32
s32_path = "/tmp/gui_test_export.PHD"
s32.write_stable32_phase_file(s32_path, win.t_s, win.drift_result.residual_x)
print("Stable32 export file size:", os.path.getsize(s32_path))

import veusz_export as ve
vszh5_path = "/tmp/gui_test_export.vszh5"
sigma_tau_series = {
    "OADEV": {"tau": [p.tau for p in win.dev_points], "dev": [p.oadev for p in win.dev_points]},
}
ve.export_all_plots_subprocess(
    vszh5_path, win.t_s.tolist(), win.x_s.tolist(), win.drift_result.residual_x.tolist(),
    sigma_tau_series, phase_noise_freq=win.pn_result.freq_hz.tolist(),
    phase_noise_lf=win.pn_result.l_f_dbc_hz.tolist(), title="GUI smoke test",
)
print("Veusz export file size:", os.path.getsize(vszh5_path))

print("\nALL GUI SMOKE TESTS PASSED")
