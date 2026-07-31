"""
SA Long-Time-Measurement Stability & Phase-Noise Analysis -- PySide6 GUI
============================================================================
Desktop front-end tying together the analysis modules in this package:

  - sa_convert.py       vendor SA export -> canonical CSV
  - stability_core.py   ADEV/OADEV/MDEV/TDEV/OHDEV/Theo1/ThêoH, drift
                         removal, time-domain noise classification
  - phase_noise.py       SSB phase noise L(f), frequency-domain noise ID
  - stable32_export.py   Stable32-compatible .PHD/.FRD/.DAT export
  - veusz_export.py       Veusz .vszh5 plot export (spawned as a
                          subprocess -- see that module's docstring for
                          why: avoids a PyQt6/PySide6 conflict in one
                          process)

Follows this project's established code conventions: module docstring
with a numbered IEEE reference list, dataclasses for structured results,
matplotlib (Agg-compatible QtAgg backend) plots embedded via canvas, the
project color palette (#2b6cb0 blue / #dd6b20 orange / #38a169 green /
#805ad5 purple / #e53e3e red / #2c5282 navy), and a footnote citation
band under each plot.

References (IEEE format)
-------------------------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. Available: https://tf.nist.gov/general/pdf/2220.pdf
[2] J. A. Barnes, A. R. Chi, L. S. Cutler, D. J. Healey, D. B. Leeson,
    T. E. McGunigal, J. A. Mullen, W. L. Smith, R. L. Sydnor, R. F. C.
    Vessot, and G. M. R. Winkler, "Characterization of Frequency
    Stability," NBS Technical Note 394 / IEEE Trans. Instrum. Meas.,
    vol. IM-20, no. 2, pp. 105-120, May 1971.
[3] "PySide6 Documentation," Qt for Python. Available: https://doc.qt.io/qtforpython-6/
[4] J. D. Hunter, "Matplotlib: A 2D Graphics Environment," Comput. Sci.
    Eng., vol. 9, no. 3, pp. 90-95, 2007, doi: 10.1109/MCSE.2007.55.

Usage
-----
    python3.12 gui_app.py

Python 3.8 / 3.12 compatible.
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import List, Optional

os.environ.setdefault("QT_API", "pyside6")

import numpy as np
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QComboBox, QSpinBox, QDoubleSpinBox, QFormLayout, QGroupBox, QMessageBox,
    QTextEdit, QSplitter, QStatusBar,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import stability_core as sc
import phase_noise as pn
import sa_convert as sac
import stable32_export as s32

PALETTE = {
    "blue": "#2b6cb0", "orange": "#dd6b20", "green": "#38a169",
    "purple": "#805ad5", "red": "#e53e3e", "navy": "#2c5282",
    "orange_dark": "#c05621",
}
SOURCE_NOTE = ("Analysis per NIST SP1065 [1] / NBS TN394 [2]. Time-domain "
               "estimators: ADEV, OADEV, MDEV, TDEV, OHDEV, Theo1, ThêoH. "
               "Frequency-domain: SSB phase noise L(f) via Welch PSD.")


def _footnote(fig: Figure, text: str = SOURCE_NOTE) -> None:
    fig.text(0.5, 0.02, text, ha="center", va="bottom", fontsize=6.6, wrap=True)
    fig.tight_layout(rect=(0, 0.10, 1, 1))


class MplCanvas(FigureCanvas):
    def __init__(self, width=7, height=5, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        super().__init__(self.fig)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SA Long-Time-Measurement Stability & Phase-Noise Analysis")
        self.resize(1200, 800)

        self.t_s: Optional[np.ndarray] = None
        self.x_s: Optional[np.ndarray] = None
        self.value_kind: str = "phase_s"
        self.tau0: float = 1.0
        self.f0_hz: float = 1.0e7
        self.drift_result: Optional[sc.DriftFitResult] = None
        self.dev_points: List[sc.StabilityPoint] = []
        self.theoh_points = []
        self.pn_result: Optional[pn.PhaseNoiseResult] = None
        self.freq_class = []

        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # --- Top control bar ---
        ctrl = QGroupBox("Data Input")
        ctrl_layout = QHBoxLayout(ctrl)
        self.btn_load_csv = QPushButton("Load Canonical CSV...")
        self.btn_load_csv.clicked.connect(self.on_load_canonical_csv)
        self.btn_convert_sa = QPushButton("Convert Vendor SA File...")
        self.btn_convert_sa.clicked.connect(self.on_convert_sa_file)
        self.vendor_combo = QComboBox()
        self.vendor_combo.addItems(["generic", "keysight", "rs"])
        self.tau0_spin = QDoubleSpinBox()
        self.tau0_spin.setDecimals(6)
        self.tau0_spin.setRange(1e-6, 1e6)
        self.tau0_spin.setValue(1.0)
        self.tau0_spin.valueChanged.connect(self._on_tau0_changed)
        self.f0_spin = QDoubleSpinBox()
        self.f0_spin.setDecimals(1)
        self.f0_spin.setRange(1.0, 1e12)
        self.f0_spin.setValue(1.0e7)
        self.f0_spin.valueChanged.connect(self._on_f0_changed)
        ctrl_layout.addWidget(self.btn_load_csv)
        ctrl_layout.addWidget(QLabel("Vendor:"))
        ctrl_layout.addWidget(self.vendor_combo)
        ctrl_layout.addWidget(self.btn_convert_sa)
        ctrl_layout.addWidget(QLabel("tau0 (s):"))
        ctrl_layout.addWidget(self.tau0_spin)
        ctrl_layout.addWidget(QLabel("f0 (Hz):"))
        ctrl_layout.addWidget(self.f0_spin)
        outer.addWidget(ctrl)

        # --- Analysis control bar ---
        analysis_bar = QGroupBox("Analysis")
        a_layout = QHBoxLayout(analysis_bar)
        self.drift_order_spin = QSpinBox()
        self.drift_order_spin.setRange(0, 2)
        self.drift_order_spin.setValue(1)
        self.btn_run_drift = QPushButton("Remove Drift")
        self.btn_run_drift.clicked.connect(self.on_run_drift)
        self.btn_run_stability = QPushButton("Run Stability Analysis")
        self.btn_run_stability.clicked.connect(self.on_run_stability)
        self.btn_run_phasenoise = QPushButton("Run SSB Phase Noise")
        self.btn_run_phasenoise.clicked.connect(self.on_run_phase_noise)
        a_layout.addWidget(QLabel("Drift fit order:"))
        a_layout.addWidget(self.drift_order_spin)
        a_layout.addWidget(self.btn_run_drift)
        a_layout.addWidget(self.btn_run_stability)
        a_layout.addWidget(self.btn_run_phasenoise)
        outer.addWidget(analysis_bar)

        # --- Export bar ---
        export_bar = QGroupBox("Export")
        e_layout = QHBoxLayout(export_bar)
        self.btn_export_stable32 = QPushButton("Export Stable32 File...")
        self.btn_export_stable32.clicked.connect(self.on_export_stable32)
        self.btn_export_veusz = QPushButton("Export Veusz (.vszh5)...")
        self.btn_export_veusz.clicked.connect(self.on_export_veusz)
        e_layout.addWidget(self.btn_export_stable32)
        e_layout.addWidget(self.btn_export_veusz)
        outer.addWidget(export_bar)

        # --- Tabs ---
        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, stretch=1)

        self.canvas_raw = MplCanvas()
        self.tabs.addTab(self.canvas_raw, "Raw / Residual")

        self.canvas_sigmatau = MplCanvas()
        self.tabs.addTab(self.canvas_sigmatau, "Sigma-Tau (ADEV family)")

        self.table_noise = QTableWidget()
        self.tabs.addTab(self.table_noise, "Time-Domain Noise ID")

        self.canvas_phasenoise = MplCanvas()
        self.tabs.addTab(self.canvas_phasenoise, "SSB Phase Noise")

        self.table_freq_noise = QTableWidget()
        self.tabs.addTab(self.table_freq_noise, "Freq-Domain Noise ID")

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, "Log")

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._log("Ready. Load a canonical CSV or convert a vendor SA export to begin.")

    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        self.log.append(msg)
        self.status.showMessage(msg, 5000)

    def _on_tau0_changed(self, val: float) -> None:
        self.tau0 = val

    def _on_f0_changed(self, val: float) -> None:
        self.f0_hz = val

    def _error(self, context: str, exc: Exception) -> None:
        detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._log("ERROR during {0}: {1}".format(context, exc))
        QMessageBox.critical(self, "Error: {0}".format(context), str(exc) + "\n\n" + detail[-2000:])

    # ------------------------------------------------------------------
    def on_load_canonical_csv(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load canonical CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        try:
            t, x, kind = sc.load_canonical_csv(path)
            self.t_s, self.x_s, self.value_kind = t, x, kind
            if kind != "phase_s":
                self._log("Note: loaded column is '{0}'; converting to phase (s) for "
                          "ADEV/MDEV analysis.".format(kind))
                if kind == "freq_hz":
                    self.x_s = sc.freq_to_phase((self.x_s - self.f0_hz) / self.f0_hz, self.tau0)
                elif kind == "frac_freq":
                    self.x_s = sc.freq_to_phase(self.x_s, self.tau0)
            diffs = np.diff(self.t_s)
            self.tau0 = float(np.median(diffs)) if len(diffs) else 1.0
            self.tau0_spin.setValue(self.tau0)
            self._plot_raw()
            self._log("Loaded {0} points from {1} (tau0={2:.6g} s, kind={3}).".format(
                len(self.t_s), path, self.tau0, kind))
        except Exception as exc:
            self._error("loading CSV", exc)

    def on_convert_sa_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select vendor SA export file")
        if not path:
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "Save canonical CSV as", "canonical.csv",
                                                    "CSV Files (*.csv)")
        if not out_path:
            return
        try:
            kind = sac.convert_to_canonical_csv(path, out_path, vendor=self.vendor_combo.currentText())
            self._log("Converted {0} -> {1} (detected kind: {2}). "
                      "Verify units against your instrument's export documentation.".format(
                          path, out_path, kind))
            if kind == "time_series":
                t, x, k = sc.load_canonical_csv(out_path)
                self.t_s, self.x_s, self.value_kind = t, x, k
                self._plot_raw()
            else:
                data = np.loadtxt(out_path, delimiter=",", skiprows=1)
                self.pn_result = pn.parse_direct_phase_noise_trace(data[:, 0], data[:, 1])
                self._plot_phase_noise()
        except Exception as exc:
            self._error("converting SA file", exc)

    def on_run_drift(self) -> None:
        if self.x_s is None:
            QMessageBox.warning(self, "No data", "Load a time series first.")
            return
        try:
            order = self.drift_order_spin.value()
            if order == 0:
                self.drift_result = sc.DriftFitResult(order=0, coeffs=[0.0],
                                                        residual_x=self.x_s.copy(),
                                                        drift_rate=0.0, r_squared=0.0)
            else:
                self.drift_result = sc.fit_and_remove_drift(self.x_s, self.t_s, order=order)
            self._plot_raw()
            self._log("Drift fit (order {0}): drift_rate={1:.4e} s/s^2, R^2={2:.4f}".format(
                order, self.drift_result.drift_rate, self.drift_result.r_squared))
        except Exception as exc:
            self._error("drift removal", exc)

    def on_run_stability(self) -> None:
        if self.x_s is None:
            QMessageBox.warning(self, "No data", "Load a time series first.")
            return
        try:
            x_use = self.drift_result.residual_x if self.drift_result is not None else self.x_s
            self.dev_points = sc.compute_all_deviations(x_use, self.tau0)
            self.theoh_points = sc.compute_theoh_family(x_use, self.tau0)
            self._plot_sigma_tau()
            classifications = sc.classify_noise(self.dev_points)
            self._fill_noise_table(classifications)
            self._log("Stability analysis complete: {0} tau points (AVAR family) + "
                      "{1} ThêoH points.".format(len(self.dev_points), len(self.theoh_points)))
        except Exception as exc:
            self._error("stability analysis", exc)

    def on_run_phase_noise(self) -> None:
        if self.x_s is None:
            QMessageBox.warning(self, "No data", "Load a time series first.")
            return
        try:
            x_use = self.drift_result.residual_x if self.drift_result is not None else self.x_s
            self.pn_result = pn.ssb_phase_noise_from_time_series(x_use, self.tau0, self.f0_hz)
            self._plot_phase_noise()
            self.freq_class = pn.classify_freq_domain_noise(self.pn_result)
            self._fill_freq_noise_table(self.freq_class)
            self._log("SSB phase noise computed via Welch PSD (f0={0:.4g} Hz).".format(self.f0_hz))
        except Exception as exc:
            self._error("phase noise analysis", exc)

    # ------------------------------------------------------------------
    def on_export_stable32(self) -> None:
        if self.x_s is None:
            QMessageBox.warning(self, "No data", "Load a time series first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Stable32 phase file", "output.PHD",
                                               "Stable32 Phase (*.PHD)")
        if not path:
            return
        try:
            x_use = self.drift_result.residual_x if self.drift_result is not None else self.x_s
            s32.write_stable32_phase_file(path, self.t_s, x_use, title="SA Stability Tool export")
            self._log("Wrote Stable32 phase file: {0}".format(path))
        except Exception as exc:
            self._error("Stable32 export", exc)

    def on_export_veusz(self) -> None:
        if self.x_s is None:
            QMessageBox.warning(self, "No data", "Load a time series first.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Veusz document", "output.vszh5",
                                               "Veusz Documents (*.vszh5)")
        if not path:
            return
        try:
            import veusz_export as ve
            x_resid = self.drift_result.residual_x if self.drift_result is not None else None
            sigma_tau_series = {}
            if self.dev_points:
                sigma_tau_series["OADEV"] = {"tau": [p.tau for p in self.dev_points],
                                              "dev": [p.oadev for p in self.dev_points]}
                sigma_tau_series["MDEV"] = {"tau": [p.tau for p in self.dev_points],
                                             "dev": [p.mdev for p in self.dev_points]}
                sigma_tau_series["TDEV"] = {"tau": [p.tau for p in self.dev_points],
                                             "dev": [p.tdev for p in self.dev_points]}
            pn_f = self.pn_result.freq_hz.tolist() if self.pn_result is not None else None
            pn_l = self.pn_result.l_f_dbc_hz.tolist() if self.pn_result is not None else None
            ve.export_all_plots_subprocess(
                path, self.t_s.tolist(), self.x_s.tolist(),
                x_resid.tolist() if x_resid is not None else None,
                sigma_tau_series, phase_noise_freq=pn_f, phase_noise_lf=pn_l,
                title="SA Stability Tool export",
            )
            self._log("Wrote Veusz document: {0}".format(path))
        except Exception as exc:
            self._error("Veusz export", exc)

    # ------------------------------------------------------------------
    def _plot_raw(self) -> None:
        fig = self.canvas_raw.fig
        fig.clear()
        ax = fig.add_subplot(211)
        ax.plot(self.t_s, self.x_s, color=PALETTE["blue"], lw=0.8)
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Phase / time error x(t) (s)")
        ax.set_title("Raw input series")
        if self.drift_result is not None:
            ax2 = fig.add_subplot(212)
            ax2.plot(self.t_s, self.drift_result.residual_x, color=PALETTE["orange"], lw=0.8)
            ax2.set_xlabel("Time (s)")
            ax2.set_ylabel("Residual (s)")
            ax2.set_title("Drift-removed residual (order {0})".format(self.drift_result.order))
        _footnote(fig)
        self.canvas_raw.draw()

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
                   ms=3, label="TDEV")
        ax.loglog(tau, [p.ohdev for p in self.dev_points], "d-", color=PALETTE["purple"],
                   ms=3, label="OHDEV")
        if self.theoh_points:
            ax.loglog([p[0] for p in self.theoh_points], [p[2] for p in self.theoh_points],
                      "x-", color=PALETTE["red"], ms=4, label="ThêoH")
        ax.set_xlabel("Averaging time tau (s)")
        ax.set_ylabel("Deviation")
        ax.set_title("Frequency stability (sigma-tau)")
        ax.legend(fontsize=8)
        ax.grid(True, which="both", alpha=0.3)
        _footnote(fig)
        self.canvas_sigmatau.draw()

    def _plot_phase_noise(self) -> None:
        fig = self.canvas_phasenoise.fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.semilogx(self.pn_result.freq_hz, self.pn_result.l_f_dbc_hz, color=PALETTE["navy"], lw=1.0)
        ax.set_xlabel("Fourier frequency offset f (Hz)")
        ax.set_ylabel("L(f) (dBc/Hz)")
        ax.set_title("SSB Phase Noise")
        ax.grid(True, which="both", alpha=0.3)
        _footnote(fig)
        self.canvas_phasenoise.draw()

    def _fill_noise_table(self, classifications: list) -> None:
        self.table_noise.setColumnCount(6)
        self.table_noise.setHorizontalHeaderLabels(
            ["tau (s)", "m", "ADEV slope", "MDEV slope", "Noise type", "Confidence"])
        self.table_noise.setRowCount(len(classifications))
        for i, c in enumerate(classifications):
            self.table_noise.setItem(i, 0, QTableWidgetItem("{0:.4g}".format(c.tau)))
            self.table_noise.setItem(i, 1, QTableWidgetItem(str(c.m)))
            self.table_noise.setItem(i, 2, QTableWidgetItem("{0:.3f}".format(c.slope_adev)))
            self.table_noise.setItem(i, 3, QTableWidgetItem("{0:.3f}".format(c.slope_mdev)))
            self.table_noise.setItem(i, 4, QTableWidgetItem(c.noise_type))
            self.table_noise.setItem(i, 5, QTableWidgetItem(c.confidence))
        self.table_noise.resizeColumnsToContents()

    def _fill_freq_noise_table(self, classes: list) -> None:
        self.table_freq_noise.setColumnCount(4)
        self.table_freq_noise.setHorizontalHeaderLabels(
            ["f_lo (Hz)", "f_hi (Hz)", "Slope (dB/decade)", "Noise type"])
        self.table_freq_noise.setRowCount(len(classes))
        for i, c in enumerate(classes):
            self.table_freq_noise.setItem(i, 0, QTableWidgetItem("{0:.4g}".format(c.f_lo_hz)))
            self.table_freq_noise.setItem(i, 1, QTableWidgetItem("{0:.4g}".format(c.f_hi_hz)))
            self.table_freq_noise.setItem(i, 2, QTableWidgetItem("{0:.2f}".format(c.slope_db_per_decade)))
            self.table_freq_noise.setItem(i, 3, QTableWidgetItem(c.noise_type))
        self.table_freq_noise.resizeColumnsToContents()


def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
