#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R&S FSP Spectrum Analyzer Trace Logger
======================================

Connects to a Rohde & Schwarz FSP-series spectrum analyzer over Ethernet (VISA TCPIP),
detects active traces, waits for the running sweep to finish, then captures every
N seconds and appends a CSV row per (frequency, capture) sample.

CSV layout (one row per frequency point, per capture):
    date, time, timestamp_iso, freq_hz, trace1_dBm, trace2_dBm, trace3_dBm, ...
Only columns for traces that were active at the start of the run are included.

Features
--------
* QtPy abstraction layer (works with PyQt5 / PyQt6 / PySide2 / PySide6)
* Filename field, planned start time, manual Start, Stop
* Active-trace LEDs (1, 2, 3) + Recording LED
* Per-capture progress bar (driven by sweep time)
* Live plot of last captured traces (pyqtgraph)
* Sanity check: ensures N >= sweep_time * sweep_count (+ safety margin),
  with a warning dialog quoting the minimum allowed N
* Demo mode: built-in mock instrument so the GUI runs without hardware

Python: written for 3.8+; auto-detects 3.12 and uses faster paths where it helps.

Dependencies:
    pip install qtpy PyQt5 pyqtgraph pyvisa pyvisa-py numpy
"""

from __future__ import annotations

import csv
import math
import os
import sys
import time
import random
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Python version handling
# ---------------------------------------------------------------------------
PY_VERSION = sys.version_info
IS_PY312_PLUS = PY_VERSION >= (3, 12)
if PY_VERSION < (3, 8):
    sys.stderr.write("This program requires Python 3.8 or newer.\n")
    sys.exit(1)

# perf_counter_ns is available since 3.7; on 3.12 it has slightly lower overhead.
_perf = time.perf_counter

# ---------------------------------------------------------------------------
# Qt imports via QtPy
# ---------------------------------------------------------------------------
try:
    from qtpy import QtCore, QtGui, QtWidgets
    from qtpy.QtCore import Qt, QThread, Signal, Slot, QDateTime, QTimer
except Exception as exc:  # pragma: no cover
    sys.stderr.write(
        "QtPy or a Qt binding is not installed. Install with:\n"
        "    pip install qtpy PyQt5\n\n"
        f"Original error: {exc}\n"
    )
    raise

import pyqtgraph as pg

# pyvisa is optional at import time so the GUI still launches in demo mode.
try:
    import pyvisa  # type: ignore
    _HAS_PYVISA = True
except Exception:
    pyvisa = None  # type: ignore
    _HAS_PYVISA = False


# ===========================================================================
# Instrument abstraction
# ===========================================================================
class FSPError(Exception):
    """Raised for any instrument-side error."""


class FSPInstrument:
    """
    Thin wrapper around a VISA session to an R&S FSP spectrum analyzer.

    All methods are synchronous and intended to be called from a worker thread.
    """

    MAX_TRACES = 3  # FSP supports up to 3 traces simultaneously

    def __init__(self, resource: str, timeout_ms: int = 15000):
        if not _HAS_PYVISA:
            raise FSPError(
                "pyvisa is not installed. `pip install pyvisa pyvisa-py` "
                "or use Demo Mode."
            )
        self.resource = resource
        self.rm = pyvisa.ResourceManager("@py")
        self.inst = self.rm.open_resource(resource)
        self.inst.timeout = timeout_ms
        # R&S returns ASCII numbers separated by commas by default; that's fine
        # but for big traces we ask for explicit format.
        try:
            self.inst.write("FORM ASC")
        except Exception:
            pass

    # ---- low level -----------------------------------------------------
    def query(self, cmd: str) -> str:
        return self.inst.query(cmd).strip()

    def write(self, cmd: str) -> None:
        self.inst.write(cmd)

    def close(self) -> None:
        try:
            # Restore continuous sweep on the way out
            self.inst.write("INIT:CONT ON")
        except Exception:
            pass
        try:
            self.inst.close()
        except Exception:
            pass
        try:
            self.rm.close()
        except Exception:
            pass

    # ---- high level ----------------------------------------------------
    def idn(self) -> str:
        return self.query("*IDN?")

    def active_traces(self) -> List[int]:
        """Return list of trace numbers currently displayed (1..3)."""
        active: List[int] = []
        for n in range(1, self.MAX_TRACES + 1):
            # FSP: DISP:WIND:TRAC<n>:STAT? returns 1/0
            try:
                ans = self.query(f"DISP:WIND:TRAC{n}:STAT?")
            except Exception:
                # Fall back to short form
                ans = self.query(f"DISP:TRAC{n}:STAT?")
            if ans.strip().lstrip("+").startswith("1"):
                active.append(n)
        return active

    def sweep_settings(self) -> Dict[str, float]:
        f_start = float(self.query("FREQ:STAR?"))
        f_stop = float(self.query("FREQ:STOP?"))
        n_pts = int(float(self.query("SWE:POIN?")))
        sweep_time = float(self.query("SWE:TIME?"))
        try:
            sweep_count = int(float(self.query("SWE:COUN?")))
        except Exception:
            sweep_count = 1
        if sweep_count < 1:
            sweep_count = 1
        return dict(
            f_start=f_start,
            f_stop=f_stop,
            n_pts=n_pts,
            sweep_time=sweep_time,
            sweep_count=sweep_count,
        )

    def frequency_axis(self, settings: Optional[Dict[str, float]] = None) -> np.ndarray:
        s = settings or self.sweep_settings()
        return np.linspace(s["f_start"], s["f_stop"], int(s["n_pts"]))

    def arm_single(self) -> None:
        """Put the instrument in single-sweep mode and clear status."""
        self.write("INIT:CONT OFF")
        self.write("*CLS")

    def trigger_and_wait(self, timeout_s: float) -> None:
        """Start a single sweep and block until *OPC? returns 1."""
        # Save current timeout, raise it for the long *OPC? wait.
        saved = self.inst.timeout
        try:
            self.inst.timeout = max(saved, int(timeout_s * 1000) + 5000)
            self.write("INIT;*WAI")
            # Belt-and-braces: poll *OPC? as well in case *WAI returns early.
            self.query("*OPC?")
        finally:
            self.inst.timeout = saved

    def fetch_trace(self, trace_num: int) -> np.ndarray:
        raw = self.query(f"TRAC:DATA? TRACE{trace_num}")
        # Comma-separated ASCII floats
        return np.fromstring(raw, sep=",", dtype=float)


# ===========================================================================
# Mock instrument (for Demo Mode and testing)
# ===========================================================================
class MockFSPInstrument:
    """
    Emulates an R&S FSP just well enough to drive the GUI / logger
    without any hardware attached.
    """
    MAX_TRACES = 3

    def __init__(self, resource: str = "MOCK::FSP", timeout_ms: int = 15000,
                 active=(1, 2), n_pts: int = 801,
                 f_start: float = 1.0e9, f_stop: float = 2.0e9,
                 sweep_time: float = 1.0, sweep_count: int = 1):
        self.resource = resource
        self._active = list(active)
        self._n_pts = int(n_pts)
        self._f_start = float(f_start)
        self._f_stop = float(f_stop)
        self._sweep_time = float(sweep_time)
        self._sweep_count = int(sweep_count)
        self._continuous = True
        self._sweep_started = 0.0
        self._frame = 0

    # interface compatibility
    def idn(self) -> str:
        return "Rohde&Schwarz,FSP-MOCK,1234567,1.99"

    def active_traces(self) -> List[int]:
        return list(self._active)

    def sweep_settings(self) -> Dict[str, float]:
        return dict(
            f_start=self._f_start, f_stop=self._f_stop,
            n_pts=self._n_pts, sweep_time=self._sweep_time,
            sweep_count=self._sweep_count,
        )

    def frequency_axis(self, settings=None) -> np.ndarray:
        return np.linspace(self._f_start, self._f_stop, self._n_pts)

    def arm_single(self) -> None:
        self._continuous = False

    def trigger_and_wait(self, timeout_s: float) -> None:
        # Simulate sweep duration
        total = self._sweep_time * self._sweep_count
        deadline = _perf() + min(total, max(0.05, timeout_s))
        self._sweep_started = _perf()
        while _perf() < deadline:
            time.sleep(0.02)
        self._frame += 1

    def fetch_trace(self, trace_num: int) -> np.ndarray:
        f = self.frequency_axis()
        # Build a believable spectrum: noise floor + some peaks per trace.
        rng = np.random.default_rng(seed=(self._frame * 31 + trace_num))
        noise = -90 + 3.0 * rng.standard_normal(self._n_pts)
        x = (f - self._f_start) / max(1.0, (self._f_stop - self._f_start))
        # Different trace shapes
        if trace_num == 1:
            sig = -30 - 40 * (x - 0.30) ** 2 / 0.005
        elif trace_num == 2:
            sig = -25 - 40 * (x - 0.55) ** 2 / 0.003
        else:
            sig = -35 - 40 * (x - 0.75) ** 2 / 0.004
        sig = np.maximum(sig, -120)
        # Add a slow drift between captures
        drift = 1.5 * math.sin(self._frame / 4.0 + trace_num)
        return np.maximum(noise, sig) + drift

    def close(self) -> None:
        pass


# ===========================================================================
# Acquisition worker (runs in a QThread)
# ===========================================================================
@dataclass
class RunConfig:
    interval_s: float
    filename: str
    start_at: Optional[datetime] = None  # None = start immediately
    safety_margin: float = 0.10  # 10% headroom for "different sweep" check


class AcquisitionWorker(QtCore.QObject):
    # Signals to the GUI
    statusMessage = Signal(str)
    activeTracesDetected = Signal(list)        # list[int]
    sweepInfo = Signal(dict)                   # sweep_settings dict
    captureStarted = Signal(int, float)        # capture_index, sweep_total_s
    captureProgress = Signal(int, float)       # capture_index, fraction 0..1
    captureFinished = Signal(int, object, dict)  # idx, freq array, {trace: data}
    recordingStateChanged = Signal(bool)
    errorOccurred = Signal(str)
    finished = Signal()

    def __init__(self, instrument, config: RunConfig, parent=None):
        super().__init__(parent)
        self.inst = instrument
        self.cfg = config
        self._stop = False
        self._capture_idx = 0
        self._freq_axis: Optional[np.ndarray] = None
        self._active: List[int] = []
        self._sweep_total: float = 1.0
        self._csv_path = config.filename
        self._csv_file = None
        self._csv_writer = None

    # ----- control -----
    @Slot()
    def stop(self):
        self._stop = True

    # ----- main loop -----
    @Slot()
    def run(self):
        try:
            self._run_inner()
        except Exception as exc:
            tb = traceback.format_exc()
            self.errorOccurred.emit(f"{exc}\n\n{tb}")
        finally:
            try:
                if self._csv_file is not None:
                    self._csv_file.flush()
                    self._csv_file.close()
            except Exception:
                pass
            self.recordingStateChanged.emit(False)
            self.finished.emit()

    def _run_inner(self):
        self.statusMessage.emit("Reading sweep settings…")
        settings = self.inst.sweep_settings()
        self.sweepInfo.emit(settings)
        self._sweep_total = settings["sweep_time"] * settings["sweep_count"]

        self.statusMessage.emit("Detecting active traces…")
        active = self.inst.active_traces()
        if not active:
            raise RuntimeError("No traces are active on the instrument.")
        self._active = active
        self.activeTracesDetected.emit(active)

        self._freq_axis = self.inst.frequency_axis(settings)

        # Open CSV, write header
        self._open_csv()

        # Wait until planned start time (if any)
        if self.cfg.start_at is not None:
            self._wait_until(self.cfg.start_at)
            if self._stop:
                return

        self.statusMessage.emit("Recording…")
        self.recordingStateChanged.emit(True)

        # Put instrument in single-sweep mode for clean grabs
        self.inst.arm_single()

        next_trigger = _perf()
        while not self._stop:
            # Wait until it's time for the next capture
            now = _perf()
            if now < next_trigger:
                # Sleep in small slices so Stop is responsive
                self._sleep_responsive(next_trigger - now)
                if self._stop:
                    break

            self._capture_idx += 1
            idx = self._capture_idx
            self.captureStarted.emit(idx, self._sweep_total)

            # Trigger sweep + drive progress bar based on elapsed time
            self._trigger_with_progress(idx)
            if self._stop:
                break

            # Fetch all active traces
            traces: Dict[int, np.ndarray] = {}
            for tn in self._active:
                traces[tn] = self.inst.fetch_trace(tn)

            # Sanity: frequency axis should not have changed mid-run
            current_axis = self.inst.frequency_axis()
            if (current_axis.shape != self._freq_axis.shape
                    or not np.allclose(current_axis, self._freq_axis, rtol=1e-9, atol=1e-3)):
                self.errorOccurred.emit(
                    "Sweep settings changed on the instrument during the run. "
                    "Recording stopped to keep the frequency axis consistent."
                )
                break

            # Write rows
            self._write_capture(traces)

            # Notify GUI for plot update
            self.captureFinished.emit(idx, self._freq_axis.copy(),
                                      {k: v.copy() for k, v in traces.items()})

            # Schedule next trigger (drift-free cadence)
            next_trigger += self.cfg.interval_s
            # If we fell behind, snap forward but keep cadence tight
            if _perf() > next_trigger + self.cfg.interval_s:
                next_trigger = _perf()

        self.statusMessage.emit("Stopped.")

    # ----- helpers -----
    def _open_csv(self):
        # Ensure parent dir exists
        d = os.path.dirname(os.path.abspath(self._csv_path))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        self._csv_file = open(self._csv_path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv_file)
        header = ["date", "time", "timestamp_iso", "freq_hz"] + \
                 [f"trace{n}_dBm" for n in self._active]
        self._csv_writer.writerow(header)
        self._csv_file.flush()

    def _write_capture(self, traces: Dict[int, np.ndarray]):
        now = datetime.now()
        d = now.strftime("%Y-%m-%d")
        t = now.strftime("%H:%M:%S.%f")[:-3]
        iso = now.isoformat(timespec="milliseconds")
        freq = self._freq_axis
        # Validate trace lengths
        for tn, arr in traces.items():
            if arr.shape[0] != freq.shape[0]:
                raise RuntimeError(
                    f"Trace {tn} returned {arr.shape[0]} points, "
                    f"expected {freq.shape[0]}."
                )
        rows = []
        for i in range(freq.shape[0]):
            row = [d, t, iso, f"{freq[i]:.6f}"]
            for tn in self._active:
                row.append(f"{traces[tn][i]:.4f}")
            rows.append(row)
        self._csv_writer.writerows(rows)
        self._csv_file.flush()

    def _wait_until(self, target: datetime):
        self.statusMessage.emit(f"Waiting until {target.strftime('%H:%M:%S')}…")
        while not self._stop:
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def _sleep_responsive(self, seconds: float):
        end = _perf() + seconds
        while not self._stop and _perf() < end:
            time.sleep(min(0.1, end - _perf()))

    def _trigger_with_progress(self, idx: int):
        """
        Tell the instrument to take a single sweep, then poll *OPC? —
        but in parallel emit progress based on the known sweep time so the
        progress bar advances smoothly.
        """
        total = max(0.05, self._sweep_total)

        # Start a timer-driven progress emission via a small busy loop in this
        # thread; we run the trigger blocking but split into a separate "thread"
        # would over-engineer this. Instead, we use a non-blocking pattern:
        # set INIT; then poll *OPC? while emitting progress.
        try:
            # Begin sweep without blocking on *WAI
            self.inst.write("INIT")  # type: ignore[attr-defined]
            poll_started = _perf()
            # Poll *OPC? with a generous timeout but emit progress in between.
            # We can't rely on *OPC? being non-blocking, so we use STAT:OPER:COND?
            # if available; otherwise fall back to time-based progress.
            while not self._stop:
                elapsed = _perf() - poll_started
                frac = min(0.99, elapsed / total)
                self.captureProgress.emit(idx, frac)
                # Try a short non-blocking-ish status query
                try:
                    # ESR bit 0 = Operation Complete after *OPC.
                    # Issue *OPC once; subsequent *ESR? polls return when done.
                    if elapsed < 0.05:
                        self.inst.write("*OPC")  # type: ignore[attr-defined]
                    esr = self.inst.query("*ESR?")  # type: ignore[attr-defined]
                    if int(float(esr)) & 0x01:
                        break
                except Exception:
                    # If ESR-style polling isn't available (e.g. mock), fall
                    # back to a time-based wait.
                    if elapsed >= total:
                        break
                # Cap the wait at sweep_time + generous slack
                if elapsed > total * 3 + 5.0:
                    raise FSPError("Timed out waiting for sweep completion.")
                time.sleep(0.05)
            self.captureProgress.emit(idx, 1.0)
        except AttributeError:
            # Mock path: use trigger_and_wait + linear progress via a QTimer-less loop
            t0 = _perf()
            self.inst.trigger_and_wait(total + 5.0)
            while _perf() - t0 < total and not self._stop:
                self.captureProgress.emit(idx, min(0.99, (_perf() - t0) / total))
                time.sleep(0.05)
            self.captureProgress.emit(idx, 1.0)


# ===========================================================================
# Custom LED widget
# ===========================================================================
class LedIndicator(QtWidgets.QFrame):
    def __init__(self, label: str, color_on=QtGui.QColor("#2ecc71"),
                 color_off=QtGui.QColor("#555555"), parent=None):
        super().__init__(parent)
        self._on = False
        self._on_color = color_on
        self._off_color = color_off
        self._label_text = label
        self.setFixedHeight(28)
        self.setMinimumWidth(70)

    def setOn(self, on: bool):
        if on != self._on:
            self._on = on
            self.update()

    def isOn(self) -> bool:
        return self._on

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        # LED circle
        d = 16
        cx, cy = 14, self.height() // 2
        color = self._on_color if self._on else self._off_color
        grad = QtGui.QRadialGradient(cx - 3, cy - 3, d)
        grad.setColorAt(0.0, color.lighter(160))
        grad.setColorAt(1.0, color.darker(180))
        p.setBrush(QtGui.QBrush(grad))
        p.setPen(QtGui.QPen(QtGui.QColor("#222"), 1))
        p.drawEllipse(cx - d // 2, cy - d // 2, d, d)
        # Label
        p.setPen(QtGui.QPen(self.palette().windowText(), 1))
        f = self.font()
        p.setFont(f)
        p.drawText(cx + d // 2 + 6, 0, self.width() - cx - d, self.height(),
                   Qt.AlignVCenter | Qt.AlignLeft, self._label_text)
        p.end()


# ===========================================================================
# Main GUI
# ===========================================================================
TRACE_COLORS = ["#f1c40f", "#3498db", "#e74c3c"]  # 1, 2, 3


class MainWindow(QtWidgets.QMainWindow):
    requestStop = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R&S FSP Trace Logger")
        self.resize(1100, 720)

        self.instrument = None  # FSPInstrument or MockFSPInstrument
        self.thread: Optional[QThread] = None
        self.worker: Optional[AcquisitionWorker] = None
        self._sweep_settings: Dict[str, float] = {}
        self._active_traces: List[int] = []

        self._build_ui()
        self._wire_signals()

    # -------- UI construction --------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        # Connection group
        conn_box = QtWidgets.QGroupBox("Connection")
        cl = QtWidgets.QGridLayout(conn_box)
        cl.addWidget(QtWidgets.QLabel("VISA Resource:"), 0, 0)
        self.resource_edit = QtWidgets.QLineEdit("TCPIP::192.168.1.10::INSTR")
        cl.addWidget(self.resource_edit, 0, 1, 1, 3)
        self.demo_check = QtWidgets.QCheckBox("Demo Mode (no hardware)")
        cl.addWidget(self.demo_check, 0, 4)
        self.connect_btn = QtWidgets.QPushButton("Connect")
        cl.addWidget(self.connect_btn, 0, 5)
        self.disconnect_btn = QtWidgets.QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        cl.addWidget(self.disconnect_btn, 0, 6)
        cl.addWidget(QtWidgets.QLabel("Instrument ID:"), 1, 0)
        self.idn_label = QtWidgets.QLabel("(not connected)")
        self.idn_label.setStyleSheet("color: #888;")
        cl.addWidget(self.idn_label, 1, 1, 1, 6)
        root.addWidget(conn_box)

        # Settings group
        set_box = QtWidgets.QGroupBox("Recording Settings")
        sl = QtWidgets.QGridLayout(set_box)
        sl.addWidget(QtWidgets.QLabel("Output File:"), 0, 0)
        self.file_edit = QtWidgets.QLineEdit(
            os.path.join(os.path.expanduser("~"), "fsp_traces.csv"))
        sl.addWidget(self.file_edit, 0, 1, 1, 4)
        self.browse_btn = QtWidgets.QPushButton("Browse…")
        sl.addWidget(self.browse_btn, 0, 5)

        sl.addWidget(QtWidgets.QLabel("Interval N (s):"), 1, 0)
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setRange(0.1, 86400.0)
        self.interval_spin.setDecimals(2)
        self.interval_spin.setValue(5.0)
        sl.addWidget(self.interval_spin, 1, 1)

        sl.addWidget(QtWidgets.QLabel("Planned start:"), 1, 2)
        self.start_dt = QtWidgets.QDateTimeEdit(QDateTime.currentDateTime())
        self.start_dt.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.start_dt.setCalendarPopup(True)
        sl.addWidget(self.start_dt, 1, 3)
        self.now_btn = QtWidgets.QPushButton("Set Now")
        sl.addWidget(self.now_btn, 1, 4)

        self.start_manual_btn = QtWidgets.QPushButton("Start Now")
        self.start_scheduled_btn = QtWidgets.QPushButton("Start at Time")
        self.stop_btn = QtWidgets.QPushButton("Stop")
        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.stop_btn.setEnabled(False)
        sl.addWidget(self.start_manual_btn, 2, 1)
        sl.addWidget(self.start_scheduled_btn, 2, 2)
        sl.addWidget(self.stop_btn, 2, 3)
        root.addWidget(set_box)

        # Status / LEDs group
        st_box = QtWidgets.QGroupBox("Status")
        stl = QtWidgets.QGridLayout(st_box)
        self.led_t1 = LedIndicator("Trace 1", QtGui.QColor(TRACE_COLORS[0]))
        self.led_t2 = LedIndicator("Trace 2", QtGui.QColor(TRACE_COLORS[1]))
        self.led_t3 = LedIndicator("Trace 3", QtGui.QColor(TRACE_COLORS[2]))
        self.led_rec = LedIndicator("RECORDING", QtGui.QColor("#e74c3c"))
        stl.addWidget(self.led_t1, 0, 0)
        stl.addWidget(self.led_t2, 0, 1)
        stl.addWidget(self.led_t3, 0, 2)
        stl.addWidget(self.led_rec, 0, 3)

        stl.addWidget(QtWidgets.QLabel("Capture progress:"), 1, 0)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        stl.addWidget(self.progress, 1, 1, 1, 3)

        self.status_label = QtWidgets.QLabel("Idle.")
        stl.addWidget(self.status_label, 2, 0, 1, 4)
        root.addWidget(st_box)

        # Plot
        plot_box = QtWidgets.QGroupBox("Last Captured Traces")
        pl = QtWidgets.QVBoxLayout(plot_box)
        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground("#202020")
        self.plot.setLabel("bottom", "Frequency", units="Hz")
        self.plot.setLabel("left", "Power", units="dBm")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.addLegend()
        pl.addWidget(self.plot)
        self._plot_curves: Dict[int, pg.PlotDataItem] = {}
        root.addWidget(plot_box, stretch=1)

    def _wire_signals(self):
        self.connect_btn.clicked.connect(self.on_connect)
        self.disconnect_btn.clicked.connect(self.on_disconnect)
        self.browse_btn.clicked.connect(self.on_browse)
        self.now_btn.clicked.connect(
            lambda: self.start_dt.setDateTime(QDateTime.currentDateTime()))
        self.start_manual_btn.clicked.connect(lambda: self.on_start(scheduled=False))
        self.start_scheduled_btn.clicked.connect(lambda: self.on_start(scheduled=True))
        self.stop_btn.clicked.connect(self.on_stop)

    # -------- Slots --------
    @Slot()
    def on_browse(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Choose output CSV", self.file_edit.text(),
            "CSV files (*.csv);;All files (*)")
        if path:
            self.file_edit.setText(path)

    @Slot()
    def on_connect(self):
        try:
            if self.demo_check.isChecked():
                self.instrument = MockFSPInstrument()
            else:
                if not _HAS_PYVISA:
                    raise FSPError(
                        "pyvisa is not installed; install it or enable Demo Mode.")
                self.instrument = FSPInstrument(self.resource_edit.text().strip())
            idn = self.instrument.idn()
            self.idn_label.setText(idn)
            self.idn_label.setStyleSheet("color: #2ecc71;")
            # Refresh trace LEDs and sweep info immediately
            self._refresh_instrument_state()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.start_manual_btn.setEnabled(True)
            self.start_scheduled_btn.setEnabled(True)
            self.demo_check.setEnabled(False)
            self.resource_edit.setEnabled(False)
            self.status_label.setText("Connected.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Connection failed", str(exc))

    @Slot()
    def on_disconnect(self):
        if self.thread is not None:
            QtWidgets.QMessageBox.warning(
                self, "Recording active", "Stop recording before disconnecting.")
            return
        if self.instrument is not None:
            try:
                self.instrument.close()
            except Exception:
                pass
            self.instrument = None
        self.idn_label.setText("(not connected)")
        self.idn_label.setStyleSheet("color: #888;")
        self.connect_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.demo_check.setEnabled(True)
        self.resource_edit.setEnabled(True)
        for led in (self.led_t1, self.led_t2, self.led_t3):
            led.setOn(False)
        self.status_label.setText("Disconnected.")

    def _refresh_instrument_state(self):
        try:
            self._sweep_settings = self.instrument.sweep_settings()
            self._active_traces = self.instrument.active_traces()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Instrument query failed", str(exc))
            return
        self._update_trace_leds(self._active_traces)
        s = self._sweep_settings
        self.status_label.setText(
            f"Sweep: {s['f_start']/1e6:.3f}–{s['f_stop']/1e6:.3f} MHz, "
            f"{int(s['n_pts'])} pts, sweep_time={s['sweep_time']*1000:.1f} ms × "
            f"count={int(s['sweep_count'])} (total {s['sweep_time']*s['sweep_count']*1000:.1f} ms)"
        )

    def _update_trace_leds(self, active: List[int]):
        self.led_t1.setOn(1 in active)
        self.led_t2.setOn(2 in active)
        self.led_t3.setOn(3 in active)

    def _min_required_interval(self) -> float:
        s = self._sweep_settings
        if not s:
            return 0.0
        total = s["sweep_time"] * s["sweep_count"]
        return total * 1.10  # 10% safety margin

    @Slot()
    def on_start(self, scheduled: bool):
        if self.instrument is None:
            return
        # Refresh once more so the sanity check uses live values
        self._refresh_instrument_state()
        if not self._active_traces:
            QtWidgets.QMessageBox.warning(
                self, "No active traces",
                "No traces are currently displayed on the spectrum analyzer.")
            return
        N = float(self.interval_spin.value())
        min_N = self._min_required_interval()
        if N < min_N:
            QtWidgets.QMessageBox.warning(
                self, "Interval too short",
                f"The chosen interval N = {N:.3f} s is shorter than the minimum "
                f"required for the current sweep settings.\n\n"
                f"Sweep time × count = {self._sweep_settings['sweep_time']*self._sweep_settings['sweep_count']:.3f} s\n"
                f"Minimum N (with 10% margin) = {min_N:.3f} s\n\n"
                f"Increase N to at least {min_N:.3f} s, or change the sweep settings "
                f"on the analyzer, then try again."
            )
            return

        filename = self.file_edit.text().strip()
        if not filename:
            QtWidgets.QMessageBox.warning(
                self, "Missing filename", "Please specify an output CSV filename.")
            return

        start_at = None
        if scheduled:
            start_at = self.start_dt.dateTime().toPyDateTime()
            if start_at < datetime.now():
                QtWidgets.QMessageBox.warning(
                    self, "Start time is in the past",
                    "Pick a start time in the future or use Start Now.")
                return

        cfg = RunConfig(interval_s=N, filename=filename, start_at=start_at)

        # Build worker + thread
        self.thread = QThread(self)
        self.worker = AcquisitionWorker(self.instrument, cfg)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.statusMessage.connect(self.on_status)
        self.worker.activeTracesDetected.connect(self._update_trace_leds)
        self.worker.sweepInfo.connect(self.on_sweep_info)
        self.worker.captureStarted.connect(self.on_capture_started)
        self.worker.captureProgress.connect(self.on_capture_progress)
        self.worker.captureFinished.connect(self.on_capture_finished)
        self.worker.recordingStateChanged.connect(self.led_rec.setOn)
        self.worker.errorOccurred.connect(self.on_worker_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.requestStop.connect(self.worker.stop, Qt.DirectConnection)
        self.thread.start()

        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)

    @Slot()
    def on_stop(self):
        if self.worker is not None:
            self.requestStop.emit()
            self.status_label.setText("Stopping…")

    @Slot(str)
    def on_status(self, msg: str):
        self.status_label.setText(msg)

    @Slot(dict)
    def on_sweep_info(self, info: dict):
        self._sweep_settings = info

    @Slot(int, float)
    def on_capture_started(self, idx: int, total_s: float):
        self.progress.setValue(0)
        self.status_label.setText(f"Capture #{idx} — sweeping ({total_s:.2f} s)…")

    @Slot(int, float)
    def on_capture_progress(self, idx: int, frac: float):
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    @Slot(int, object, dict)
    def on_capture_finished(self, idx: int, freq, traces: dict):
        self.progress.setValue(1000)
        self.status_label.setText(f"Capture #{idx} written ({len(freq)} pts × {len(traces)} traces).")
        # Update plot
        self.plot.clear()
        self._plot_curves.clear()
        for tn in sorted(traces.keys()):
            color = TRACE_COLORS[(tn - 1) % len(TRACE_COLORS)]
            curve = self.plot.plot(
                freq, traces[tn], pen=pg.mkPen(color, width=2),
                name=f"Trace {tn}")
            self._plot_curves[tn] = curve

    @Slot(str)
    def on_worker_error(self, msg: str):
        QtWidgets.QMessageBox.critical(self, "Acquisition error", msg)

    @Slot()
    def on_worker_finished(self):
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)
            self.thread = None
        self.worker = None
        self.led_rec.setOn(False)
        self.progress.setValue(0)
        self.start_manual_btn.setEnabled(True)
        self.start_scheduled_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(True)
        self.status_label.setText("Idle.")

    # Make sure we shut down cleanly
    def closeEvent(self, ev):
        try:
            if self.worker is not None:
                self.requestStop.emit()
            if self.thread is not None:
                self.thread.quit()
                self.thread.wait(3000)
            if self.instrument is not None:
                self.instrument.close()
        except Exception:
            pass
        super().closeEvent(ev)


# ===========================================================================
# Entry point
# ===========================================================================
def main():
    # Allow forcing demo mode from CLI for convenience
    demo = "--demo" in sys.argv
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("R&S FSP Trace Logger")
    win = MainWindow()
    if demo:
        win.demo_check.setChecked(True)
    win.show()
    sys.exit(app.exec_() if hasattr(app, "exec_") else app.exec())


if __name__ == "__main__":
    main()
