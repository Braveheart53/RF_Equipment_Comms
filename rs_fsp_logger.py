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
# Version
# ---------------------------------------------------------------------------
# 0.5.0 — first version that connected to a real FSP-38; INIT:IMM-based
#         single-sweep arming. Trace detection via DISP:TRAC<n>:STAT? + MODE?.
# 0.6.0 — Honors continuous sweep (no INIT:IMM), probe-based trace detection
#         via TRAC:DATA?, error-queue draining around every fetch, defensive
#         __init__ that won't hang the kernel on a flaky link, GUI version
#         label, dialog robustness improvements.
# 0.7.0 — FIX: TRAC:DATA? rejected by FSP-38 firmware 4.50 with -100, hangs
#         30 s before VisaIOError. Switched fetch_trace to canonical
#         'TRAC? TRACE<n>' (per FSP Operating Manual Vol 2 §6.1.13.13).
#         Switched active_traces() back to MODE-based detection ('BLAN' =
#         hidden, anything else = displayed) — lightweight, runs on GUI
#         thread without killing Spyder kernel. Removed 30 s fetch test
#         from Diagnostics (the processEvents spin loop was starving
#         Spyder's heartbeat). Probe Traces button now synchronous.
APP_VERSION = "0.7.4"

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
      - Trace data:          TRAC? TRACE<n>         (FSP/FSE canonical form
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
                 backend: str = "@py", debug: bool = False,
                 continuous_sweep: bool = True):
        if not _HAS_PYVISA:
            raise FSPError(
                "pyvisa is not installed. `pip install pyvisa pyvisa-py` "
                "or use Demo Mode."
            )
        self.resource = resource
        self.debug = debug
        # When True (default), the FSP is left in its existing continuous-
        # sweep state — we don't issue INIT:CONT OFF or INIT:IMM. Instead we
        # synchronize on *OPC? at sweep boundaries and read whatever the
        # latest completed sweep produced.
        self.continuous_sweep = continuous_sweep
        # Cached number of trace points (set by sweep_settings); used by
        # active_traces() to validate trace-data probes without parsing
        # the entire payload.
        self._cached_n_pts: Optional[int] = None
        # Cached working trace-fetch syntax. Discovered on first successful
        # fetch_trace() call and reused for the rest of the session to
        # avoid re-trying broken syntaxes (which can take >30 s each on
        # this firmware).
        self._trace_fetch_cmd_template: Optional[str] = None
        # FSP supports two measurement screens (Screen A = WINDow1,
        # Screen B = WINDow2). The user's spectrum config can live on
        # either one. SCPI defaults to Screen A; if Screen A is at boot
        # defaults (0-2 MHz, etc.) and Screen B holds the real config,
        # FREQ:* queries return useless values and TRAC? gets -100
        # 'execution error' on the inactive screen. We auto-detect which
        # screen has the real config in sweep_settings() and cache it here.
        # 1 = Screen A (default), 2 = Screen B.
        self.active_screen: int = 1
        self._screen_discovered: bool = False

        # CONNECT — keep this minimal. Anything that touches the SCPI parser
        # here can hang the calling thread (and on Spyder's main thread, that
        # kills the kernel via missed heartbeats). We open the resource,
        # set terminators, and STOP. Housekeeping is done lazily on first
        # use, and is wrapped in short timeouts so it can't take down the
        # GUI even if the FSP is in a weird state.
        self.rm = pyvisa.ResourceManager(backend)
        try:
            self.inst = self.rm.open_resource(resource)
        except Exception:
            try: self.rm.close()
            except Exception: pass
            raise
        # Cap connect-time timeout to 5 s so a non-responsive instrument
        # can't freeze us; caller can raise it later as needed.
        try:
            self.inst.timeout = min(int(timeout_ms), 5000)
        except Exception:
            pass
        # Standard message terminators for R&S over TCPIP
        try:
            self.inst.read_termination = "\n"
            self.inst.write_termination = "\n"
        except Exception:
            pass
        # Restore the caller-requested timeout for normal operation.
        try:
            self.inst.timeout = timeout_ms
        except Exception:
            pass
        # Track whether one-time setup writes (FORM ASC etc) have run.
        self._configured = False

    def _ensure_configured(self) -> None:
        """Send one-time housekeeping writes the first time we actually use
        the connection. Each write is independently guarded so a single
        rejected command doesn't abort the whole setup.

        Called lazily by query() before the first SCPI operation.
        """
        if self._configured:
            return
        # Set the flag FIRST so re-entry from inside these calls (via the
        # query/write helpers) doesn't recurse forever.
        self._configured = True
        # NOTE: 'INST SAN' (select Spectrum Analyzer personality) is critical
        # on FSP-38 boxes where SCPI is otherwise routed to a different
        # instrument personality (Receiver / Analog Demod / VSA), which causes
        # FREQ:* queries to return values from the wrong screen and TRAC?
        # to be rejected with -100. We try the most common spelling first;
        # if it errors, we'll see it in the drained queue but proceed.
        for cmd in ("*CLS", "INST:SEL SAN", "FORM ASC", "FORM:DEXP:DSEP POIN"):
            try:
                self.inst.write(cmd)
            except Exception as exc:
                self._log(f"setup write {cmd!r} failed: {exc}")
        # Give the FSP a beat to switch personalities before we start
        # querying. A 200 ms wait is plenty in practice; we also drain any
        # errors the personality switch might have produced.
        try:
            time.sleep(0.2)
        except Exception:
            pass
        try:
            stale = self._drain_error_queue()
            if stale:
                self._log(f"drained startup errors: {stale}")
        except Exception:
            pass
        # Log the active personality so the user can confirm the SCPI side
        # is talking to the spectrum analyzer screen.
        try:
            personality = self.inst.query("INST?").strip()
            self._log(f"INST? -> {personality!r} (SAN = Spectrum Analyzer)")
        except Exception as exc:
            self._log(f"INST? probe failed: {exc}")

    # ---- low level -----------------------------------------------------
    def _log(self, msg: str) -> None:
        if self.debug:
            sys.stderr.write(f"[FSP] {msg}\n")

    def query(self, cmd: str) -> str:
        # Lazy housekeeping on first SCPI use. Skip when we ARE the
        # housekeeping (otherwise we recurse forever).
        if not self._configured and not cmd.upper().startswith("SYST:ERR"):
            self._ensure_configured()
        self._log(f"Q  {cmd}")
        ans = self.inst.query(cmd).strip()
        self._log(f" -> {ans[:80]}{'...' if len(ans) > 80 else ''}")
        return ans

    def write(self, cmd: str) -> None:
        if not self._configured:
            self._ensure_configured()
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
        # Always restore continuous sweep on the way out (cheap, harmless
        # even if it was already on).
        try:
            self.inst.write("INIT:CONT ON")
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

        Detection strategy: query DISP:TRAC<n>:MODE? for each trace and
        treat anything other than 'BLAN' (blanked) as displayed.

        Why this works on FSP-38:
        - MODE? returns one of {WRIT, MAXH, MINH, AVER, VIEW, BLAN}.
        - On this firmware MODE? consistently returns the trace's actual
          mode for displayed traces. The user-confirmed configuration is
          T1=clear/write, T2=max hold, T3=average — if MODE? returns
          'WRIT' for all three (firmware quirk), they're STILL all displayed,
          which is the answer we need. Only 'BLAN' means hidden.

        This is far cheaper than reading TRAC:DATA? — each MODE? query
        returns ~5 bytes and is non-blocking, vs hundreds of floats per
        trace. That matters: this method runs on the GUI thread when the
        user clicks Start or Diagnostics, and a heavy probe was killing
        the Spyder kernel's heartbeat.
        """
        # Drain any stale errors so a previous failure doesn't attribute
        # itself to our queries here.
        try:
            stale = self._drain_error_queue()
            if stale:
                self._log(f"drained stale errors before active_traces: {stale}")
        except Exception:
            pass

        # Cap timeout: each MODE? should return in milliseconds.
        saved = self.inst.timeout
        try:
            self.inst.timeout = 2000
            active: List[int] = []
            for n in range(1, self.MAX_TRACES + 1):
                cmd = f"DISP:TRAC{n}:MODE?"
                try:
                    ans = self.query(cmd).strip().upper().strip('"').strip("'")
                except Exception as exc:
                    self._log(f"MODE? trace {n} failed: {exc}")
                    # On query failure, drain errors and skip this trace.
                    try:
                        self._drain_error_queue()
                    except Exception:
                        pass
                    continue
                # Anything other than 'BLAN' means the trace is displayed.
                # FSP returns one of: WRIT, MAXH, MINH, AVER, VIEW, BLAN.
                if ans and not ans.startswith("BLAN"):
                    self._log(f"trace {n}: MODE={ans!r} => DISPLAYED")
                    active.append(n)
                else:
                    self._log(f"trace {n}: MODE={ans!r} => hidden")
            # Drain any straggling errors so they don't pollute later calls.
            try:
                self._drain_error_queue()
            except Exception:
                pass
        finally:
            self.inst.timeout = saved
        return active

    def force_screen(self, screen: int) -> None:
        """Force SCPI to address a specific FSP screen (1=A, 2=B).

        On FSP, the SENSe<1|2>: numeric suffix routes per-query to a
        specific measurement window — this is independent of which window
        is the "active measurement window" (DISP:WIND:SEL state). So
        forcing a screen is just a matter of recording which SENSe prefix
        to use; subsequent FREQ:* / SWE:* / TRAC? queries are built with
        the right suffix in _read_screen_freq, sweep_settings, and
        fetch_trace.

        Resets the cached trace-fetch template since the previous one may
        have been keyed to a different screen.
        """
        if screen not in (1, 2):
            raise ValueError(f"screen must be 1 or 2, got {screen}")
        self._log(f"force_screen({screen}): SCPI will now use "
                  f"{self._scpi_screen_prefix(screen) or '(no prefix = SENS1)'} "
                  f"for FREQ/SWE queries")
        self.active_screen = screen
        self._screen_discovered = True
        self._trace_fetch_cmd_template = None  # re-discover for new screen

    def reset_screen_discovery(self) -> None:
        """Clear the cached active-screen choice so the next sweep_settings()
        call re-runs auto-discovery."""
        self._screen_discovered = False
        self.active_screen = 1
        self._trace_fetch_cmd_template = None

    def _scpi_screen_prefix(self, screen: Optional[int] = None) -> str:
        """Build the SENSe<n>: prefix for screen-routed queries.

        FSP routes FREQ/SWE queries via the SENSe<1|2> numeric suffix:
        Screen A = SENS1, Screen B = SENS2. Without the suffix, queries
        always hit Screen A regardless of DISP:WIND:SEL state.

        Pass screen=1, 2, or None (uses self.active_screen).
        """
        n = self.active_screen if screen is None else screen
        return "" if n == 1 else f"SENS{n}:"

    def _read_screen_freq(self, screen: Optional[int] = None) -> Dict[str, float]:
        """Read FREQ:STAR/STOP/CENT/SPAN for a given FSP screen.

        Uses the SENSe<n> prefix to route the query; this works regardless
        of which screen is currently the "active measurement window" (the
        DISP:WIND:SEL state). Returns NaN for any individual query that
        errors.
        """
        p = self._scpi_screen_prefix(screen)
        try:    f_start_raw = float(self.query(f"{p}FREQ:STAR?"))
        except Exception: f_start_raw = float("nan")
        try:    f_stop_raw  = float(self.query(f"{p}FREQ:STOP?"))
        except Exception: f_stop_raw  = float("nan")
        try:    f_center    = float(self.query(f"{p}FREQ:CENT?"))
        except Exception: f_center    = float("nan")
        try:    f_span      = float(self.query(f"{p}FREQ:SPAN?"))
        except Exception: f_span      = float("nan")
        return dict(f_start_raw=f_start_raw, f_stop_raw=f_stop_raw,
                    f_center=f_center, f_span=f_span)

    def _discover_active_screen(self) -> None:
        """Identify which FSP screen (A=WIND1 or B=WIND2) holds the user's
        spectrum config, and select it as the SCPI-active screen.

        Heuristic: query frequencies on each screen; the screen with a
        higher center frequency wins (the FSP boots Screen A at 0-2 MHz
        defaults; if the user is on Screen B at 13.9 GHz, Screen B's
        center will be vastly higher). If both look default, leave
        Screen A active.

        Sets self.active_screen to 1 or 2, and (if 2) sends DISP:WIND2:SEL
        so that subsequent unsuffixed FREQ/SWE queries route to Screen B.
        """
        if self._screen_discovered:
            return
        self._screen_discovered = True   # set first to prevent recursion
        self._log("--- screen discovery: probing both FSP screens via SENSe suffix ---")
        # Probe each screen using the SENSe<n>: prefix — this routes the
        # query to the right screen WITHOUT changing DISP:WIND:SEL state.
        # Screen A = no prefix (or SENS1:), Screen B = SENS2:.
        a = self._read_screen_freq(screen=1)
        self._log(f"  Screen A (SENS1): center={a['f_center']}, span={a['f_span']}, "
                  f"start={a['f_start_raw']}, stop={a['f_stop_raw']}")
        try:
            self._drain_error_queue()
        except Exception:
            pass
        b = self._read_screen_freq(screen=2)
        self._log(f"  Screen B (SENS2): center={b['f_center']}, span={b['f_span']}, "
                  f"start={b['f_start_raw']}, stop={b['f_stop_raw']}")
        try:
            self._drain_error_queue()
        except Exception:
            pass
        # Decide. Prefer the screen with the higher (finite, positive)
        # center frequency. Treat 0/NaN center as "empty/default".
        def score(d):
            c = d['f_center']
            if c != c or c <= 0:
                return -1.0
            return c
        score_a, score_b = score(a), score(b)
        if score_b > score_a:
            self.active_screen = 2
            self._log(f"  => Screen B wins (center {b['f_center']} > "
                      f"{a['f_center']}); active_screen = 2")
        else:
            self.active_screen = 1
            self._log(f"  => Screen A wins; active_screen = 1")

    def sweep_settings(self) -> Dict[str, float]:
        """Read sweep settings from the FSP.

        On FSP-38 firmware 4.50, FREQ:STAR? / FREQ:STOP? have been observed
        to return values that disagree with the front-panel display when
        the user's spectrum config is on Screen B but SCPI defaults to
        Screen A. We auto-detect which screen has the real config (in
        _discover_active_screen) and route subsequent queries there.

        We ALSO query FREQ:CENT? and FREQ:SPAN? as a cross-check, and
        prefer whichever pair yields a positive span.
        """
        # First call only: identify which screen the user is using.
        self._discover_active_screen()
        f = self._read_screen_freq()
        f_start_raw = f['f_start_raw']
        f_stop_raw  = f['f_stop_raw']
        f_center    = f['f_center']
        f_span      = f['f_span']
        # Prefer center/span when both are finite and span is positive AND
        # the start/stop pair is degenerate (span=0) or the two pairs
        # disagree. The FSP-38 has been observed to return zero start/stop
        # while center/span correctly reflect the screen.
        derived_start = f_center - f_span / 2.0
        derived_stop = f_center + f_span / 2.0
        raw_span = f_stop_raw - f_start_raw
        center_span_ok = (f_span > 0
                          and f_span == f_span         # NaN check
                          and f_center == f_center)
        # Decision rule: trust start/stop only if their span > 0 AND it
        # matches center/span (within 1 Hz). Otherwise fall back to center/span.
        if (raw_span > 0
                and (not center_span_ok
                     or abs(raw_span - f_span) < 1.0)):
            f_start, f_stop = f_start_raw, f_stop_raw
            freq_source = "STAR/STOP"
        elif center_span_ok:
            f_start, f_stop = derived_start, derived_stop
            freq_source = "CENT/SPAN (STAR/STOP unreliable)"
            self._log(f"FREQ:STAR/STOP returned {f_start_raw}/{f_stop_raw} "
                      f"(span={raw_span}); using CENT={f_center} SPAN={f_span} "
                      f"=> start={f_start}, stop={f_stop}")
        else:
            # Neither source is good — last resort, use raw values and warn.
            f_start, f_stop = f_start_raw, f_stop_raw
            freq_source = "STAR/STOP (CENT/SPAN unavailable)"
        # Use the SENSe<n>: prefix so SWE:* hits the right screen.
        p = self._scpi_screen_prefix()
        n_pts = int(float(self.query(f"{p}SWE:POIN?")))
        sweep_time = float(self.query(f"{p}SWE:TIME?"))
        try:
            sweep_count = int(float(self.query(f"{p}SWE:COUN?")))
        except Exception:
            sweep_count = 1
        if sweep_count < 1:
            sweep_count = 1
        # Cache n_pts so active_traces() can validate probe lengths without
        # an extra round-trip.
        self._cached_n_pts = n_pts
        return dict(f_start=f_start, f_stop=f_stop, n_pts=n_pts,
                    sweep_time=sweep_time, sweep_count=sweep_count,
                    f_center=f_center, f_span=f_span,
                    f_start_raw=f_start_raw, f_stop_raw=f_stop_raw,
                    freq_source=freq_source,
                    active_screen=self.active_screen)

    def frequency_axis(self, settings: Optional[Dict[str, float]] = None) -> np.ndarray:
        s = settings or self.sweep_settings()
        return np.linspace(s["f_start"], s["f_stop"], int(s["n_pts"]))

    def arm_single(self) -> None:
        """Prepare the instrument for the next acquisition.

        In continuous-sweep mode (the default and what the user wants),
        this is a no-op — we leave INIT:CONT alone, since the FSP is
        already sweeping and toggling it would either error or interrupt.
        Single-sweep mode is preserved as an option but not used.
        """
        if self.continuous_sweep:
            # Just clear stale errors so subsequent SYST:ERR? checks are
            # meaningful. No INIT:CONT OFF, no *CLS-induced state change.
            self._drain_error_queue()
            return
        self.write("INIT:CONT OFF")
        self.write("*CLS")
        self._drain_error_queue()

    def trigger_and_wait(self, timeout_s: float) -> None:
        """
        Synchronize with the next completed sweep and return.

        Continuous-sweep mode (default): we do NOT send INIT:IMM (that
        command is rejected by the FSP with -200 "Function not available"
        when continuous sweep is already running and is unnecessary anyway
        — the instrument is already sweeping). Instead we issue *OPC? which
        on the FSP holds until all pending operations (i.e. the in-flight
        sweep) complete, giving us a clean boundary at which to read trace
        data. We deliberately do NOT use *WAI here because *WAI in cont
        mode never returns (there's always another sweep pending).

        Single-sweep mode (only if continuous_sweep=False): uses the
        traditional INIT:IMM;*WAI then *OPC? barrier.
        """
        saved = self.inst.timeout
        # Generous timeout: 5 s base + 3x sweep total. *OPC? in cont mode
        # may need to wait for the current sweep to finish.
        eff_ms = max(saved, int(timeout_s * 1000 * 3) + 5000)
        try:
            self.inst.timeout = eff_ms
            if self.continuous_sweep:
                # Just wait for the current sweep to finish. We don't
                # arm anything — the FSP's natural sweep cadence drives
                # acquisition.
                try:
                    self.query("*OPC?")
                except Exception as exc:
                    # *OPC? timeout in cont mode is non-fatal: the trace
                    # buffer still contains the last completed sweep. Log
                    # and proceed.
                    self._log(f"*OPC? in cont mode raised {exc}; proceeding")
                # Drain any unrelated errors that may have queued.
                self._drain_error_queue()
            else:
                self.write("INIT:IMM;*WAI")
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
        # Drain any stale errors BEFORE the read so a -410 "Query interrupted"
        # from a previous failed command can't poison this fetch.
        try:
            stale = self._drain_error_queue()
            if stale:
                self._log(f"drained stale errors before fetch_trace: {stale}")
        except Exception:
            pass
        try:
            self.inst.timeout = eff_ms
            # Force ASCII format every fetch — cheap insurance in case the
            # user (or a previous program) left it in REAL,32 binary mode,
            # which would make our ASCII parsing fail silently / time out.
            try:
                self.inst.write("FORM ASC")
            except Exception:
                pass
            # FSP trace-data fetch syntax — the manual gives several forms
            # and FSP-38 firmware 4.50 has been observed to reject some of
            # them with -100 'Command error'. We try a list of candidates
            # in order, falling through to the next on failure. Once one
            # succeeds we cache it on the instance so subsequent fetches
            # skip straight to the working syntax (no retries on the hot
            # path during recording).
            #
            # Candidates, ordered by manual-stated canonicality:
            #   1. TRAC? TRACE<n>            — the form shown in the
            #      Operating Manual Vol 2 §6.1.13.13 example.
            #   2. TRAC:DATA? TRACE<n>       — explicit :DATA form.
            #   3. TRAC1? TRACE<n>           — explicit window-1 suffix.
            #   4. :TRAC? TRACE<n>           — leading colon (some R&S
            #                                  firmware required this).
            arr = self._fetch_trace_with_syntax_discovery(trace_num)
        finally:
            self.inst.timeout = saved
        return arr

    def _fetch_trace_with_syntax_discovery(
            self, trace_num: int) -> np.ndarray:
        """Try multiple FSP trace-fetch syntaxes until one works; cache the
        winner on the instance for subsequent calls.

        Returns the trace as a numpy float array.
        Raises FSPError if all candidates fail, with the FSP error queue
        contents from each attempt.
        """
        # Build the candidate list. If we've already discovered a working
        # syntax for this session, use it directly — avoids -100 errors
        # piling up in the error queue on every recording capture.
        if self._trace_fetch_cmd_template:
            cmd = self._trace_fetch_cmd_template.format(n=trace_num)
            self._log(f"Q  {cmd}  (cached working syntax)")
            return np.asarray(
                self.inst.query_ascii_values(
                    cmd, container=np.array, separator=","),
                dtype=float)
        # Build candidates. If screen discovery determined Screen B is
        # active, prioritize TRAC2:* (Screen B trace). Otherwise prioritize
        # TRAC1:* / TRAC. We always include all forms as fallbacks because
        # firmware variants accept different spellings.
        if getattr(self, "active_screen", 1) == 2:
            candidates = [
                "TRAC2? TRACE{n}",
                "TRAC2:DATA? TRACE{n}",
                "TRAC? TRACE{n}",
                "TRAC:DATA? TRACE{n}",
                "TRAC1? TRACE{n}",
                ":TRAC2? TRACE{n}",
            ]
        else:
            candidates = [
                "TRAC? TRACE{n}",
                "TRAC:DATA? TRACE{n}",
                "TRAC1? TRACE{n}",
                "TRAC1:DATA? TRACE{n}",
                ":TRAC? TRACE{n}",
                "TRAC2? TRACE{n}",
            ]
        all_errors: List[str] = []
        # During discovery we use a short per-attempt timeout (5 s) so a
        # broken syntax that hangs can't burn 30 s before falling through.
        # The caller (fetch_trace) will already have set a longer timeout
        # for the successful query — but we override it here for discovery
        # only, and restore it before the successful return.
        outer_timeout = self.inst.timeout
        try:
            self.inst.timeout = 5000
            for tmpl in candidates:
                cmd = tmpl.format(n=trace_num)
                self._log(f"Q  {cmd}  (syntax discovery, 5 s cap)")
                # Drain any errors from the previous candidate so they don't
                # contaminate this one's error queue.
                try:
                    self._drain_error_queue()
                except Exception:
                    pass
                try:
                    vals = self.inst.query_ascii_values(
                        cmd, container=np.array, separator=",")
                except Exception as exc:
                    errs = []
                    try:
                        errs = self._drain_error_queue()
                    except Exception:
                        pass
                    self._log(f"  failed: {exc}; FSP errors: {errs}")
                    all_errors.append(
                        f"{tmpl!r}: {exc.__class__.__name__}: {exc}"
                        + (f" | {errs}" if errs else ""))
                    continue
                # Even if no exception, the FSP may have queued -100. Drain
                # and inspect.
                try:
                    errs = self._drain_error_queue()
                except Exception:
                    errs = []
                arr = np.asarray(vals, dtype=float)
                if errs:
                    self._log(f"  returned {arr.size} pts BUT FSP errors: {errs}")
                    all_errors.append(
                        f"{tmpl!r}: returned {arr.size} pts but FSP errors {errs}")
                    continue
                if arr.size == 0:
                    self._log("  returned 0 points (empty)")
                    all_errors.append(f"{tmpl!r}: returned 0 points")
                    continue
                # Success! Cache this template for the rest of the session.
                self._trace_fetch_cmd_template = tmpl
                self._log(f"  SUCCESS: {arr.size} points; caching syntax "
                          f"{tmpl!r} for session")
                return arr
        finally:
            self.inst.timeout = outer_timeout
        # All candidates failed. Raise with the full error log.
        raise FSPError(
            f"All trace-fetch syntaxes failed for trace {trace_num}.\n"
            + "\n".join(f"  - {e}" for e in all_errors))


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
        self.setWindowTitle(f"R&S FSP Trace Logger v{APP_VERSION}")
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

        # Header strip with app title + version
        header = QtWidgets.QHBoxLayout()
        title_lbl = QtWidgets.QLabel("<b>R&amp;S FSP Trace Logger</b>")
        title_lbl.setStyleSheet("font-size: 14pt;")
        header.addWidget(title_lbl)
        header.addStretch(1)
        version_lbl = QtWidgets.QLabel(f"v{APP_VERSION}")
        version_lbl.setStyleSheet("color: #888; font-family: monospace;")
        version_lbl.setToolTip(
            "0.7.0: TRAC? (no :DATA), MODE-based detection, no spin loops.\n"
            "0.6.0: continuous-sweep aware, probe-based trace detection.\n"
            "0.5.0: initial real-FSP version (single-sweep, MODE/STAT detection).")
        header.addWidget(version_lbl)
        root.addLayout(header)

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

        # FSP screen selector. The FSP-38 has two measurement screens
        # (Screen A = WIND1, Screen B = WIND2). SCPI defaults to Screen A;
        # if the user's spectrum config is on Screen B, all FREQ:* / TRAC?
        # queries against Screen A return defaults / -100 errors. The
        # auto-discovery heuristic isn't always reliable (some firmware
        # configurations report 0/2 MHz on both screens), so we expose a
        # manual override here. "Auto" lets the code pick; A/B force.
        cl.addWidget(QtWidgets.QLabel("Screen:"), 2, 0)
        self.screen_auto_rb = QtWidgets.QRadioButton("Auto")
        self.screen_a_rb = QtWidgets.QRadioButton("A")
        self.screen_b_rb = QtWidgets.QRadioButton("B")
        self.screen_auto_rb.setChecked(True)
        self.screen_auto_rb.setToolTip(
            "Auto-detect which FSP screen has the user's spectrum config "
            "(by comparing center frequencies on each screen).")
        self.screen_a_rb.setToolTip(
            "Force SCPI to talk to FSP Screen A (WINDow1).")
        self.screen_b_rb.setToolTip(
            "Force SCPI to talk to FSP Screen B (WINDow2). Use this if "
            "your spectrum trace is on the bottom half of a split screen "
            "or if Auto picked the wrong screen.")
        scr_group = QtWidgets.QButtonGroup(self)
        scr_group.addButton(self.screen_auto_rb)
        scr_group.addButton(self.screen_a_rb)
        scr_group.addButton(self.screen_b_rb)
        scr_row = QtWidgets.QHBoxLayout()
        scr_row.addWidget(self.screen_auto_rb)
        scr_row.addWidget(self.screen_a_rb)
        scr_row.addWidget(self.screen_b_rb)
        scr_row.addStretch(1)
        scr_widget = QtWidgets.QWidget()
        scr_widget.setLayout(scr_row)
        cl.addWidget(scr_widget, 2, 1, 1, 5)

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
        # Probe button — manually re-detects which traces are displayed
        # on the FSP and updates the LEDs. Uses lightweight DISP:TRAC<n>:MODE?
        # queries (a few ms each), so it runs synchronously on the GUI
        # thread without blocking noticeably.
        self.probe_btn = QtWidgets.QPushButton("Probe Traces")
        self.probe_btn.setEnabled(False)
        self.probe_btn.setToolTip(
            "Query the FSP to determine which traces are currently "
            "displayed and update the LEDs.")
        stl.addWidget(self.probe_btn, 0, 4)

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
        self.probe_btn.clicked.connect(self.on_probe_traces)
        self.browse_btn.clicked.connect(self.on_browse)
        self.now_btn.clicked.connect(
            lambda: self.start_dt.setDateTime(QDateTime.currentDateTime()))
        self.start_manual_btn.clicked.connect(lambda: self.on_start(scheduled=False))
        self.start_scheduled_btn.clicked.connect(lambda: self.on_start(scheduled=True))
        self.stop_btn.clicked.connect(self.on_stop)
        # Screen selector: when the user picks Auto / A / B, push the
        # choice to the instrument and refresh sweep settings.
        self.screen_auto_rb.toggled.connect(self._on_screen_changed)
        self.screen_a_rb.toggled.connect(self._on_screen_changed)
        self.screen_b_rb.toggled.connect(self._on_screen_changed)

    # -------- Slots --------
    @Slot()
    def _on_screen_changed(self):
        """Handle a click on the Screen radio group (Auto / A / B).

        Pushes the choice to the FSPInstrument and re-runs sweep_settings
        so the user immediately sees the resulting frequency readback.
        Toggling fires the slot twice (off + on); we no-op the off side.
        """
        sender = self.sender()
        if sender is None or not sender.isChecked():
            return
        if self.instrument is None or not isinstance(self.instrument, FSPInstrument):
            return
        try:
            if self.screen_auto_rb.isChecked():
                self.instrument.reset_screen_discovery()
                self.statusBar().showMessage(
                    "Screen: Auto — will re-detect on next query.", 4000)
            elif self.screen_a_rb.isChecked():
                self.instrument.force_screen(1)
                self.statusBar().showMessage(
                    "Screen: forced to A (WINDow1).", 4000)
            elif self.screen_b_rb.isChecked():
                self.instrument.force_screen(2)
                self.statusBar().showMessage(
                    "Screen: forced to B (WINDow2).", 4000)
            # Refresh sweep readback so the user sees the new frequency.
            try:
                s = self.instrument.sweep_settings()
                self._sweep_settings = s
                fc = s.get("f_center")
                fsp = s.get("f_span")
                src = s.get("freq_source", "?")
                if fc and fc == fc and fc > 0:
                    self.statusBar().showMessage(
                        f"Screen {self.instrument.active_screen}: "
                        f"center={fc/1e6:.3f} MHz, span={fsp/1e6:.3f} MHz "
                        f"({src})", 8000)
            except Exception as exc:
                self.statusBar().showMessage(
                    f"Screen change OK but sweep readback failed: {exc}", 6000)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Screen change failed",
                f"Could not switch FSP screen: {exc}")

    @Slot()
    def on_diagnostics(self):
        """Probe the instrument and show what SCPI is actually returning.

        Wrapped in an outer try/finally that ALWAYS shows the dialog — even
        if the probe code itself crashes — so the user always gets visible
        feedback. Also disables the Diagnostics button for the duration to
        prevent reentrant clicks (processEvents pumping queued clicks during
        the long fetch test was triggering recursive on_diagnostics calls,
        flooding stderr and never letting any single dialog actually open).
        """
        if self.instrument is None:
            return
        # Hard-disable the button so queued clicks can't recurse during
        # processEvents in the fetch-test loop.
        try:
            self.diag_btn.setEnabled(False)
        except Exception:
            pass
        lines: List[str] = []
        try:
            lines.append(f"*IDN?         -> {self.instrument.idn()}")
        except Exception as exc:
            lines.append(f"*IDN?         -> ERROR: {exc}")

        # Sweep mode
        if isinstance(self.instrument, FSPInstrument):
            lines.append("")
            mode_label = "continuous" if self.instrument.continuous_sweep else "single"
            lines.append(f"Sweep handling: {mode_label} ("
                         f"continuous_sweep={self.instrument.continuous_sweep})")

            # Instrument personality — critical for diagnosing the
            # "FREQ:* returns wrong values + TRAC? -100" failure mode, where
            # SCPI is talking to a non-Spectrum-Analyzer personality.
            lines.append("")
            lines.append("Instrument personality (must be SAN for spectrum traces):")
            # NOTE: INST:LIST? is intentionally omitted — on FSP-38 firmware
            # 4.50 it hangs until VI_ERROR_TMO and pollutes the error queue
            # with -113 'Undefined header' for every subsequent query.
            for cmd in ("INST?", "INST:NSEL?"):
                try:
                    ans = self.instrument.inst.query(cmd).strip()
                    errs = self.instrument._drain_error_queue()
                    suffix = f"  [errors: {errs}]" if errs else ""
                    lines.append(f"  {cmd:14s} -> {ans!r}{suffix}")
                except Exception as exc:
                    lines.append(f"  {cmd:14s} -> EXC: {exc}")

            # Show which screen we're currently routing to.
            lines.append(f"  active_screen = {self.instrument.active_screen} "
                         f"(1=A/WIND1, 2=B/WIND2)")

        # Trace detection — lightweight MODE? probe (BLAN = hidden, anything
        # else = displayed). This is the same logic active_traces() uses.
        lines.append("")
        lines.append("Trace mode probe (DISP:TRAC<n>:MODE?  — 'BLAN' means hidden):")
        if isinstance(self.instrument, FSPInstrument):
            inst = self.instrument
            saved = inst.inst.timeout
            try:
                inst.inst.timeout = max(2000, int(saved or 0))
                for n in (1, 2, 3):
                    cmd = f"DISP:TRAC{n}:MODE?"
                    t0 = time.perf_counter()
                    err_msg = ""
                    ans = ""
                    try:
                        ans = inst.inst.query(cmd).strip()
                    except Exception as exc:
                        err_msg = f" EXC={exc.__class__.__name__}"
                    dt = time.perf_counter() - t0
                    errs = inst._drain_error_queue()
                    norm = ans.upper().strip('"').strip("'")
                    decision = ("hidden" if (not norm or norm.startswith("BLAN"))
                                else "DISPLAYED")
                    err_suffix = f"  errs={errs}" if errs else ""
                    lines.append(
                        f"  DISP:TRAC{n}:MODE? -> {ans!r:>10s} in "
                        f"{dt*1000:.0f} ms{err_msg}  =>  {decision}{err_suffix}"
                    )
                # Reference: STAT? readings for the curious. Cheap.
                lines.append("")
                lines.append("Reference (DISP:TRAC<n>:STAT? — only flags currently selected):")
                for n in (1, 2, 3):
                    cmd = f"DISP:TRAC{n}:STAT?"
                    try:
                        ans = inst.inst.query(cmd).strip()
                        errs = inst._drain_error_queue()
                        suffix = f"  [errors: {errs}]" if errs else ""
                        lines.append(f"  {cmd:25s} -> {ans!r}{suffix}")
                    except Exception as exc:
                        lines.append(f"  {cmd:25s} -> EXC: {exc}")
            finally:
                inst.inst.timeout = saved
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

        # NOTE: We deliberately do NOT run an end-to-end fetch test here.
        # Doing so on the GUI thread (or even via a worker thread with a
        # processEvents spin loop on the GUI thread) was killing the Spyder
        # kernel — the spin loop starves Spyder's heartbeat. The lightweight
        # MODE? probe and sweep-settings query above are sufficient diagnostic
        # info for nearly every troubleshooting case. If the user needs a
        # full fetch test, they can simply press Start (which uses worker
        # threads properly via QThread/moveToThread).
        lines.append("")
        lines.append("(Skipping end-to-end fetch test — use Start to record.)")

        # ALWAYS show a dialog — even if the probe above blew up.
        try:
            if not lines:
                lines = ["Diagnostics produced no output."]
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("FSP Diagnostics")
            dlg.resize(820, 620)
            dlg.setModal(True)
            v = QtWidgets.QVBoxLayout(dlg)
            text = QtWidgets.QPlainTextEdit("\n".join(lines))
            text.setReadOnly(True)
            text.setFont(QtGui.QFont("Monospace"))
            text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            v.addWidget(text)
            btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            btns.accepted.connect(dlg.accept)
            v.addWidget(btns)
            # Force the dialog to the front so it can't get hidden behind
            # the IDE / main window on Windows.
            dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            (dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec())
        except Exception as exc:
            # Last-ditch fallback: at least pop a message box.
            try:
                QtWidgets.QMessageBox.critical(
                    self, "FSP Diagnostics (fallback)",
                    "Diagnostics dialog failed to open.\n\n"
                    f"Reason: {exc}\n\n"
                    + "\n".join(lines[-30:]))
            except Exception:
                pass
        finally:
            try:
                self.diag_btn.setEnabled(True)
            except Exception:
                pass

    @Slot()
    def on_probe_traces(self):
        """Probe the FSP for currently displayed traces and update the LEDs.

        With MODE-based detection this is fast (3 short queries + sweep
        settings, total ~10–20 ms on a healthy connection), so we run it
        synchronously on the GUI thread — no worker thread, no processEvents
        spin loop. (The previous spin-loop pattern was the actual cause of
        Spyder kernel deaths because it starved the kernel's heartbeat.)
        """
        if self.instrument is None:
            return
        self.probe_btn.setEnabled(False)
        original_status = self.status_label.text()
        self.status_label.setText("Probing traces…")
        QtWidgets.QApplication.processEvents()  # one paint, no loop
        try:
            try:
                self._sweep_settings = self.instrument.sweep_settings()
            except Exception as exc:
                self._sweep_settings = None
                self._log_status(f"Sweep query failed during probe: {exc}")
            try:
                self._active_traces = self.instrument.active_traces()
            except Exception as exc:
                self._active_traces = []
                QtWidgets.QMessageBox.warning(
                    self, "Probe failed",
                    f"{exc.__class__.__name__}: {exc}")
                self.status_label.setText(original_status)
                return
            self._update_trace_leds(self._active_traces)
            s = self._sweep_settings
            if isinstance(s, dict):
                self.status_label.setText(
                    f"Probe complete. Sweep: {s['f_start']/1e6:.3f}–"
                    f"{s['f_stop']/1e6:.3f} MHz, {int(s['n_pts'])} pts, "
                    f"sweep_time={s['sweep_time']*1000:.1f} ms. "
                    f"Active traces: {self._active_traces or 'none'}."
                )
            else:
                self.status_label.setText(
                    f"Probe complete. Active traces: "
                    f"{self._active_traces or 'none'}."
                )
        finally:
            self.probe_btn.setEnabled(True)

    def _log_status(self, msg: str) -> None:
        """Best-effort: write a non-fatal status note to stderr."""
        try:
            sys.stderr.write(f"[fsp_logger] {msg}\n")
        except Exception:
            pass

    @Slot()
    def on_browse(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Choose output CSV", self.file_edit.text(),
            "CSV files (*.csv);;All files (*)")
        if path:
            self.file_edit.setText(path)

    @Slot()
    def on_connect(self):
        """Connect to the instrument with minimal SCPI traffic.

        Important on Spyder: this runs on the main (GUI) thread, which is
        also the thread Spyder's kernel uses for its heartbeat. A long
        synchronous SCPI operation here can cause Spyder to declare the
        kernel dead and kill it. We therefore do the bare minimum:
          1. Open the VISA resource (fast, local).
          2. Query *IDN? once (one short round-trip).
          3. Query sweep settings (5 short round-trips).
        We do NOT probe traces on connect — that requires reading 501
        floats per trace and can take seconds. The user can press
        Diagnostics or Start to trigger probing on demand.
        """
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
            # Step 1: identify the instrument. Just one short query.
            idn = self.instrument.idn()
            self.idn_label.setText(idn)
            self.idn_label.setStyleSheet("color: #2ecc71;")
            # Step 2: read sweep settings (cheap). Skip trace probing here.
            try:
                self._sweep_settings = self.instrument.sweep_settings()
                s = self._sweep_settings
                self.status_label.setText(
                    f"Connected. Sweep: {s['f_start']/1e6:.3f}–"
                    f"{s['f_stop']/1e6:.3f} MHz, {int(s['n_pts'])} pts, "
                    f"sweep_time={s['sweep_time']*1000:.1f} ms. "
                    f"(Trace LEDs will populate on Start or Diagnostics.)"
                )
            except Exception as exc:
                self.status_label.setText(
                    f"Connected, but sweep query failed: {exc}")
            # Trace LEDs: leave dim until the user actively probes.
            self._active_traces = []
            self._update_trace_leds([])

            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.diag_btn.setEnabled(True)
            self.probe_btn.setEnabled(True)
            self.start_manual_btn.setEnabled(True)
            self.start_scheduled_btn.setEnabled(True)
            self.demo_check.setEnabled(False)
            self.resource_edit.setEnabled(False)
            self.backend_combo.setEnabled(False)
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
        self.probe_btn.setEnabled(False)
        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.demo_check.setEnabled(True)
        self.resource_edit.setEnabled(True)
        self.backend_combo.setEnabled(True)
        for led in (self.led_t1, self.led_t2, self.led_t3):
            led.setOn(False)
        self.status_label.setText("Disconnected.")

    def _refresh_instrument_state(self):
        # Sweep settings: cheap and essential. If this fails, we surface a
        # warning but don't break the connection.
        try:
            self._sweep_settings = self.instrument.sweep_settings()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Sweep query failed",
                f"Could not read sweep settings: {exc}\n\n"
                "You can still try Diagnostics or recording.")
            self._sweep_settings = None
        # Active traces: probe-based and slower. Non-fatal if it fails —
        # the user can configure traces and retry, or just hit Diagnostics.
        try:
            self._active_traces = self.instrument.active_traces()
        except Exception as exc:
            self._active_traces = []
            self.status_label.setText(
                f"Trace detection failed: {exc} — try Diagnostics.")
        self._update_trace_leds(self._active_traces)
        s = self._sweep_settings
        if s:
            self.status_label.setText(
                f"Sweep: {s['f_start']/1e6:.3f}–{s['f_stop']/1e6:.3f} MHz, "
                f"{int(s['n_pts'])} pts, sweep_time={s['sweep_time']*1000:.1f} ms × "
                f"count={int(s['sweep_count'])} (total {s['sweep_time']*s['sweep_count']*1000:.1f} ms),"
                f" traces={self._active_traces}"
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
