#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Qt GUI of the SHR Converter: Signal Hound .shr -> CSV and Veusz .vszh5.

===============================================================================
 Title          : SHR Converter - graphical user interface
 Filename       : shr_converter_gui.py
 Version        : 0.0.2 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12 (3.10 or later)
 Requires       : shr_converter_core.py 0.0.2 and its requirements; Qt.py
                  (abstraction layer) + PySide6 (binding); pyqtgraph (preview)
 Optional       : QtPy instead of Qt.py (SHR_CONVERTER_QT_LAYER=qtpy), psutil
                  (memory read-out), Veusz (open/render), cupy (GPU)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Derived from   : Qt binding selection, ThemeManager, menu/toolbar/dock layout,
                  TaskThread and About dialog follow the author's EMF Envelope
                  FFT Analyzer 0.0.4 and QuickSyn SCPI controller 0.0.10.
 Start with     : python shr_converter.py   (the launcher; it keeps Qt out of
                  the conversion worker processes)
 Status         : Internal draft - smoke-tested offscreen (--gui-smoke).
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

WINDOW
------
    +-- menu bar: File  Edit  View  Convert  Veusz  Help ----------------------+
    +-- toolbar: Add files | Add folder | Inspect | Convert | Stop | Veusz ... -+
    | Settings dock (left)   | Preview | File info | Outputs  (centre tabs)     |
    |  Input files table     |  spectrogram (peak hold), statistics spectrum,  |
    |  Output folder         |  level versus time - pyqtgraph, crosshair       |
    |  CSV / Veusz /         |                                                 |
    |  Selection /           |                                                 |
    |  Performance groups    |                                                 |
    +-- Log dock (bottom, bounded) --------------------------------------------+
    +-- status bar: message | cursor read-out | memory | progress -------------+

Inspect (Ctrl+I) reads the selected file's header, shows the processing plan
and computes the preview without writing anything. Convert (F5) converts every
listed file; Shift+F5 only the selected ones; Esc stops after the current
block and deletes that file's partial outputs.

MEMORY
------
The preview of each converted file is kept on disk (pickle, protocol 5, in a
private temporary folder deleted on exit); only the file shown is in memory.
Edit > Free memory (Ctrl+Shift+M) drops the shown preview too and runs
flush_memory() (garbage collector, CuPy pools, malloc_trim / EmptyWorkingSet).
The status bar shows this process's resident memory (psutil).

REFERENCES
----------
[G1] M. Ottosson et al., "Qt.py - Minimal Python 2 & 3 shim around all Qt
     bindings," v2.0.7. https://github.com/mottosso/Qt.py
[G2] The Qt Company, "Qt for Python (PySide6)." https://doc.qt.io/qtforpython-6/
[G3] pyqtgraph developers, "pyqtgraph documentation."
     https://pyqtgraph.readthedocs.io/en/latest/
[G4] J. Sanders, "Veusz - a scientific plotting package." https://veusz.github.io/

REVISION HISTORY (newest first)
----------------
0.0.2  2026-10-28  With shr_converter_core 0.0.2, shr_reader 0.0.1 and
                   vszh5_writer 0.0.21: CSV group "Combine" (csv_decimate,
                   peak hold / power mean / min), Selection "Join the files
                   of one recording" (multi-file Spike recordings), reader
                   version in the log and About box (py-shr-parser is no
                   longer used), every file of a joined recording gets its
                   status, smoke test of join + decimation.
0.0.1  2026-10-28  First internal draft with shr_converter_core 0.0.1 and
                   vszh5_writer 0.0.20.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

_MODULE_FOLDER = Path(globals().get("__file__", Path.cwd() / "_")).resolve().parent
if str(_MODULE_FOLDER) not in sys.path:
    sys.path.insert(0, str(_MODULE_FOLDER))

import shr_converter_core as core  # noqa: E402
import vszh5_writer  # noqa: E402

__version__ = "0.0.2"
__author__ = core.__author__
APP_NAME = core.PROGRAM_NAME
APP_ORG = "NRAO-GBO"
#: QSettings scope; the smoke test points it elsewhere so the user's own
#: settings are never read or overwritten.
SETTINGS_SCOPE = [APP_ORG, APP_NAME]
#: Manual opened by Help > User manual (F1).
MANUAL_PDF = _MODULE_FOLDER / "docs" / f"SHR_Converter_Manual_v{__version__}.pdf"


# %% ===========================================================================
#    QT BINDING (Qt.py abstraction layer, PySide6 binding)
# =============================================================================
QT_LAYER_PREFERENCE = os.environ.get("SHR_CONVERTER_QT_LAYER", "qt.py").strip().lower()


def _import_qt() -> tuple[Any, Any, Any, str, str, list[str]]:
    """QtCore, QtGui, QtWidgets through Qt.py (else QtPy, else PySide6 directly).

    Qt.py is asked for PySide6 (QT_PREFERRED_BINDING); pyqtgraph is pointed
    at the same binding. Returns the modules, the layer and binding names
    and the errors of layers that failed.
    """
    os.environ.setdefault("QT_PREFERRED_BINDING", "PySide6")   # read by Qt.py
    os.environ.setdefault("QT_API", "pyside6")                  # read by QtPy
    os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")        # read by pyqtgraph
    order = ["qtpy", "qt.py"] if QT_LAYER_PREFERENCE == "qtpy" else ["qt.py", "qtpy"]
    errors: list[str] = []
    for layer in order + ["pyside6"]:
        try:
            if layer == "qt.py":
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")      # Qt.py notes modules we never use
                    import Qt as qt_layer
                from Qt import QtCore as c, QtGui as g, QtWidgets as w
                return (c, g, w, f"Qt.py {qt_layer.__version__}",
                        f"{qt_layer.__binding__} {qt_layer.__binding_version__} (Qt {qt_layer.__qt_version__})",
                        errors)
            if layer == "qtpy":
                import qtpy as qt_layer
                from qtpy import QtCore as c, QtGui as g, QtWidgets as w
                return c, g, w, f"QtPy {qt_layer.__version__}", f"{qt_layer.API_NAME} (Qt {qt_layer.QT_VERSION})", errors
            import PySide6
            from PySide6 import QtCore as c, QtGui as g, QtWidgets as w
            return c, g, w, "PySide6 directly (no abstraction layer)", f"PySide6 {PySide6.__version__}", errors
        except Exception as exc:  # noqa: BLE001 - try the next layer
            errors.append(f"{layer}: {type(exc).__name__}: {exc}")
    raise ImportError("no Qt binding: install Qt.py and PySide6 "
                      "(mamba install -c conda-forge qt.py pyside6)\n" + "\n".join(errors))


QtCore, QtGui, QtWidgets, QT_ABSTRACTION, QT_BINDING, _QT_IMPORT_ERRORS = _import_qt()
try:
    import pyqtgraph as pg
    pg.setConfigOptions(imageAxisOrder="row-major", antialias=False)
    HAVE_PYQTGRAPH = True
except Exception:  # noqa: BLE001 - the preview tab then explains what is missing
    pg = None
    HAVE_PYQTGRAPH = False

#: QAction/QActionGroup are in QtGui in Qt 6 and QtWidgets in Qt 5.
QAction = getattr(QtGui, "QAction", None) or getattr(QtWidgets, "QAction")
QActionGroup = getattr(QtGui, "QActionGroup", None) or getattr(QtWidgets, "QActionGroup")
#: Plot colours shared with the Veusz pages.
COLOURS = vszh5_writer.TRACE_COLOURS
#: Longest trace drawn in the preview; longer ones are reduced (peaks kept).
PREVIEW_MAX_POINTS = 20_000


def preview_trace(x: np.ndarray, y: np.ndarray, method: str, is_db: bool) -> tuple[np.ndarray, np.ndarray]:
    """Shorten (x, y) to at most PREVIEW_MAX_POINTS for drawing.

    ``method``: "max", "min" or "power_mean" (dB or RMS), as the Veusz pages;
    x becomes the mean of each block. Short traces are returned unchanged.
    """
    factor = int(np.ceil(len(y) / PREVIEW_MAX_POINTS))
    if factor <= 1:
        return np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    x_out = vszh5_writer.block_reduce(np.asarray(x, dtype=float)[None, :], 1, factor, "mean")[0]
    return x_out, core._reduce_trace(np.asarray(y, dtype=float), factor, method, is_db)


# %% ===========================================================================
#    THEME MANAGER (light / dark / system)
# =============================================================================
class ThemeManager:
    """Light, dark or system palettes for the whole application.

    Explicit palettes for the two forced modes (Qt 6's colour-scheme hint is
    honoured unevenly across platforms); "system" restores the default.
    pyqtgraph plots are recoloured by the window.
    """

    LIGHT, DARK, SYSTEM = "light", "dark", "system"

    def __init__(self, app: Any) -> None:
        self.app = app
        self._default_palette = QtGui.QPalette(app.palette())
        self._default_style = app.style().objectName() if app.style() else "fusion"
        self.current = self.SYSTEM

    @staticmethod
    def _palette(dark: bool) -> Any:
        role = QtGui.QPalette.ColorRole
        group = QtGui.QPalette.ColorGroup
        palette = QtGui.QPalette()
        if dark:
            colours = {role.Window: (32, 33, 36), role.WindowText: (226, 228, 231),
                       role.Base: (24, 25, 28), role.AlternateBase: (42, 43, 47),
                       role.ToolTipBase: (42, 43, 47), role.ToolTipText: (226, 228, 231),
                       role.Text: (226, 228, 231), role.Button: (42, 43, 47),
                       role.ButtonText: (226, 228, 231), role.BrightText: (255, 96, 96),
                       role.Link: (72, 140, 214), role.Highlight: (72, 140, 214),
                       role.HighlightedText: (18, 18, 20)}
        else:
            colours = {role.Window: (246, 246, 248), role.WindowText: (24, 25, 28),
                       role.Base: (255, 255, 255), role.AlternateBase: (238, 239, 242),
                       role.ToolTipBase: (255, 255, 220), role.ToolTipText: (24, 25, 28),
                       role.Text: (24, 25, 28), role.Button: (240, 241, 244),
                       role.ButtonText: (24, 25, 28), role.BrightText: (190, 30, 30),
                       role.Link: (50, 118, 198), role.Highlight: (50, 118, 198),
                       role.HighlightedText: (255, 255, 255)}
        for colour_role, rgb in colours.items():
            palette.setColor(colour_role, QtGui.QColor(*rgb))
        if dark:
            for disabled in (role.Text, role.ButtonText, role.WindowText):
                palette.setColor(group.Disabled, disabled, QtGui.QColor(128, 130, 134))
        return palette

    def apply(self, mode: str) -> None:
        """Apply ``light``, ``dark`` or ``system``."""
        self.current = mode
        if mode in (self.DARK, self.LIGHT):
            self.app.setStyle("Fusion")
            self.app.setPalette(self._palette(mode == self.DARK))
        else:
            self.app.setStyle(self._default_style)
            self.app.setPalette(self._default_palette)

    def is_dark(self) -> bool:
        return self.app.palette().color(QtGui.QPalette.ColorRole.Window).lightness() < 128


# %% ===========================================================================
#    SMALL WIDGET HELPERS
# =============================================================================
def make_spin(minimum: float, maximum: float, value: float, decimals: int = 0, step: float = 1.0,
              suffix: str = "", special: str = "", tip: str = "") -> Any:
    """QSpinBox (decimals=0) or QDoubleSpinBox; ``special`` replaces the minimum's text."""
    if decimals == 0:
        spin = QtWidgets.QSpinBox()
        spin.setRange(int(minimum), int(maximum))
        spin.setSingleStep(int(step))
        spin.setValue(int(value))
    else:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(value)
    if suffix:
        spin.setSuffix(suffix)
    if special:
        spin.setSpecialValueText(special)
    if tip:
        spin.setToolTip(tip)
    spin.setKeyboardTracking(False)
    return spin


def make_combo(items: Sequence[tuple[str, Any]], current: Any = None, tip: str = "") -> Any:
    """QComboBox of (text, data) items with ``current`` data selected."""
    combo = QtWidgets.QComboBox()
    for text, data in items:
        combo.addItem(text, data)
    if current is not None:
        combo.setCurrentIndex(max(combo.findData(current), 0))
    if tip:
        combo.setToolTip(tip)
    return combo


def set_combo(combo: Any, data: Any) -> None:
    index = combo.findData(data)
    if index >= 0:
        combo.setCurrentIndex(index)


def monospace_font() -> Any:
    return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)


def open_with_system(path: str | os.PathLike) -> None:
    """Open a file or folder with the platform's default application."""
    target = str(path)
    if os.name == "nt":
        os.startfile(target)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


# %% ===========================================================================
#    BACKGROUND TASKS
# =============================================================================
class TaskThread(QtCore.QThread):
    """Runs ``job(log, progress, deliver, is_cancelled)`` off the GUI thread.

    Signals: messageLogged(str), progressed(float, str), resultDelivered(object),
    taskFinished(object), taskFailed(str). The conversion itself runs in
    worker processes (shr_converter_core), so the window stays responsive.
    """

    messageLogged = QtCore.Signal(str)
    progressed = QtCore.Signal(float, str)
    resultDelivered = QtCore.Signal(object)
    taskFinished = QtCore.Signal(object)
    taskFailed = QtCore.Signal(str)

    def __init__(self, name: str, job: Callable[..., Any], parent: Any = None) -> None:
        super().__init__(parent)
        self.task_name = name
        self.job = job
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # noqa: D401 - Qt API
        try:
            value = self.job(self.messageLogged.emit, self.progressed.emit, self.resultDelivered.emit,
                             lambda: self._cancelled)
            self.taskFinished.emit(value)
        except core.ConversionCancelled:
            self.taskFailed.emit(f"{self.task_name}: stopped by the user")
        except Exception as exc:  # noqa: BLE001 - shown in the log; never crashes the GUI
            self.taskFailed.emit(f"{self.task_name}: {type(exc).__name__}: {exc}")


# %% ===========================================================================
#    PREVIEW (pyqtgraph)
# =============================================================================
class PreviewPanel(QtWidgets.QWidget):
    """Spectrogram, statistics spectrum and level versus time of one result.

    The y axis of the spectrogram and the x axis of the time plot are elapsed
    seconds from the first selected sweep (the .vszh5 can use UTC/local time).
    Mouse: drag = pan, wheel = zoom, right-click = pyqtgraph menu (export).
    """

    cursorMoved = QtCore.Signal(str)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.title = QtWidgets.QLabel("Inspect or convert a file to see its preview.")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.result: core.ConvertResult | None = None
        if not HAVE_PYQTGRAPH:
            layout.addWidget(QtWidgets.QLabel("pyqtgraph is not installed: no preview "
                                              "(mamba install -c conda-forge pyqtgraph)."))
            self.view = None
            return
        # Three plots in one GraphicsLayoutWidget: spectrogram (image + colour
        # bar), statistics spectrum (x linked to the spectrogram's frequency
        # axis, so zooming one zooms both) and level versus time.
        self.view = pg.GraphicsLayoutWidget()
        layout.addWidget(self.view, 1)
        self.image_plot = self.view.addPlot(row=0, col=0, title="Spectrogram")
        self.image_item = pg.ImageItem()
        self.image_plot.addItem(self.image_item)
        self.colour_bar = pg.ColorBarItem(colorMap=pg.colormap.get("viridis"), interactive=True)
        self.colour_bar.setImageItem(self.image_item, insert_in=self.image_plot)
        self.stats_plot = self.view.addPlot(row=1, col=0, title="Statistics over the selected sweeps")
        self.stats_plot.addLegend(offset=(-10, 10))
        self.stats_plot.setXLink(self.image_plot)
        self.time_plot = self.view.addPlot(row=2, col=0, title="Level versus time")
        self.time_plot.addLegend(offset=(-10, 10))
        for plot in (self.image_plot, self.stats_plot, self.time_plot):
            plot.showGrid(x=True, y=True, alpha=0.25)
            for name in ("left", "bottom"):
                plot.getAxis(name).enableAutoSIPrefix(False)     # the label carries the unit
        self.curves = {
            "max": self.stats_plot.plot(name="max hold", pen=pg.mkPen(COLOURS[1], width=1)),
            "mean": self.stats_plot.plot(name="power mean", pen=pg.mkPen(COLOURS[0], width=1)),
            "min": self.stats_plot.plot(name="min hold", pen=pg.mkPen(COLOURS[2], width=1)),
            "peak": self.time_plot.plot(name="peak per sweep", pen=pg.mkPen(COLOURS[1], width=1)),
            "band": self.time_plot.plot(name="power mean per sweep", pen=pg.mkPen(COLOURS[0], width=1)),
        }
        # No clipToView/auto-downsampling: before the view has a size they cut
        # a trace to one point; long traces are reduced by preview_trace().
        self.view.ci.layout.setRowStretchFactor(0, 3)
        self.view.ci.layout.setRowStretchFactor(1, 2)
        self.view.ci.layout.setRowStretchFactor(2, 2)
        self._proxy = pg.SignalProxy(self.view.scene().sigMouseMoved, rateLimit=30, slot=self._mouse_moved)

    def clear(self) -> None:
        """Forget the shown result (Free memory)."""
        self.result = None
        self.title.setText("Preview cleared.")
        if self.view is not None:
            self.image_item.clear()
            for curve in self.curves.values():
                curve.setData([], [])

    def show_result(self, result: core.ConvertResult) -> None:
        """Draw ``result`` (a ConvertResult from Inspect or Convert)."""
        self.result = result
        info, plan = result.info, result.plan
        unit = info.amplitude_unit
        funit, fscale = core.frequency_unit(result.frequency_hz[-1] - result.frequency_hz[0],
                                            result.frequency_hz[-1])
        t0 = float(result.t0_ms)                               # first selected sweep
        start = core.utc_iso(np.array([result.t0_ms]))[0]
        self.title.setText(f"<b>{info.name}</b> - {plan.n_sweeps} sweeps x {plan.n_cols} bins, start "
                           f"{start} UTC (time axes: seconds from the start); spectrogram "
                           f"{plan.row_factor} sweep(s) x {plan.col_factor} bin(s) per pixel")
        if self.view is None:
            return
        # The same even grid as the Veusz page: pauses show as blank rows.
        rows = (np.asarray(result.image_time_ms, dtype=float) - t0) / 1000.0
        image, (y0, y1), _how = vszh5_writer.regularize_rows(result.image, rows)
        height = y1 - y0
        x0 = result.image_edges_hz[0] / fscale
        width = (result.image_edges_hz[-1] - result.image_edges_hz[0]) / fscale
        # Colour scale as the Veusz "data" mode: 1st percentile to the maximum,
        # so the noise floor is dark and every signal above it stands out.
        finite = image[np.isfinite(image)]
        low, high = ((float(np.percentile(finite, 1.0)), float(finite.max())) if finite.size else (0.0, 1.0))
        self.image_item.setImage(image, autoLevels=False)          # NaN pixels are drawn transparent
        self.image_item.setRect(QtCore.QRectF(x0, y0, width, height))
        self.colour_bar.setLevels((low, high if high > low else low + 1.0))
        self.colour_bar.axis.setLabel(f"Level ({unit})")
        self.image_plot.setLabel("bottom", f"Frequency ({funit})")
        self.image_plot.setLabel("left", "Time from start (s)")
        f = result.frequency_hz / fscale
        db = info.is_db
        self.curves["max"].setData(*preview_trace(f, result.stat_max, "max", db))
        self.curves["mean"].setData(*preview_trace(f, result.stat_power_mean, "power_mean", db))
        self.curves["min"].setData(*preview_trace(f, result.stat_min, "min", db))
        self.stats_plot.setLabel("bottom", f"Frequency ({funit})")
        self.stats_plot.setLabel("left", f"Level ({unit})")
        # Per-sweep series (already thinned by the core for long captures,
        # and again here to PREVIEW_MAX_POINTS with peak hold / power mean).
        t = (np.asarray(result.timestamp_ms, dtype=float) - t0) / 1000.0
        self.curves["peak"].setData(*preview_trace(t, result.peak, "max", db))
        self.curves["band"].setData(*preview_trace(t, result.power_mean, "power_mean", db))
        self.time_plot.setLabel("bottom", "Time from start (s)")
        self.time_plot.setLabel("left", f"Level ({unit})")
        self.auto_range()

    def auto_range(self) -> None:
        """View > Auto-range (Ctrl+0): fit all three plots to their data."""
        if self.view is not None:
            for plot in (self.image_plot, self.stats_plot, self.time_plot):
                plot.enableAutoRange()

    def apply_theme(self, dark: bool) -> None:
        """Recolour the plots (pyqtgraph does not follow the Qt palette)."""
        if self.view is None:
            return
        background, foreground = ("#18191c", "#e2e4e7") if dark else ("#ffffff", "#18191c")
        self.view.setBackground(background)
        for plot in (self.image_plot, self.stats_plot, self.time_plot):
            plot.titleLabel.setText(plot.titleLabel.text, color=foreground)
            for name in ("left", "bottom"):
                axis = plot.getAxis(name)
                axis.setPen(pg.mkPen(foreground))
                axis.setTextPen(pg.mkPen(foreground))
            if plot.legend is not None:
                plot.legend.setLabelTextColor(foreground)
                plot.legend.setBrush(pg.mkBrush(background + "c0"))     # readable over the grid
                for _sample, label in plot.legend.items:
                    label.setText(label.text, color=foreground)
        self.colour_bar.axis.setPen(pg.mkPen(foreground))
        self.colour_bar.axis.setTextPen(pg.mkPen(foreground))

    def _mouse_moved(self, event: Any) -> None:
        """Cursor read-out in the status bar (rate-limited by a SignalProxy)."""
        if self.result is None:
            return
        position = event[0]
        for plot, text in ((self.image_plot, "spectrogram"), (self.stats_plot, "statistics"),
                           (self.time_plot, "time")):
            if plot.sceneBoundingRect().contains(position):
                point = plot.vb.mapSceneToView(position)
                self.cursorMoved.emit(f"{text}: x = {point.x():.6g}, y = {point.y():.6g}")
                return


# %% ===========================================================================
#    SETTINGS PANEL
# =============================================================================
class SettingsPanel(QtWidgets.QScrollArea):
    """Input list and every ConvertOptions control, grouped."""

    inspectRequested = QtCore.Signal()
    convertRequested = QtCore.Signal()
    stopRequested = QtCore.Signal()
    selectionChanged = QtCore.Signal()

    COLUMNS = ("File", "Sweeps", "Bins", "Start (MHz)", "Stop (MHz)", "Length (s)", "Status")

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        self.setWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        defaults = core.ConvertOptions()
        self.infos: dict[str, core.ShrInfo] = {}

        # -- inputs ---------------------------------------------------------------------
        inputs = QtWidgets.QGroupBox("Input .shr files (drop files or folders here)")
        grid = QtWidgets.QVBoxLayout(inputs)
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(150)
        self.table.itemSelectionChanged.connect(self.selectionChanged.emit)
        grid.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        for text, slot in (("Add files...", self.browse_files), ("Add folder...", self.browse_folder),
                           ("Remove", self.remove_selected), ("Clear", self.clear_inputs)):
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(lambda _c=False, s=slot: s())
            buttons.addWidget(button)
        grid.addLayout(buttons)
        layout.addWidget(inputs)

        # -- output folder -------------------------------------------------------------------
        output = QtWidgets.QGroupBox("Output")
        form = QtWidgets.QFormLayout(output)
        self.beside_inputs = QtWidgets.QCheckBox("Beside each input file")
        self.beside_inputs.setChecked(True)
        self.output_dir = QtWidgets.QLineEdit()
        self.output_dir.setPlaceholderText("output folder")
        browse = QtWidgets.QPushButton("Browse...")
        browse.clicked.connect(lambda _c=False: self.browse_output())
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.output_dir, 1)
        row.addWidget(browse)
        self.beside_inputs.toggled.connect(lambda on: (self.output_dir.setEnabled(not on), browse.setEnabled(not on)))
        self.output_dir.setEnabled(False)
        browse.setEnabled(False)
        form.addRow(self.beside_inputs)
        form.addRow("Folder", row)
        layout.addWidget(output)

        # -- CSV ----------------------------------------------------------------------------------
        self.csv_group = QtWidgets.QGroupBox("CSV")
        self.csv_group.setCheckable(True)
        self.csv_group.setChecked(defaults.write_csv)
        form = QtWidgets.QFormLayout(self.csv_group)
        self.layout_combo = make_combo([(f"{k.replace('_', ' ')} - {v}", k) for k, v in core.CSV_LAYOUTS.items()],
                                       defaults.csv_layout, "Layout of the main CSV file")
        self.format_combo = make_combo([("lossless (%.9g, exact float32)", "lossless"),
                                        ("fixed decimals", "fixed")], defaults.csv_number_format)
        self.decimals_spin = make_spin(0, 12, defaults.csv_decimals, tip="decimals of the fixed format")
        self.format_combo.currentIndexChanged.connect(
            lambda _i: self.decimals_spin.setEnabled(self.format_combo.currentData() == "fixed"))
        self.decimals_spin.setEnabled(defaults.csv_number_format == "fixed")
        number_row = QtWidgets.QHBoxLayout()
        number_row.addWidget(self.format_combo, 1)
        number_row.addWidget(self.decimals_spin)
        self.delimiter_combo = make_combo([(k, k) for k in core.DELIMITERS], defaults.csv_delimiter)
        self.time_checks = {}
        times = QtWidgets.QGridLayout()
        for i, key in enumerate(core.TIME_COLUMNS):
            check = QtWidgets.QCheckBox(key)
            check.setToolTip(core.TIME_COLUMNS[key])
            check.setChecked(key in defaults.csv_time_columns)
            self.time_checks[key] = check
            times.addWidget(check, i // 2, i % 2)
        companions = QtWidgets.QGridLayout()
        self.header_table = QtWidgets.QCheckBox("_header")
        self.sweeps_table = QtWidgets.QCheckBox("_sweeps")
        self.stats_table = QtWidgets.QCheckBox("_statistics")
        for check, tip in ((self.header_table, "every header field with its unit"),
                           (self.sweeps_table, "one row per sweep: time, GPS, overflow, peak, power mean"),
                           (self.stats_table, "one row per bin: max, min, power mean, dB mean, std")):
            check.setChecked(True)
            check.setToolTip(tip)
            companions.addWidget(check, 0, companions.count())
        self.split_spin = make_spin(0, 1440, defaults.csv_split_minutes, 1, 5.0, " min", "one file",
                                    tip="start a new CSV file every N minutes of recording "
                                        "(sweeps as rows and long layouts); one file when 0")
        self.disk_check = QtWidgets.QCheckBox("refuse when the estimated CSV does not fit on the drive")
        self.disk_check.setChecked(defaults.check_disk_space)
        # CSV time decimation: N selected sweeps -> one CSV row (statistics,
        # spectrogram, _sweeps.csv and the .vszh5 still use every sweep).
        self.decimate_spin = make_spin(1, 1_000_000, defaults.csv_decimate, special="every sweep",
                                       tip="combine every N selected sweeps into one CSV row; only the "
                                           "main CSV is decimated")
        self.decimate_combo = make_combo([(f"{k.replace('_', ' ')} - {v}", k)
                                          for k, v in core.CSV_DECIMATE_DETECTORS.items()],
                                         defaults.csv_decimate_detector, "how the sweeps of a row are combined")
        self.decimate_spin.valueChanged.connect(lambda v: self.decimate_combo.setEnabled(v > 1))
        self.decimate_combo.setEnabled(defaults.csv_decimate > 1)
        decimate_row = QtWidgets.QHBoxLayout()
        decimate_row.addWidget(self.decimate_spin)
        decimate_row.addWidget(QtWidgets.QLabel("sweeps per row,"))
        decimate_row.addWidget(self.decimate_combo, 1)
        form.addRow("Layout", self.layout_combo)
        form.addRow("Combine", decimate_row)
        form.addRow("Split every", self.split_spin)
        form.addRow("Numbers", number_row)
        form.addRow("Delimiter", self.delimiter_combo)
        form.addRow("Time columns", times)
        form.addRow("Companion tables", companions)
        form.addRow(self.disk_check)
        layout.addWidget(self.csv_group)

        # -- Veusz -------------------------------------------------------------------------------------
        self.vsz_group = QtWidgets.QGroupBox("Veusz document (.vszh5)")
        self.vsz_group.setCheckable(True)
        self.vsz_group.setChecked(defaults.write_vszh5)
        form = QtWidgets.QFormLayout(self.vsz_group)
        self.rows_spin = make_spin(10, 100000, defaults.image_max_rows, step=100, tip="maximum spectrogram rows")
        self.cols_spin = make_spin(10, 100000, defaults.image_max_columns, step=100,
                                   tip="maximum spectrogram columns")
        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(self.rows_spin)
        size_row.addWidget(QtWidgets.QLabel("rows x"))
        size_row.addWidget(self.cols_spin)
        size_row.addWidget(QtWidgets.QLabel("columns"))
        self.reduction_combo = make_combo([(f"{k} - {v}", k) for k, v in core.IMAGE_REDUCTIONS.items()],
                                          defaults.image_reduction)
        self.colormap_combo = make_combo([(c, c) for c in core.COLORMAPS], defaults.colormap)
        self.z_combo = make_combo([(f"{k} - {v}", k) for k, v in core.Z_MODES.items()], defaults.z_mode)
        self.zmin_spin = make_spin(-400, 400, defaults.z_min, 2, 5.0)
        self.zmax_spin = make_spin(-400, 400, defaults.z_max, 2, 5.0)
        z_row = QtWidgets.QHBoxLayout()
        z_row.addWidget(self.z_combo, 1)
        z_row.addWidget(self.zmin_spin)
        z_row.addWidget(self.zmax_spin)
        self.z_combo.currentIndexChanged.connect(lambda _i: self._z_enabled())
        self.time_axis_combo = make_combo([(f"{k} - {v}", k) for k, v in core.TIME_AXES.items()],
                                          defaults.time_axis)
        self.selected_edit = QtWidgets.QLineEdit(defaults.selected_sweeps)
        self.selected_edit.setToolTip("selected-sweeps page: first, last, peak and/or sweep indices "
                                      "(negative counts from the end), comma-separated")
        pages = QtWidgets.QGridLayout()
        self.page_checks = {}
        for i, (key, caption) in enumerate((("page_spectrogram", "spectrogram"), ("page_statistics", "statistics"),
                                            ("page_selected_sweeps", "selected sweeps"),
                                            ("page_level_vs_time", "level vs time"), ("page_gps", "GPS track"),
                                            ("page_header", "header"))):
            check = QtWidgets.QCheckBox(caption)
            check.setChecked(True)
            self.page_checks[key] = check
            pages.addWidget(check, i // 3, i % 3)
        self.compress_check = QtWidgets.QCheckBox("compress (gzip)")
        self.compress_check.setChecked(defaults.vszh5_compress)
        self.render_check = QtWidgets.QCheckBox("render PDF (bookmarked) and PNG with Veusz")
        self.png_combo = make_combo([("PNG: first page", "first"), ("PNG: all pages", "all"),
                                     ("no PNG", "none")], defaults.render_png)
        self.dpi_spin = make_spin(50, 600, defaults.render_dpi, step=25, suffix=" dpi")
        render_row = QtWidgets.QHBoxLayout()
        render_row.addWidget(self.png_combo)
        render_row.addWidget(self.dpi_spin)
        self.veusz_edit = QtWidgets.QLineEdit()
        self.veusz_edit.setPlaceholderText(vszh5_writer.find_veusz_exe() or "Veusz program (auto-detected)")
        veusz_browse = QtWidgets.QPushButton("...")
        veusz_browse.clicked.connect(lambda _c=False: self.browse_veusz())
        veusz_row = QtWidgets.QHBoxLayout()
        veusz_row.addWidget(self.veusz_edit, 1)
        veusz_row.addWidget(veusz_browse)
        form.addRow("Spectrogram", size_row)
        form.addRow("Reduction", self.reduction_combo)
        form.addRow("Colour map", self.colormap_combo)
        form.addRow("Colour scale", z_row)
        form.addRow("Time axis", self.time_axis_combo)
        form.addRow("Sweeps to plot", self.selected_edit)
        self.series_spin = make_spin(100, 10_000_000, defaults.time_series_max_points, step=10_000,
                                     tip="level-vs-time and GPS series are thinned to this many points "
                                         "(peak hold, power mean) - for multi-hour captures")
        form.addRow("Time-series points", self.series_spin)
        form.addRow("Pages", pages)
        form.addRow(self.compress_check)
        form.addRow(self.render_check)
        form.addRow("Render", render_row)
        form.addRow("Veusz", veusz_row)
        layout.addWidget(self.vsz_group)

        # -- selection ---------------------------------------------------------------------------------
        selection = QtWidgets.QGroupBox("Selection")
        form = QtWidgets.QFormLayout(selection)
        self.start_spin = make_spin(0, 2 ** 31 - 1, 0, tip="first sweep index")
        self.stop_spin = make_spin(0, 2 ** 31 - 1, 0, special="end", tip="stop index (exclusive); 0 = end")
        self.step_spin = make_spin(1, 1_000_000, 1, tip="take every Nth sweep")
        sweep_row = QtWidgets.QHBoxLayout()
        for label, spin in (("start", self.start_spin), ("stop", self.stop_spin), ("step", self.step_spin)):
            sweep_row.addWidget(QtWidgets.QLabel(label))
            sweep_row.addWidget(spin)
        self.fmin_spin = make_spin(0, 1e6, 0, 6, 1.0, " MHz", "first bin")
        self.fmax_spin = make_spin(0, 1e6, 0, 6, 1.0, " MHz", "last bin")
        freq_row = QtWidgets.QHBoxLayout()
        freq_row.addWidget(self.fmin_spin)
        freq_row.addWidget(QtWidgets.QLabel("to"))
        freq_row.addWidget(self.fmax_spin)
        self.join_check = QtWidgets.QCheckBox("Join the files of one recording (multi-file Spike recordings)")
        self.join_check.setToolTip("Files with the same bin axis whose times follow on are converted as ONE "
                                   "recording, named <first file>_joined; others are converted on their own")
        self.join_check.setChecked(defaults.join_files)
        form.addRow("Sweeps", sweep_row)
        form.addRow("Frequency", freq_row)
        form.addRow(self.join_check)
        layout.addWidget(selection)

        # -- performance -------------------------------------------------------------------------------
        performance = QtWidgets.QGroupBox("Performance and memory")
        form = QtWidgets.QFormLayout(performance)
        self.workers_spin = make_spin(0, 256, 0, special=f"auto ({core.default_workers()})",
                                      tip="worker processes; auto = CPUs - 1")
        self.ram_spin = make_spin(16, 1_048_576, defaults.ram_budget_mb, step=256, suffix=" MB",
                                  tip="memory for blocks in flight (all workers together)")
        self.compute_combo = make_combo([("auto (CuPy if a GPU is found)", "auto"), ("CPU (NumPy)", "cpu"),
                                         ("GPU (CuPy; falls back to CPU)", "gpu")], defaults.compute)
        self.table_combo = make_combo([("auto (disk when large)", "auto"), ("memory", "memory"),
                                       ("disk (memory-mapped)", "disk")], defaults.sweep_table_storage,
                                      "where the per-sweep table (time, GPS, peak per sweep) is kept")
        self.flush_check = QtWidgets.QCheckBox("free memory after each file")
        self.flush_check.setChecked(defaults.flush_after_file)
        form.addRow("Workers", self.workers_spin)
        form.addRow("RAM budget", self.ram_spin)
        form.addRow("Statistics on", self.compute_combo)
        form.addRow("Per-sweep table", self.table_combo)
        form.addRow(self.flush_check)
        layout.addWidget(performance)

        # -- actions -----------------------------------------------------------------------------------
        actions = QtWidgets.QHBoxLayout()
        self.inspect_button = QtWidgets.QPushButton("Inspect (Ctrl+I)")
        self.convert_button = QtWidgets.QPushButton("Convert all (F5)")
        self.stop_button = QtWidgets.QPushButton("Stop (Esc)")
        self.stop_button.setEnabled(False)
        self.inspect_button.clicked.connect(lambda _c=False: self.inspectRequested.emit())
        self.convert_button.clicked.connect(lambda _c=False: self.convertRequested.emit())
        self.stop_button.clicked.connect(lambda _c=False: self.stopRequested.emit())
        for button in (self.inspect_button, self.convert_button, self.stop_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        layout.addStretch(1)
        self._z_enabled()
        body.setMinimumWidth(560)
        self.setMinimumWidth(600)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # -- inputs -------------------------------------------------------------------------------------------
    def paths(self, selected_only: bool = False) -> list[str]:
        rows = (sorted({i.row() for i in self.table.selectedIndexes()}) if selected_only
                else range(self.table.rowCount()))
        return [self.table.item(r, 0).data(QtCore.Qt.ItemDataRole.UserRole) for r in rows]

    def add_paths(self, items: Sequence[str]) -> list[str]:
        """Add files (folders: their *.shr); read each header for the table."""
        added = []
        known = set(self.paths())
        for path in core.expand_inputs(items):
            if path in known or not path.lower().endswith(".shr"):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QtWidgets.QTableWidgetItem(Path(path).name)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.table.setItem(row, 0, item)
            try:
                info = core.read_info(path)
                self.infos[path] = info
                f1 = info.first_bin_hz + (info.n_bins - 1) * info.bin_hz
                cells = [str(info.n_sweeps), str(info.n_bins), f"{info.first_bin_hz / 1e6:.6f}",
                         f"{f1 / 1e6:.6f}", f"{info.duration_s:.3f}",
                         "note: " + "; ".join(info.notes) if info.notes else "ready"]
            except Exception as exc:  # noqa: BLE001 - shown in the table
                cells = ["", "", "", "", "", f"unreadable: {type(exc).__name__}: {exc}"]
            for column, text in enumerate(cells, start=1):
                self.table.setItem(row, column, QtWidgets.QTableWidgetItem(text))
            known.add(path)
            added.append(path)
        self.table.resizeColumnsToContents()
        return added

    def set_status(self, path: str, text: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole) == path:
                self.table.setItem(row, 6, QtWidgets.QTableWidgetItem(text))

    def remove_selected(self) -> None:
        for row in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.infos.pop(self.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole), None)
            self.table.removeRow(row)

    def clear_inputs(self) -> None:
        self.table.setRowCount(0)
        self.infos.clear()

    def browse_files(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add Signal Hound .shr files", "",
                                                          "Signal Hound sweeps (*.shr *.SHR);;All files (*)")
        if files:
            self.add_paths(files)

    def browse_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Add every .shr file in a folder")
        if folder:
            self.add_paths([folder])

    def browse_output(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Output folder", self.output_dir.text())
        if folder:
            self.output_dir.setText(folder)
            self.beside_inputs.setChecked(False)

    def browse_veusz(self) -> None:
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Veusz program", "",
                                                        "Programs (*.exe);;All files (*)" if os.name == "nt"
                                                        else "All files (*)")
        if name:
            self.veusz_edit.setText(name)

    def _z_enabled(self) -> None:
        manual = self.z_combo.currentData() == "manual"
        self.zmin_spin.setEnabled(manual)
        self.zmax_spin.setEnabled(manual)

    # -- options ---------------------------------------------------------------------------------------------
    def options(self) -> core.ConvertOptions:
        """ConvertOptions from the controls (validated)."""
        opts = core.ConvertOptions(
            output_dir="" if self.beside_inputs.isChecked() else self.output_dir.text().strip(),
            write_csv=self.csv_group.isChecked(), csv_layout=self.layout_combo.currentData(),
            csv_number_format=self.format_combo.currentData(), csv_decimals=self.decimals_spin.value(),
            csv_delimiter=self.delimiter_combo.currentData(),
            csv_time_columns=tuple(k for k, c in self.time_checks.items() if c.isChecked()),
            csv_header_table=self.header_table.isChecked(), csv_sweeps_table=self.sweeps_table.isChecked(),
            csv_statistics_table=self.stats_table.isChecked(), write_vszh5=self.vsz_group.isChecked(),
            vszh5_compress=self.compress_check.isChecked(), image_max_rows=self.rows_spin.value(),
            image_max_columns=self.cols_spin.value(), image_reduction=self.reduction_combo.currentData(),
            colormap=self.colormap_combo.currentData(), z_mode=self.z_combo.currentData(),
            z_min=self.zmin_spin.value(), z_max=self.zmax_spin.value(),
            time_axis=self.time_axis_combo.currentData(), selected_sweeps=self.selected_edit.text(),
            render=self.render_check.isChecked(), render_png=self.png_combo.currentData(),
            render_dpi=self.dpi_spin.value(), veusz_exe=self.veusz_edit.text().strip(),
            sweep_start=self.start_spin.value(), sweep_stop=self.stop_spin.value(),
            sweep_step=self.step_spin.value(), freq_min_hz=self.fmin_spin.value() * 1e6,
            freq_max_hz=self.fmax_spin.value() * 1e6, workers=self.workers_spin.value(),
            ram_budget_mb=self.ram_spin.value(), compute=self.compute_combo.currentData(),
            flush_after_file=self.flush_check.isChecked(),
            csv_split_minutes=self.split_spin.value(), check_disk_space=self.disk_check.isChecked(),
            time_series_max_points=self.series_spin.value(),
            sweep_table_storage=self.table_combo.currentData(),
            csv_decimate=self.decimate_spin.value(), csv_decimate_detector=self.decimate_combo.currentData(),
            join_files=self.join_check.isChecked(),
            **{key: check.isChecked() for key, check in self.page_checks.items()})
        if opts.write_csv and not opts.csv_time_columns and opts.csv_layout != "frequencies_as_rows":
            opts.csv_time_columns = ("epoch_ms",)
        opts.validate()
        return opts

    def set_options(self, opts: core.ConvertOptions) -> None:
        """Show ``opts`` in the controls."""
        self.beside_inputs.setChecked(not opts.output_dir)
        self.output_dir.setText(opts.output_dir)
        self.csv_group.setChecked(opts.write_csv)
        set_combo(self.layout_combo, opts.csv_layout)
        set_combo(self.format_combo, opts.csv_number_format)
        self.decimals_spin.setValue(opts.csv_decimals)
        set_combo(self.delimiter_combo, opts.csv_delimiter)
        for key, check in self.time_checks.items():
            check.setChecked(key in opts.csv_time_columns)
        self.header_table.setChecked(opts.csv_header_table)
        self.sweeps_table.setChecked(opts.csv_sweeps_table)
        self.stats_table.setChecked(opts.csv_statistics_table)
        self.vsz_group.setChecked(opts.write_vszh5)
        self.compress_check.setChecked(opts.vszh5_compress)
        self.rows_spin.setValue(opts.image_max_rows)
        self.cols_spin.setValue(opts.image_max_columns)
        set_combo(self.reduction_combo, opts.image_reduction)
        set_combo(self.colormap_combo, opts.colormap)
        set_combo(self.z_combo, opts.z_mode)
        self.zmin_spin.setValue(opts.z_min)
        self.zmax_spin.setValue(opts.z_max)
        set_combo(self.time_axis_combo, opts.time_axis)
        self.selected_edit.setText(opts.selected_sweeps)
        for key, check in self.page_checks.items():
            check.setChecked(bool(getattr(opts, key)))
        self.render_check.setChecked(opts.render)
        set_combo(self.png_combo, opts.render_png)
        self.dpi_spin.setValue(opts.render_dpi)
        self.veusz_edit.setText(opts.veusz_exe)
        self.start_spin.setValue(opts.sweep_start)
        self.stop_spin.setValue(opts.sweep_stop)
        self.step_spin.setValue(opts.sweep_step)
        self.fmin_spin.setValue(opts.freq_min_hz / 1e6)
        self.fmax_spin.setValue(opts.freq_max_hz / 1e6)
        self.workers_spin.setValue(opts.workers)
        self.ram_spin.setValue(opts.ram_budget_mb)
        set_combo(self.compute_combo, opts.compute)
        self.flush_check.setChecked(opts.flush_after_file)
        self.split_spin.setValue(opts.csv_split_minutes)
        self.disk_check.setChecked(opts.check_disk_space)
        self.series_spin.setValue(opts.time_series_max_points)
        set_combo(self.table_combo, opts.sweep_table_storage)
        self.decimate_spin.setValue(opts.csv_decimate)
        set_combo(self.decimate_combo, opts.csv_decimate_detector)
        self.join_check.setChecked(opts.join_files)


# %% ===========================================================================
#    MAIN WINDOW
# =============================================================================
class MainWindow(QtWidgets.QMainWindow):
    """Menus, toolbar, settings dock, preview/info/outputs tabs, log dock."""

    def __init__(self, theme: ThemeManager, inputs: Sequence[str] = ()) -> None:
        super().__init__()
        self.theme = theme
        self.task: TaskThread | None = None
        self.settings_store = QtCore.QSettings(*SETTINGS_SCOPE)
        self.cache_dir = Path(tempfile.mkdtemp(prefix="shr_converter_preview_"))
        self.previews: dict[str, Path] = {}          # input path -> pickled ConvertResult
        self.outputs: dict[str, list[str]] = {}       # input path -> files written
        self.recent_inputs: list[str] = []
        self.setWindowTitle(f"{APP_NAME} v{__version__}")
        screen = QtGui.QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        width, height = 1500, 950
        if available is not None:
            width, height = min(width, available.width()), min(height, available.height() - 40)
        self.resize(width, height)

        # -- centre: preview, file info, outputs ----------------------------------------------------
        self.preview = PreviewPanel()
        self.info_text = QtWidgets.QPlainTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFont(monospace_font())
        outputs_page = QtWidgets.QWidget()
        outputs_layout = QtWidgets.QVBoxLayout(outputs_page)
        self.output_list = QtWidgets.QListWidget()
        self.output_list.itemDoubleClicked.connect(lambda item: self._open_output(item.text()))
        outputs_layout.addWidget(QtWidgets.QLabel("Files written (double-click: .vszh5 opens in Veusz, "
                                                  "others with the system's program)"))
        outputs_layout.addWidget(self.output_list, 1)
        self.tabs = QtWidgets.QTabWidget()
        self.tabs.addTab(self.preview, "Preview")
        self.tabs.addTab(self.info_text, "File info")
        self.tabs.addTab(outputs_page, "Outputs")
        self.setCentralWidget(self.tabs)

        # -- docks ------------------------------------------------------------------------------------------
        self.settings = SettingsPanel()
        self.settings_dock = QtWidgets.QDockWidget("Files and settings", self)
        self.settings_dock.setObjectName("settings_dock")
        self.settings_dock.setWidget(self.settings)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, self.settings_dock)
        self.resizeDocks([self.settings_dock], [620], QtCore.Qt.Orientation.Horizontal)
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(monospace_font())
        self.log_text.setMaximumBlockCount(5000)          # bounded memory
        self.log_dock = QtWidgets.QDockWidget("Log", self)
        self.log_dock.setObjectName("log_dock")
        self.log_dock.setWidget(self.log_text)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [160], QtCore.Qt.Orientation.Vertical)

        # -- status bar --------------------------------------------------------------------------------------
        self.cursor_label = QtWidgets.QLabel("")
        self.cursor_label.setMinimumWidth(320)
        self.memory_label = QtWidgets.QLabel("")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setMaximumWidth(240)
        self.progress.setVisible(False)
        for widget in (self.cursor_label, self.memory_label, self.progress):
            self.statusBar().addPermanentWidget(widget)
        self._memory_timer = QtCore.QTimer(self)
        self._memory_timer.timeout.connect(self._update_memory)
        self._memory_timer.start(2000)

        self._build_menus()
        self._build_toolbar()
        self.preview.cursorMoved.connect(self.cursor_label.setText)
        self.settings.inspectRequested.connect(self.inspect_selected)
        self.settings.convertRequested.connect(lambda: self.convert(selected_only=False))
        self.settings.stopRequested.connect(self.stop_task)
        self.settings.selectionChanged.connect(self._selection_changed)
        self.setAcceptDrops(True)
        self._restore_settings()
        if inputs:
            self.add_inputs(inputs)
        self.log(f"{APP_NAME} {__version__} (core {core.__version__}, shr_reader {core.SHR_READER_VERSION}, "
                 f"vszh5_writer {vszh5_writer.__version__}); Qt layer {QT_ABSTRACTION}, binding {QT_BINDING}")
        self.statusBar().showMessage("Add .shr files, then Inspect (Ctrl+I) or Convert (F5).")

    # -- menus and toolbar ------------------------------------------------------------------------------
    def _action(self, menu: Any, text: str, slot: Callable[[], Any], shortcut: Any = None, tip: str = "") -> Any:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QtGui.QKeySequence(shortcut))
        if tip:
            action.setStatusTip(tip)
            action.setToolTip(tip)
        action.triggered.connect(lambda _checked=False: slot())
        if menu is not None:
            menu.addAction(action)
        return action

    def _build_menus(self) -> None:
        """File, Edit, View, Convert, Veusz and Help."""
        bar = self.menuBar()
        sk = QtGui.QKeySequence.StandardKey
        file_menu = bar.addMenu("&File")
        self.act_add = self._action(file_menu, "&Add files...", self.settings.browse_files, sk.Open,
                                    "Add Signal Hound .shr files")
        self.act_folder = self._action(file_menu, "Add &folder...", self.settings.browse_folder, "Ctrl+Shift+O",
                                       "Add every .shr file of a folder")
        self.recent_menu = file_menu.addMenu("&Recent inputs")
        self._action(file_menu, "&Remove selected", self.settings.remove_selected, "Del")
        self._action(file_menu, "&Clear list", self.settings.clear_inputs)
        file_menu.addSeparator()
        self._action(file_menu, "Choose &output folder...", self.settings.browse_output)
        self._action(file_menu, "Open output fol&der", self.open_output_folder, "Ctrl+Shift+D")
        file_menu.addSeparator()
        self._action(file_menu, "&Save settings...", self.save_settings_file, sk.Save)
        self._action(file_menu, "&Load settings...", self.load_settings_file)
        self._action(file_menu, "Reset settings to &defaults", lambda: self.settings.set_options(core.ConvertOptions()))
        self._action(file_menu, "Save lo&g...", self.save_log)
        file_menu.addSeparator()
        self._action(file_menu, "&Quit", self.close, sk.Quit)

        edit_menu = bar.addMenu("&Edit")
        self._action(edit_menu, "Copy &file info", lambda: QtWidgets.QApplication.clipboard().setText(
            self.info_text.toPlainText()), "Ctrl+Shift+C")
        self._action(edit_menu, "Copy &log", lambda: QtWidgets.QApplication.clipboard().setText(
            self.log_text.toPlainText()))
        self._action(edit_menu, "C&lear log", self.log_text.clear)
        edit_menu.addSeparator()
        self.act_free = self._action(edit_menu, "&Free memory (preview, caches, GC)", self.free_memory,
                                     "Ctrl+Shift+M", "Drop the shown preview and return freed memory to the system")

        view_menu = bar.addMenu("&View")
        theme_menu = view_menu.addMenu("&Theme (light / dark)")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions = {}
        for mode, caption in ((ThemeManager.SYSTEM, "&System default"), (ThemeManager.LIGHT, "&Light"),
                              (ThemeManager.DARK, "&Dark")):
            action = QAction(caption, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _c=False, m=mode: self.set_theme(m))
            self._theme_group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[mode] = action
        self.act_toggle_theme = self._action(view_menu, "Toggle light/dar&k", self.toggle_theme, "Ctrl+T")
        view_menu.addSeparator()
        self._action(view_menu, "&Auto-range plots", self.preview.auto_range, "Ctrl+0")
        view_menu.addSeparator()
        for dock, text, key in ((self.settings_dock, "&Settings panel", "Ctrl+Shift+E"),
                                (self.log_dock, "L&og panel", "Ctrl+Shift+L")):
            toggle = dock.toggleViewAction()
            toggle.setText(text)
            toggle.setShortcut(QtGui.QKeySequence(key))
            view_menu.addAction(toggle)
        self.view_menu = view_menu
        self._action(view_menu, "F&ull screen", self.toggle_full_screen, "F11")

        convert_menu = bar.addMenu("&Convert")
        self.act_inspect = self._action(convert_menu, "&Inspect selected (no files written)", self.inspect_selected,
                                        "Ctrl+I", "Header, plan and preview of the selected file")
        self.act_convert = self._action(convert_menu, "Convert &all", lambda: self.convert(False), "F5",
                                        "Convert every listed file")
        self.act_convert_sel = self._action(convert_menu, "Convert &selected", lambda: self.convert(True),
                                            "Shift+F5", "Convert the selected files")
        self.act_stop = self._action(convert_menu, "S&top", self.stop_task, "Esc",
                                     "Stop after the current block; partial files are deleted")
        convert_menu.addSeparator()
        self._action(convert_menu, "Show &plan of selected", self.show_plan, "Ctrl+P")
        self._action(convert_menu, "Run &self-test", self.run_selftest)

        veusz_menu = bar.addMenu("Veu&sz")
        self.act_veusz = self._action(veusz_menu, "&Open .vszh5 of selected in Veusz", self.open_in_veusz,
                                      "Ctrl+Shift+Z")
        self._action(veusz_menu, "&Render .vszh5 of selected to PDF/PNG", self.render_selected, "Ctrl+R")
        self._action(veusz_menu, "Open rendered P&DF", self.open_pdf)

        help_menu = bar.addMenu("&Help")
        self._action(help_menu, "User &manual (PDF)", self.open_manual, sk.HelpContents)
        self._action(help_menu, "&Keyboard shortcuts", self.show_shortcuts)
        help_menu.addSeparator()
        self._action(help_menu, f"&About {APP_NAME}", self.show_about)
        self._action(help_menu, "About &Qt", QtWidgets.QApplication.aboutQt)
        self.act_stop.setEnabled(False)

    def _build_toolbar(self) -> None:
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("main_toolbar")
        toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        for action in (self.act_add, self.act_folder, None, self.act_inspect, self.act_convert, self.act_stop,
                       None, self.act_veusz, self.act_free, None, self.act_toggle_theme):
            if action is None:
                toolbar.addSeparator()
            else:
                toolbar.addAction(action)
        toggle = toolbar.toggleViewAction()
        toggle.setText("&Toolbar")
        self.view_menu.insertAction(self.settings_dock.toggleViewAction(), toggle)

    # -- logging, theme, memory ---------------------------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in str(text).splitlines() or [""]:
            self.log_text.appendPlainText(f"{stamp}  {line}")

    def set_theme(self, mode: str) -> None:
        self.theme.apply(mode)
        if mode in self._theme_actions:
            self._theme_actions[mode].setChecked(True)
        self.preview.apply_theme(self.theme.is_dark())
        self.settings_store.setValue("theme", mode)
        self.statusBar().showMessage(f"Theme: {mode}", 3000)

    def toggle_theme(self) -> None:
        self.set_theme(ThemeManager.LIGHT if self.theme.is_dark() else ThemeManager.DARK)

    def _update_memory(self) -> None:
        rss = core.memory_mb()
        self.memory_label.setText(f"RAM {rss:,.0f} MB" if rss == rss else "")

    def free_memory(self) -> None:
        """Drop the shown preview (it stays on disk) and flush memory."""
        before = core.memory_mb()
        self.preview.clear()
        collected = core.flush_memory()
        after = core.memory_mb()
        self.log(f"Free memory: {collected} objects collected; RSS {before:,.0f} -> {after:,.0f} MB "
                 f"(previews stay on disk in {self.cache_dir})")

    def toggle_full_screen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    # -- inputs -----------------------------------------------------------------------------------------------
    def add_inputs(self, items: Sequence[str]) -> None:
        """Add files/folders to the list, remember them as recent, log header notes."""
        added = self.settings.add_paths(items)          # reads each header (fast: 472 bytes)
        for path in added:
            if path in self.recent_inputs:
                self.recent_inputs.remove(path)
            self.recent_inputs.insert(0, path)
            info = self.settings.infos.get(path)
            if info is not None and info.notes:
                self.log(f"{info.name}: " + "; ".join(info.notes))
        del self.recent_inputs[15:]
        self._fill_recent_menu()
        if added:
            self.log(f"added {len(added)} file(s)")
            if self.settings.table.currentRow() < 0:
                self.settings.table.selectRow(0)

    def _fill_recent_menu(self) -> None:
        """Rebuild File > Recent inputs (newest first)."""
        self.recent_menu.clear()
        for path in self.recent_inputs:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(lambda _c=False, p=path: self.add_inputs([p]))
        self.recent_menu.setEnabled(bool(self.recent_inputs))

    def dragEnterEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        """Accept files and folders dragged onto the window."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        """Add the dropped files and folders (folders: every *.shr inside)."""
        self.add_inputs([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def _current_path(self) -> str | None:
        """The selected input, else the first one, else None."""
        paths = self.settings.paths(selected_only=True)
        if paths:
            return paths[0]
        all_paths = self.settings.paths()
        return all_paths[0] if all_paths else None

    def _selection_changed(self) -> None:
        """Show the selected file: header and plan (File info), cached preview, outputs."""
        path = self._current_path()
        if path is None:
            return
        info = self.settings.infos.get(path)
        if info is not None:
            # The plan follows the current settings, so the CSV estimate, the
            # seconds per spectrogram row and the free disk space are always
            # those of the conversion that Convert would start now.
            lines = info.summary_lines()
            try:
                opts = self.settings.options()
                plan = core.make_plan(info, opts)
                lines += [""] + plan.lines()
                folder = Path(opts.output_dir) if opts.output_dir else Path(path).parent
                free = core.disk_free_bytes(folder)
                lines.append(f"Free on output  : {core.human_bytes(free)} ({folder})"
                             + ("  <-- NOT ENOUGH for the CSV" if plan.est_csv_bytes > 0.95 * free else ""))
            except Exception as exc:  # noqa: BLE001 - e.g. an empty selection
                lines += ["", f"Plan: {exc}"]
            self.info_text.setPlainText("\n".join(lines))
        if path in self.previews:
            # Previews live on disk (one pickle per file); only the shown one
            # is loaded, so many converted files never fill the memory.
            try:
                self.preview.show_result(core.load_pickle(self.previews[path]))
            except Exception as exc:  # noqa: BLE001
                self.log(f"preview of {Path(path).name} not readable: {exc}")
        self._show_outputs(path)

    def _show_outputs(self, path: str) -> None:
        """List the files written for ``path`` on the Outputs tab."""
        self.output_list.clear()
        for name in self.outputs.get(path, []):
            self.output_list.addItem(name)

    # -- tasks ---------------------------------------------------------------------------------------------------
    def _start(self, name: str, job: Callable[..., Any], on_result: Callable[[Any], None],
               on_finished: Callable[[Any], None] | None = None) -> None:
        """Run ``job`` in a TaskThread; one task at a time.

        The thread's signals arrive in the GUI thread (queued connections),
        so the slots below may touch widgets safely.
        """
        if self.task is not None and self.task.isRunning():
            QtWidgets.QMessageBox.information(self, APP_NAME, "A task is already running (Esc stops it).")
            return
        self.task = TaskThread(name, job, self)
        self.task.messageLogged.connect(self.log)
        self.task.progressed.connect(self._progress)
        self.task.resultDelivered.connect(on_result)
        self.task.taskFinished.connect(lambda _v: self._task_done(f"{name} finished"))
        if on_finished is not None:
            self.task.taskFinished.connect(on_finished)
        self.task.taskFailed.connect(lambda text: (self.log(text), self._task_done(text)))
        self._busy(True)
        self.task.start()

    def _busy(self, busy: bool) -> None:
        """Enable Stop and disable the start actions while a task runs (and back)."""
        for action in (self.act_inspect, self.act_convert, self.act_convert_sel):
            action.setEnabled(not busy)
        self.act_stop.setEnabled(busy)
        self.settings.inspect_button.setEnabled(not busy)
        self.settings.convert_button.setEnabled(not busy)
        self.settings.stop_button.setEnabled(busy)
        self.progress.setVisible(busy)
        self.progress.setValue(0)

    def _progress(self, fraction: float, text: str) -> None:
        """Progress bar in tenths of a percent, message in the status bar."""
        self.progress.setValue(int(round(1000 * fraction)))
        self.progress.setMaximum(1000)
        self.statusBar().showMessage(text)

    def _task_done(self, text: str) -> None:
        """A task finished or failed: back to idle."""
        self._busy(False)
        self.statusBar().showMessage(text, 8000)

    def stop_task(self) -> None:
        """Ask the running task to stop; the core stops after the current block
        and deletes that file's partial outputs."""
        if self.task is not None and self.task.isRunning():
            self.task.cancel()
            self.log("stop requested - after the current block")

    def inspect_selected(self) -> None:
        """Header, plan and preview of the selected file; nothing is written."""
        path = self._current_path()
        if path is None:
            self.statusBar().showMessage("Add a .shr file first.", 4000)
            return
        try:
            opts = self.settings.options()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, APP_NAME, str(exc))
            return
        # Inspect = the full statistics pass without any output file: the same
        # code as Convert, so the preview shows exactly what Convert will write.
        opts.write_csv = opts.write_vszh5 = opts.render = False
        self.log(f"Inspect {Path(path).name}")

        def job(log: Any, progress: Any, deliver: Any, cancelled: Any) -> int:
            deliver(core.convert_file(path, opts, progress=progress, cancel=cancelled, log=log))
            return 1
        self._start("Inspect", job, self._deliver)

    def convert(self, selected_only: bool) -> None:
        """Convert every listed file (F5) or the selected ones (Shift+F5).

        One worker pool serves the whole batch (core.convert_files); each
        finished file arrives through _deliver() while the next one runs.
        """
        paths = self.settings.paths(selected_only=selected_only)
        if not paths:
            self.statusBar().showMessage("No files to convert.", 4000)
            return
        try:
            opts = self.settings.options()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, APP_NAME, str(exc))
            return
        if not (opts.write_csv or opts.write_vszh5):
            QtWidgets.QMessageBox.information(self, APP_NAME, "Tick CSV and/or Veusz document first.")
            return
        self._save_settings()                          # a crash later never loses the settings
        # Log only the options that differ from the defaults (short, and what matters).
        self.log(f"Convert {len(paths)} file(s); options: " + json.dumps(
            {k: v for k, v in asdict(opts).items() if v != getattr(core.ConvertOptions(), k)}))
        for path in paths:
            self.settings.set_status(path, "queued")

        def job(log: Any, progress: Any, deliver: Any, cancelled: Any) -> int:
            return len(core.convert_files(paths, opts, progress=progress, cancel=cancelled, log=log,
                                          deliver=deliver))
        self._start("Convert", job, self._deliver)

    def _deliver(self, item: Any) -> None:
        """A ConvertResult (or an Exception for a failed file) from the task."""
        if isinstance(item, Exception):
            return                       # already logged by the core
        path = item.info.path
        # The result already has its per-sweep arrays thinned (ConvertResult.
        # slim), so the pickle stays small even for a multi-hour capture.
        cache = self.cache_dir / f"preview_{hashlib.sha1(path.encode('utf-8')).hexdigest()[:16]}.pkl"
        try:
            core.save_pickle(item, cache)          # previews live on disk
            self.previews[path] = cache
        except Exception as exc:  # noqa: BLE001
            self.log(f"preview cache not written: {exc}")
        members = list(item.info.paths) or [path]       # every file of a joined recording
        if item.outputs:
            joined = f" (joined, {len(members)} files)" if len(members) > 1 else ""
            for member in members:
                self.outputs[member] = list(item.outputs)
                self.settings.set_status(member, f"done in {item.seconds:.1f} s - "
                                                 f"{len(item.outputs)} file(s){joined}")
        else:
            self.settings.set_status(path, "inspected")
        self.preview.show_result(item)
        self.info_text.setPlainText("\n".join(item.info.summary_lines() + [""] + item.plan.lines() + [""]
                                              + item.summary_lines() + [""] + item.log))
        self._show_outputs(path)
        self.tabs.setCurrentWidget(self.preview)

    def show_plan(self) -> None:
        """Convert > Show plan (Ctrl+P): the File info tab of the selected file."""
        path = self._current_path()
        if path and path in self.settings.infos:
            self._selection_changed()
            self.tabs.setCurrentWidget(self.info_text)

    def run_selftest(self) -> None:
        """Convert > Run self-test: core.self_test() on synthetic files, in the background."""
        def job(log: Any, progress: Any, deliver: Any, cancelled: Any) -> bool:
            ok = core.self_test(report=log, workers=2)
            log("SELF-TEST " + ("PASSED" if ok else "FAILED"))
            return ok
        self.log("Self-test (synthetic files in a temporary folder) ...")
        self._start("Self-test", job, lambda _r: None)

    # -- outputs and Veusz ----------------------------------------------------------------------------------
    def _vszh5_of_current(self) -> Path | None:
        """The .vszh5 of the selected file: from this session's outputs, else on disk."""
        path = self._current_path()
        if path is None:
            return None
        for name in self.outputs.get(path, []):
            if name.endswith(".vszh5"):
                return Path(name)
        try:
            stem = core.output_stem(path, self.settings.options())
        except Exception:  # noqa: BLE001 - invalid options
            return None
        candidate = stem.with_name(stem.name + ".vszh5")
        return candidate if candidate.is_file() else None

    def open_in_veusz(self) -> None:
        """Veusz > Open: start Veusz on the selected file's document."""
        target = self._vszh5_of_current()
        if target is None:
            self.statusBar().showMessage("Convert the selected file with the Veusz document first.", 5000)
            return
        self._open_output(str(target))

    def _open_output(self, name: str) -> None:
        """Open an output: .vszh5 in Veusz (own process, not waited for), others with the system."""
        if name.endswith(".vszh5"):
            exe = self.settings.veusz_edit.text().strip() or vszh5_writer.find_veusz_exe()
            if exe:
                subprocess.Popen([exe, name])
                self.log(f"opened {Path(name).name} in Veusz ({exe})")
                return
            self.log("Veusz not found (set it in the Veusz group or VEUSZ_EXE); opening with the system")
        try:
            open_with_system(name)
        except Exception as exc:  # noqa: BLE001
            self.log(f"cannot open {name}: {exc}")

    def render_selected(self) -> None:
        """Veusz > Render: PDF (bookmarked) and PNG of an existing .vszh5, in the background."""
        target = self._vszh5_of_current()
        if target is None:
            self.statusBar().showMessage("No .vszh5 for the selected file yet.", 5000)
            return
        opts = self.settings.options()
        path = self._current_path()

        def job(log: Any, progress: Any, deliver: Any, cancelled: Any) -> list[str]:
            files = [str(p) for p in core.render_existing(target, opts)]
            for f in files:
                log(f"  rendered {f}")
            return files

        def finished(files: Any) -> None:
            if path:
                self.outputs.setdefault(path, [])
                self.outputs[path] += [f for f in files if f not in self.outputs[path]]
                self._show_outputs(path)
        self._start("Render", job, lambda _r: None, finished)

    def open_pdf(self) -> None:
        """Veusz > Open rendered PDF."""
        target = self._vszh5_of_current()
        pdf = target.with_name(target.stem + ".pdf") if target else None
        if pdf and pdf.is_file():
            open_with_system(pdf)
        else:
            self.statusBar().showMessage("No rendered PDF yet (Veusz > Render).", 5000)

    def open_output_folder(self) -> None:
        """File > Open output folder (of the selected file, with the current settings)."""
        path = self._current_path()
        if path is None:
            return
        try:
            folder = core.output_stem(path, self.settings.options()).parent
        except Exception:  # noqa: BLE001
            folder = Path(path).parent
        open_with_system(folder)

    # -- settings ------------------------------------------------------------------------------------------------
    def _save_settings(self) -> None:
        """Options (JSON), recent files, window geometry and dock layout to QSettings."""
        try:
            self.settings_store.setValue("options", self.settings.options().to_json())
        except ValueError:
            pass
        self.settings_store.setValue("recent", json.dumps(self.recent_inputs))
        self.settings_store.setValue("geometry", self.saveGeometry())
        self.settings_store.setValue("state", self.saveState())

    def _restore_settings(self) -> None:
        """Theme, options, recent files and window layout from QSettings (tolerates stale values)."""
        mode = str(self.settings_store.value("theme", ThemeManager.SYSTEM))
        self.set_theme(mode if mode in self._theme_actions else ThemeManager.SYSTEM)
        try:
            text = self.settings_store.value("options", "")
            if text:
                self.settings.set_options(core.ConvertOptions.from_mapping(json.loads(str(text))))
            self.recent_inputs = [p for p in json.loads(str(self.settings_store.value("recent", "[]")))
                                  if isinstance(p, str)]
        except Exception as exc:  # noqa: BLE001 - stale or foreign settings
            self.log(f"settings not restored: {exc}")
        self._fill_recent_menu()
        geometry = self.settings_store.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = self.settings_store.value("state")
        if state is not None:
            self.restoreState(state)

    def save_settings_file(self) -> None:
        """File > Save settings: the options as a JSON file (shareable, also for --cli use)."""
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save settings", "shr_converter_settings.json",
                                                        "JSON (*.json)")
        if name:
            Path(name).write_text(self.settings.options().to_json(), encoding="utf-8")
            self.log(f"settings saved to {name}")

    def load_settings_file(self) -> None:
        """File > Load settings: options from a JSON file (unknown keys ignored)."""
        name, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load settings", "", "JSON (*.json)")
        if name:
            self.settings.set_options(core.ConvertOptions.from_mapping(
                json.loads(Path(name).read_text(encoding="utf-8"))))
            self.log(f"settings loaded from {name}")

    def save_log(self) -> None:
        """File > Save log."""
        name, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save log", "shr_converter_log.txt",
                                                        "Text (*.txt)")
        if name:
            Path(name).write_text(self.log_text.toPlainText(), encoding="utf-8")

    # -- help ----------------------------------------------------------------------------------------------------
    def open_manual(self) -> None:
        """Help > User manual (F1): docs/SHR_Converter_Manual_v<version>.pdf."""
        if MANUAL_PDF.is_file():
            open_with_system(MANUAL_PDF)
        else:
            QtWidgets.QMessageBox.information(self, APP_NAME, f"Manual not found:\n{MANUAL_PDF}")

    def show_shortcuts(self) -> None:
        """Help > Keyboard shortcuts: every action that has one, from the menus."""
        rows = []
        for action in self.findChildren(QAction):
            keys = action.shortcut().toString()
            if keys and action.text():
                rows.append(f"{keys:<16} {action.text().replace('&', '')}")
        QtWidgets.QMessageBox.information(self, "Keyboard shortcuts", "\n".join(sorted(set(rows))))

    def build_about_box(self) -> Any:
        """The About box: author, licence, and the versions actually loaded."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(f"About {APP_NAME}")
        box.setTextFormat(QtCore.Qt.TextFormat.RichText)
        gpu = core.get_backend("auto")[1]
        box.setText(
            f"<h3>{APP_NAME} {__version__}</h3>"
            f"<p>Signal Hound Spike .shr sweep files to CSV and native Veusz documents.</p>"
            f"<p>{core.__author__}, {core.__company__}<br>{core.__email__}</p>"
            f"<p>{core.__copyright__}<br>Licence: {core.__license__}</p>"
            f"<table>"
            f"<tr><td>GUI / core</td><td>{__version__} / {core.__version__}</td></tr>"
            f"<tr><td>vszh5_writer</td><td>{vszh5_writer.__version__}</td></tr>"
            f"<tr><td>shr_reader</td><td>{core.SHR_READER_VERSION} (reader, same author)</td></tr>"
            f"<tr><td>Python</td><td>{platform.python_version()} ({platform.system()})</td></tr>"
            f"<tr><td>NumPy</td><td>{np.__version__}</td></tr>"
            f"<tr><td>Qt layer</td><td>{QT_ABSTRACTION}</td></tr>"
            f"<tr><td>Qt binding</td><td>{QT_BINDING}</td></tr>"
            f"<tr><td>pyqtgraph</td><td>{pg.__version__ if HAVE_PYQTGRAPH else 'not installed'}</td></tr>"
            f"<tr><td>Compute</td><td>{gpu}</td></tr>"
            f"<tr><td>Veusz</td><td>{vszh5_writer.find_veusz_exe() or 'not found'}</td></tr>"
            f"</table>")
        return box

    def show_about(self) -> None:
        """Help > About."""
        box = self.build_about_box()
        box.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        box.exec()

    # -- closing -------------------------------------------------------------------------------------------------
    def closeEvent(self, event: Any) -> None:  # noqa: N802 - Qt API
        """Stop a running task (its partial files are deleted), save settings, drop the preview cache."""
        if self.task is not None and self.task.isRunning():
            self.task.cancel()
            self.task.wait(30000)                    # the current block finishes first
        self._save_settings()
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        event.accept()


# %% ===========================================================================
#    START-UP AND SMOKE TEST
# =============================================================================
def launch_gui(inputs: Sequence[str] = ()) -> int:
    """Create (or reuse, e.g. in Spyder) the QApplication and show the window."""
    app = QtWidgets.QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ORG)
    window = MainWindow(ThemeManager(app), inputs)
    window.show()
    if owns_app:
        return app.exec()
    globals()["_spyder_window"] = window          # keep a reference in an IPython kernel
    return 0


def gui_smoke_test(report: Callable[[str], None] = print, workers: int = 2) -> bool:
    """Offscreen GUI test: add, inspect, convert (CSV + .vszh5), themes, About, free memory."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    SETTINGS_SCOPE[:] = [APP_ORG + "-test", APP_NAME + "-smoke"]
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    ok = True

    def check(name: str, condition: bool) -> None:
        nonlocal ok
        ok &= bool(condition)
        report(("PASS " if condition else "FAIL ") + name)

    def wait(window: MainWindow, seconds: float = 300.0) -> None:
        deadline = time.time() + seconds
        while window.task is not None and window.task.isRunning() and time.time() < deadline:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    with tempfile.TemporaryDirectory(prefix="shr_gui_smoke_") as folder:
        source = core.write_synthetic_shr(Path(folder) / "smoke.shr", n_sweeps=80, n_bins=2001, gps=True)
        window = MainWindow(ThemeManager(app))
        window.settings.set_options(core.ConvertOptions())
        window.add_inputs([str(source)])
        check("file listed with its header", window.settings.table.rowCount() == 1
              and window.settings.table.item(0, 1).text() == "80")
        window.settings.table.selectRow(0)
        window.inspect_selected()
        wait(window)
        check("inspect shows a preview", window.preview.result is not None
              and window.preview.result.image.shape[0] > 0)
        check("inspect wrote nothing", not any(Path(folder).glob("*.csv")))
        window.settings.workers_spin.setValue(workers)
        saved = core.IN_PROCESS_MAX_SAMPLES
        core.IN_PROCESS_MAX_SAMPLES = 0          # real worker processes, even for this small file
        try:
            window.convert(selected_only=False)
            wait(window)
        finally:
            core.IN_PROCESS_MAX_SAMPLES = saved
        written = sorted(p.name for p in Path(folder).iterdir())
        check("convert wrote CSV, companions and .vszh5",
              {"smoke.csv", "smoke_header.csv", "smoke_sweeps.csv", "smoke_statistics.csv",
               "smoke.vszh5"} <= set(written))
        check("outputs tab lists the files", window.output_list.count() >= 5)
        check("conversion ran in worker processes", "worker process" in window.info_text.toPlainText())
        # join + CSV decimation through the controls (two halves of one recording)
        joined_dir = Path(folder) / "join"
        joined_dir.mkdir()
        halves = core.split_recording(source, [joined_dir / "half1.shr", joined_dir / "half2.shr"], [40, 40])
        window.settings.clear_inputs()
        window.add_inputs([str(h) for h in halves])
        window.settings.join_check.setChecked(True)
        window.settings.decimate_spin.setValue(4)
        window.settings.vsz_group.setChecked(False)
        window.convert(selected_only=False)
        wait(window)
        joined_csv = joined_dir / "half1_joined.csv"
        rows = joined_csv.read_text().splitlines() if joined_csv.is_file() else []
        check("join + combine 4 sweeps per row: one CSV of 20 rows", len(rows) == 21
              and "sweeps_combined" in rows[0] and window.settings.options().join_files)
        window.settings.join_check.setChecked(False)
        window.settings.decimate_spin.setValue(1)
        window.settings.vsz_group.setChecked(True)
        window.settings.clear_inputs()
        window.add_inputs([str(source)])
        window.settings.table.selectRow(0)
        for mode in (ThemeManager.DARK, ThemeManager.LIGHT, ThemeManager.SYSTEM):
            window.set_theme(mode)
        check("themes switch (dark/light/system)", window.theme.current == ThemeManager.SYSTEM)
        box = window.build_about_box()
        check("About names the versions", vszh5_writer.__version__ in box.text() and __version__ in box.text()
              and core.SHR_READER_VERSION in box.text())
        box.deleteLater()
        window.free_memory()
        check("free memory clears the preview", window.preview.result is None)
        window._selection_changed()
        check("preview reloads from the disk cache", window.preview.result is not None)
        cache = window.cache_dir
        window.close()
        app.processEvents()
        check("preview cache removed on close", not cache.exists())
    QtCore.QSettings(*SETTINGS_SCOPE).clear()
    return ok


if __name__ == "__main__":
    # Start through shr_converter.py; this keeps working for a direct start.
    sys.exit(launch_gui(sys.argv[1:]))
