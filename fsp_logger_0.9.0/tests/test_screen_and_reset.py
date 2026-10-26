#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Regression tests for logger bundle 0.9.0: screen routing and trace reset
========================================================================
 Filename       : tests/test_screen_and_reset.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-26
 Language       : Python 3.8 through 3.12
 Requires       : numpy, qtpy + a Qt binding, pyqtgraph (the logger module
                  imports them); skipped when they are missing.
 Status         : SOFTWARE TESTS against fsp_simulator - synthetic data, not
                  hardware validation.

The real FSPInstrument, AcquisitionWorker and MainWindow are run against
fsp_simulator.SimulatedFSPSession. Each defect test fails on 0.8.3 (see the
"0.8.3:" notes) and passes on 0.9.0.

Run:  python -m unittest discover -s tests -v
"""

# %% IMPORTS
from __future__ import annotations

import csv
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest import mock
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fsp_simulator import SimulatedFSPSession, SimulatedScreen  # noqa: E402

try:                                    # the logger needs Qt + pyqtgraph
    import rs_fsp_logger as L           # noqa: E402
    _LOGGER_IMPORT_ERROR = ""
except Exception as error:              # pragma: no cover - environment dependent
    L = None
    _LOGGER_IMPORT_ERROR = f"{type(error).__name__}: {error}"

needs_logger = unittest.skipIf(L is None, "logger not importable: " + _LOGGER_IMPORT_ERROR)


# %% FIXTURES
def two_screens(a_modes=None, b_modes=None, b_center_high=True):
    """Screen A near start-up defaults, Screen B the user's configuration."""
    a = SimulatedScreen(9e3, 2e6, 501, 0.1, 1,
                        modes=a_modes or {1: "WRIT", 2: "BLAN", 3: "BLAN"})
    if b_center_high:
        b = SimulatedScreen(13.0e9, 14.8e9, 801, 0.1, 1,
                            modes=b_modes or {1: "WRIT", 2: "MAXH", 3: "AVER"})
    else:
        b = SimulatedScreen(100e3, 300e3, 801, 0.1, 1,
                            modes=b_modes or {1: "WRIT", 2: "MAXH", 3: "AVER"})
    return {1: a, 2: b}


def instrument(screens=None, **session_kwargs):
    session = SimulatedFSPSession(screens or two_screens(), time_scale=0.0, **session_kwargs)
    return L.FSPInstrument("SIM::FSP", session=session), session


def mode_writes(session):
    return [c for c in session.command_log if ":MODE " in c]


# %% SCREEN ROUTING (instrument layer)
@needs_logger
class ScreenRoutingTests(unittest.TestCase):

    def test_auto_reads_trace_modes_from_detected_screen(self):
        # 0.8.3: [1] (Screen A's modes via DISP:TRAC<n>:MODE?) while data came from B.
        inst, session = instrument()
        inst.sweep_settings()
        self.assertEqual(inst.active_screen, 2)
        self.assertEqual(inst.active_traces(), [1, 2, 3])
        queries = [c for c in session.command_log if c.endswith(":MODE?")]
        self.assertTrue(queries and all(c.startswith("DISP:WIND2:") for c in queries), queries)

    def test_forced_screen_a_reads_screen_a(self):
        inst, _session = instrument()
        inst.set_screen_mode("A")
        self.assertEqual(inst.active_traces(), [1])
        self.assertEqual(inst.sweep_settings()["n_pts"], 501)

    def test_choice_applied_before_first_query(self):
        # 0.8.3: a new connection always started in Auto (no set_screen_mode).
        inst, session = instrument(two_screens(b_center_high=False))
        inst.set_screen_mode("B")
        settings = inst.sweep_settings()
        self.assertEqual(settings["active_screen"], 2)
        self.assertEqual(settings["screen_mode"], 2)
        self.assertFalse([c for c in session.command_log if c.startswith("FREQ:")],
                         "a forced screen must not run auto-detection on Screen A")
        self.assertEqual(inst.active_traces(), [1, 2, 3])

    def test_auto_redetects_only_when_refreshed(self):
        # 0.8.3: detection ran once per connection; a front-panel change was ignored.
        screens = two_screens(b_center_high=False)
        inst, session = instrument(screens)
        inst.sweep_settings()
        self.assertEqual(inst.active_screen, 1)
        screens[2].f_start, screens[2].f_stop = 13.0e9, 14.8e9      # user reconfigures B
        inst.sweep_settings()
        self.assertEqual(inst.active_screen, 1, "must not switch between captures")
        inst.refresh_screen_selection()
        inst.sweep_settings()
        self.assertEqual(inst.active_screen, 2)
        inst.set_screen_mode("A")
        inst.refresh_screen_selection()                              # forced: unchanged
        inst.sweep_settings()
        self.assertEqual(inst.active_screen, 1)

    def test_fetch_template_is_per_screen(self):
        # 0.8.3: a template cached on Screen A was reused after a change to B.
        inst, _session = instrument()
        inst.set_screen_mode("A")
        self.assertEqual(inst.fetch_trace(1).size, 501)
        inst.set_screen_mode("auto")
        inst.sweep_settings()                                        # detects B
        self.assertEqual(inst.fetch_trace(1).size, 801)
        self.assertEqual(inst._trace_fetch_templates[1], "TRAC? TRACE{n}")
        self.assertEqual(inst._trace_fetch_templates[2], "TRAC2? TRACE{n}")

    def test_fetch_never_falls_back_to_other_screen(self):
        # 0.8.3: TRAC2? failing fell through to TRAC? TRACE<n> = Screen A data.
        class NoTrac2(SimulatedFSPSession):
            def _dispatch(self, command, is_query):
                if command.lstrip(":").upper().startswith("TRAC2"):
                    self.command_log.append(command)
                    self._push_error(-100, "Command error")
                    raise L.FSPError("VI_ERROR_TMO simulated")
                return super()._dispatch(command, is_query)
        session = NoTrac2(two_screens(), time_scale=0.0)
        inst = L.FSPInstrument("SIM", session=session)
        inst.set_screen_mode("B")
        with self.assertRaises(L.FSPError):
            inst.fetch_trace(1)
        fetches = [c for c in session.command_log if "TRACE1" in c]
        self.assertTrue(fetches and all(c.lstrip(":").upper().startswith("TRAC2") for c in fetches), fetches)

    def test_screen_a_window_form_survives_deviating_unsuffixed_routing(self):
        # A firmware routing bare headers to B cannot mislead the WIND1 queries.
        inst, _session = instrument(unsuffixed_screen=2)
        inst.set_screen_mode("A")
        self.assertEqual(inst.active_traces(), [1])

    def test_unreadable_modes_raise_instead_of_reporting_none(self):
        class Mute(SimulatedFSPSession):
            def _dispatch(self, command, is_query):
                if ":TRAC" in command.upper() and command.upper().startswith("DISP"):
                    self.command_log.append(command)
                    raise L.FSPError("VI_ERROR_TMO simulated")
                return super()._dispatch(command, is_query)
        inst = L.FSPInstrument("SIM", session=Mute(two_screens(), time_scale=0.0))
        inst.set_screen_mode("B")
        with self.assertRaises(L.FSPError):
            inst.active_traces()

    def test_normalize_mode(self):
        n = L.FSPInstrument.normalize_mode
        self.assertEqual([n("MAXHOLD"), n('"WRIT"'), n("blank"), n(""), n("RMS")],
                         ["MAXH", "WRIT", "BLAN", None, "RMS"])


# %% TRACE RESET (instrument layer)
@needs_logger
class TraceResetTests(unittest.TestCase):

    def test_reset_goes_through_clear_write_and_restores_each_mode(self):
        inst, session = instrument()
        inst.sweep_settings()
        results = inst.reset_active_traces()
        self.assertEqual([(r["trace"], r["original"], r["restored"], r["ok"]) for r in results],
                         [(1, "WRIT", "WRIT", True), (2, "MAXH", "MAXH", True), (3, "AVER", "AVER", True)])
        self.assertEqual(mode_writes(session), [
            "DISP:WIND2:TRAC1:MODE WRIT", "DISP:WIND2:TRAC2:MODE WRIT", "DISP:WIND2:TRAC3:MODE WRIT",
            "DISP:WIND2:TRAC2:MODE MAXH", "DISP:WIND2:TRAC3:MODE AVER"])
        self.assertEqual(session.screens[2].modes, {1: "WRIT", 2: "MAXH", 3: "AVER"})
        self.assertEqual(session.screens[1].modes, {1: "WRIT", 2: "BLAN", 3: "BLAN"},
                         "the other screen must be untouched")

    def test_reset_restarts_max_hold(self):
        inst, session = instrument()
        inst.sweep_settings()
        for _ in range(12):
            session.query("*OPC?")
        held = inst.fetch_trace(2) - inst.fetch_trace(1)
        self.assertGreater(held.max(), 1.0, "max hold should sit above clear/write before reset")
        inst.reset_active_traces()
        session.query("*OPC?")
        np.testing.assert_allclose(inst.fetch_trace(2), inst.fetch_trace(1))

    def test_blank_traces_untouched(self):
        inst, session = instrument(two_screens(b_modes={1: "BLAN", 2: "MAXH", 3: "BLAN"}))
        results = inst.reset_active_traces()
        self.assertEqual([r["trace"] for r in results], [2])
        self.assertFalse([c for c in mode_writes(session) if "TRAC1" in c or "TRAC3" in c])

    def test_view_trace_refrozen_after_a_fresh_sweep(self):
        inst, session = instrument(two_screens(b_modes={1: "WRIT", 2: "BLAN", 3: "VIEW"}))
        inst.sweep_settings()
        frozen = inst.fetch_trace(3).copy()
        for _ in range(3):
            session.query("*OPC?")
        np.testing.assert_array_equal(inst.fetch_trace(3), frozen)
        results = inst.reset_active_traces(view_settle_s=0.0)
        self.assertTrue(all(r["ok"] for r in results))
        log = list(session.command_log)
        i_writ = log.index("DISP:WIND2:TRAC3:MODE WRIT")
        i_view = log.index("DISP:WIND2:TRAC3:MODE VIEW")
        self.assertIn("*OPC?", log[i_writ:i_view], "a sweep boundary must precede re-freezing")
        self.assertFalse(np.array_equal(inst.fetch_trace(3), frozen))
        session.query("*OPC?")
        refrozen = inst.fetch_trace(3).copy()
        session.query("*OPC?")
        np.testing.assert_array_equal(inst.fetch_trace(3), refrozen)

    def test_reset_raises_when_nothing_readable(self):
        class Mute(SimulatedFSPSession):
            def _dispatch(self, command, is_query):
                if ":MODE" in command.upper() or ":STAT" in command.upper():
                    self.command_log.append(command)
                    raise L.FSPError("VI_ERROR_TMO simulated")
                return super()._dispatch(command, is_query)
        session = Mute(two_screens(), time_scale=0.0)
        inst = L.FSPInstrument("SIM", session=session)
        with self.assertRaises(L.FSPError):
            inst.reset_active_traces()
        self.assertFalse(mode_writes(session), "nothing may be written when modes are unknown")

    def test_summary_text(self):
        text = L.MainWindow.format_reset_summary([
            dict(trace=1, screen="B", original="WRIT", restored="WRIT", ok=True, note=""),
            dict(trace=2, screen="B", original="MAXH", restored="MAXH", ok=True, note="")])
        self.assertEqual(text, "Screen B: T1 WRIT ok; T2 MAXH->WRIT->MAXH ok")


# %% RESET WHILE RECORDING (worker owns the session)
@needs_logger
class RecordingResetTests(unittest.TestCase):

    def test_reset_served_between_captures_and_logged(self):
        inst, session = instrument()
        with tempfile.TemporaryDirectory() as folder:
            csv_path = Path(folder) / "run.csv"
            worker = L.AcquisitionWorker(inst, L.RunConfig(interval_s=0.05, filename=str(csv_path)))
            finished, resets = [], []
            # Direct connections: no Qt event loop runs in this test, and the
            # signals are emitted from the worker's thread.
            worker.traceResetFinished.connect(resets.append, L.Qt.DirectConnection)
            worker.finished.connect(lambda: finished.append(True), L.Qt.DirectConnection)
            thread = threading.Thread(target=worker.run, daemon=True)
            thread.start()
            deadline = time.time() + 10
            while session.sweeps_completed < 4 and time.time() < deadline:
                time.sleep(0.01)
            worker.request_trace_reset()                       # from another thread
            while not resets and time.time() < deadline:
                time.sleep(0.01)
            time.sleep(0.15)
            worker.stop()
            thread.join(10)
            self.assertTrue(finished)
            self.assertEqual(len(resets), 1)
            self.assertTrue(all(r["ok"] for r in resets[0]), resets)
            self.assertEqual(session.concurrency_violations, 0)
            with open(Path(folder) / "run_events.csv", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([(r["event"], r["trace"], r["original_mode"]) for r in rows],
                             [("trace_reset", "1", "WRIT"), ("trace_reset", "2", "MAXH"),
                              ("trace_reset", "3", "AVER")])
            with open(csv_path, newline="") as stream:
                header = next(csv.reader(stream))
            self.assertEqual(header[-3:], ["trace1_dBm", "trace2_dBm", "trace3_dBm"])


# %% GUI (offscreen)
@needs_logger
class GuiTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._config = tempfile.TemporaryDirectory()
        L.QtCore.QSettings.setDefaultFormat(L.QtCore.QSettings.IniFormat)
        L.QtCore.QSettings.setPath(L.QtCore.QSettings.IniFormat, L.QtCore.QSettings.UserScope,
                                   cls._config.name)
        cls.app = L.QtWidgets.QApplication.instance() or L.QtWidgets.QApplication([])

    @classmethod
    def tearDownClass(cls):
        cls._config.cleanup()

    def make_window(self):
        win = L.MainWindow()
        win.settings.setValue("confirm_trace_reset", False)
        win.demo_check.setChecked(True)
        return win

    def pump_until(self, predicate, seconds=10.0):
        deadline = time.time() + seconds
        while not predicate() and time.time() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()
        return predicate()

    def test_screen_choice_before_connect_is_applied(self):
        # 0.8.3: B shown, Auto used until the buttons were toggled.
        win = self.make_window()
        try:
            win.screen_b_rb.setChecked(True)
            win.on_connect()
            self.assertEqual(win.instrument.active_screen, 2)
            self.assertEqual(win.screen_in_use_label.text(), "In use: Screen B (forced)")
            self.assertEqual(win._active_traces, [1, 3])                 # demo Screen B
            self.assertTrue(win.led_t3.isOn() and not win.led_t2.isOn())
            win.screen_auto_rb.setChecked(True)                          # one click, no toggling
            self.assertEqual(win.instrument.active_screen, 1)
            self.assertEqual(win._active_traces, [1, 2])                 # demo Screen A
            self.assertIn("Max Hold", win.led_t2.toolTip())
        finally:
            win.on_disconnect()
            win.close()

    def test_idle_reset_runs_in_worker_and_restores(self):
        win = self.make_window()
        try:
            win.on_connect()
            win.instrument.inst.time_scale = 0.0
            win.on_reset_traces()
            self.assertIsNotNone(win.reset_thread)
            self.assertFalse(win.probe_btn.isEnabled(), "VISA controls locked during reset")
            self.assertTrue(self.pump_until(lambda: win.reset_thread is None))
            self.assertEqual(win.last_trace_reset_summary,
                             "Screen A: T1 WRIT ok; T2 MAXH->WRIT->MAXH ok")
            self.assertTrue(win.probe_btn.isEnabled() and win.reset_traces_btn.isEnabled())
            self.assertEqual(win.instrument.inst.concurrency_violations, 0)
        finally:
            win.on_disconnect()
            win.close()

    def test_reset_during_recording(self):
        win = self.make_window()
        with tempfile.TemporaryDirectory() as folder:
            try:
                win.file_edit.setText(str(Path(folder) / "rec.csv"))
                win.on_connect()
                win.instrument.inst.time_scale = 0.05
                win.interval_spin.setValue(1.2)
                win.on_start(scheduled=False)
                self.assertTrue(self.pump_until(lambda: win.instrument.inst.sweeps_completed >= 3, 15))
                win.on_reset_traces()
                self.assertTrue(win._reset_pending)
                self.assertTrue(self.pump_until(lambda: not win._reset_pending, 15))
                self.assertIn("T2 MAXH->WRIT->MAXH ok", win.last_trace_reset_summary)
                win.on_stop()
                self.assertTrue(self.pump_until(lambda: win.thread is None, 20))
                self.assertTrue((Path(folder) / "rec_events.csv").is_file())
                self.assertEqual(win.instrument.inst.concurrency_violations, 0)
            finally:
                if win.thread is None:
                    win.on_disconnect()
                win.close()

    def test_diagnostics_compares_both_screens(self):
        win = self.make_window()
        try:
            win.on_connect()
            with mock.patch.object(L.QtWidgets.QDialog, "exec_", lambda self: 0, create=True), \
                    mock.patch.object(L.QtWidgets.QDialog, "exec", lambda self: 0, create=True):
                win.on_diagnostics()
            text = win.last_diagnostics_text
            self.assertIn("DEMO MODE: simulated FSP session", text)
            self.assertIn("Screen A (1)", text)
            self.assertIn("Screen B (2)", text)
            self.assertIn("trace 2 MODE   MAXH DISPLAYED", text)
            self.assertIn("Mode queries: Screen A via DISP:WIND1:TRAC<n>, Screen B via DISP:WIND2:TRAC<n>", text)
            self.assertIn("Parsed active traces (Screen A (auto)): [1, 2]", text)
            self.assertTrue(win.diag_btn.isEnabled())
        finally:
            win.on_disconnect()
            win.close()

    def test_confirmation_prompt_and_do_not_ask_again(self):
        win = self.make_window()
        try:
            win.on_connect()
            win.settings.setValue("confirm_trace_reset", True)
            answers = []

            def fake_exec(box):
                answers.append(box.text())
                box.checkBox().setChecked(True)
                return L.QtWidgets.QMessageBox.Yes
            with mock.patch.object(L.QtWidgets.QMessageBox, "exec_", fake_exec, create=True), \
                    mock.patch.object(L.QtWidgets.QMessageBox, "exec", fake_exec, create=True):
                self.assertTrue(win._confirm_trace_reset())
            self.assertIn("Reset every displayed trace on Screen A (auto)?", answers[0])
            self.assertFalse(win._confirm_reset_enabled())
            self.assertFalse(win.confirm_reset_action.isChecked())
            win.confirm_reset_action.setChecked(True)
            self.assertTrue(win._confirm_reset_enabled())
        finally:
            win.on_disconnect()
            win.close()

    def test_about_versions_read_from_modules(self):
        self.assertEqual(L.MainWindow.sibling_module_version("vszh5_writer.py"), "0.0.18")
        self.assertEqual(L.MainWindow.sibling_module_version("fsp_simulator.py"), "0.0.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
