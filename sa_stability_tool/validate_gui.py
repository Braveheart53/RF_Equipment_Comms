#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Headless smoke test of Time_Stability_App.py (no display needed).

===============================================================================
 Title          : Time Stability App GUI Smoke Test
 Filename       : validate_gui.py
 Version        : 0.0.2  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.2
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : PySide6, numpy, scipy, matplotlib, h5py
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
Instantiates the QApplication and MainWindow under the offscreen Qt
platform and drives the window's own code paths: CSV load, drift removal,
stability analysis, phase-noise analysis, and BOTH exports through the
window's export_stable32_to() and export_veusz_to() methods (the methods
the File dialogs call). 0.0.1 called the export modules directly instead,
although its README said the GUI export paths were driven.

When a Veusz program is found the render is started too and waited for
(it runs in a child process, reported through the window's Qt signal). A
failed render is a warning, because rendering is optional; set
SMOKE_RENDER=1 to make it a failure (and to force the render attempt).

REVISION HISTORY
----------------
0.0.1  (baseline)  Smoke test of gui_app.py; exports called directly.
0.0.2  2026-10-11  Targets Time_Stability_App.py; drives the window's export
                   methods; checks the .vszh5 is HDF5; optional render;
                   own folder + temporary folder; full header; Spyder cells.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP (offscreen Qt)
# =============================================================================
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QT_API"] = "pyside6"

_HERE = Path(globals().get("__file__") or "validate_gui.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import h5py                       # noqa: E402
import numpy as np                # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import stability_core as sc       # noqa: E402
import Time_Stability_App as app_mod  # noqa: E402

__version__ = "0.0.2"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="gui_smoke_"))

# %% ===========================================================================
#    SYNTHETIC INPUT THROUGH THE CSV LOADER
# =============================================================================
N = 2048
TAU0 = 1.0
x = sc.generate_power_law_phase(N, TAU0, alpha=-1, seed=9)
t = np.arange(len(x)) * TAU0
csv_path = TMP / "gui_test_input.csv"
with open(csv_path, "w") as f:
    f.write("time_s,phase_s\n")
    for a, b in zip(t, x):
        f.write("{0},{1}\n".format(a, b))

app = QApplication.instance() or QApplication(sys.argv)
win = app_mod.MainWindow()
print("window title:", win.windowTitle())
assert win.windowTitle().startswith("Time Stability App " + app_mod.__version__)

# Equivalent to what the load dialog does
t_loaded, x_loaded, kind = sc.load_canonical_csv(str(csv_path))
win.t_s, win.x_s, win.value_kind = t_loaded, x_loaded, kind
win.source_path = str(csv_path)
win.tau0 = float(np.median(np.diff(win.t_s)))
win._plot_raw()
print("plot_raw OK, tau0=", win.tau0)

# %% ===========================================================================
#    ANALYSIS BUTTONS
# =============================================================================
win.on_run_drift()
print("drift OK:", win.drift_result.order, win.drift_result.drift_rate, win.drift_result.r_squared)

win.on_run_stability()
print("stability OK: n_dev_points=", len(win.dev_points), "n_theoh=", len(win.theoh_points))
print("noise table rows:", win.table_noise.rowCount())
assert win.table_noise.rowCount() > 0

win.on_run_phase_noise()
print("phase noise OK: n_freq_points=", len(win.pn_result.freq_hz))
print("freq noise table rows:", win.table_freq_noise.rowCount())
assert win.table_freq_noise.rowCount() > 0

# %% ===========================================================================
#    EXPORTS THROUGH THE WINDOW'S OWN METHODS
# =============================================================================
s32_path = TMP / "gui_test_export.PHD"
win.export_stable32_to(str(s32_path))
print("Stable32 export file size:", os.path.getsize(s32_path))

render = bool(app_mod.ve.find_veusz()) or os.environ.get("SMOKE_RENDER") == "1"
vszh5_path = win.export_veusz_to(str(TMP / "gui_test_export.vszh5"), render=render)
print("Veusz export file size:", vszh5_path.stat().st_size)
assert h5py.is_hdf5(str(vszh5_path)), "the .vszh5 is not an HDF5 file"
with h5py.File(vszh5_path, "r") as f:
    n_data = len(f["Veusz/Data"])
print("datasets in the .vszh5:", n_data)

if render:
    print("waiting for the background render...")
    deadline = time.time() + 300
    while time.time() < deadline and "Rendered" not in win.log.toPlainText() \
            and "render not done" not in win.log.toPlainText():
        app.processEvents()
        time.sleep(0.1)
    last = win.log.toPlainText().splitlines()[-1]
    print("render result:", last)
    if not last.startswith("Rendered"):
        # The render is optional; a Veusz found on PATH may be broken for
        # this Python. SMOKE_RENDER=1 makes a failed render a failed test.
        assert os.environ.get("SMOKE_RENDER") != "1", last
        print("WARNING: render failed (optional step) - see the line above")
else:
    print("render skipped (no Veusz program found; set TIME_STABILITY_VEUSZ)")

print("\nALL GUI SMOKE TESTS PASSED")
