#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Tests of the batch CSV -> Veusz converter (core, command line, dialog, logger)
=============================================================================
 Filename       : tests/test_batch_convert.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-29
 Language       : Python 3.8 through 3.12
 Requires       : numpy, h5py (reports); qtpy + Qt binding and pyqtgraph for
                  the dialog/logger tests (skipped without them)
 Status         : SOFTWARE TESTS on synthetic logger CSVs (fsp_background's
                  own writer), not measurement data.

Run:  python -m unittest discover -s tests -v
"""

# %% IMPORTS
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fsp_background  # noqa: E402
import fsp_batch_core as core  # noqa: E402

try:
    import h5py  # noqa: F401
    HAVE_H5PY = True
except ImportError:  # pragma: no cover
    HAVE_H5PY = False

try:
    from qtpy import QtCore, QtWidgets  # noqa: E402
    import fsp_batch_convert as B  # noqa: E402
    import rs_fsp_logger as L  # noqa: E402
    QT_ERROR = ""
except Exception as error:  # pragma: no cover - environment dependent
    B = L = None
    QT_ERROR = f"{type(error).__name__}: {error}"

needs_qt = unittest.skipIf(B is None, "Qt/pyqtgraph not importable: " + QT_ERROR)
needs_h5py = unittest.skipUnless(HAVE_H5PY, "h5py needed to write reports")


# %% FIXTURES
def write_logger_csv(path: Path, traces=(1, 2), captures: int = 3, bins: int = 11) -> Path:
    """A small, valid logger CSV written by the logger's own CSV writer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frequencies = np.linspace(1.0e9, 2.0e9, bins)
    writer = fsp_background.AsyncCaptureCsvWriter(path, frequencies, traces)
    start = datetime(2026, 10, 29, 12, 0, 0)
    for index in range(captures):
        data = {n: -90.0 + 10.0 * n + np.sin(np.arange(bins) + index) for n in traces}
        writer.submit(start + timedelta(seconds=2 * index), data)
    writer.close()
    return path


def make_tree(root: Path) -> dict:
    """root/run1.csv, root/a/b/run2.csv, root/c/run1.csv + non-logger CSVs."""
    paths = dict(top=write_logger_csv(root / "run1.csv"),
                 deep=write_logger_csv(root / "a" / "b" / "run2.csv", traces=(1, 2, 3)),
                 same_name=write_logger_csv(root / "c" / "run1.csv", traces=(2,)))
    (root / "run1_events.csv").write_text("timestamp_iso,event,screen,trace,original_mode,"
                                          "restored_mode,ok,note\n", encoding="utf-8")
    (root / "a" / "notes.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    hidden = root / ".run9_reports_20260101_000000.abc"
    hidden.mkdir()
    write_logger_csv(hidden / "staged.csv")
    return paths


# %% CORE
class CheckAndDiscoveryTests(unittest.TestCase):

    def setUp(self):
        self.folder_object = tempfile.TemporaryDirectory()
        self.root = Path(self.folder_object.name)

    def tearDown(self):
        self.folder_object.cleanup()

    def test_logger_header_recognised(self):
        check = core.check_logger_csv(write_logger_csv(self.root / "x.csv", traces=(1, 3)))
        self.assertTrue(check.is_logger_csv)
        self.assertEqual(check.traces, (1, 3))

    def test_byte_order_mark_accepted(self):
        path = self.root / "bom.csv"
        path.write_text("﻿date,time,timestamp_iso,freq_hz,trace1_dBm\n", encoding="utf-8")
        self.assertTrue(core.check_logger_csv(path).is_logger_csv)

    def test_other_csvs_rejected(self):
        cases = {"events.csv": "timestamp_iso,event,screen,trace\n",
                 "dup.csv": "date,time,timestamp_iso,freq_hz,trace1_dBm,trace1_dBm\n",
                 "extra.csv": "date,time,timestamp_iso,freq_hz,trace1_dBm,comment\n",
                 "notrace.csv": "date,time,timestamp_iso,freq_hz\n",
                 "empty.csv": ""}
        for name, text in cases.items():
            path = self.root / name
            path.write_text(text, encoding="utf-8")
            self.assertFalse(core.check_logger_csv(path).is_logger_csv, name)

    def test_folder_scan_recursive_and_flat(self):
        paths = make_tree(self.root)
        found, skipped = core.expand_inputs([self.root], recursive=True)
        self.assertEqual(sorted(p for p, _ in found),
                         sorted(p.resolve() for p in paths.values()))
        self.assertTrue(all(base == self.root.resolve() for _, base in found))
        self.assertEqual(sorted(c.path.name for c in skipped), ["notes.csv", "run1_events.csv"])
        flat, _ = core.expand_inputs([self.root], recursive=False)
        self.assertEqual([p.name for p, _ in flat], ["run1.csv"])

    def test_duplicates_and_missing(self):
        paths = make_tree(self.root)
        found, skipped = core.expand_inputs([paths["top"], self.root, paths["top"],
                                             self.root / "missing.csv"])
        self.assertEqual(len(found), 3)
        self.assertIsNone(found[0][1], "a file added on its own has no scanned folder")
        self.assertIn("not found", [c.reason for c in skipped])


class PlanningTests(unittest.TestCase):

    def setUp(self):
        self.folder_object = tempfile.TemporaryDirectory()
        self.root = Path(self.folder_object.name)
        self.paths = make_tree(self.root / "in")
        self.found, _ = core.expand_inputs([self.root / "in"])

    def tearDown(self):
        self.folder_object.cleanup()

    def names(self, jobs):
        return sorted(str(j.output_dir.relative_to(self.root)) for j in jobs)

    def test_beside_each_csv(self):
        jobs = core.plan_jobs(self.found, core.BatchOptions(), stamp="S")
        self.assertEqual(self.names(jobs), sorted([os.path.join("in", "run1_reports_S"),
                                                   os.path.join("in", "a", "b", "run2_reports_S"),
                                                   os.path.join("in", "c", "run1_reports_S")]))

    def test_one_folder_mirrored(self):
        options = core.BatchOptions(output_mode="folder", output_root=str(self.root / "out"))
        jobs = core.plan_jobs(self.found, options, stamp="S")
        self.assertEqual(self.names(jobs), sorted([os.path.join("out", "run1_reports_S"),
                                                   os.path.join("out", "a", "b", "run2_reports_S"),
                                                   os.path.join("out", "c", "run1_reports_S")]))

    def test_one_folder_flat_makes_names_unique(self):
        options = core.BatchOptions(output_mode="folder", output_root=str(self.root / "out"),
                                    mirror_subfolders=False)
        jobs = core.plan_jobs(self.found, options, stamp="S")
        self.assertEqual(self.names(jobs), sorted([os.path.join("out", "run1_reports_S"),
                                                   os.path.join("out", "run1_reports_S_2"),
                                                   os.path.join("out", "run2_reports_S")]))

    def test_existing_folder_never_reused(self):
        (self.root / "in" / "run1_reports_S").mkdir()
        jobs = core.plan_jobs([(self.paths["top"].resolve(), None)], core.BatchOptions(), stamp="S")
        self.assertEqual(jobs[0].output_dir.name, "run1_reports_S_2")

    def test_skip_existing(self):
        done = self.root / "in" / "run1_reports_20200101_000000"
        done.mkdir()
        (done / "report.json").write_text("{}", encoding="utf-8")
        jobs = core.plan_jobs([(self.paths["top"].resolve(), None), (self.paths["deep"].resolve(), None)],
                              core.BatchOptions(skip_existing=True), stamp="S")
        self.assertIn("already reported", jobs[0].skip_reason)
        self.assertEqual(jobs[1].skip_reason, "")

    def test_options_validated(self):
        for options in (core.BatchOptions(output_mode="folder", output_root=""),
                        core.BatchOptions(jobs=0), core.BatchOptions(output_mode="x")):
            with self.assertRaises(ValueError):
                core.plan_jobs(self.found, options)


class ProcessHelperTests(unittest.TestCase):

    def test_command_and_environment(self):
        job = core.BatchJob(Path("a.csv"), Path("a_reports_S"))
        options = core.BatchOptions(render=True, veusz_exe="/opt/veusz", max_matrix_mib=64)
        command = core.report_command(job, options)
        self.assertEqual(command[1], str(core.REPORT_SCRIPT))
        self.assertEqual(command[2:], ["--csv", "a.csv", "--output-dir", "a_reports_S",
                                       "--max-matrix-mib", "64", "--render"])
        environment = core.report_environment(options, base={"PATH": "x"})
        self.assertEqual(environment["OMP_NUM_THREADS"], "1")
        self.assertEqual(environment["VEUSZ_EXE"], "/opt/veusz")
        self.assertEqual(environment["PATH"], "x")

    def test_parse_output(self):
        ok = core.parse_report_output(0, 'noise\n{"status": "completed", "output_directory": "/r", '
                                         '"pages": 15, "rendering": {"status": "not_requested"}}\n', "")
        self.assertTrue(ok.ok)
        self.assertEqual((ok.pages, ok.rendering, ok.message), (15, "not_requested", ""))
        unrendered = core.parse_report_output(0, json.dumps(dict(pages=3, rendering=dict(
            status="unavailable_or_failed", error="Veusz not found"))), "")
        self.assertIn("Veusz not found", unrendered.message)
        failed = core.parse_report_output(1, "", "Traceback\nReport generation failed: bad grid\n")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.message, "Report generation failed: bad grid")

    def test_cleanup_only_this_jobs_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            job = core.BatchJob(root / "x.csv", root / "x_reports_S")
            mine = root / ".x_reports_S.k3j2"
            other = root / ".x_reports_S_2.k3j2"
            for path in (mine, other):
                path.mkdir()
            self.assertEqual(core.cleanup_partial_output(job), [mine])
            self.assertTrue(other.exists())
            mine.mkdir()
            job.output_dir.mkdir()                     # finished: nothing is removed
            self.assertEqual(core.cleanup_partial_output(job), [])
            self.assertTrue(mine.exists())


@needs_h5py
class CommandLineTests(unittest.TestCase):

    def setUp(self):
        self.folder_object = tempfile.TemporaryDirectory()
        self.root = Path(self.folder_object.name)
        self.paths = make_tree(self.root / "in")

    def tearDown(self):
        self.folder_object.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(HERE / "fsp_batch_convert.py"), "--cli", *args],
                              capture_output=True, text=True, timeout=600,
                              env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))

    def test_convert_folder_then_skip_existing(self):
        out = self.root / "out"
        first = self.run_cli(str(self.root / "in"), "--output-dir", str(out), "--jobs", "2")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        summary = json.loads(first.stdout.strip().splitlines()[-1])
        self.assertEqual(summary, dict(converted=3, failed=0, skipped=0, cancelled=0))
        reports = sorted(str(p.relative_to(out).parent.parent) for p in out.rglob("report.json"))
        self.assertEqual(reports, [".", os.path.join("a", "b"), "c"])
        for report in out.rglob("report.json"):
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["logger_version"], "0.10.0")
            self.assertTrue((report.parent / "fsp_report.vszh5").is_file())
        second = self.run_cli(str(self.root / "in"), "--output-dir", str(out), "--skip-existing")
        self.assertEqual(json.loads(second.stdout.strip().splitlines()[-1])["skipped"], 3)

    def test_dry_run_and_nothing_found(self):
        dry = self.run_cli(str(self.root / "in"), "--dry-run")
        self.assertEqual(dry.returncode, 0)
        self.assertEqual(sum(line.startswith("plan") for line in dry.stdout.splitlines()), 3)
        self.assertFalse(list((self.root / "in").rglob("report.json")))
        empty = self.root / "empty"
        empty.mkdir()
        self.assertEqual(self.run_cli(str(empty)).returncode, 2)

    @unittest.skipIf(os.name == "nt", "POSIX signal")
    def test_ctrl_c_stops_running_jobs_at_once(self):
        import signal
        slow = self.root / "slow_report.py"
        slow.write_text(textwrap.dedent('''
            import sys, time, pathlib
            out = pathlib.Path(sys.argv[sys.argv.index("--output-dir") + 1])
            (out.parent / ("." + out.name + ".tmp1")).mkdir(parents=True)
            time.sleep(120)
        '''), encoding="utf-8")
        code = ("import sys, pathlib; sys.path.insert(0, sys.argv[1]); import fsp_batch_core as c; "
                "c.REPORT_SCRIPT = pathlib.Path(sys.argv[2]); sys.exit(c.main(sys.argv[3:]))")
        out = self.root / "out"
        process = subprocess.Popen([sys.executable, "-c", code, str(HERE), str(slow), str(self.root / "in"),
                                    "--output-dir", str(out), "--jobs", "2"],
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        deadline = time.time() + 30
        while time.time() < deadline and len(list(out.rglob(".*.tmp1"))) < 2:
            time.sleep(0.05)
        started = time.time()
        process.send_signal(signal.SIGINT)
        text = process.communicate(timeout=60)[0]
        self.assertLess(time.time() - started, 15, "must not wait for the running conversions")
        self.assertEqual(process.returncode, 1, text)
        self.assertIn("Interrupted", text)
        self.assertEqual(list(out.rglob(".*.tmp1")), [])

    def test_failed_csv_reported_and_cleaned(self):
        bad = self.root / "bad" / "broken.csv"
        bad.parent.mkdir()
        bad.write_text("date,time,timestamp_iso,freq_hz,trace1_dBm\n2026-10-29,12:00:00,"
                       "2026-10-29T12:00:00,2.0,-50\n2026-10-29,12:00:00,2026-10-29T12:00:00,1.0,-50\n",
                       encoding="utf-8")
        result = self.run_cli(str(bad.parent))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("FAIL", result.stdout)
        self.assertEqual([p.name for p in bad.parent.iterdir()], ["broken.csv"],
                         "no report or staging folder may remain")


# %% DIALOG AND LOGGER
@needs_qt
@needs_h5py
class DialogTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._config = tempfile.TemporaryDirectory()
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, QtCore.QSettings.UserScope, cls._config.name)
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls._config.cleanup()

    def setUp(self):
        self.folder_object = tempfile.TemporaryDirectory()
        self.root = Path(self.folder_object.name)
        self.paths = make_tree(self.root / "in")
        # each test starts from the dialog defaults, not the previous test's choices
        B.theme_module.shared_settings().remove(B.SETTINGS_GROUP)
        self.dialogs = []

    def tearDown(self):
        for dialog in self.dialogs:            # never leave a batch running behind a test
            if dialog.running:
                dialog.cancel()
                dialog.wait_for_idle(30)
            dialog.close()
        self.folder_object.cleanup()

    def make_dialog(self, *args, **kwargs):
        dialog = B.BatchConvertDialog(*args, **kwargs)
        self.dialogs.append(dialog)
        return dialog

    def pump(self, predicate, seconds=60.0):
        deadline = time.time() + seconds
        while not predicate() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        return predicate()

    def test_folder_and_single_file_in_one_batch(self):
        dialog = self.make_dialog(None, standalone=True, theme_mode="dark")
        try:
            loose = write_logger_csv(self.root / "loose" / "single.csv")
            dialog.add_inputs([str(self.root / "in"), str(loose)])
            self.assertEqual(dialog.table.rowCount(), 4)
            self.assertIn("2 other file(s) skipped", dialog.log_view.toPlainText())
            dialog.folder_radio.setChecked(True)
            dialog.output_edit.setText(str(self.root / "out"))
            dialog.jobs_spin.setValue(2)
            self.assertTrue(dialog.start())
            self.assertFalse(dialog.add_files_btn.isEnabled(), "inputs locked while running")
            self.assertTrue(dialog.wait_for_idle(300))
            statuses = [dialog.table.item(r, dialog.COL_STATUS).text() for r in range(4)]
            self.assertTrue(all(s.startswith("Done") for s in statuses), statuses)
            self.assertEqual(len(list((self.root / "out").rglob("report.json"))), 4)
            # a file added on its own has no scanned folder: its report sits at the top
            self.assertTrue(any(p.name.startswith("single_reports_") for p in (self.root / "out").iterdir()))
            self.assertFalse(dialog.start_btn.isEnabled(), "every row Done: nothing left to convert")
            self.assertEqual(dialog.palette().color(dialog.backgroundRole()).name(), "#24272e")
        finally:
            dialog.close()

    def test_cancel_kills_and_removes_staging(self):
        slow = self.root / "slow_report.py"
        slow.write_text(textwrap.dedent('''
            import sys, time, pathlib
            out = pathlib.Path(sys.argv[sys.argv.index("--output-dir") + 1])
            staging = out.parent / ("." + out.name + ".tmp1")
            staging.mkdir(parents=True)
            print("staging", staging, flush=True)
            time.sleep(60)
        '''), encoding="utf-8")
        original = core.REPORT_SCRIPT
        core.REPORT_SCRIPT = slow
        dialog = self.make_dialog(None, standalone=True)
        try:
            dialog.add_inputs([str(self.root / "in")])
            self.assertTrue(dialog.beside_radio.isChecked(), "default: next to each CSV")
            dialog.jobs_spin.setValue(1)
            self.assertTrue(dialog.start())
            self.assertTrue(self.pump(lambda: any(p.name.startswith(".") for p in
                                                  (self.root / "in" / "a" / "b").iterdir()), 30))
            dialog.cancel()
            self.assertTrue(dialog.wait_for_idle(30))
            statuses = [dialog.table.item(r, dialog.COL_STATUS).text() for r in range(3)]
            self.assertEqual(statuses, ["Cancelled"] * 3)
            # the slow stand-in stages in ".<report folder>.tmp1" as fsp_reports does
            self.assertFalse([p for p in (self.root / "in").rglob(".*_reports_*.tmp1")])
            self.assertIn("0 converted, 0 failed, 0 skipped, 3 cancelled", dialog.last_summary)
        finally:
            core.REPORT_SCRIPT = original
            dialog.close()

    def test_blocked_dialog_does_not_start(self):
        dialog = self.make_dialog(None)
        try:
            dialog.add_inputs([str(self.paths["top"])])
            dialog.set_blocked("The logger is sampling")
            self.assertFalse(dialog.start_btn.isEnabled())
            self.assertFalse(dialog.start())
            dialog.set_blocked("")
            self.assertTrue(dialog.start_btn.isEnabled())
        finally:
            dialog.close()

    def test_standalone_launcher(self):
        count = len(B._OPEN_WINDOWS)
        self.assertEqual(B.main([str(self.paths["top"]), "--theme", "light"]), 0)
        window = B._OPEN_WINDOWS[-1]
        self.assertEqual(len(B._OPEN_WINDOWS), count + 1)
        self.assertTrue(window.standalone and window.isVisible())
        self.assertEqual(window.table.rowCount(), 1)
        self.assertEqual(window.theme_mode, "light")
        window.close()
        self.assertEqual(B.main(["--cli", "--dry-run", str(self.root / "in")]), 0)

    def test_theme_choice_stored_when_standalone(self):
        dialog = self.make_dialog(None, standalone=True, theme_mode="light")
        try:
            dialog.choose_theme("dark")
            self.assertEqual(dialog.theme_mode, "dark")
            self.assertEqual(str(dialog.settings.value("theme")), "dark")
            self.assertTrue(dialog.theme_actions["dark"].isChecked())
        finally:
            dialog.close()

    def test_logger_menu_opens_themed_dialog_with_interlocks(self):
        win = L.MainWindow()
        try:
            win.apply_theme("light", persist=False)
            # keep references: PySide6 may collect chained temporary wrappers
            menus = {m.title(): m for m in win.menuBar().findChildren(QtWidgets.QMenu)}
            file_actions = menus["&File"].actions()
            tools_actions = menus["&Tools"].actions()
            menu_texts = [a.text() for a in file_actions]
            self.assertIn("Batch convert CSV files to Veusz plots…", [a.text() for a in tools_actions])
            self.assertIn("Batch convert CSV files to Veusz plots…", menu_texts)
            win.batch_action.trigger()
            dialog = win.batch_dialog
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(dialog.theme_mode, "light")
            win.apply_theme("dark", persist=False)                    # logger -> dialog
            self.assertEqual(dialog.theme_mode, "dark")
            dialog.choose_theme("light")                              # dialog -> logger
            self.assertEqual(win.theme_mode, "light")
            # sampling blocks the batch ...
            win.thread = object()
            win._update_report_availability()
            self.assertTrue(dialog.blocked_reason)
            win.thread = None
            win._update_report_availability()
            self.assertEqual(dialog.blocked_reason, "")
            # ... and a running batch blocks sampling
            win.demo_check.setChecked(True)
            win.on_connect()
            dialog.add_inputs([str(self.paths["top"])])
            self.assertTrue(dialog.start())
            win._update_report_availability()
            self.assertFalse(win.start_manual_btn.isEnabled())
            self.assertTrue(dialog.wait_for_idle(300))
            win._update_report_availability()
            self.assertTrue(win.start_manual_btn.isEnabled())
            self.assertEqual(win.sibling_module_version("fsp_batch_convert.py"), B.__version__)
        finally:
            if win.batch_dialog is not None:
                win.batch_dialog.close()
            win.on_disconnect()
            win.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
