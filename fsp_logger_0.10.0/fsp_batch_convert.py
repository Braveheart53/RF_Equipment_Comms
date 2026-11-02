#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Batch converter: logger CSV files -> Veusz plots / reports (dialog + launcher)
=============================================================================
===============================================================================
 Title          : FSP Logger Batch Converter
 Filename       : fsp_batch_convert.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-29
 Modified       : 2026-10-29
 Language       : Python 3.8 through 3.12
 Requires       : fsp_batch_core.py, fsp_gui_theme.py, fsp_reports.py,
                  vszh5_writer.py (same folder); QtPy + PyQt5 (default) or
                  PySide6 (QT_API=pyside6); h5py for the reports
 Optional       : Veusz with h5py for PDF + PNG
 Licence        : Same terms as rs_fsp_logger.py (not declared by the owner;
                  no grant inferred).
 Attribution    : AI-assisted (Claude) addition to the owner's logger bundle.
                  Input list (Add files / Add folder / Remove / Clear, drag
                  and drop) follows the owner's SHR Converter 0.0.2 GUI.
 Status         : Internal draft - offscreen GUI tests, PyQt5 and PySide6.
===============================================================================

USAGE
-----
    python fsp_batch_convert.py                    stand-alone window
    python fsp_batch_convert.py D:/runs a.csv      window with these inputs
    python fsp_batch_convert.py --cli D:/runs      no window (see --cli --help)
    rs_fsp_logger.py: File > Batch convert CSV files to Veusz plots...

DESCRIPTION
-----------
One dialog converts a single CSV, several CSVs or whole folders (optionally
with sub-folders) of R&S FSP logger CSV files into native Veusz reports. Each
CSV gets a NEW report folder <stem>_reports_<stamp>, made by fsp_reports.py in
its own process exactly as the logger's single-file button makes it: the same
pages, statistics tables, report.json/report.md and optional PDF + PNG.

* Inputs: Add files..., Add folder..., drag and drop, or paths on the command
  line. Only logger CSVs are listed (recognised by their header); other CSVs
  met in a folder (report tables, <run>_events.csv, ...) are skipped and
  named in the log.
* Output: next to each CSV, or all under one folder (keeping the scanned
  sub-folder structure, so equal names in different folders never meet).
  Existing report folders are never overwritten; optionally skip CSVs that
  already have one.
* Processing: up to N report processes at once (default: half the logical
  CPUs, 1-4), each with BLAS threads capped at 1; Cancel stops the queue,
  ends running processes and removes their unfinished (hidden) folders.
* Theme: the logger's Dark / Light / System choice (View > Theme here sets
  the same shared preference). Opened from the logger, it follows the
  logger's theme and the logger cannot start sampling while a batch runs
  (and the batch cannot start while the logger samples).

REVISION HISTORY (newest first)
-------------------------------
0.0.1  2026-10-29  First version, logger bundle 0.10.0.
===============================================================================
"""

from __future__ import annotations

# %% IMPORTS (Qt is not needed for --cli)
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, Sequence, Tuple

_HERE = Path(globals().get("__file__") or "fsp_batch_convert.py").resolve().parent
if str(_HERE) not in sys.path:              # sibling modules, also from Spyder
    sys.path.insert(0, str(_HERE))

import fsp_batch_core as core  # noqa: E402

if __name__ == "__main__" and "--cli" in sys.argv[1:]:
    sys.exit(core.main([argument for argument in sys.argv[1:] if argument != "--cli"]))

from qtpy import QtCore, QtGui, QtWidgets  # noqa: E402
from qtpy.QtCore import Qt, Signal  # noqa: E402

import fsp_gui_theme as theme_module  # noqa: E402

__version__ = "0.0.1"
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"

APP_NAME = "FSP Logger Batch Converter"
SETTINGS_GROUP = "batch_convert"
#: Bytes of each report process's output kept for the log (tail).
OUTPUT_TAIL_BYTES = 65536

STATUS_READY = "Ready"
STATUS_QUEUED = "Queued"
STATUS_RUNNING = "Running…"
STATUS_DONE = "Done"
STATUS_FAILED = "Failed"
STATUS_SKIPPED = "Skipped"
STATUS_CANCELLED = "Cancelled"


def _exec(dialog) -> int:
    """exec_() on PyQt5, exec() on PySide6."""
    return dialog.exec_() if hasattr(dialog, "exec_") else dialog.exec()


def _human_size(size: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return str(size)


# %% DIALOG
class BatchConvertDialog(QtWidgets.QDialog):
    """Convert many logger CSVs to Veusz reports; also the stand-alone window.

    Parameters
    ----------
    parent:
        The logger's MainWindow when opened from it, else None.
    standalone:
        True when this is the program's only window (adds File > Exit and
        stores the theme choice itself).
    theme_mode:
        'dark', 'light' or 'system'; default: the shared stored choice.
    settings:
        QSettings to use (the logger passes its own; same location).
    inputs:
        Paths to add at start.
    """

    #: True while conversions run (the logger blocks sampling meanwhile).
    runningChanged = Signal(bool)

    # Status second so it stays visible however long the folder paths are.
    COLUMNS = ("File", "Status", "Traces", "Size", "Folder", "Report folder")
    COL_FILE, COL_STATUS, COL_TRACES, COL_SIZE, COL_FOLDER, COL_OUTPUT = range(6)
    #: Widest a column may grow when sized to its contents (pixels).
    MAX_COLUMN_WIDTH = 420

    def __init__(self, parent=None, standalone: bool = False, theme_mode: Optional[str] = None,
                 settings=None, inputs: Sequence[str] = ()):
        super().__init__(parent)
        self.standalone = bool(standalone)
        self.settings = settings or theme_module.shared_settings()
        self.base_palette = QtGui.QPalette(self.palette())
        self.theme_mode = theme_mode or theme_module.saved_mode(self.settings)
        # key -> {"path": Path, "base": Path|None, "check": CsvCheck, "job": BatchJob|None}
        self.entries: Dict[str, dict] = {}
        self.queue: Deque[str] = deque()
        self.processes: Dict[str, QtCore.QProcess] = {}
        self.outputs: Dict[str, Tuple[bytearray, bytearray]] = {}
        self.blocked_reason = ""
        self.running = False
        self.cancelling = False
        self.close_after_batch = False
        self.batch_started = 0.0
        self.counts = dict(done=0, failed=0, skipped=0, cancelled=0, total=0)
        self.options = core.BatchOptions()
        self.last_summary = ""
        #: Set by the logger: callable(mode) that applies a theme to the logger
        #: AND this dialog and stores it. None when stand-alone.
        self.theme_handler = None
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setObjectName("batchConvertDialog")
        self.setAcceptDrops(True)
        self.setSizeGripEnabled(True)
        self.resize(1080, 800)
        if self.standalone:
            self.setWindowFlags(self.windowFlags() | Qt.WindowMinMaxButtonsHint)
        self._build_ui()
        self._build_menus()
        self._restore_settings()
        self.apply_theme(self.theme_mode)
        self._update_controls()
        if inputs:
            self.add_inputs(inputs)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("<b>Batch convert logger CSV files to Veusz plots</b>")
        title.setStyleSheet("font-size: 13pt;")
        header.addWidget(title)
        header.addStretch(1)
        version = QtWidgets.QLabel(f"v{__version__}")
        version.setStyleSheet("font-family: monospace;")
        header.addWidget(version)
        root.addLayout(header)

        # Inputs ---------------------------------------------------------------
        inputs = QtWidgets.QGroupBox("Input CSV files (one file, several files or whole folders; drop them here)")
        grid = QtWidgets.QVBoxLayout(inputs)
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setObjectName("inputTable")
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)                 # wrapping would override the elide mode
        self.table.setTextElideMode(Qt.ElideMiddle)   # long paths keep their file/folder name
        self.table.setMinimumHeight(170)
        self.table.itemSelectionChanged.connect(self._update_controls)
        self.table.itemDoubleClicked.connect(lambda _item: self.open_selected_output())
        grid.addWidget(self.table)
        buttons = QtWidgets.QHBoxLayout()
        self.add_files_btn = QtWidgets.QPushButton("Add files…")
        self.add_folder_btn = QtWidgets.QPushButton("Add folder…")
        self.remove_btn = QtWidgets.QPushButton("Remove")
        self.clear_btn = QtWidgets.QPushButton("Clear")
        self.add_files_btn.clicked.connect(lambda _c=False: self.browse_files())
        self.add_folder_btn.clicked.connect(lambda _c=False: self.browse_folder())
        self.remove_btn.clicked.connect(lambda _c=False: self.remove_selected())
        self.clear_btn.clicked.connect(lambda _c=False: self.clear_inputs())
        for button in (self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn):
            buttons.addWidget(button)
        self.recursive_check = QtWidgets.QCheckBox("Include sub-folders")
        self.recursive_check.setChecked(True)
        self.recursive_check.setToolTip("Add folder… also scans every sub-folder for logger CSVs.")
        buttons.addWidget(self.recursive_check)
        buttons.addStretch(1)
        self.inputs_label = QtWidgets.QLabel("No files.")
        buttons.addWidget(self.inputs_label)
        grid.addLayout(buttons)
        root.addWidget(inputs, stretch=3)

        # Output ---------------------------------------------------------------
        output = QtWidgets.QGroupBox("Output (a NEW report folder <name>_reports_<date_time> per CSV)")
        form = QtWidgets.QGridLayout(output)
        self.beside_radio = QtWidgets.QRadioButton("Next to each CSV")
        self.folder_radio = QtWidgets.QRadioButton("All in one folder:")
        self.beside_radio.setChecked(True)
        group = QtWidgets.QButtonGroup(self)
        group.addButton(self.beside_radio)
        group.addButton(self.folder_radio)
        self.output_edit = QtWidgets.QLineEdit()
        self.output_edit.setPlaceholderText("output folder")
        self.output_browse_btn = QtWidgets.QPushButton("Browse…")
        self.output_browse_btn.clicked.connect(lambda _c=False: self.browse_output())
        self.mirror_check = QtWidgets.QCheckBox("Keep the sub-folder structure of added folders")
        self.mirror_check.setChecked(True)
        self.skip_check = QtWidgets.QCheckBox("Skip CSVs that already have a report folder there")
        self.skip_check.setToolTip("A <name>_reports_* folder holding report.json counts as done.")
        for widget in (self.beside_radio, self.folder_radio):
            widget.toggled.connect(lambda _on: self._update_controls())
        form.addWidget(self.beside_radio, 0, 0)
        form.addWidget(self.folder_radio, 1, 0)
        form.addWidget(self.output_edit, 1, 1)
        form.addWidget(self.output_browse_btn, 1, 2)
        form.addWidget(self.mirror_check, 2, 1)
        form.addWidget(self.skip_check, 3, 0, 1, 2)
        form.setColumnStretch(1, 1)
        root.addWidget(output)

        # Processing -----------------------------------------------------------
        processing = QtWidgets.QGroupBox("Processing")
        form = QtWidgets.QGridLayout(processing)
        form.addWidget(QtWidgets.QLabel("Parallel conversions:"), 0, 0)
        self.jobs_spin = QtWidgets.QSpinBox()
        self.jobs_spin.setRange(1, max(1, os.cpu_count() or 1))
        self.jobs_spin.setValue(core.default_jobs())
        self.jobs_spin.setToolTip("Report processes running at once (each uses one BLAS thread).")
        form.addWidget(self.jobs_spin, 0, 1)
        form.addWidget(QtWidgets.QLabel("Matrix limit per CSV:"), 0, 2)
        self.matrix_spin = QtWidgets.QSpinBox()
        self.matrix_spin.setRange(16, 1048576)
        self.matrix_spin.setSingleStep(256)
        self.matrix_spin.setSuffix(" MiB")
        self.matrix_spin.setValue(512)
        self.matrix_spin.setToolTip("fsp_reports.py --max-matrix-mib: larger CSVs fail instead of exhausting disk/RAM.")
        form.addWidget(self.matrix_spin, 0, 3)
        self.render_check = QtWidgets.QCheckBox("Also render PDF + PNG (requires Veusz)")
        form.addWidget(self.render_check, 1, 0, 1, 2)
        form.addWidget(QtWidgets.QLabel("Veusz program:"), 2, 0)
        self.veusz_edit = QtWidgets.QLineEdit()
        self.veusz_edit.setPlaceholderText("auto-detected (VEUSZ_EXE or the usual install folders)")
        form.addWidget(self.veusz_edit, 2, 1, 1, 2)
        self.veusz_btn = QtWidgets.QPushButton("…")
        self.veusz_btn.setToolTip("Select the Veusz program (shared with the logger).")
        self.veusz_btn.clicked.connect(lambda _c=False: self.browse_veusz())
        form.addWidget(self.veusz_btn, 2, 3)
        self.render_check.toggled.connect(lambda _on: self._update_controls())
        form.setColumnStretch(1, 1)
        root.addWidget(processing)

        # Progress + buttons ---------------------------------------------------
        progress_row = QtWidgets.QHBoxLayout()
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        progress_row.addWidget(self.progress, 1)
        self.status_label = QtWidgets.QLabel("Idle.")
        self.status_label.setObjectName("batchStatus")
        progress_row.addWidget(self.status_label, 1)
        root.addLayout(progress_row)
        self.blocked_label = QtWidgets.QLabel("")
        self.blocked_label.setWordWrap(True)
        self.blocked_label.setVisible(False)
        root.addWidget(self.blocked_label)

        actions = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Convert")
        self.start_btn.setToolTip("Convert every listed CSV that is not Done yet (F5).")
        self.cancel_btn = QtWidgets.QPushButton("Cancel")
        self.cancel_btn.setToolTip("Stop the queue, end running conversions, remove their unfinished folders.")
        self.open_btn = QtWidgets.QPushButton("Open report folder")
        self.close_btn = QtWidgets.QPushButton("Close")
        self.start_btn.clicked.connect(lambda _c=False: self.start())
        self.cancel_btn.clicked.connect(lambda _c=False: self.cancel())
        self.open_btn.clicked.connect(lambda _c=False: self.open_selected_output())
        self.close_btn.clicked.connect(lambda _c=False: self.close())
        actions.addWidget(self.start_btn)
        actions.addWidget(self.cancel_btn)
        actions.addStretch(1)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.close_btn)
        root.addLayout(actions)

        # Log ---------------------------------------------------------------------
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setObjectName("batchLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)     # bounded memory on long batches
        self.log_view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        self.log_view.setMinimumHeight(110)
        root.addWidget(self.log_view, stretch=2)

        shortcut_class = getattr(QtWidgets, "QShortcut", None) or QtGui.QShortcut
        delete = shortcut_class(QtGui.QKeySequence(QtGui.QKeySequence.Delete), self.table)
        delete.activated.connect(self.remove_selected)

    def _build_menus(self) -> None:
        self.menu_bar = QtWidgets.QMenuBar(self)
        self.menu_bar.setNativeMenuBar(False)
        self.layout().setMenuBar(self.menu_bar)
        action_class = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        group_class = getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup

        def action(menu, text, callback, shortcut=""):
            result = action_class(text, self)
            result.triggered.connect(lambda _checked=False: callback())
            if shortcut:
                result.setShortcut(QtGui.QKeySequence(shortcut))
            menu.addAction(result)
            return result

        file_menu = self.menu_bar.addMenu("&File")
        self.add_files_action = action(file_menu, "Add CSV files…", self.browse_files, "Ctrl+O")
        self.add_folder_action = action(file_menu, "Add folder…", self.browse_folder, "Ctrl+Shift+O")
        self.remove_action = action(file_menu, "Remove selected", self.remove_selected)
        self.clear_action = action(file_menu, "Clear list", self.clear_inputs)
        file_menu.addSeparator()
        self.start_action = action(file_menu, "Convert", self.start, "F5")
        self.cancel_action = action(file_menu, "Cancel", self.cancel, "Shift+F5")
        file_menu.addSeparator()
        action(file_menu, "E&xit" if self.standalone else "Close", self.close,
               "Ctrl+Q" if self.standalone else "Ctrl+W")

        view_menu = self.menu_bar.addMenu("&View")
        theme_menu = view_menu.addMenu("Theme")
        self.theme_group = group_class(self)
        self.theme_group.setExclusive(True)
        self.theme_actions = {}
        for mode, label in theme_module.THEME_MODES:
            result = action_class(label, self)
            result.setCheckable(True)
            result.triggered.connect(lambda checked, value=mode: self.choose_theme(value) if checked else None)
            self.theme_group.addAction(result)
            theme_menu.addAction(result)
            self.theme_actions[mode] = result

        tools_menu = self.menu_bar.addMenu("&Tools")
        action(tools_menu, "Select Veusz program…", self.browse_veusz)
        action(tools_menu, "Open selected report folder", self.open_selected_output)

        help_menu = self.menu_bar.addMenu("&Help")
        action(help_menu, "Usage", self.show_usage, "F1")
        action(help_menu, f"About {APP_NAME}…", self.show_about)

    # ------------------------------------------------------------------ theme
    def apply_theme(self, mode: str) -> None:
        """Apply a theme to this dialog only (the logger calls this too)."""
        theme = theme_module.apply_theme(self, self.base_palette, mode)
        self.theme_mode = theme.mode
        for name, result in getattr(self, "theme_actions", {}).items():
            result.setChecked(name == theme.mode)

    def choose_theme(self, mode: str) -> None:
        """View > Theme. From the logger: the logger applies it everywhere;
        stand-alone: apply and store the shared preference."""
        if self.theme_handler is not None:
            self.theme_handler(mode)
            return
        self.apply_theme(mode)
        self.settings.setValue(theme_module.SETTINGS_THEME_KEY, self.theme_mode)

    # ------------------------------------------------------------------ settings
    def _restore_settings(self) -> None:
        s = self.settings

        def value(key, default):
            return s.value(f"{SETTINGS_GROUP}/{key}", default)

        def flag(key, default):
            return str(value(key, default)).strip().lower() in ("true", "1", "yes")

        self.folder_radio.setChecked(str(value("output_mode", "beside")) == "folder")
        self.beside_radio.setChecked(not self.folder_radio.isChecked())
        self.output_edit.setText(str(value("output_root", "")))
        self.mirror_check.setChecked(flag("mirror", True))
        self.recursive_check.setChecked(flag("recursive", True))
        self.render_check.setChecked(flag("render", False))
        self.skip_check.setChecked(flag("skip_existing", False))
        try:
            self.jobs_spin.setValue(int(value("jobs", core.default_jobs())))
            self.matrix_spin.setValue(int(value("max_matrix_mib", 512)))
        except (TypeError, ValueError):
            pass
        self.veusz_edit.setText(str(s.value("veusz_executable", "") or os.environ.get("VEUSZ_EXE", "")))
        self.last_folder = str(value("last_folder", str(Path.home())))

    def _save_settings(self) -> None:
        s = self.settings
        for key, data in (("output_mode", "folder" if self.folder_radio.isChecked() else "beside"),
                          ("output_root", self.output_edit.text().strip()),
                          ("mirror", self.mirror_check.isChecked()),
                          ("recursive", self.recursive_check.isChecked()),
                          ("render", self.render_check.isChecked()),
                          ("skip_existing", self.skip_check.isChecked()),
                          ("jobs", self.jobs_spin.value()),
                          ("max_matrix_mib", self.matrix_spin.value()),
                          ("last_folder", self.last_folder)):
            s.setValue(f"{SETTINGS_GROUP}/{key}", data)
        if self.veusz_edit.text().strip():
            s.setValue("veusz_executable", self.veusz_edit.text().strip())

    # ------------------------------------------------------------------ inputs
    def log(self, text: str) -> None:
        self.log_view.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _row_of(self, key: str) -> int:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self.COL_FILE)
            if item is not None and item.data(Qt.UserRole) == key:
                return row
        return -1

    def _set_cell(self, key: str, column: int, text: str, tooltip: str = "") -> None:
        row = self._row_of(key)
        if row < 0:
            return
        item = QtWidgets.QTableWidgetItem(text)
        item.setToolTip(tooltip or text)
        self.table.setItem(row, column, item)

    def status_of(self, key: str) -> str:
        row = self._row_of(key)
        item = self.table.item(row, self.COL_STATUS) if row >= 0 else None
        return item.text() if item is not None else ""

    def add_inputs(self, items: Sequence[str]) -> List[str]:
        """Add CSV files and folders (folders: their logger CSVs)."""
        found, skipped = core.expand_inputs(items, recursive=self.recursive_check.isChecked())
        added: List[str] = []
        for path, base in found:
            key = os.path.normcase(str(path))
            if key in self.entries:
                continue
            check = core.check_logger_csv(path)
            self.entries[key] = dict(path=path, base=base, check=check, job=None)
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QtWidgets.QTableWidgetItem(path.name)
            item.setData(Qt.UserRole, key)
            item.setToolTip(str(path))
            self.table.setItem(row, self.COL_FILE, item)
            for column, text in ((self.COL_FOLDER, str(path.parent)),
                                 (self.COL_SIZE, _human_size(check.size_bytes)),
                                 (self.COL_TRACES, ", ".join(str(t) for t in check.traces)),
                                 (self.COL_STATUS, STATUS_READY), (self.COL_OUTPUT, "")):
                cell = QtWidgets.QTableWidgetItem(text)
                cell.setToolTip(text)
                self.table.setItem(row, column, cell)
            added.append(key)
        for check in skipped:
            self.log(f"skipped {check.path} — {check.reason}")
        if added:
            self.log(f"added {len(added)} logger CSV file(s)"
                     + (f"; {len(skipped)} other file(s) skipped" if skipped else ""))
        elif items and not skipped:
            self.log("nothing new to add")
        self._fit_columns()
        self._update_controls()
        return added

    def _fit_columns(self) -> None:
        """Size columns to their contents, but no wider than MAX_COLUMN_WIDTH."""
        self.table.resizeColumnsToContents()
        for column in range(self.table.columnCount()):
            if self.table.columnWidth(column) > self.MAX_COLUMN_WIDTH:
                self.table.setColumnWidth(column, self.MAX_COLUMN_WIDTH)

    def browse_files(self) -> None:
        if self.running:
            return
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Add logger CSV files", self.last_folder, "CSV files (*.csv);;All files (*)")
        if paths:
            self.last_folder = str(Path(paths[0]).parent)
            self.add_inputs(paths)

    def browse_folder(self) -> None:
        if self.running:
            return
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Add a folder of logger CSV files",
                                                            self.last_folder)
        if folder:
            self.last_folder = folder
            self.add_inputs([folder])

    def browse_output(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Folder for the report folders",
                                                            self.output_edit.text() or self.last_folder)
        if folder:
            self.output_edit.setText(folder)
            self.folder_radio.setChecked(True)

    def browse_veusz(self) -> None:
        executable, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select the Veusz program", self.veusz_edit.text() or os.environ.get("VEUSZ_EXE", ""),
            "All files (*)")
        if executable:
            self.veusz_edit.setText(executable)
            self.settings.setValue("veusz_executable", executable)

    def remove_selected(self) -> None:
        if self.running:
            return
        for row in sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True):
            key = self.table.item(row, self.COL_FILE).data(Qt.UserRole)
            self.entries.pop(key, None)
            self.table.removeRow(row)
        self._update_controls()

    def clear_inputs(self) -> None:
        if self.running:
            return
        self.table.setRowCount(0)
        self.entries.clear()
        self._update_controls()

    def selected_keys(self) -> List[str]:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        return [self.table.item(row, self.COL_FILE).data(Qt.UserRole) for row in rows]

    # ------------------------------------------------------------------ drag and drop
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.running:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths and not self.running:
            self.add_inputs(paths)
            event.acceptProposedAction()

    # ------------------------------------------------------------------ state
    def set_blocked(self, reason: str) -> None:
        """The logger blocks new batches while it samples (reason shown)."""
        reason = reason or ""
        if reason != self.blocked_reason:
            self.blocked_reason = reason
            self.blocked_label.setText(reason)
            self.blocked_label.setVisible(bool(reason))
            self._update_controls()

    def pending_keys(self) -> List[str]:
        """Rows that Convert will process: every row not Done."""
        keys = []
        for row in range(self.table.rowCount()):
            key = self.table.item(row, self.COL_FILE).data(Qt.UserRole)
            if not self.status_of(key).startswith(STATUS_DONE):
                keys.append(key)
        return keys

    def _update_controls(self) -> None:
        idle = not self.running
        for widget in (self.add_files_btn, self.add_folder_btn, self.remove_btn, self.clear_btn,
                       self.recursive_check, self.beside_radio, self.folder_radio, self.mirror_check,
                       self.skip_check, self.jobs_spin, self.matrix_spin, self.render_check):
            widget.setEnabled(idle)
        folder_mode = self.folder_radio.isChecked()
        self.output_edit.setEnabled(idle and folder_mode)
        self.output_browse_btn.setEnabled(idle and folder_mode)
        self.mirror_check.setEnabled(idle and folder_mode)
        self.veusz_edit.setEnabled(idle and self.render_check.isChecked())
        self.veusz_btn.setEnabled(idle and self.render_check.isChecked())
        can_start = idle and not self.blocked_reason and bool(self.pending_keys())
        self.start_btn.setEnabled(can_start)
        self.cancel_btn.setEnabled(self.running and not self.cancelling)
        self.remove_btn.setEnabled(idle and bool(self.selected_keys()))
        self.open_btn.setEnabled(any(self._output_of(key) for key in self.selected_keys()))
        for result, enabled in ((getattr(self, "start_action", None), can_start),
                                (getattr(self, "cancel_action", None), self.cancel_btn.isEnabled()),
                                (getattr(self, "add_files_action", None), idle),
                                (getattr(self, "add_folder_action", None), idle),
                                (getattr(self, "remove_action", None), idle),
                                (getattr(self, "clear_action", None), idle)):
            if result is not None:
                result.setEnabled(enabled)
        rows = self.table.rowCount()
        self.inputs_label.setText(f"{rows} logger CSV file(s)" if rows else "No files.")

    def _output_of(self, key: str) -> str:
        entry = self.entries.get(key)
        job = entry.get("job") if entry else None
        if job is not None and Path(job.output_dir).is_dir():
            return str(job.output_dir)
        return ""

    def _options_from_ui(self) -> core.BatchOptions:
        return core.BatchOptions(
            output_mode="folder" if self.folder_radio.isChecked() else "beside",
            output_root=self.output_edit.text().strip(),
            mirror_subfolders=self.mirror_check.isChecked(),
            recursive=self.recursive_check.isChecked(),
            render=self.render_check.isChecked(),
            jobs=self.jobs_spin.value(),
            skip_existing=self.skip_check.isChecked(),
            veusz_exe=self.veusz_edit.text().strip() if self.render_check.isChecked() else "",
            max_matrix_mib=self.matrix_spin.value())

    # ------------------------------------------------------------------ running
    def start(self) -> bool:
        """Plan and start a batch; False (with a reason in the log) if not."""
        if self.running or self.blocked_reason:
            return False
        keys = self.pending_keys()
        if not keys:
            self.log("nothing to convert (every listed CSV is Done)")
            return False
        options = self._options_from_ui()
        try:
            options.validate()
        except ValueError as error:
            self.log(f"cannot start: {error}")
            QtWidgets.QMessageBox.warning(self, APP_NAME, f"Cannot start: {error}")
            return False
        if not core.REPORT_SCRIPT.is_file():
            self.log(f"cannot start: {core.REPORT_SCRIPT} is missing")
            return False
        self.options = options
        jobs = core.plan_jobs([(self.entries[k]["path"], self.entries[k]["base"]) for k in keys], options)
        self.queue.clear()
        self.counts = dict(done=0, failed=0, skipped=0, cancelled=0, total=len(jobs))
        for key, job in zip(keys, jobs):
            self.entries[key]["job"] = job
            self._set_cell(key, self.COL_OUTPUT, str(job.output_dir))
            if job.skip_reason:
                self.counts["skipped"] += 1
                self._set_cell(key, self.COL_STATUS, f"{STATUS_SKIPPED}: {job.skip_reason}")
            else:
                self.queue.append(key)
                self._set_cell(key, self.COL_STATUS, STATUS_QUEUED)
        self._save_settings()
        self.running = True
        self.cancelling = False
        self.batch_started = time.perf_counter()
        self.progress.setRange(0, max(1, len(jobs)))
        self.progress.setValue(self.counts["skipped"])
        self.log(f"batch: {len(self.queue)} to convert, {self.counts['skipped']} skipped, "
                 f"{options.jobs} at a time" + ("; rendering PDF + PNG" if options.render else ""))
        self.runningChanged.emit(True)
        self._update_controls()
        self._pump()
        return True

    def _pump(self) -> None:
        """Start queued jobs up to the parallel limit; finish the batch when empty."""
        while self.queue and len(self.processes) < self.options.jobs and not self.cancelling:
            self._launch(self.queue.popleft())
        if not self.queue and not self.processes and self.running:
            self._finish_batch()
        self._update_status()

    def _launch(self, key: str) -> None:
        job = self.entries[key]["job"]
        command = core.report_command(job, self.options)
        process = QtCore.QProcess(self)
        environment = QtCore.QProcessEnvironment()
        for name, data in core.report_environment(self.options).items():
            environment.insert(name, data)
        process.setProcessEnvironment(environment)
        self.outputs[key] = (bytearray(), bytearray())
        process.readyReadStandardOutput.connect(lambda k=key, p=process: self._read(k, p))
        process.readyReadStandardError.connect(lambda k=key, p=process: self._read(k, p))
        process.finished.connect(lambda code, status, k=key, p=process: self._job_finished(k, p, code, status))
        process.errorOccurred.connect(lambda error, k=key, p=process: self._job_error(k, p, error))
        self.processes[key] = process
        self._set_cell(key, self.COL_STATUS, STATUS_RUNNING)
        self.log(f"start   {job.csv_path.name}  ->  {job.output_dir}")
        process.start(command[0], command[1:])

    def _read(self, key: str, process) -> None:
        buffers = self.outputs.get(key)
        if buffers is None:
            return
        buffers[0].extend(bytes(process.readAllStandardOutput()))
        buffers[1].extend(bytes(process.readAllStandardError()))
        for buffer in buffers:
            del buffer[:-OUTPUT_TAIL_BYTES]

    def _job_error(self, key: str, process, error) -> None:
        if error == QtCore.QProcess.FailedToStart and key in self.processes:
            buffers = self.outputs.setdefault(key, (bytearray(), bytearray()))
            buffers[1].extend(("cannot start Python: " + process.errorString()).encode("utf-8"))
            self._job_finished(key, process, -1, QtCore.QProcess.CrashExit)

    def _job_finished(self, key: str, process, exit_code: int, exit_status) -> None:
        if self.processes.pop(key, None) is None:
            return                                           # already handled
        self._read(key, process)
        stdout, stderr = (bytes(b).decode("utf-8", errors="replace") for b in self.outputs.pop(key))
        process.deleteLater()
        job = self.entries[key]["job"]
        if self.cancelling and exit_status != QtCore.QProcess.NormalExit:
            removed = core.cleanup_partial_output(job)
            self.counts["cancelled"] += 1
            self._set_cell(key, self.COL_STATUS, STATUS_CANCELLED)
            self.log(f"cancel  {job.csv_path.name}" + (" (unfinished folder removed)" if removed else ""))
        else:
            code = exit_code if exit_status == QtCore.QProcess.NormalExit else -1
            result = core.parse_report_output(code, stdout, stderr, str(job.output_dir))
            if result.ok:
                self.counts["done"] += 1
                text = f"{STATUS_DONE}: {result.pages} pages" + (f"; {result.message}" if result.message else "")
                self._set_cell(key, self.COL_STATUS, text)
                self.log(f"done    {job.csv_path.name}: {result.pages} pages"
                         + (f"; {result.message}" if result.message else ""))
            else:
                core.cleanup_partial_output(job)
                self.counts["failed"] += 1
                self._set_cell(key, self.COL_STATUS, f"{STATUS_FAILED}: {result.message}")
                self.log(f"FAILED  {job.csv_path.name}: {result.message}")
        self.progress.setValue(self.counts["done"] + self.counts["failed"] + self.counts["skipped"]
                               + self.counts["cancelled"])
        self._pump()
        self._update_controls()

    def _update_status(self) -> None:
        c = self.counts
        if self.running:
            self.status_label.setText(
                f"{c['done']} done, {c['failed']} failed, {c['skipped']} skipped of {c['total']}; "
                f"{len(self.processes)} running, {len(self.queue)} queued")

    def _finish_batch(self) -> None:
        c = self.counts
        for key in list(self.queue):
            self._set_cell(key, self.COL_STATUS, STATUS_CANCELLED)
            c["cancelled"] += 1
        self.queue.clear()
        elapsed = time.perf_counter() - self.batch_started
        self.running = False
        self.cancelling = False
        self.last_summary = (f"{c['done']} converted, {c['failed']} failed, {c['skipped']} skipped, "
                             f"{c['cancelled']} cancelled in {elapsed:.1f} s")
        self.status_label.setText(self.last_summary)
        self.log("batch finished: " + self.last_summary)
        self.progress.setValue(self.progress.maximum())
        self._fit_columns()
        self.runningChanged.emit(False)
        self._update_controls()
        if self.close_after_batch:
            QtCore.QTimer.singleShot(0, self.close)

    def cancel(self) -> None:
        """Stop the queue and end running report processes."""
        if not self.running or self.cancelling:
            return
        self.cancelling = True
        for key in list(self.queue):
            self._set_cell(key, self.COL_STATUS, STATUS_CANCELLED)
            self.counts["cancelled"] += 1
        self.queue.clear()
        self.log(f"cancelling: {len(self.processes)} running conversion(s) will be ended")
        for process in list(self.processes.values()):
            process.kill()
        self._update_controls()
        if not self.processes:
            self._finish_batch()

    def wait_for_idle(self, timeout_s: float = 600.0) -> bool:
        """Process events until the batch ends (scripts and tests)."""
        deadline = time.perf_counter() + timeout_s
        app = QtWidgets.QApplication.instance()
        while self.running and time.perf_counter() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            for process in list(self.processes.values()):
                process.waitForFinished(20)
        app.processEvents()
        return not self.running

    # ------------------------------------------------------------------ misc
    def open_selected_output(self) -> None:
        for key in self.selected_keys():
            folder = self._output_of(key)
            if folder:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))
                return

    def show_usage(self) -> None:
        text = (__doc__ or "").split("USAGE", 1)[-1].split("REVISION HISTORY", 1)[0]
        box = QtWidgets.QDialog(self)
        box.setWindowTitle(f"{APP_NAME} — usage")
        box.resize(760, 560)
        layout = QtWidgets.QVBoxLayout(box)
        view = QtWidgets.QPlainTextEdit("USAGE" + text)
        view.setReadOnly(True)
        view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        layout.addWidget(view)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(box.reject)
        layout.addWidget(buttons)
        _exec(box)

    def show_about(self) -> None:
        QtWidgets.QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME} {__version__}</b><br>"
            "Author / application owner: William W. Wallace<br>"
            "Company: NRAO/GBO<br>Email: wwallace@nrao.edu<br>"
            f"Batch core {core.__version__}; theme {theme_module.__version__}; "
            "reports by fsp_reports.py next to this file.<br>"
            "Part of the R&amp;S FSP Trace Logger bundle (AI-assisted, 2026-10-29).")

    def closeEvent(self, event):
        if self.running:
            if self.close_after_batch:
                event.ignore()
                return
            answer = QtWidgets.QMessageBox.question(
                self, APP_NAME, "Conversions are running. Cancel them and close?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if answer == QtWidgets.QMessageBox.Yes:
                self.close_after_batch = True
                self.cancel()
            event.ignore()
            return
        self._save_settings()
        event.accept()


# %% STAND-ALONE LAUNCHER
_OPEN_WINDOWS: List[BatchConvertDialog] = []   # keeps windows alive in Spyder
_OWNS_APPLICATION = False


def build_gui_parser():
    import argparse
    parser = argparse.ArgumentParser(
        prog="fsp_batch_convert.py",
        description=f"{APP_NAME}: logger CSV files -> Veusz plots. Without --cli a window opens "
                    "(optionally pre-filled with the given files/folders). "
                    "Use --cli for a run without a window (fsp_batch_convert.py --cli --help).")
    parser.add_argument("inputs", nargs="*", help="CSV files and/or folders to list at start")
    parser.add_argument("--theme", choices=[m for m, _ in theme_module.THEME_MODES],
                        help="override the stored theme for this window")
    parser.add_argument("--version", action="version",
                        version=f"{APP_NAME} {__version__} (batch core {core.__version__})")
    return parser


def main(argv=None) -> int:
    """Open the stand-alone window (or run --cli). Returns an exit status."""
    global _OWNS_APPLICATION
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--cli" in argv:
        return core.main([argument for argument in argv if argument != "--cli"])
    args = build_gui_parser().parse_args(argv)
    app = QtWidgets.QApplication.instance()
    _OWNS_APPLICATION = app is None
    if app is None:
        app = QtWidgets.QApplication(sys.argv[:1])
        app.setApplicationName(APP_NAME)
    window = BatchConvertDialog(None, standalone=True, theme_mode=args.theme, inputs=args.inputs)
    window.setAttribute(Qt.WA_DeleteOnClose, False)
    window.show()
    _OPEN_WINDOWS.append(window)
    if _OWNS_APPLICATION:
        return app.exec_() if hasattr(app, "exec_") else app.exec()
    return 0                                     # Spyder / IPython: its event loop runs it


if __name__ == "__main__":
    _status = main()
    if _OWNS_APPLICATION:
        sys.exit(_status)
