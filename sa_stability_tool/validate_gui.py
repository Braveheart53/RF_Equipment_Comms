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
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : Qt.py + PySide6, numpy, scipy, matplotlib, h5py
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
Creates the window under the offscreen Qt platform (settings in a temporary
INI folder, message boxes recorded instead of shown) and drives the
window's own code paths:

  * menus (File, Analysis, Export, View, Help); View > Light / Dark changes
    the palette and the plot colours and is remembered;
  * Run All on the worker thread (window stays live), then the result;
  * a job finishing after new data were loaded is discarded;
  * loading a new file clears the previous drift fit and results;
  * a freq_hz canonical CSV: matching lengths, f0 from the data;
  * Stable32 phase / frequency / sigma-tau exports; .vszh5 export; a
    decimal-comma R&S trace converted and classified; Close Data;
  * the background render when a Veusz program is found (a failed render
    is a warning; SMOKE_RENDER=1 makes it a failure).

Exit status 0 = all PASS, 1 = any FAIL.

REVISION HISTORY
----------------
0.0.1  (baseline)  Smoke test of gui_app.py; exports called directly.
0.0.2  2026-10-11  Targets Time_Stability_App.py; window export methods.
0.0.3  2026-10-11  Qt.py; menus, light/dark, worker threads, stale-result
                   discard, reload reset, freq_hz CSV, all export kinds,
                   decimal-comma conversion, Close Data; temporary settings;
                   modal boxes recorded; PASS/FAIL exit status.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP (offscreen Qt, temporary settings)
# =============================================================================
from __future__ import annotations

import builtins
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_PREFERRED_BINDING", "PySide6")

_HERE = Path(globals().get("__file__") or "validate_gui.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import h5py                                   # noqa: E402
import numpy as np                            # noqa: E402
from Qt import QtCore, QtWidgets              # noqa: E402

import stability_core as sc                   # noqa: E402
import Time_Stability_App as app_mod          # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="gui_smoke_"))
FAILURES = []
BOXES = []


def check(ok: bool, label: str) -> bool:
    """Print and record one PASS/FAIL line."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)
    return ok


def wait_idle(win, timeout: float = 300.0) -> None:
    """Process events until no background job is running."""
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if not win._running:
            app.processEvents()
            return
        time.sleep(0.02)
    raise TimeoutError("background job did not finish")


# Settings go to a temporary INI folder, not the user's registry/config.
fmt = QtCore.QSettings.Format.IniFormat
QtCore.QSettings.setDefaultFormat(fmt)
QtCore.QSettings.setPath(fmt, QtCore.QSettings.Scope.UserScope, str(TMP / "settings"))
# Modal message boxes would block a headless test: record them instead.
QtWidgets.QMessageBox.critical = staticmethod(lambda *a, **k: BOXES.append(("critical", a[1:3])))
QtWidgets.QMessageBox.warning = staticmethod(lambda *a, **k: BOXES.append(("warning", a[1:3])))

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
win = app_mod.MainWindow()
print("window title:", win.windowTitle())
check(win.windowTitle().startswith("Time Stability App " + app_mod.__version__), "window title has the version")

# %% ===========================================================================
#    MENUS AND LIGHT / DARK DISPLAY
# =============================================================================
menus = [a.text().replace("&", "") for a in win.menuBar().actions()]
check(menus == ["File", "Analysis", "Export", "View", "Help"], f"menu bar {menus}")
win.set_theme("dark")
window_col = app.palette().color(app.palette().ColorRole.Window).name()
check(win.act_dark.isChecked() and window_col == "#2b2d30", f"dark palette applied ({window_col})")
check(win.canvas_raw.fig.get_facecolor()[:3] != (1.0, 1.0, 1.0), "plots follow the dark theme")
check(str(QtCore.QSettings(app_mod.SETTINGS_ORG, app_mod.SETTINGS_APP).value("view/theme")) == "dark",
      "theme remembered in QSettings")
win.set_theme("light")
check(win.act_light.isChecked() and not win.act_dark.isChecked(), "light display restored (exclusive)")

# %% ===========================================================================
#    LOAD A PHASE CSV, RUN ALL ON THE WORKER THREAD
# =============================================================================
N = 4096
x = sc.generate_power_law_phase(N - 1, 1.0, alpha=-1, seed=9)
t = np.arange(len(x)) * 1.0
(TMP / "phase.csv").write_text("time_s,phase_s\n" + "".join(f"{a},{b!r}\n" for a, b in zip(t, map(float, x))))
win.load_csv_path(str(TMP / "phase.csv"))
check(win.x_s is not None and len(win.x_s) == N and win.tau0 == 1.0, "phase CSV loaded, tau0 = 1 s")
win.drift_order_spin.setValue(1)
t0 = time.time()
win.on_run_all()
check("run all" in win._running and not win.btn_run_all.isEnabled(), "Run All runs in the background")
wait_idle(win)
print(f"run all finished in {time.time() - t0:.2f} s")
check(win.drift_result is not None and len(win.dev_points) > 0 and len(win.theoh_points) > 0
      and win.pn_result is not None, "drift, stability and phase noise applied")
check(win.table_noise.rowCount() > 0 and win.table_noise.columnCount() == 7, "noise table incl. OHDEV slope")
check(win.table_freq_noise.rowCount() > 0, "frequency-domain noise table filled")
check(win.btn_run_all.isEnabled(), "buttons re-enabled after the job")

# %% ===========================================================================
#    STALE RESULTS ARE DISCARDED; RELOAD CLEARS RESULTS
# =============================================================================
f_hz = 10e6 + 1e-3 * np.cumsum(np.random.default_rng(2).standard_normal(3000))
(TMP / "freq.csv").write_text("time_s,freq_hz\n" + "".join(f"{i},{v!r}\n" for i, v in enumerate(map(float, f_hz))))
win.on_run_stability()
win.load_csv_path(str(TMP / "freq.csv"))            # new data while the job runs
wait_idle(win)
check("Discarded stability result" in win.log.toPlainText(), "late result of the old data discarded")
check(win.drift_result is None and not win.dev_points and win.pn_result is None,
      "loading new data cleared drift fit and results (0.0.2 kept a stale residual)")
check(len(win.t_s) == len(win.x_s) == 3001 and win.value_kind == "freq_hz", "freq_hz CSV: lengths match")
check(abs(win.f0_hz - float(np.median(f_hz))) < 1e-3, f"f0 set from the data ({win.f0_hz:.6f} Hz)")
check("Loaded 3000 rows (freq_hz)" in win.log.toPlainText(), "log names the column read")
win.run_all_blocking()
check(len(win.dev_points) > 0, "Run All (blocking) on the frequency data")

# %% ===========================================================================
#    EXPORTS
# =============================================================================
for kind, ext in (("phase", "PHD"), ("freq", "FRD"), ("table", "DAT")):
    p = TMP / f"out.{ext}"
    win.export_stable32_to(str(p), kind)
    check(p.is_file() and p.stat().st_size > 100, f"Stable32 {kind} export")
veusz_exe = app_mod.ve.find_veusz()
render = bool(veusz_exe) or os.environ.get("SMOKE_RENDER") == "1"
vszh5 = win.export_veusz_to(str(TMP / "gui_test_export.vszh5"), render=render)
check(h5py.is_hdf5(str(vszh5)), "Veusz export is an HDF5 .vszh5")
if render:
    end = time.time() + 300
    while time.time() < end and "Rendered" not in win.log.toPlainText() \
            and "render not done" not in win.log.toPlainText():
        app.processEvents()
        time.sleep(0.1)
    last = [ln for ln in win.log.toPlainText().splitlines() if "ender" in ln][-1]
    print("render result:", last)
    if last.startswith("Rendered"):
        check(True, "background render")
    else:
        check(os.environ.get("SMOKE_RENDER") != "1", "background render (optional)")
        print("WARNING: render failed (optional step)")
else:
    print("render skipped (no Veusz program found; set TIME_STABILITY_VEUSZ)")

# %% ===========================================================================
#    DECIMAL-COMMA R&S TRACE, CLOSE DATA
# =============================================================================
fr = np.logspace(0, 5, 40)
(TMP / "rs.dat").write_text("Type;FSWP Phase Noise;\nValues;40;\n" + "".join(
    f"{a!r};{b!r};\n".replace(".", ",") for a, b in zip(map(float, fr), map(float, -20 * np.log10(fr) - 60))))
win.vendor_combo.setCurrentText("rs")
kind = win.convert_sa_path(str(TMP / "rs.dat"), str(TMP / "rs_out.csv"))
check(kind == "freq_trace" and win.table_freq_noise.rowCount() > 0, "decimal-comma R&S trace converted and classified")
win.on_close_data()
check(win.x_s is None and not win.btn_run_all.isEnabled(), "Close Data released the series")
check(not [b for b in BOXES if b[0] == "critical"], f"no error boxes ({BOXES})")

# %% ===========================================================================
#    SUMMARY
# =============================================================================
win.close()
print("\n{0} failure(s)".format(len(FAILURES)))
if not FAILURES:
    print("ALL GUI SMOKE TESTS PASSED")
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
