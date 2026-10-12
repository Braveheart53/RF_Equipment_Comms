#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Time Stability App - Qt GUI for SA long-time-measurement stability analysis.

===============================================================================
 Title          : Time Stability App (SA Long-Time-Measurement Stability &
                  Phase-Noise Analysis GUI)
 Filename       : Time_Stability_App.py   (was gui_app.py in 0.0.1)
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13 (3.8 syntax kept on purpose)
 Requires       : Qt.py (-> PySide6), numpy, scipy, matplotlib, h5py and the
                  package modules stability_core, phase_noise, sa_convert,
                  stable32_export, veusz_export, vszh5_writer
 Optional       : threadpoolctl (faster threaded Thêo1), cupy (GPU Thêo1),
                  Veusz program or package (render PDF/PNG)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Internal draft - not yet run against instrument data
===============================================================================

LICENCE
-------
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
The full text is in the file LICENSE distributed with this program.

DESCRIPTION
-----------
Desktop front-end for the analysis modules of this package:

  - sa_convert.py       vendor SA export -> canonical CSV
  - stability_core.py   ADEV/OADEV/MDEV/TDEV/OHDEV/Thêo1/ThêoH, drift
                        removal, time-domain noise identification
  - phase_noise.py      SSB phase noise L(f), frequency-domain noise ID
  - stable32_export.py  Stable32 phase / frequency / sigma-tau files
  - veusz_export.py     native Veusz HDF5 (.vszh5) document, written
                        in-process with h5py; optional PDF/PNG render in a
                        child process

Workflow: File > Load Canonical CSV (or Convert Vendor SA File) -> check
tau0 (from the time stamps) and f0 (from the data for freq_hz files) ->
Analysis > Remove Drift (order 0/1/2) -> Run Stability Analysis / Run SSB
Phase Noise (or Run All, Ctrl+R) -> Export > Stable32 / Veusz.

Qt: the GUI is written against Qt.py [3], an abstraction over the Qt
bindings; QT_PREFERRED_BINDING defaults to PySide6 and matplotlib is told to
use the same binding. View > Light / Dark switches the Fusion palette and the
plot colours; the choice is remembered (QSettings).

Responsiveness and parallelism: every analysis runs on a worker thread and
reports back through a Qt signal, so the window never freezes. Inside the
analysis, stability_core runs its estimators on a thread pool (workers =
the "Threads" box, default all CPUs) and can run Thêo1 on a GPU (CuPy).
Results from a job that finishes after new data were loaded are discarded.
Long series are drawn from a min/max envelope (veusz_export.envelope_decimate)
so a 10^7-point record still plots quickly; every sample is analysed and
exported.

Memory: File > Close Data releases the series and all results.

SPYDER
------
Run the file (F5) or the cells in order. With an IPython Qt event loop
(graphics backend Qt) main() shows the window and returns; otherwise it
runs the event loop until the window closes. An existing QApplication is
reused; sys.exit() is not called inside IPython.

USAGE
-----
    python Time_Stability_App.py

REFERENCES (IEEE format)
------------------------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf
[2] J. A. Barnes et al., "Characterization of frequency stability," IEEE
    Trans. Instrum. Meas., vol. IM-20, no. 2, pp. 105-120, May 1971; also
    NBS Technical Note 394, Oct. 1970.
    https://nvlpubs.nist.gov/nistpubs/Legacy/TN/nbstechnicalnote394.pdf
[3] M. Ottosson et al., "Qt.py - minimal Python 2 & 3 shim around all Qt
    bindings." https://github.com/mottosso/Qt.py
[4] The Qt Company, "Qt for Python (PySide6) documentation."
    https://doc.qt.io/qtforpython-6/
[5] J. D. Hunter, "Matplotlib: a 2D graphics environment," Comput. Sci.
    Eng., vol. 9, no. 3, pp. 90-95, 2007, doi: 10.1109/MCSE.2007.55.
[6] Veusz Developers, "Veusz - a scientific plotting package."
    https://veusz.github.io/

REVISION HISTORY
----------------
0.0.1  (baseline)  gui_app.py: PySide6 window; Veusz export through a
                   subprocess (veusz.embed).
0.0.2  2026-10-11  Renamed Time_Stability_App.py; native .vszh5 export
                   in-process; optional background render; export methods
                   export_veusz_to() / export_stable32_to(); Spyder-safe
                   entry point; full header and cells.
0.0.3  2026-10-11  Qt.py (PySide6 by default) instead of direct PySide6 imports.
                   Menu bar (File, Analysis, Export, View, Help), shortcuts,
                   View > Light / Dark (Fusion palette + plot colours,
                   remembered). Analyses on worker threads (window stays
                   live; stale results discarded); Run All; Threads and
                   GPU controls feeding stability_core's thread pool / CuPy.
                   FIX: loading a file now clears the previous drift fit and
                   results (0.0.2 applied a stale residual). FIX: frequency
                   CSVs load with matching lengths and the log names the
                   column actually read (0.0.2 always printed "converting to
                   phase"); f0 is filled from freq_hz data. FIX: drift rate
                   logged in 1/s. tau0 to 1e-9 s (9 decimals). SA conversion
                   asks what a time series holds (phase_s/freq_hz/frac_freq);
                   a converted phase-noise trace is classified too. Stable32
                   export of phase, frequency or the sigma-tau table. Render
                   an existing .vszh5. Long series plotted from an envelope.
                   File > Close Data frees memory. Help > About.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND PATHS
# =============================================================================
from __future__ import annotations

import builtins
import importlib.util
import os
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

os.environ.setdefault("QT_PREFERRED_BINDING", "PySide6")   # Qt.py binding choice
import Qt  # noqa: E402  (Qt.py)
from Qt import QtCore, QtGui, QtWidgets  # noqa: E402

os.environ["QT_API"] = Qt.__binding__.lower()               # matplotlib: same binding
import numpy as np  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

# Spyder's runcell defines __file__ only while a cell runs: capture it once.
_THIS_FILE = Path(globals().get("__file__") or "Time_Stability_App.py").resolve()
_HERE = _THIS_FILE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import phase_noise as pn            # noqa: E402
import sa_convert as sac            # noqa: E402
import stability_core as sc         # noqa: E402
import stable32_export as s32       # noqa: E402
import veusz_export as ve           # noqa: E402  (h5py only - no Veusz, no Qt)

__version__ = "0.0.3"               # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"    # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"

APP_NAME = "Time Stability App"
SETTINGS_ORG, SETTINGS_APP = "NRAO-GBO", "TimeStabilityApp"
#: Points drawn per on-screen trace (min/max envelope above this).
SCREEN_MAX_POINTS = 50_000


# %% ===========================================================================
#    THEMES AND PLOT HELPERS
# =============================================================================
PALETTE = {
    "blue": "#2b6cb0", "orange": "#dd6b20", "green": "#38a169",
    "purple": "#805ad5", "red": "#e53e3e", "navy": "#2c5282",
    "orange_dark": "#c05621",
}
#: Plot colours per theme (lines keep PALETTE; navy is too dark on black).
THEMES: Dict[str, Dict[str, str]] = {
    "light": {"figure": "#ffffff", "axes": "#ffffff", "text": "#1a202c",
              "grid": "#a0aec0", "navy": PALETTE["navy"]},
    "dark": {"figure": "#1f2124", "axes": "#26292d", "text": "#e2e8f0",
             "grid": "#718096", "navy": "#63b3ed"},
}
SOURCE_NOTE = ("Analysis per NIST SP1065 [1] / NBS TN394 [2]. Time-domain "
               "estimators: ADEV, OADEV, MDEV, TDEV, OHDEV, Thêo1, ThêoH. "
               "Frequency-domain: SSB phase noise L(f) via Welch PSD.")


def make_palette(dark: bool) -> "QtGui.QPalette":
    """Fusion palette: the platform default (light) or a dark variant."""
    if not dark:
        return QtWidgets.QApplication.style().standardPalette()
    role, grp = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    p = QtGui.QPalette()
    colors = {
        role.Window: "#2b2d30", role.WindowText: "#e2e8f0", role.Base: "#1f2124",
        role.AlternateBase: "#2b2d30", role.ToolTipBase: "#2b2d30",
        role.ToolTipText: "#e2e8f0", role.Text: "#e2e8f0", role.Button: "#33363a",
        role.ButtonText: "#e2e8f0", role.BrightText: "#ff6b6b", role.Link: "#63b3ed",
        role.Highlight: "#3182ce", role.HighlightedText: "#ffffff",
    }
    for r, c in colors.items():
        p.setColor(r, QtGui.QColor(c))
    for r in (role.Text, role.ButtonText, role.WindowText):
        p.setColor(grp.Disabled, r, QtGui.QColor("#7a8089"))
    return p


def style_figure(fig: Figure, theme: str) -> None:
    """Apply the theme colours to every axes, legend and text of ``fig``."""
    th = THEMES[theme]
    fig.set_facecolor(th["figure"])
    for ax in fig.axes:
        ax.set_facecolor(th["axes"])
        ax.tick_params(colors=th["text"], which="both")
        for spine in ax.spines.values():
            spine.set_color(th["text"])
        ax.xaxis.label.set_color(th["text"])
        ax.yaxis.label.set_color(th["text"])
        ax.title.set_color(th["text"])
        leg = ax.get_legend()
        if leg is not None:
            leg.get_frame().set_facecolor(th["axes"])
            leg.get_frame().set_edgecolor(th["grid"])
            for txt in leg.get_texts():
                txt.set_color(th["text"])
    for txt in fig.texts:
        txt.set_color(th["text"])


def _footnote(fig: Figure, theme: str, text: str = SOURCE_NOTE) -> None:
    """Citation band under a figure, then theme colours."""
    fig.text(0.5, 0.02, text, ha="center", va="bottom", fontsize=6.6, wrap=True)
    fig.tight_layout(rect=(0, 0.10, 1, 1))
    style_figure(fig, theme)


class MplCanvas(FigureCanvas):
    """A matplotlib figure embedded as a Qt widget."""

    def __init__(self, width: float = 7, height: float = 5, dpi: int = 100) -> None:
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)


class _Bridge(QtCore.QObject):
    """Carries worker-thread results to the GUI thread (queued signals)."""

    job_done = QtCore.Signal(object, object, object, object)   # tag, generation, result, error
    render_done = QtCore.Signal(object, object)                # files, error


def _enabled_text(flag: bool) -> str:
    return "on" if flag else "off"


# %% ===========================================================================
#    MAIN WINDOW
# =============================================================================
class MainWindow(QtWidgets.QMainWindow):
    """Time Stability App main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__} - SA Long-Time-Measurement "
                            f"Stability & Phase-Noise Analysis")
        self.resize(1250, 840)
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)

        # ---- data and results ------------------------------------------------
        self.t_s: Optional[np.ndarray] = None
        self.x_s: Optional[np.ndarray] = None
        self.value_kind: str = "phase_s"
        self.tau0: float = 1.0
        self.f0_hz: float = 1.0e7
        self.source_path: str = ""
        self.drift_result: Optional[sc.DriftFitResult] = None
        self.dev_points: List[sc.StabilityPoint] = []
        self.theoh_points: list = []
        self.noise_class: list = []
        self.pn_result: Optional[pn.PhaseNoiseResult] = None
        self.freq_class: list = []
        self.last_vszh5: Optional[Path] = None

        # ---- background work -------------------------------------------------
        self._gen = 0                               # data generation counter
        self._running: Dict[str, float] = {}        # tag -> start time
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis")
        self._bridge = _Bridge()
        self._bridge.job_done.connect(self._on_job_done)
        self._bridge.render_done.connect(self._on_render_finished)

        theme = str(self.settings.value("view/theme", "light"))
        self.theme = theme if theme in THEMES else "light"
        self._build_ui()
        self._build_menus()
        self.set_theme(self.theme, save=False)
        self._update_enabled()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer = QtWidgets.QVBoxLayout(central)

        # --- Data input ---
        ctrl = QtWidgets.QGroupBox("Data Input")
        c_layout = QtWidgets.QHBoxLayout(ctrl)
        self.btn_load_csv = QtWidgets.QPushButton("Load Canonical CSV...")
        self.btn_load_csv.clicked.connect(self.on_load_canonical_csv)
        self.btn_convert_sa = QtWidgets.QPushButton("Convert Vendor SA File...")
        self.btn_convert_sa.clicked.connect(self.on_convert_sa_file)
        self.vendor_combo = QtWidgets.QComboBox()
        self.vendor_combo.addItems(["generic", "keysight", "rs"])
        self.value_combo = QtWidgets.QComboBox()
        self.value_combo.addItems(list(sac.CANONICAL_VALUE_COLUMNS))
        self.value_combo.setToolTip("What a converted TIME SERIES holds: phase (s), "
                                    "frequency (Hz) or fractional frequency.\n"
                                    "The analyzer file does not say; check your export.")
        self.tau0_spin = QtWidgets.QDoubleSpinBox()
        self.tau0_spin.setDecimals(9)
        self.tau0_spin.setRange(1e-9, 1e7)
        self.tau0_spin.setValue(1.0)
        self.tau0_spin.valueChanged.connect(self._on_tau0_changed)
        self.f0_spin = QtWidgets.QDoubleSpinBox()
        self.f0_spin.setDecimals(3)
        self.f0_spin.setRange(1e-3, 1e13)
        self.f0_spin.setValue(1.0e7)
        self.f0_spin.valueChanged.connect(self._on_f0_changed)
        for w in (self.btn_load_csv, QtWidgets.QLabel("Vendor:"), self.vendor_combo,
                  QtWidgets.QLabel("Series holds:"), self.value_combo, self.btn_convert_sa,
                  QtWidgets.QLabel("tau0 (s):"), self.tau0_spin,
                  QtWidgets.QLabel("f0 (Hz):"), self.f0_spin):
            c_layout.addWidget(w)
        outer.addWidget(ctrl)

        # --- Analysis ---
        analysis_bar = QtWidgets.QGroupBox("Analysis")
        a_layout = QtWidgets.QHBoxLayout(analysis_bar)
        self.drift_order_spin = QtWidgets.QSpinBox()
        self.drift_order_spin.setRange(0, 2)
        self.drift_order_spin.setValue(1)
        self.btn_run_drift = QtWidgets.QPushButton("Remove Drift")
        self.btn_run_drift.clicked.connect(self.on_run_drift)
        self.btn_run_stability = QtWidgets.QPushButton("Run Stability Analysis")
        self.btn_run_stability.clicked.connect(self.on_run_stability)
        self.btn_run_phasenoise = QtWidgets.QPushButton("Run SSB Phase Noise")
        self.btn_run_phasenoise.clicked.connect(self.on_run_phase_noise)
        self.btn_run_all = QtWidgets.QPushButton("Run All")
        self.btn_run_all.setToolTip("Drift removal (order > 0), stability and phase noise (Ctrl+R)")
        self.btn_run_all.clicked.connect(self.on_run_all)
        self.workers_spin = QtWidgets.QSpinBox()
        self.workers_spin.setRange(1, max(1, sc.available_cpus()))
        self.workers_spin.setValue(sc.available_cpus())
        self.workers_spin.setToolTip("Threads for the estimators (stability_core thread pool)")
        self.chk_gpu = QtWidgets.QCheckBox("GPU (CuPy)")
        has_cupy = importlib.util.find_spec("cupy") is not None
        self.chk_gpu.setEnabled(has_cupy)
        self.chk_gpu.setToolTip("Run the Thêo1/ThêoBR sums on a CUDA GPU with CuPy"
                                if has_cupy else "CuPy is not installed")
        self.workers_spin.valueChanged.connect(lambda _v: self._update_enabled())
        self.chk_gpu.toggled.connect(lambda _v: self._update_enabled())
        for w in (QtWidgets.QLabel("Drift fit order:"), self.drift_order_spin, self.btn_run_drift,
                  self.btn_run_stability, self.btn_run_phasenoise, self.btn_run_all,
                  QtWidgets.QLabel("Threads:"), self.workers_spin, self.chk_gpu):
            a_layout.addWidget(w)
        outer.addWidget(analysis_bar)

        # --- Export ---
        export_bar = QtWidgets.QGroupBox("Export")
        e_layout = QtWidgets.QHBoxLayout(export_bar)
        self.btn_export_stable32 = QtWidgets.QPushButton("Export Stable32 File...")
        self.btn_export_stable32.clicked.connect(self.on_export_stable32)
        self.btn_export_veusz = QtWidgets.QPushButton("Export Veusz (.vszh5)...")
        self.btn_export_veusz.setToolTip(
            "Native Veusz HDF5 document with every result and six plot pages.\n"
            "Written with h5py - Veusz is not needed. Open it in Veusz with File > Open.")
        self.btn_export_veusz.clicked.connect(self.on_export_veusz)
        veusz_exe = ve.find_veusz()
        self.chk_render = QtWidgets.QCheckBox("Render PDF/PNG (needs Veusz)")
        self.chk_render.setChecked(bool(veusz_exe))
        self.chk_render.setToolTip(
            "After writing the .vszh5, render a multipage PDF and one PNG per page "
            "in a separate process.\nVeusz program: "
            + (veusz_exe or "not found - set TIME_STABILITY_VEUSZ or VEUSZ_EXE "
               "(the veusz Python package is tried as a fallback)"))
        for w in (self.btn_export_stable32, self.btn_export_veusz, self.chk_render):
            e_layout.addWidget(w)
        e_layout.addStretch(1)
        outer.addWidget(export_bar)

        # --- Tabs ---
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs, stretch=1)
        self.canvas_raw = MplCanvas()
        self.tabs.addTab(self.canvas_raw, "Raw / Residual")
        self.canvas_sigmatau = MplCanvas()
        self.tabs.addTab(self.canvas_sigmatau, "Sigma-Tau (ADEV family)")
        self.table_noise = QtWidgets.QTableWidget()
        self.tabs.addTab(self.table_noise, "Time-Domain Noise ID")
        self.canvas_phasenoise = MplCanvas()
        self.tabs.addTab(self.canvas_phasenoise, "SSB Phase Noise")
        self.table_freq_noise = QtWidgets.QTableWidget()
        self.tabs.addTab(self.table_freq_noise, "Freq-Domain Noise ID")
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, "Log")

        self.status = QtWidgets.QStatusBar()
        self.setStatusBar(self.status)
        self.busy_label = QtWidgets.QLabel("")
        self.status.addPermanentWidget(self.busy_label)
        self._log(f"{APP_NAME} {__version__} ready ({Qt.__binding__} "
                  f"{Qt.__binding_version__}, {sc.available_cpus()} CPU(s)). Load a canonical "
                  f"CSV or convert a vendor SA export to begin.")

    def _action(self, menu: "QtWidgets.QMenu", text: str, slot: Callable[[], Any],
                shortcut: str = "", tip: str = "") -> "QtWidgets.QAction":
        act = QtWidgets.QAction(text, self)
        if shortcut:
            act.setShortcut(QtGui.QKeySequence(shortcut))
        if tip:
            act.setStatusTip(tip)
        act.triggered.connect(lambda _checked=False: slot())
        menu.addAction(act)
        return act

    def _build_menus(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu("&File")
        self.act_load = self._action(m_file, "&Load Canonical CSV...", self.on_load_canonical_csv, "Ctrl+O")
        self.act_convert = self._action(m_file, "&Convert Vendor SA File...", self.on_convert_sa_file)
        m_file.addSeparator()
        self.act_close = self._action(m_file, "Close &Data (free memory)", self.on_close_data, "Ctrl+W")
        m_file.addSeparator()
        self._action(m_file, "&Quit", self.close, "Ctrl+Q")

        m_an = bar.addMenu("&Analysis")
        self.act_drift = self._action(m_an, "Remove &Drift", self.on_run_drift, "Ctrl+D")
        self.act_stab = self._action(m_an, "Run &Stability Analysis", self.on_run_stability, "Ctrl+T")
        self.act_pn = self._action(m_an, "Run SSB &Phase Noise", self.on_run_phase_noise, "Ctrl+P")
        self.act_all = self._action(m_an, "Run &All", self.on_run_all, "Ctrl+R")

        m_ex = bar.addMenu("&Export")
        self.act_s32 = self._action(m_ex, "&Stable32 File (phase / frequency / sigma-tau)...",
                                    self.on_export_stable32)
        self.act_vsz = self._action(m_ex, "&Veusz HDF5 (.vszh5)...", self.on_export_veusz, "Ctrl+E")
        self.act_render = self._action(m_ex, "&Render a .vszh5 to PDF/PNG...", self.on_render_existing)

        m_view = bar.addMenu("&View")
        group = QtWidgets.QActionGroup(self)
        group.setExclusive(True)
        self.act_light = QtWidgets.QAction("&Light display", self, checkable=True)
        self.act_dark = QtWidgets.QAction("&Dark display", self, checkable=True)
        for act, name in ((self.act_light, "light"), (self.act_dark, "dark")):
            group.addAction(act)
            m_view.addAction(act)
            act.triggered.connect(lambda _c=False, n=name: self.set_theme(n))

        m_help = bar.addMenu("&Help")
        self._action(m_help, "&About...", self.on_about)

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------
    def set_theme(self, name: str, save: bool = True) -> None:
        """Switch light/dark: Fusion palette for widgets, colours for plots."""
        if name not in THEMES:
            return
        self.theme = name
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyle("Fusion")
            app.setPalette(make_palette(name == "dark"))
        (self.act_dark if name == "dark" else self.act_light).setChecked(True)
        if save:
            self.settings.setValue("view/theme", name)
        self._replot_all()

    def _replot_all(self) -> None:
        if self.x_s is not None:
            self._plot_raw()
        if self.dev_points:
            self._plot_sigma_tau()
        if self.pn_result is not None:
            self._plot_phase_noise()
        for canvas in (self.canvas_raw, self.canvas_sigmatau, self.canvas_phasenoise):
            style_figure(canvas.fig, self.theme)
            canvas.draw_idle()

    # ------------------------------------------------------------------
    # Log, errors, busy state
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.log.append(msg)
        self.status.showMessage(msg, 5000)

    def _on_tau0_changed(self, val: float) -> None:
        self.tau0 = val

    def _on_f0_changed(self, val: float) -> None:
        self.f0_hz = val

    def _error(self, context: str, exc: BaseException, tb: str = "") -> None:
        detail = tb or "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._log("ERROR during {0}: {1}".format(context, exc))
        QtWidgets.QMessageBox.critical(self, "Error: {0}".format(context),
                                       str(exc) + "\n\n" + detail[-2000:])

    def _need_data(self) -> bool:
        if self.x_s is None:
            QtWidgets.QMessageBox.warning(self, "No data", "Load a time series first.")
            return False
        return True

    def _update_enabled(self) -> None:
        busy = bool(self._running)
        has = self.x_s is not None
        for w in (self.btn_run_drift, self.btn_run_stability, self.btn_run_phasenoise,
                  self.btn_run_all, self.act_drift, self.act_stab, self.act_pn, self.act_all):
            w.setEnabled(has and not busy)
        for w in (self.btn_export_stable32, self.btn_export_veusz, self.act_s32, self.act_vsz,
                  self.act_close):
            w.setEnabled(has and not busy)
        for w in (self.btn_load_csv, self.btn_convert_sa, self.act_load, self.act_convert):
            w.setEnabled(not busy)
        prefix = ("Running: " + ", ".join(sorted(self._running)) + "  |  ") if busy else ""
        self.busy_label.setText(prefix + f"threads {self.workers_spin.value()}, "
                                         f"GPU {_enabled_text(self.chk_gpu.isChecked())}")

    # ------------------------------------------------------------------
    # Background jobs
    # ------------------------------------------------------------------
    def _submit(self, tag: str, fn: Callable[..., Any], *args: Any) -> None:
        """Run fn(*args) on a worker thread; the result arrives in _on_job_done."""
        gen = self._gen
        self._running[tag] = time.perf_counter()
        self._update_enabled()
        self._log(f"Started: {tag} ...")
        fut = self._executor.submit(fn, *args)

        def done(f: Any) -> None:            # runs on the worker thread
            try:
                self._bridge.job_done.emit(tag, gen, f.result(), None)
            except BaseException as exc:      # noqa: BLE001 - reported in the GUI
                self._bridge.job_done.emit(tag, gen, None,
                                           (exc, "".join(traceback.format_exception(
                                               type(exc), exc, exc.__traceback__))))
        fut.add_done_callback(done)

    def _on_job_done(self, tag: str, gen: int, result: Any, error: Any) -> None:
        """GUI thread: apply a finished job (or report its error)."""
        started = self._running.pop(tag, None)
        self._update_enabled()
        if gen != self._gen:
            self._log(f"Discarded {tag} result (new data were loaded meanwhile).")
            return
        if error is not None:
            self._error(tag, error[0], error[1])
            return
        elapsed = time.perf_counter() - started if started else float("nan")
        getattr(self, "_apply_" + tag.replace(" ", "_"))(result)
        self._log(f"Finished: {tag} in {elapsed:.2f} s.")

    def _settings_now(self) -> Tuple[int, bool]:
        workers = int(self.workers_spin.value())
        use_gpu = bool(self.chk_gpu.isChecked())
        if use_gpu and not sc.gpu_available()[0]:
            self._log("GPU requested but not usable ({0}); using the CPU.".format(sc.gpu_available()[1]))
            use_gpu = False
        return workers, use_gpu

    # ---- pure computations (run on worker threads) ---------------------------
    @staticmethod
    def compute_drift(x: np.ndarray, t: np.ndarray, order: int) -> sc.DriftFitResult:
        """Drift fit; order 0 returns the series unchanged."""
        if order == 0:
            return sc.DriftFitResult(order=0, coeffs=[0.0], residual_x=np.array(x, copy=True),
                                     drift_rate=0.0, r_squared=0.0)
        return sc.fit_and_remove_drift(x, t, order=order)

    @staticmethod
    def compute_stability(x: np.ndarray, tau0: float, workers: int, use_gpu: bool) -> tuple:
        """AVAR sweep, ThêoH curve and noise identification."""
        pts = sc.compute_all_deviations(x, tau0, workers=workers)
        theoh = sc.compute_theoh_family(x, tau0, workers=workers, use_gpu=use_gpu)
        return pts, theoh, sc.classify_noise(pts)

    @staticmethod
    def compute_phase_noise(x: np.ndarray, tau0: float, f0_hz: float, workers: int) -> tuple:
        """Welch L(f) and its noise identification."""
        res = pn.ssb_phase_noise_from_time_series(x, tau0, f0_hz, workers=workers)
        return res, pn.classify_freq_domain_noise(res)

    @classmethod
    def compute_all(cls, x: np.ndarray, t: np.ndarray, order: int, tau0: float, f0_hz: float,
                    workers: int, use_gpu: bool) -> tuple:
        """Drift (order > 0), then stability and phase noise on the residual."""
        drift = cls.compute_drift(x, t, order) if order > 0 else None
        x_use = drift.residual_x if drift is not None else x
        return (drift, cls.compute_stability(x_use, tau0, workers, use_gpu),
                cls.compute_phase_noise(x_use, tau0, f0_hz, workers))

    # ---- results applied on the GUI thread ------------------------------------
    def _apply_drift(self, result: sc.DriftFitResult) -> None:
        self.drift_result = result
        if self.dev_points or self.pn_result is not None:
            self._log("Drift fit changed: earlier stability/phase-noise results cleared - re-run them.")
        self._clear_results(keep_drift=True)
        self._plot_raw()
        self._log("Drift fit (order {0}): D = {1:.4e} 1/s (fractional frequency per second), "
                  "R^2 = {2:.4f}".format(result.order, result.drift_rate, result.r_squared))

    def _apply_stability(self, result: tuple) -> None:
        self.dev_points, self.theoh_points, self.noise_class = result
        self._plot_sigma_tau()
        self._fill_noise_table(self.noise_class)
        self._log("Stability analysis: {0} tau points (AVAR family) + {1} ThêoH points.".format(
            len(self.dev_points), len(self.theoh_points)))

    def _apply_phase_noise(self, result: tuple) -> None:
        self.pn_result, self.freq_class = result
        self._plot_phase_noise()
        self._fill_freq_noise_table(self.freq_class)
        self._log("SSB phase noise via Welch PSD (f0 = {0:.6g} Hz).".format(self.f0_hz))

    def _apply_run_all(self, result: tuple) -> None:
        drift, stab, pnr = result
        if drift is not None:
            self._apply_drift(drift)
        self._apply_stability(stab)
        self._apply_phase_noise(pnr)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def _clear_results(self, keep_drift: bool = False) -> None:
        if not keep_drift:
            self.drift_result = None
        self.dev_points, self.theoh_points, self.noise_class = [], [], []
        self.pn_result, self.freq_class = None, []
        for table in (self.table_noise, self.table_freq_noise):
            table.clearContents()
            table.setRowCount(0)
        for canvas in (self.canvas_sigmatau, self.canvas_phasenoise):
            canvas.fig.clear()
            style_figure(canvas.fig, self.theme)
            canvas.draw_idle()

    def _new_data(self) -> None:
        """Forget every result of the previous data (and invalidate jobs)."""
        self._gen += 1
        self._clear_results()
        self.last_vszh5 = None

    def on_load_canonical_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load canonical CSV", "",
                                                        "CSV Files (*.csv);;All files (*)")
        if path:
            try:
                self.load_csv_path(path)
            except Exception as exc:  # noqa: BLE001
                self._error("loading CSV", exc)

    def load_csv_path(self, path: str) -> None:
        """Load a canonical CSV (phase_s, freq_hz or frac_freq column)."""
        s = sc.load_canonical_series(path)
        self._new_data()
        self.t_s, self.x_s, self.value_kind = s.t, s.x, s.source_column
        self.source_path = path
        self.tau0 = s.tau0
        self.tau0_spin.setValue(s.tau0)
        if s.source_column == "freq_hz" and s.f0_hz:
            self.f0_spin.setValue(s.f0_hz)
        self._plot_raw()
        msg = "Loaded {0} rows ({1}) from {2}: {3} phase points, tau0 = {4:.9g} s.".format(
            s.n_rows, s.source_column, path, len(s.x), s.tau0)
        if s.source_column != "phase_s":
            msg += (" Frequency integrated to phase (one more point than rows)"
                    + ("; f0 set to the median frequency {0:.12g} Hz".format(s.f0_hz)
                       if s.f0_hz else "") + ".")
        self._log(msg)
        self._update_enabled()

    def on_convert_sa_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select vendor SA export file")
        if not path:
            return
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save canonical CSV as",
                                                            "canonical.csv", "CSV Files (*.csv)")
        if out_path:
            try:
                self.convert_sa_path(path, out_path)
            except Exception as exc:  # noqa: BLE001
                self._error("converting SA file", exc)

    def convert_sa_path(self, path: str, out_path: str) -> str:
        """Convert a vendor export; load a time series or classify a trace."""
        kind = sac.convert_to_canonical_csv(path, out_path, vendor=self.vendor_combo.currentText(),
                                            value_column_name=self.value_combo.currentText())
        self._log("Converted {0} -> {1} (detected kind: {2}). Verify units against your "
                  "instrument's export documentation.".format(path, out_path, kind))
        if kind == "time_series":
            self.load_csv_path(out_path)
        else:
            data = np.loadtxt(out_path, delimiter=",", skiprows=1, ndmin=2)
            self.pn_result = pn.parse_direct_phase_noise_trace(data[:, 0], data[:, 1])
            self.freq_class = pn.classify_freq_domain_noise(self.pn_result)
            self._plot_phase_noise()
            self._fill_freq_noise_table(self.freq_class)
            self.tabs.setCurrentWidget(self.canvas_phasenoise)
        return kind

    def on_close_data(self) -> None:
        """Release the series and all results (memory)."""
        self._new_data()
        self.t_s = self.x_s = None
        self.source_path = ""
        self.canvas_raw.fig.clear()
        style_figure(self.canvas_raw.fig, self.theme)
        self.canvas_raw.draw_idle()
        self._log("Data and results released.")
        self._update_enabled()

    # ------------------------------------------------------------------
    # Analysis slots
    # ------------------------------------------------------------------
    def _x_use(self) -> np.ndarray:
        return self.drift_result.residual_x if self.drift_result is not None else self.x_s

    def on_run_drift(self) -> None:
        if self._need_data():
            self._submit("drift", self.compute_drift, self.x_s, self.t_s,
                         int(self.drift_order_spin.value()))

    def on_run_stability(self) -> None:
        if self._need_data():
            workers, use_gpu = self._settings_now()
            self._submit("stability", self.compute_stability, self._x_use(), self.tau0,
                         workers, use_gpu)

    def on_run_phase_noise(self) -> None:
        if self._need_data():
            workers, _ = self._settings_now()
            self._submit("phase noise", self.compute_phase_noise, self._x_use(), self.tau0,
                         self.f0_hz, workers)

    def on_run_all(self) -> None:
        if self._need_data():
            workers, use_gpu = self._settings_now()
            self._submit("run all", self.compute_all, self.x_s, self.t_s,
                         int(self.drift_order_spin.value()), self.tau0, self.f0_hz,
                         workers, use_gpu)

    def run_all_blocking(self) -> None:
        """Run All on the calling thread (scripts and tests)."""
        workers, use_gpu = self._settings_now()
        self._apply_run_all(self.compute_all(self.x_s, self.t_s, int(self.drift_order_spin.value()),
                                             self.tau0, self.f0_hz, workers, use_gpu))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def on_export_stable32(self) -> None:
        if not self._need_data():
            return
        filters = ("Stable32 phase (*.PHD);;Stable32 frequency (*.FRD);;"
                   "Sigma-tau table (*.DAT)")
        path, chosen = QtWidgets.QFileDialog.getSaveFileName(self, "Save Stable32 file",
                                                             "output.PHD", filters)
        if not path:
            return
        kind = ("freq" if "frequency" in chosen or path.upper().endswith(".FRD") else
                "table" if "table" in chosen or path.upper().endswith(".DAT") else "phase")
        try:
            self.export_stable32_to(path, kind)
        except Exception as exc:  # noqa: BLE001
            self._error("Stable32 export", exc)

    def export_stable32_to(self, path: str, kind: str = "phase") -> str:
        """Write the (drift-removed, if available) phase, its fractional
        frequency, or the sigma-tau table as a Stable32 ASCII file."""
        x_use = self._x_use()
        title = Path(self.source_path).name if self.source_path else "SA Stability Tool export"
        if kind == "phase":
            s32.write_stable32_phase_file(path, self.t_s, x_use, title=title)
        elif kind == "freq":
            y = sc.phase_to_freq(x_use, self.tau0)
            s32.write_stable32_freq_file(path, self.t_s[:-1], y, title=title)
        elif kind == "table":
            if not self.dev_points:
                raise ValueError("Run the stability analysis before exporting the sigma-tau table.")
            rows = [(p.tau, p.m, p.n_used, p.adev, p.oadev, p.mdev, p.tdev, p.ohdev)
                    for p in self.dev_points]
            s32.write_stable32_sigma_tau_table(
                path, rows, columns=("tau_s", "m", "n", "adev", "oadev", "mdev", "tdev_s", "ohdev"),
                title=title)
        else:
            raise ValueError("kind must be phase, freq or table")
        self._log("Wrote Stable32 {0} file: {1}".format(kind, path))
        return path

    def on_export_veusz(self) -> None:
        if not self._need_data():
            return
        default = (Path(self.source_path).stem if self.source_path else "output") + ".vszh5"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save Veusz HDF5 document", default,
                                                        "Veusz HDF5 documents (*.vszh5)")
        if path:
            try:
                self.export_veusz_to(path, render=self.chk_render.isChecked())
            except Exception as exc:  # noqa: BLE001
                self._error("Veusz export", exc)

    def export_veusz_to(self, path: str, render: bool = False) -> Path:
        """Write the native .vszh5 (in-process); optionally start a render."""
        source = Path(self.source_path).name if self.source_path else ""
        written = ve.export_vszh5(
            path, self.t_s, self.x_s,
            x_residual=self.drift_result.residual_x if self.drift_result is not None else None,
            tau0=self.tau0, f0_hz=self.f0_hz, dev_points=self.dev_points,
            theoh_points=self.theoh_points, noise_classes=self.noise_class,
            phase_noise=self.pn_result, freq_classes=self.freq_class, drift=self.drift_result,
            title=source or "SA Stability Tool export", source=source)
        self.last_vszh5 = written
        self._log("Wrote Veusz HDF5 document: {0} ({1:.1f} KiB) - open it in Veusz "
                  "with File > Open.".format(written, written.stat().st_size / 1024.0))
        if render:
            self.start_render(written)
        return written

    def on_render_existing(self) -> None:
        start = str(self.last_vszh5) if self.last_vszh5 else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Render Veusz HDF5 document",
                                                        start, "Veusz HDF5 documents (*.vszh5)")
        if path:
            self.start_render(Path(path))

    def start_render(self, path: Path) -> None:
        """Render a .vszh5 in a child process on a background thread."""
        self._log("Rendering PDF/PNG from {0} in the background...".format(Path(path).name))
        threading.Thread(target=self._render_worker, args=(Path(path),),
                         name="vszh5-render", daemon=True).start()

    def _render_worker(self, path: Path) -> None:
        """Worker thread: render in a child process, report via the bridge."""
        try:
            files = ve.render_vszh5_subprocess(path, png_pages="all")
            self._bridge.render_done.emit(files, None)
        except Exception as exc:  # noqa: BLE001 - reported in the log
            self._bridge.render_done.emit(None, "{0}: {1}".format(type(exc).__name__, exc))

    def _on_render_finished(self, files: Any, error: Any) -> None:
        """GUI thread: log the render result."""
        if error:
            self._log("Veusz render not done ({0}). The .vszh5 is complete - open it "
                      "in Veusz.".format(error))
        else:
            self._log("Rendered {0} file(s): {1}".format(
                len(files), ", ".join(Path(f).name for f in files)))

    # ------------------------------------------------------------------
    # Help
    # ------------------------------------------------------------------
    def on_about(self) -> None:
        gpu = sc.gpu_available() if self.chk_gpu.isEnabled() else (False, "CuPy not installed")
        QtWidgets.QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b> (SA Time Stability Tools)<br>"
            f"{__copyright__}<br>{__author__} &lt;{__email__}&gt;, {__company__}<br>"
            f"Licence: {__license__} - no warranty.<br><br>"
            f"Qt binding: {Qt.__binding__} {Qt.__binding_version__} via Qt.py {Qt.__version__}<br>"
            f"Python {sys.version.split()[0]}, NumPy {np.__version__}<br>"
            f"stability_core {sc.__version__}, phase_noise {pn.__version__}, "
            f"veusz_export {ve.__version__} (vszh5_writer {ve.vw.__version__})<br>"
            f"CPUs: {sc.available_cpus()}; GPU: {'yes - ' + gpu[1] if gpu[0] else 'no'}<br><br>"
            f"Methods: NIST SP 1065; IEEE Std 1139-2008. See README.md for references.")

    # ------------------------------------------------------------------
    # Plots (GUI thread only)
    # ------------------------------------------------------------------
    def _plot_raw(self) -> None:
        fig = self.canvas_raw.fig
        fig.clear()
        if self.x_s is None:
            self.canvas_raw.draw_idle()
            return
        t_d, x_d = ve.envelope_decimate(self.t_s, self.x_s, SCREEN_MAX_POINTS)
        ax = fig.add_subplot(211 if self.drift_result is not None else 111)
        ax.plot(t_d, x_d, color=PALETTE["blue"], lw=0.8)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Phase / time error x(t) (s)")
        ax.set_title("Raw input series" + (" (min/max envelope)" if len(x_d) < len(self.x_s) else ""))
        ax.grid(True, alpha=0.3)
        if self.drift_result is not None:
            t_r, r_d = ve.envelope_decimate(self.t_s, self.drift_result.residual_x, SCREEN_MAX_POINTS)
            ax2 = fig.add_subplot(212)
            ax2.plot(t_r, r_d, color=PALETTE["orange"], lw=0.8)
            ax2.set_xlabel("Time (s)")
            ax2.set_ylabel("Residual (s)")
            ax2.set_title("Drift-removed residual (order {0})".format(self.drift_result.order))
            ax2.grid(True, alpha=0.3)
        _footnote(fig, self.theme)
        self.canvas_raw.draw_idle()

    def _plot_sigma_tau(self) -> None:
        fig = self.canvas_sigmatau.fig
        fig.clear()
        ax = fig.add_subplot(111)
        tau = [p.tau for p in self.dev_points]
        ax.loglog(tau, [p.oadev for p in self.dev_points], "o-", color=PALETTE["blue"],
                  ms=3, label="OADEV")
        ax.loglog(tau, [p.mdev for p in self.dev_points], "s-", color=PALETTE["orange"],
                  ms=3, label="MDEV")
        ax.loglog(tau, [p.tdev for p in self.dev_points], "^-", color=PALETTE["green"],
                  ms=3, label="TDEV (s)")
        ax.loglog(tau, [p.ohdev for p in self.dev_points], "d-", color=PALETTE["purple"],
                  ms=3, label="OHDEV")
        if self.theoh_points:
            ax.loglog([p[0] for p in self.theoh_points], [p[2] for p in self.theoh_points],
                      "x-", color=PALETTE["red"], ms=4, label="ThêoH")
        ax.set_xlabel("Averaging time tau (s)")
        ax.set_ylabel("Deviation (TDEV in s)")
        ax.set_title("Frequency stability (sigma-tau)")
        ax.legend(fontsize=8)
        ax.grid(True, which="both", alpha=0.3)
        _footnote(fig, self.theme)
        self.canvas_sigmatau.draw_idle()

    def _plot_phase_noise(self) -> None:
        fig = self.canvas_phasenoise.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.semilogx(self.pn_result.freq_hz, self.pn_result.l_f_dbc_hz,
                    color=THEMES[self.theme]["navy"], lw=1.0)
        ax.set_xlabel("Fourier frequency offset f (Hz)")
        ax.set_ylabel("L(f) (dBc/Hz)")
        ax.set_title("SSB Phase Noise ({0})".format(self.pn_result.method))
        ax.grid(True, which="both", alpha=0.3)
        _footnote(fig, self.theme)
        self.canvas_phasenoise.draw_idle()

    def _fill_noise_table(self, classifications: list) -> None:
        self.table_noise.setColumnCount(7)
        self.table_noise.setHorizontalHeaderLabels(
            ["tau (s)", "m", "ADEV slope", "MDEV slope", "OHDEV slope", "Noise type", "Confidence"])
        self.table_noise.setRowCount(len(classifications))
        for i, c in enumerate(classifications):
            cells = ["{0:.4g}".format(c.tau), str(c.m), "{0:.3f}".format(c.slope_adev),
                     "{0:.3f}".format(c.slope_mdev), "{0:.3f}".format(c.slope_hdev),
                     c.noise_type, c.confidence]
            for j, text in enumerate(cells):
                self.table_noise.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table_noise.resizeColumnsToContents()

    def _fill_freq_noise_table(self, classes: list) -> None:
        self.table_freq_noise.setColumnCount(4)
        self.table_freq_noise.setHorizontalHeaderLabels(
            ["f_lo (Hz)", "f_hi (Hz)", "Slope (dB/decade)", "Noise type"])
        self.table_freq_noise.setRowCount(len(classes))
        for i, c in enumerate(classes):
            cells = ["{0:.4g}".format(c.f_lo_hz), "{0:.4g}".format(c.f_hi_hz),
                     "{0:.2f}".format(c.slope_db_per_decade), c.noise_type]
            for j, text in enumerate(cells):
                self.table_freq_noise.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table_freq_noise.resizeColumnsToContents()

    # ------------------------------------------------------------------
    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API name
        """Stop accepting work; running jobs finish in the background."""
        self._executor.shutdown(wait=False)
        super().closeEvent(event)


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
#: The window shown by main(); kept so Spyder's console does not collect it.
_WINDOW: Optional[MainWindow] = None


def _ipython_qt_loop_active() -> bool:
    """True when an IPython console already runs a Qt event loop (%gui qt)."""
    get_ip = getattr(builtins, "get_ipython", None)
    if get_ip is None:
        return False
    try:
        loop = getattr(get_ip(), "active_eventloop", None)
    except Exception:  # noqa: BLE001
        return False
    return str(loop or "").lower().startswith("qt")


def main(argv: Optional[List[str]] = None) -> int:
    """Show the window; run the Qt event loop unless IPython already does."""
    global _WINDOW
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(list(argv) if argv else sys.argv)
    _WINDOW = MainWindow()
    _WINDOW.show()
    if _ipython_qt_loop_active():
        return 0                       # Spyder/IPython with a Qt backend
    run = getattr(app, "exec", None) or getattr(app, "exec_")
    return run()


if __name__ == "__main__":
    _status = main()
    if not getattr(builtins, "__IPYTHON__", False):
        sys.exit(_status)


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# Drive the open window from the console after running the cells above
# (with a Qt graphics backend so the window stays live):
#
# w = _WINDOW
# w.load_csv_path(str(_HERE / "example_data" / "example_maser_phase.csv"))
# w.run_all_blocking()                       # or w.on_run_all() (background)
# w.set_theme("dark")
# w.export_veusz_to(str(_HERE / "example.vszh5"), render=False)
