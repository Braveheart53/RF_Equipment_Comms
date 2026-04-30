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
import threading
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

    SCPI dialect notes (FSP, NOT FSW):
      - Trace state query:   DISP:TRAC<n>:STAT?     (no :WINDow node on FSP)
      - Trace data:          TRAC:DATA? TRACE<n>    (FSP/FSE canonical form
                                                     per the FSP Operating
                                                     Manual Vol 2, line
                                                     17382: TRACe<1|2>[:DATA]
                                                     TRACE1|TRACE2|TRACE3,...
                                                     The optional <1|2> on
                                                     TRACe selects the
                                                     measurement WINDOW, not
                                                     the trace.)
      - Single sweep sync:   INIT:CONT OFF; *CLS; INIT:IMM;*WAI; *OPC?
                             (FSP rejects bare INIT — must be INIT:IMMediate)
      - Data format:         FORM ASC                (binary REAL,32 supported but
                                                       ASCII is more robust over LAN)
    """

    MAX_TRACES = 3  # FSP supports up to 3 traces simultaneously

    def __init__(self, resource: str, timeout_ms: int = 30000,
                 backend: str = "@py", debug: bool = False):
        if not _HAS_PYVISA:
            raise FSPError(
                "pyvisa is not installed. `pip install pyvisa pyvisa-py` "
                "or use Demo Mode."
            )
        self.resource = resource
        self.debug = debug
        self.rm = pyvisa.ResourceManager(backend)
        self.inst = self.rm.open_resource(resource)
        self.inst.timeout = timeout_ms
        # Standard message terminators for R&S over TCPIP
        try:
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
        except Exception:
            pass
        # ASCII trace data, max digits, English number format. Flush errors.
        try:
            self.inst.write("*CLS")
            self.inst.write("FORM ASC")
            self.inst.write("FORM:DEXP:DSEP POIN")  # decimal point, not comma (locale)
        except Exception:
            pass
        # Drain any prior errors so future SYST:ERR? checks are clean
        self._drain_error_queue()

    # ---- low level -----------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.debug:
            sys.stderr.write(f"[FSP] {msg}\n")

    def query(self, cmd: str) -> str:
        self._log(f"Q  {cmd}")
        ans = self.inst.query(cmd).strip()
        self._log(f" -> {ans[:80]}{'...' if len(ans) > 80 else ''}")
        return ans

    def write(self, cmd: str) -> None:
        self._log(f"W  {cmd}")
        self.inst.write(cmd)

    def _drain_error_queue(self) -> List[str]:
        """Read every SYST:ERR? entry until '0,"No error"'. Returns the messages."""
        errors: List[str] = []
        for _ in range(20):  # safety cap
            try:
                e = self.inst.query("SYST:ERR?").strip()
            except Exception:
                break
            if not e:
                break
            # FSP returns '<code>,"<msg>"' — code 0 means no error.
            code = e.split(",", 1)[0].strip().lstrip("+-")
            try:
                if int(code) == 0:
                    break
            except ValueError:
                break
            errors.append(e)
        return errors

    def close(self) -> None:
        try:
            self.inst.write("INIT:CONT ON")  # restore continuous
        except Exception:
            pass
        try: self.inst.close()
        except Exception: pass
        try: self.rm.close()
        except Exception: pass

    # ---- high level ----------------------------------------------------
    def idn(self) -> str:
        return self.query("*IDN?")

    def _query_trace_state(self, n: int) -> Tuple[Optional[str], Optional[str]]:
        """Return (mode_token, state_token) for trace n. Either may be None.

        mode_token is the upper-cased response to DISP:TRAC<n>:MODE? (e.g.
        'WRIT', 'MAXH', 'AVER', 'VIEW', 'BLAN'). state_token is '0' or '1'
        from DISP:TRAC<n>:STAT? (or 'ON'/'OFF').
        """
        mode_tok: Optional[str] = None
        for cmd in (f"DISP:TRAC{n}:MODE?", f"DISP:WIND:TRAC{n}:MODE?"):
            try:
                ans = (self.query(cmd) or "").strip().upper().lstrip("+")
            except Exception as exc:
                self._log(f"{cmd} raised {exc}")
                continue
            if ans:
                # Drain any errors silently — we already got a response.
                self._drain_error_queue()
                mode_tok = ans
                break
            # Empty response: check if this command was rejected.
            errs = self._drain_error_queue()
            if errs and any("MODE" in e.upper() or "TRAC" in e.upper() for e in errs):
                self._log(f"{cmd} rejected: {errs}")
                continue

        state_tok: Optional[str] = None
        for cmd in (f"DISP:TRAC{n}:STAT?", f"DISP:WIND:TRAC{n}:STAT?"):
            try:
                ans = (self.query(cmd) or "").strip().upper().lstrip("+")
            except Exception as exc:
                self._log(f"{cmd} raised {exc}")
                continue
            if ans in ("0", "1", "ON", "OFF"):
                self._drain_error_queue()
                state_tok = ans
                break
            errs = self._drain_error_queue()
            if errs and any("STAT" in e.upper() or "TRAC" in e.upper() for e in errs):
                self._log(f"{cmd} rejected: {errs}")
                continue
            if ans:
                state_tok = ans
                break
        return mode_tok, state_tok

    @staticmethod
    def _is_displayed(mode_tok: Optional[str], state_tok: Optional[str]) -> bool:
        """Decide whether a trace is currently shown on the FSP screen.

        Logic (informed by FSP-38 testing):
        - If MODE? is reported and is anything OTHER than BLANK, the trace is
          displayed (handles MAXH/AVER/VIEW/MINH/WRIT cases — including
          max-hold and average traces which return STAT?=0 on FSP firmware).
        - Else if STAT? is 1/ON, treat as displayed (covers firmware versions
          that don't expose MODE? but do expose STATe?).
        - If MODE? is BLANK, the trace is hidden regardless of STAT?.
        """
        if mode_tok:
            # 'BLAN' is the FSP short form for 'BLANK'.
            if mode_tok.startswith("BLAN"):
                return False
            # Any recognised non-blank mode token => displayed.
            for tok in ("WRIT", "VIEW", "AVER", "MAXH", "MINH"):
                if mode_tok.startswith(tok):
                    return True
            # Unknown mode token but non-empty: fall through to STAT check.
        if state_tok:
            t = state_tok.lstrip("+")
            if t.startswith("1") or t.startswith("ON"):
                return True
        return False

    def active_traces(self) -> List[int]:
        """
        Return list of trace numbers currently *displayed* (1..3) on the FSP.

        FSP gotcha: STAT? alone is not sufficient — on FSP-38 firmware, traces
        in MAX HOLD or AVERAGE mode return STAT?=0 even though they are very
        much visible on screen. We therefore combine DISP:TRAC<n>:MODE? with
        DISP:TRAC<n>:STAT? and treat a trace as displayed iff MODE != BLANK
        (preferred) or STAT? == 1 (fallback).

        Reference: FSP Operating Manual Vol 2, DISPlay[:WINDow]:TRACe<n>
        subtree (lines ~9486 + MODE WRITe|VIEW|AVERage|MAXHold|MINHold|BLANk).
        """
        # Drain any stale errors from prior failed commands so they don't
        # get attributed to (and discard the result of) our first query.
        try:
            stale = self._drain_error_queue()
            if stale:
                self._log(f"drained stale errors before active_traces: {stale}")
        except Exception:
            pass

        active: List[int] = []
        for n in range(1, self.MAX_TRACES + 1):
            mode_tok, state_tok = self._query_trace_state(n)
            self._log(f"trace {n}: MODE={mode_tok!r} STAT={state_tok!r}")
            if mode_tok is None and state_tok is None:
                self._log(f"could not query trace {n} state")
                continue
            if self._is_displayed(mode_tok, state_tok):
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
        return dict(f_start=f_start, f_stop=f_stop, n_pts=n_pts,
                    sweep_time=sweep_time, sweep_count=sweep_count)

    def frequency_axis(self, settings: Optional[Dict[str, float]] = None) -> np.ndarray:
        s = settings or self.sweep_settings()
        return np.linspace(s["f_start"], s["f_stop"], int(s["n_pts"]))

    def arm_single(self) -> None:
        """Put the instrument in single-sweep mode and clear status."""
        self.write("INIT:CONT OFF")
        self.write("*CLS")
        self._drain_error_queue()

    def trigger_and_wait(self, timeout_s: float) -> None:
        """
        Start a single sweep and block until it completes.

        Uses INIT:IMM;*WAI which on FSP holds the SCPI parser until the sweep
        is done — so any subsequent query only returns at sweep end. We then
        send *OPC? as an explicit barrier. Bare "INIT" is rejected by FSP
        firmware with -200,"Function not available;INIT" — must use the long
        form INIT:IMMediate (or its short form INIT:IMM).

        Requires INIT:CONT OFF (set by arm_single).
        """
        saved = self.inst.timeout
        # Generous timeout: 5 s base + 2x sweep total
        eff_ms = max(saved, int(timeout_s * 1000) + 5000)
        try:
            self.inst.timeout = eff_ms
            self.write("INIT:IMM;*WAI")
            # *OPC? returns 1 only after *WAI completes; serves as a barrier.
            self.query("*OPC?")
        finally:
            self.inst.timeout = saved

    def fetch_trace(self, trace_num: int, timeout_s: float = 30.0) -> np.ndarray:
        """
        Read trace as ASCII floats. Robust against:
        - slow LAN responses (generous timeout, optional retry)
        - locale issues (forces FORM ASC and decimal-point separator)
        - terminator weirdness (uses read_ascii_values when available so
          pyvisa handles termination + parsing internally)
        - the FSP being mid-sweep (caller should call trigger_and_wait first,
          but we defensively re-issue *WAI before the read).
        """
        saved = self.inst.timeout
        eff_ms = max(int(saved or 0), int(timeout_s * 1000))
        try:
            self.inst.timeout = eff_ms
            # Force ASCII format every fetch — cheap insurance in case the
            # user (or a previous program) left it in REAL,32 binary mode,
            # which would make our ASCII parsing fail silently / time out.
            try:
                self.inst.write("FORM ASC")
            except Exception:
                pass
            # FSP canonical form per Operating Manual Vol 2:
            #   TRACe<1|2>[:DATA] TRACE1|TRACE2|TRACE3, <data>
            # The numeric suffix on TRACe (which we omit) selects the
            # measurement window; the TRACE<n> parameter selects which
            # trace within the window. Note the SPACE between the '?' and
            # 'TRACE<n>' is REQUIRED — it's a parameter, not part of the
            # header.
            cmd = f"TRAC:DATA? TRACE{trace_num}"
            self._log(f"Q  {cmd}  (timeout={eff_ms} ms)")
            # Prefer read_ascii_values: it understands the optional binary-block
            # header and uses pyvisa's chunked reader, which is far less likely
            # to hang waiting for a terminator that never comes.
            try:
                values = self.inst.query_ascii_values(
                    cmd, container=np.array, separator=",")
                arr = np.asarray(values, dtype=float)
            except Exception as exc:
                # Fall back to plain query + manual parse.
                self._log(f"query_ascii_values failed ({exc}); using raw query")
                raw = self.inst.query(cmd).strip()
                if not raw:
                    return np.empty(0, dtype=float)
                # If the FSP returned a binary block (#<n><len><data>) despite
                # FORM ASC, surface a clear error rather than NaN-spam.
                if raw.startswith("#"):
                    raise FSPError(
                        "FSP returned trace data in binary-block format. "
                        "Send `FORM ASC` to the instrument and retry."
                    )
                arr = np.array([s for s in raw.split(",") if s.strip()], dtype=float)
        finally:
            self.inst.timeout = saved
        return arr


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

            # Fetch all active traces. Use a generous timeout proportional
            # to sweep time + point count. Floor of 30 s handles slow LAN /
            # narrow-RBW configurations where the very first TRAC:DATA? after
            # the sweep can take noticeably longer than the sweep itself.
            n_pts = self._freq_axis.shape[0]
            fetch_timeout = max(30.0, 2.0 * self._sweep_total + n_pts * 0.002 + 10.0)
            traces: Dict[int, np.ndarray] = {}
            for tn in self._active:
                arr = self._fetch_one_with_retry(tn, fetch_timeout)
                if arr.shape[0] != n_pts:
                    raise FSPError(
                        f"Trace {tn} returned {arr.shape[0]} points, expected {n_pts}. "
                        f"This usually means a SCPI sync issue \u2014 try increasing N "
                        f"or check sweep settings."
                    )
                traces[tn] = arr

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

    def _fetch_one(self, trace_num: int, timeout_s: float) -> np.ndarray:
        """Adapter that calls fetch_trace with a timeout if the instrument supports it."""
        try:
            return self.inst.fetch_trace(trace_num, timeout_s=timeout_s)  # type: ignore[arg-type]
        except TypeError:
            # Mock signature has no timeout_s kwarg
            return self.inst.fetch_trace(trace_num)

    def _fetch_one_with_retry(self, trace_num: int, timeout_s: float) -> np.ndarray:
        """
        Fetch a single trace with a single retry on timeout / VISA error.

        On timeout we:
          1. Drain the FSP error queue (clears any pending state).
          2. Re-arm + re-trigger a single sweep so we know the trace is fresh.
          3. Retry the read with a doubled timeout.
        """
        try:
            return self._fetch_one(trace_num, timeout_s)
        except Exception as exc:
            msg = str(exc)
            # Only retry on timeout-flavored errors; let other failures bubble.
            if "VI_ERROR_TMO" not in msg and "timeout" not in msg.lower():
                raise
            # Try to recover — drain errors, re-trigger, retry once.
            try:
                if hasattr(self.inst, "_drain_error_queue"):
                    self.inst._drain_error_queue()  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                if hasattr(self.inst, "arm_single"):
                    self.inst.arm_single()
                if hasattr(self.inst, "trigger_and_wait"):
                    self.inst.trigger_and_wait(self._sweep_total)
            except Exception:
                pass
            self.statusMessage.emit(
                f"Trace {trace_num} fetch timed out \u2014 retrying with longer timeout…"
            )
            return self._fetch_one(trace_num, timeout_s * 2.0)

    def _trigger_with_progress(self, idx: int):
        """
        Trigger a single sweep on the instrument and emit smooth progress.

        We run the *blocking* trigger_and_wait() on a tiny helper thread so
        the worker thread is free to emit progress signals. This avoids the
        previous *OPC/*ESR polling race that caused VISA timeouts on real FSPs.
        """
        import threading
        total = max(0.05, self._sweep_total)
        done = threading.Event()
        err_box: List[BaseException] = []

        def _trigger():
            try:
                # Generous deadline: 3x sweep time + 5 s slack
                self.inst.trigger_and_wait(total * 3 + 5.0)
            except BaseException as exc:
                err_box.append(exc)
            finally:
                done.set()

        th = threading.Thread(target=_trigger, daemon=True)
        t0 = _perf()
        th.start()

        # Smoothly emit progress while the sweep runs. Cap at 99% until done.
        max_wait = total * 5 + 10.0
        while not done.is_set() and not self._stop:
            elapsed = _perf() - t0
            self.captureProgress.emit(idx, min(0.99, elapsed / total))
            if elapsed > max_wait:
                # Hard ceiling — don't hang forever
                break
            time.sleep(0.05)

        # If the user pressed Stop, let the trigger thread finish naturally
        # so the instrument isn't left mid-sweep with a dangling query.
        th.join(timeout=max_wait)
        if err_box:
            raise err_box[0]
        if not done.is_set():
            raise FSPError(
                f"Sweep did not complete within {max_wait:.1f} s. "
                f"Check sweep time/count on the analyzer."
            )
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
        cl.addWidget(QtWidgets.QLabel("VISA backend:"), 0, 4)
        self.backend_combo = QtWidgets.QComboBox()
        # @py = pyvisa-py (pure Python); @ivi/blank = system VISA (NI / R&S)
        self.backend_combo.addItems(["@py (pyvisa-py)", "@ivi (system VISA)"])
        cl.addWidget(self.backend_combo, 0, 5)
        self.demo_check = QtWidgets.QCheckBox("Demo Mode")
        cl.addWidget(self.demo_check, 0, 6)
        self.debug_check = QtWidgets.QCheckBox("Log SCPI to stderr")
        cl.addWidget(self.debug_check, 1, 6)
        self.connect_btn = QtWidgets.QPushButton("Connect")
        cl.addWidget(self.connect_btn, 0, 7)
        self.disconnect_btn = QtWidgets.QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        cl.addWidget(self.disconnect_btn, 0, 8)
        self.diag_btn = QtWidgets.QPushButton("Diagnostics…")
        self.diag_btn.setEnabled(False)
        cl.addWidget(self.diag_btn, 1, 8)
        cl.addWidget(QtWidgets.QLabel("Instrument ID:"), 1, 0)
        self.idn_label = QtWidgets.QLabel("(not connected)")
        self.idn_label.setStyleSheet("color: #888;")
        cl.addWidget(self.idn_label, 1, 1, 1, 5)
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
        self.diag_btn.clicked.connect(self.on_diagnostics)
        self.browse_btn.clicked.connect(self.on_browse)
        self.now_btn.clicked.connect(
            lambda: self.start_dt.setDateTime(QDateTime.currentDateTime()))
        self.start_manual_btn.clicked.connect(lambda: self.on_start(scheduled=False))
        self.start_scheduled_btn.clicked.connect(lambda: self.on_start(scheduled=True))
        self.stop_btn.clicked.connect(self.on_stop)

    # -------- Slots --------
    @Slot()
    def on_diagnostics(self):
        """Probe the instrument and show what SCPI is actually returning."""
        if self.instrument is None:
            return
        lines: List[str] = []
        try:
            lines.append(f"*IDN?         -> {self.instrument.idn()}")
        except Exception as exc:
            lines.append(f"*IDN?         -> ERROR: {exc}")

        # Trace state — combine MODE? + STAT?. On FSP-38, traces in MAXHOLD
        # or AVERAGE mode return STAT?=0 even while displayed, so neither
        # query alone is sufficient. We treat a trace as displayed iff
        # MODE != BLANK (preferred) or STAT? == 1 (fallback).
        lines.append("")
        lines.append("Trace state queries (raw responses):")
        lines.append("  MODE? = WRIT|MAXH|AVER|MINH|VIEW  ->  displayed")
        lines.append("  MODE? = BLAN                       ->  hidden")
        lines.append("  STAT? = 1                          ->  displayed (fallback)")
        if isinstance(self.instrument, FSPInstrument):
            for n in (1, 2, 3):
                for cmd in (f"DISP:TRAC{n}:MODE?",
                            f"DISP:WIND:TRAC{n}:MODE?",
                            f"DISP:TRAC{n}:STAT?",
                            f"DISP:WIND:TRAC{n}:STAT?"):
                    try:
                        ans = self.instrument.inst.query(cmd).strip()
                        errs = self.instrument._drain_error_queue()
                        suffix = f"  [errors: {errs}]" if errs else ""
                        lines.append(f"  {cmd:30s} -> {ans!r}{suffix}")
                    except Exception as exc:
                        lines.append(f"  {cmd:30s} -> EXC: {exc}")
                # Show parsed decision per trace
                try:
                    mt, st = self.instrument._query_trace_state(n)
                    decision = "DISPLAYED" if FSPInstrument._is_displayed(mt, st) else "hidden"
                    lines.append(f"  -> trace {n}: MODE={mt!r} STAT={st!r}  =>  {decision}")
                except Exception as exc:
                    lines.append(f"  -> trace {n}: parse EXC: {exc}")
        else:
            lines.append(f"  active_traces() -> {self.instrument.active_traces()}")

        # Sweep settings
        lines.append("")
        lines.append("Sweep settings:")
        try:
            s = self.instrument.sweep_settings()
            for k, v in s.items():
                lines.append(f"  {k:12s} = {v}")
        except Exception as exc:
            lines.append(f"  ERROR: {exc}")

        # Active traces (parsed)
        lines.append("")
        try:
            lines.append(f"Parsed active traces: {self.instrument.active_traces()}")
        except Exception as exc:
            lines.append(f"Parsed active traces: ERROR {exc}")

        # End-to-end data-path test: arm + sweep + fetch trace 1, time it.
        # Runs in a worker thread with a hard wall-clock cap so a stuck
        # VISA read can't freeze the GUI. The user sees an animated
        # "Running…" line in the dialog while it works.
        lines.append("")
        lines.append("Trace fetch test (TRAC:DATA? TRACE1):")
        if isinstance(self.instrument, FSPInstrument):
            inst = self.instrument
            result_holder: Dict[str, object] = {}

            def _do_fetch_test():
                try:
                    s = inst.sweep_settings()
                    sweep_total = float(s["sweep_time"]) * float(s.get("sweep_count", 1) or 1)
                    result_holder["sweep_total"] = sweep_total
                    inst.arm_single()
                    t0 = time.perf_counter()
                    inst.trigger_and_wait(sweep_total)
                    result_holder["t_sweep"] = time.perf_counter() - t0
                    t1 = time.perf_counter()
                    arr = inst.fetch_trace(
                        1, timeout_s=max(15.0, 2.0 * sweep_total + 5.0))
                    result_holder["t_fetch"] = time.perf_counter() - t1
                    result_holder["arr"] = arr
                except Exception as exc:
                    result_holder["error"] = f"{exc.__class__.__name__}: {exc}"

            th = threading.Thread(target=_do_fetch_test, daemon=True)
            th.start()
            # Hard wall-clock cap: 30 seconds is plenty for anything sane.
            # While we wait, pump the Qt event loop so the GUI stays alive.
            deadline = time.perf_counter() + 30.0
            while th.is_alive() and time.perf_counter() < deadline:
                QtWidgets.QApplication.processEvents(
                    QtCore.QEventLoop.AllEvents, 100)
                th.join(timeout=0.05)
            if th.is_alive():
                lines.append("  TIMEOUT: data-path test did not finish in 30 s.")
                lines.append("  The VISA read is stuck — check ASCII format,")
                lines.append("  read termination, and that the FSP is responding.")
                # Don't try to join — the thread will eventually die when
                # the underlying VISA call times out.
            elif "error" in result_holder:
                lines.append(f"  ERROR: {result_holder['error']}")
            else:
                st = result_holder.get("sweep_total", 0.0)
                ts = result_holder.get("t_sweep", 0.0)
                tf = result_holder.get("t_fetch", 0.0)
                arr = result_holder.get("arr")
                lines.append(f"  arming + INIT:IMM;*WAI (sweep_total ≈ {st:.3f} s)")
                lines.append(f"  sweep finished in {ts:.3f} s")
                if arr is not None and getattr(arr, "size", 0):
                    lines.append(
                        f"  fetched {arr.shape[0]} points in {tf:.3f} s; "
                        f"first={arr[0]:.2f} dBm, last={arr[-1]:.2f} dBm"
                    )
                else:
                    lines.append("  fetched 0 points (unexpected)")
            try:
                errs = inst._drain_error_queue()
                if errs:
                    lines.append(f"  post-fetch errors: {errs}")
            except Exception:
                pass

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("FSP Diagnostics")
        dlg.resize(820, 620)
        v = QtWidgets.QVBoxLayout(dlg)
        text = QtWidgets.QPlainTextEdit("\n".join(lines))
        text.setReadOnly(True)
        text.setFont(QtGui.QFont("Monospace"))
        v.addWidget(text)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()

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
                backend_token = self.backend_combo.currentText().split()[0]  # "@py" or "@ivi"
                self.instrument = FSPInstrument(
                    self.resource_edit.text().strip(),
                    backend=backend_token,
                    debug=self.debug_check.isChecked(),
                )
            idn = self.instrument.idn()
            self.idn_label.setText(idn)
            self.idn_label.setStyleSheet("color: #2ecc71;")
            # Refresh trace LEDs and sweep info immediately
            self._refresh_instrument_state()
            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.diag_btn.setEnabled(True)
            self.start_manual_btn.setEnabled(True)
            self.start_scheduled_btn.setEnabled(True)
            self.demo_check.setEnabled(False)
            self.resource_edit.setEnabled(False)
            self.backend_combo.setEnabled(False)
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
        self.diag_btn.setEnabled(False)
        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.demo_check.setEnabled(True)
        self.resource_edit.setEnabled(True)
        self.backend_combo.setEnabled(True)
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
