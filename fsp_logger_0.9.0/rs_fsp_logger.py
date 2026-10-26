#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
R&S FSP Spectrum Analyzer Trace Logger
======================================
===============================================================================
 Title          : R&S FSP Spectrum Analyzer Trace Logger
 Filename       : rs_fsp_logger.py
 Version        : 0.9.0 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Modified       : 2026-10-26
 Language       : Python 3.8 through 3.12 (tested endpoints)
 Requires       : See requirements.txt; optional standalone Veusz for PDF/PNG
 Companions     : fsp_background 0.2.0, fsp_reports 0.1.4, vszh5_writer 0.0.18,
                  fsp_simulator 0.0.1
 Licence        : Supplied logger's license not declared; no grant inferred.
 Attribution    : Author/contact copied from supplied writer at user's request;
                  this integration includes AI-generated modifications.
===============================================================================

REVISION HISTORY (newest first)
----------------
0.9.0  2026-10-26
       NEW  Reset Active Traces (button, F7, Acquisition/Tools menus,
            toolbar): every displayed trace of the selected screen is set
            to Clear/Write (DISP:WIND<s>:TRAC<n>:MODE WRIT) and back to its
            own mode, restarting max hold / min hold / average; View traces
            are re-frozen after one fresh sweep. Idle: own worker thread;
            recording: served by the acquisition worker between captures
            and logged to <csv>_events.csv. Optional confirmation prompt.
       FIX  Screen/trace mismatch that needed the Auto / A / B buttons to be
            toggled before the right traces were read:
            (1) trace modes were read with DISP:TRAC<n>:MODE?, which has no
                WINDow suffix and therefore always addresses Screen A, even
                when sweep settings and data came from Screen B; now
                DISP:WIND<s>:TRAC<n>:MODE? of the selected screen;
            (2) the Screen choice was only applied on a button toggle, so a
                new connection ran Auto even with A or B shown; it is now
                applied at connect;
            (3) Auto detected the screen once per connection; it now
                re-detects at connect, Probe, Start, Diagnostics and Reset
                (never between captures);
            (4) the trace-fetch syntax could fall back to the other screen
                (TRAC? / TRAC1? for Screen B, TRAC2? for Screen A) and was
                cached across a screen change; fetch forms and the cache are
                now per screen.
       NEW  Demo Mode runs the real FSPInstrument over fsp_simulator (two
            screens, trace modes); "In use: Screen X (auto/forced)" label;
            LED tooltips show each trace's mode; Diagnostics compares both
            screens; trace LEDs fill at connect; About reads module versions.
0.8.3: All-bin Freq_N_GHz and Combined_Freq_vs_Time native datetime plots;
       retain every prior plot. Full text menu/toolbar, dark/light/system
       display themes, persistent preference and author/About information.
0.8.1: Isolated reporting, bounded async CSV, coalesced live display, serial
       VISA ownership, cooperative stop/drain/close and reciprocal interlocks.

Processing policy
-----------------
Reports NEVER run during sampling, scheduled waiting or CSV draining.
Sampling is disabled while reports run. This protects this instance, not
other applications or hard-real-time deadlines. Numerical per-channel work
is parallel; VISA access is intentionally serial in one acquisition worker.


Connects to a Rohde & Schwarz FSP-series spectrum analyzer over Ethernet (VISA TCPIP),
detects active traces, waits for the running sweep to finish, then captures every
N seconds and writes a CSV row per (frequency, capture) sample.
Each run creates/replaces the selected CSV; it does not append to prior runs.

CSV layout (one row per frequency point, per capture):
    date, time, timestamp_iso, freq_hz, trace1_dBm, trace2_dBm, trace3_dBm, ...
Only columns for traces that were active at the start of the run are included.

Features
--------
* QtPy abstraction layer (packaged/tested with PyQt5)
* Filename field, planned start time, manual Start, Stop
* Active-trace LEDs (1, 2, 3) + Recording LED (tooltips give each mode)
* Screen A / B / Auto selection, applied at connect, with an "In use" label
* Reset Active Traces: Clear/Write, then each trace's own mode (0.9.0)
* Per-capture progress bar (driven by sweep time)
* Live plot of last captured traces (pyqtgraph)
* Sanity check: ensures N >= sweep_time * sweep_count (+ safety margin),
  with a warning dialog quoting the minimum allowed N
* Demo mode: the real instrument code over a simulated two-screen FSP
  session (fsp_simulator.py), synthetic data only

Python: written for 3.8+; auto-detects 3.12 and uses faster paths where it helps.

Dependencies:
    pip install -r requirements.txt
"""

from __future__ import annotations

import math
import os
import importlib.util
import json
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from fsp_background import AsyncCaptureCsvWriter, CaptureEventLog, LatestCaptureMailbox
from fsp_simulator import SimulatedFSPSession

# ---------------------------------------------------------------------------
# %% Version
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
# 0.9.0 — Reset Active Traces; trace modes and data read from the selected
#         screen; Screen choice applied at connect; Auto re-detects on refresh.
APP_VERSION = "0.9.0"
APP_DATE = "2026-10-26"

# ---------------------------------------------------------------------------
# %% Python version handling
# ---------------------------------------------------------------------------
PY_VERSION = sys.version_info
IS_PY312_PLUS = PY_VERSION >= (3, 12)
if PY_VERSION < (3, 8):
    sys.stderr.write("This program requires Python 3.8 or newer.\n")
    sys.exit(1)

# perf_counter_ns is available since 3.7; on 3.12 it has slightly lower overhead.
_perf = time.perf_counter

# ---------------------------------------------------------------------------
# %% Qt imports via QtPy
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
# %% Instrument abstraction
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
                 continuous_sweep: bool = True, session=None):
        """Open the VISA resource (or adopt ``session``).

        ``session`` (0.9.0) is an already-open message-based resource with
        pyvisa's write/query/query_ascii_values/timeout interface - Demo Mode
        passes fsp_simulator.SimulatedFSPSession here, so Demo and the tests
        run this real class rather than a separate mock. pyvisa is then not
        needed.
        """
        if session is None and not _HAS_PYVISA:
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
        # 0.9.0: cached per screen, {screen: template}, so a template found
        # on Screen A can never be reused for Screen B (0.8.3 kept one
        # template across an automatic screen change and read Screen A).
        self._trace_fetch_templates: Dict[int, str] = {}
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
        # 0.9.0: what the user selected - "auto" (re-detected at every
        # connect / probe / start / reset / diagnostics) or 1 / 2 (forced).
        self.screen_mode = "auto"
        # Which DISPlay header form answered MODE? per screen ("window" =
        # DISP:WIND<n>:TRAC<t>, "plain" = DISP:TRAC<t>, Screen A only).
        self._mode_query_style: Dict[int, str] = {}
        # Last trace modes read, {trace: token or None}, and their screen.
        self.last_trace_modes: Dict[int, Optional[str]] = {}
        self.last_trace_modes_screen: int = 1
        # Frequencies read on both screens by the last auto-detection.
        self.last_screen_probe: Dict[int, Dict[str, float]] = {}
        # Sweep time x count from the last sweep_settings() (reset dwell).
        self._last_sweep_total_s: Optional[float] = None
        if session is not None:
            self.rm = None
            self.inst = session
            self._configured = False
            return

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
        if self.rm is not None:
            try: self.rm.close()
            except Exception: pass

    # ---- high level ----------------------------------------------------
    def idn(self) -> str:
        return self.query("*IDN?")

    # ---- trace modes, routed to the selected screen (0.9.0) ------------
    #: Short-form trace modes the FSP reports for ...:TRAC<t>:MODE?.
    MODE_TOKENS = ("WRIT", "VIEW", "AVER", "MAXH", "MINH", "BLAN")
    #: Readable names for status text and the reset confirmation.
    MODE_NAMES = {"WRIT": "Clear/Write", "VIEW": "View", "AVER": "Average",
                  "MAXH": "Max Hold", "MINH": "Min Hold", "BLAN": "Blank"}

    @classmethod
    def normalize_mode(cls, answer: Optional[str]) -> Optional[str]:
        """Short token for a MODE? answer ('MAXH', 'MAXHOLD', '"WRIT"' ...).

        Unknown non-empty answers are returned cleaned but unchanged; an
        empty answer gives None.
        """
        if answer is None:
            return None
        text = str(answer).strip().strip('"').strip("'").strip().upper().lstrip("+")
        if not text:
            return None
        for token in cls.MODE_TOKENS:
            if text.startswith(token):
                return token
        return text

    @staticmethod
    def screen_letter(screen: Optional[int]) -> str:
        """1 -> 'A', 2 -> 'B'."""
        return "B" if screen == 2 else "A"

    def _trace_header(self, trace: int, screen: Optional[int] = None,
                      style: str = "window") -> str:
        """DISPlay header of one trace on one screen.

        'window' gives DISP:WIND<s>:TRAC<t>, the form whose WINDow<1|2>
        suffix selects Screen A or B (FSP manual, DISPlay[:WINDow<1|2>]
        commands). 'plain' gives DISP:TRAC<t>; an omitted numeric suffix is
        interpreted as suffix 1, so it reaches Screen A only and is never
        used for Screen B. 0.8.3 used the plain form for every screen,
        which is why the detected traces were always Screen A's.
        """
        number = self.active_screen if screen is None else int(screen)
        if style == "plain":
            if number != 1:
                raise ValueError("DISP:TRAC<t> without WINDow addresses Screen A only")
            return f"DISP:TRAC{int(trace)}"
        return f"DISP:WIND{number}:TRAC{int(trace)}"

    def _mode_styles(self, screen: int) -> List[str]:
        """Header forms to try for a screen, the last one that worked first."""
        styles = ["window", "plain"] if screen == 1 else ["window"]
        known = self._mode_query_style.get(screen)
        if known in styles:
            styles.remove(known)
            styles.insert(0, known)
        return styles

    def _safe_drain(self) -> List[str]:
        try:
            return self._drain_error_queue()
        except Exception:
            return []

    def trace_mode(self, trace: int, screen: Optional[int] = None) -> Optional[str]:
        """Mode token of one trace on one screen (default: selected screen).

        Returns None when no header form is answered.
        """
        number = self.active_screen if screen is None else int(screen)
        for style in self._mode_styles(number):
            cmd = self._trace_header(trace, number, style) + ":MODE?"
            try:
                answer = self.query(cmd)
            except Exception as exc:
                self._log(f"{cmd} raised {exc}")
                self._safe_drain()
                continue
            token = self.normalize_mode(answer)
            errors = self._safe_drain()
            if token:
                self._mode_query_style[number] = style
                return token
            if errors:
                self._log(f"{cmd} rejected: {errors}")
        return None

    def _trace_state_flag(self, trace: int, screen: int) -> Optional[bool]:
        """DISP[:WIND<s>]:TRAC<t>:STAT? as True/False, None if unanswered.

        Only a fallback for firmware that does not answer MODE?.
        """
        for style in self._mode_styles(screen):
            cmd = self._trace_header(trace, screen, style) + ":STAT?"
            try:
                answer = (self.query(cmd) or "").strip().upper().lstrip("+")
            except Exception as exc:
                self._log(f"{cmd} raised {exc}")
                self._safe_drain()
                continue
            self._safe_drain()
            if answer in ("1", "ON"):
                return True
            if answer in ("0", "OFF"):
                return False
        return None

    def trace_modes(self, screen: Optional[int] = None) -> Dict[int, Optional[str]]:
        """{trace: mode token or None} for traces 1..3 of one screen.

        Each MODE? returns a few bytes; the timeout is capped at 2 s so a
        rejected form cannot stall the caller.
        """
        number = self.active_screen if screen is None else int(screen)
        saved = self.inst.timeout
        try:
            self.inst.timeout = 2000
            return {n: self.trace_mode(n, number) for n in range(1, self.MAX_TRACES + 1)}
        finally:
            self.inst.timeout = saved

    def active_traces(self) -> List[int]:
        """
        Trace numbers (1..3) displayed on the SELECTED screen.

        A trace is displayed when DISP:WIND<s>:TRAC<n>:MODE? answers
        anything other than BLAN (WRIT, MAXH, MINH, AVER, VIEW). Max-hold
        and average traces count: on FSP firmware they can report STAT? = 0.
        When MODE? is not answered the STAT? flag is used instead.

        0.9.0: the query carries the WINDow suffix of the selected screen
        (and, in Auto, the screen is detected first), so Screen B's traces
        are read from Screen B. Cheap (three ~5-byte answers), so it may run
        on the GUI thread as before.

        Raises FSPError when no trace on the selected screen answers at all,
        instead of reporting "no traces".
        """
        self._discover_active_screen()
        stale = self._safe_drain()
        if stale:
            self._log(f"drained stale errors before active_traces: {stale}")
        number = self.active_screen
        saved = self.inst.timeout
        modes: Dict[int, Optional[str]] = {}
        active: List[int] = []
        unanswered = 0
        try:
            self.inst.timeout = 2000
            for n in range(1, self.MAX_TRACES + 1):
                token = self.trace_mode(n, number)
                modes[n] = token
                if token is not None:
                    shown = not token.startswith("BLAN")
                else:
                    flag = self._trace_state_flag(n, number)
                    if flag is None:
                        unanswered += 1
                    shown = bool(flag)
                self._log(f"screen {self.screen_letter(number)} trace {n}: MODE={token!r} => "
                          f"{'DISPLAYED' if shown else 'hidden'}")
                if shown:
                    active.append(n)
            self._safe_drain()
        finally:
            self.inst.timeout = saved
        self.last_trace_modes = modes
        self.last_trace_modes_screen = number
        if unanswered == self.MAX_TRACES:
            raise FSPError(
                f"No trace mode could be read on Screen {self.screen_letter(number)} "
                f"(DISP:WIND{number}:TRAC<n>:MODE? and :STAT? unanswered). "
                "Run Diagnostics, or select the other screen.")
        return active

    # ---- screen selection ------------------------------------------------
    def set_screen_mode(self, mode) -> None:
        """Apply the GUI's Screen choice: 'auto', 1 or 'A', 2 or 'B'.

        0.9.0: the GUI calls this right after connecting as well as on every
        change, so the radio button that is shown is the one in force (0.8.3
        ignored a choice made before Connect until the buttons were toggled).
        """
        key = str(mode).strip().upper()
        if key in ("AUTO", ""):
            self.reset_screen_discovery()
        elif key in ("1", "A"):
            self.force_screen(1)
        elif key in ("2", "B"):
            self.force_screen(2)
        else:
            raise ValueError(f"screen mode must be auto, A or B, got {mode!r}")

    def force_screen(self, screen: int) -> None:
        """Force SCPI to address a specific FSP screen (1=A, 2=B).

        On FSP, the SENSe<1|2>: numeric suffix routes per-query to a
        specific measurement window — this is independent of which window
        is the "active measurement window" (DISP:WIND:SEL state). So
        forcing a screen is just a matter of recording which suffix
        to use; subsequent FREQ:* / SWE:* / DISP:WIND<n>:TRAC / TRAC<n>?
        queries are built with the right suffix.

        Trace-fetch templates are cached per screen (0.9.0), so nothing
        found for one screen is reused on the other.
        """
        if screen not in (1, 2):
            raise ValueError(f"screen must be 1 or 2, got {screen}")
        self._log(f"force_screen({screen}): SCPI will now use "
                  f"{self._scpi_screen_prefix(screen) or '(no prefix = SENS1)'} "
                  f"for FREQ/SWE and DISP:WIND{screen} for trace modes")
        self.screen_mode = screen
        self.active_screen = screen
        self._screen_discovered = True

    def reset_screen_discovery(self) -> None:
        """Return to Auto: the next screen-routed query re-runs detection."""
        self.screen_mode = "auto"
        self._screen_discovered = False
        self.active_screen = 1

    def refresh_screen_selection(self) -> None:
        """Auto only: forget the last detection so the next query repeats it.

        Called at connect, Probe, Start, Diagnostics and Reset, so a screen
        changed on the analyzer's front panel is followed without toggling
        the Screen buttons (0.8.3 detected once per connection). Never
        called between captures, so a recording keeps one screen. A forced
        A or B is left unchanged.
        """
        if self.screen_mode == "auto":
            self._screen_discovered = False

    @property
    def screen_description(self) -> str:
        """e.g. 'Screen B (auto)' or 'Screen A (forced)'."""
        how = "auto" if self.screen_mode == "auto" else "forced"
        return f"Screen {self.screen_letter(self.active_screen)} ({how})"

    @property
    def _trace_fetch_cmd_template(self) -> Optional[str]:
        """Cached trace-fetch syntax of the selected screen (read-only view
        kept for diagnostics and pre-0.9.0 callers)."""
        return self._trace_fetch_templates.get(self.active_screen)

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

        Sets self.active_screen to 1 or 2. Nothing is written to the
        analyzer: every later query carries the screen's own suffix
        (SENS<n>:, DISP:WIND<n>:, TRAC<n>?), so DISP:WIND<n>:SEL is not
        needed. With both screens configured, the heuristic can pick the
        screen you are NOT using; force A or B in that case.
        """
        if self._screen_discovered:
            return
        self._screen_discovered = True   # set first to prevent recursion
        previous = self.active_screen
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
        self.last_screen_probe = {1: dict(a), 2: dict(b)}
        if score_b > score_a:
            self.active_screen = 2
            self._log(f"  => Screen B wins (center {b['f_center']} > "
                      f"{a['f_center']}); active_screen = 2")
        else:
            self.active_screen = 1
            self._log(f"  => Screen A wins; active_screen = 1")
        if self.active_screen != previous:
            self._log(f"  screen changed {self.screen_letter(previous)} -> "
                      f"{self.screen_letter(self.active_screen)}")

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
        self._last_sweep_total_s = float(sweep_time) * int(sweep_count)
        return dict(f_start=f_start, f_stop=f_stop, n_pts=n_pts,
                    sweep_time=sweep_time, sweep_count=sweep_count,
                    f_center=f_center, f_span=f_span,
                    f_start_raw=f_start_raw, f_stop_raw=f_stop_raw,
                    freq_source=freq_source,
                    active_screen=self.active_screen,
                    screen_mode=self.screen_mode)

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

    #: Trace-data query forms per screen. TRACe<1|2> selects the screen and
    #: an omitted suffix counts as 1 (Screen A). 0.9.0: Screen B is never
    #: read through an unsuffixed or TRAC1 form and Screen A never through
    #: TRAC2, so a failing query cannot silently return the other screen's
    #: trace (0.8.3 fell back across screens and cached the result).
    TRACE_FETCH_CANDIDATES = {
        1: ("TRAC? TRACE{n}", "TRAC:DATA? TRACE{n}", "TRAC1? TRACE{n}",
            "TRAC1:DATA? TRACE{n}", ":TRAC? TRACE{n}"),
        2: ("TRAC2? TRACE{n}", "TRAC2:DATA? TRACE{n}", ":TRAC2? TRACE{n}",
            ":TRAC2:DATA? TRACE{n}"),
    }

    def _fetch_trace_with_syntax_discovery(
            self, trace_num: int) -> np.ndarray:
        """Try the selected screen's trace-fetch syntaxes until one works;
        cache the winner for that screen.

        Returns the trace as a numpy float array.
        Raises FSPError if all candidates fail, with the FSP error queue
        contents from each attempt.
        """
        screen = self.active_screen if self.active_screen in (1, 2) else 1
        # A syntax already found for this screen is used directly — avoids
        # -100 errors piling up in the error queue on every capture.
        cached = self._trace_fetch_templates.get(screen)
        if cached:
            cmd = cached.format(n=trace_num)
            self._log(f"Q  {cmd}  (cached working syntax, screen {self.screen_letter(screen)})")
            return np.asarray(
                self.inst.query_ascii_values(
                    cmd, container=np.array, separator=","),
                dtype=float)
        candidates = self.TRACE_FETCH_CANDIDATES[screen]
        all_errors: List[str] = []
        # During discovery we use a short per-attempt timeout (5 s) so a
        # broken syntax that hangs can't burn 30 s before falling through.
        outer_timeout = self.inst.timeout
        try:
            self.inst.timeout = 5000
            for tmpl in candidates:
                cmd = tmpl.format(n=trace_num)
                self._log(f"Q  {cmd}  (syntax discovery, 5 s cap)")
                self._safe_drain()
                try:
                    vals = self.inst.query_ascii_values(
                        cmd, container=np.array, separator=",")
                except Exception as exc:
                    errs = self._safe_drain()
                    self._log(f"  failed: {exc}; FSP errors: {errs}")
                    all_errors.append(
                        f"{tmpl!r}: {exc.__class__.__name__}: {exc}"
                        + (f" | {errs}" if errs else ""))
                    continue
                # Even if no exception, the FSP may have queued -100.
                errs = self._safe_drain()
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
                self._trace_fetch_templates[screen] = tmpl
                self._log(f"  SUCCESS: {arr.size} points; caching syntax "
                          f"{tmpl!r} for screen {self.screen_letter(screen)}")
                return arr
        finally:
            self.inst.timeout = outer_timeout
        raise FSPError(
            f"All Screen {self.screen_letter(screen)} trace-fetch syntaxes failed "
            f"for trace {trace_num}.\n"
            + "\n".join(f"  - {e}" for e in all_errors))

    # ---- trace reset (0.9.0) ---------------------------------------------
    #: Longest wait for a fresh sweep before a View trace is frozen again.
    RESET_VIEW_SETTLE_MAX_S = 60.0

    def _sweep_total_s(self) -> float:
        """Sweep time x count of the selected screen (cached when known)."""
        if self._last_sweep_total_s is not None:
            return float(self._last_sweep_total_s)
        prefix = self._scpi_screen_prefix()
        try:
            sweep_time = float(self.query(f"{prefix}SWE:TIME?"))
        except Exception:
            sweep_time = 1.0
        try:
            count = max(1, int(float(self.query(f"{prefix}SWE:COUN?"))))
        except Exception:
            count = 1
        self._last_sweep_total_s = sweep_time * count
        return self._last_sweep_total_s

    @staticmethod
    def _sleep_interruptible(seconds: float, stop_event=None) -> None:
        end = time.perf_counter() + max(0.0, float(seconds))
        while time.perf_counter() < end:
            if stop_event is not None and stop_event.is_set():
                return
            time.sleep(max(0.0, min(0.05, end - time.perf_counter())))

    def reset_active_traces(self, traces: Optional[Sequence[int]] = None,
                            stop_event=None,
                            view_settle_s: Optional[float] = None) -> List[Dict[str, object]]:
        """Restart every displayed trace of the selected screen.

        Each displayed trace is switched to Clear/Write
        (DISP:WIND<s>:TRAC<n>:MODE WRIT) and then back to the mode it had
        (MAXH, MINH, AVER, VIEW; a WRIT trace stays WRIT). Leaving and
        re-entering Max Hold, Min Hold or Average restarts the accumulation
        on the analyzer, so this is the remote equivalent of pressing
        CLEAR/WRITE and then the trace's own mode again. Blank traces are not
        touched; the sweep, frequency and level settings are not changed.

        View traces are frozen copies: after WRIT the analyzer needs one full
        sweep before VIEW is restored, or the frozen trace would hold part of
        a sweep. When a View trace is present this waits sweep time x count
        (+10 %, at most RESET_VIEW_SETTLE_MAX_S, or ``view_settle_s``) and a
        sweep boundary (*OPC?). Without View traces the restore follows at
        once.

        Must run on the thread that owns this VISA session (the acquisition
        worker while recording, a short-lived worker when idle).

        Parameters
        ----------
        traces:
            Trace numbers to reset; default: every displayed trace.
        stop_event:
            threading.Event that cuts a View settle wait short.
        view_settle_s:
            Override of the View settle wait, in seconds.

        Returns
        -------
        list of dict
            One per trace: trace, screen ('A'/'B'), original, restored,
            ok (restored == original) and note (problems, if any).

        Raises
        ------
        FSPError
            No trace mode could be read on the selected screen.
        """
        self._discover_active_screen()
        number = self.active_screen
        stale = self._safe_drain()
        if stale:
            self._log(f"drained stale errors before reset: {stale}")
        modes = self.trace_modes(number)
        if all(mode is None for mode in modes.values()):
            raise FSPError(f"No trace mode could be read on Screen {self.screen_letter(number)}; "
                           "nothing was changed.")
        if traces is None:
            targets = [n for n, mode in sorted(modes.items()) if mode and not mode.startswith("BLAN")]
        else:
            targets = sorted({int(n) for n in traces})
        results: List[Dict[str, object]] = []
        switched: List[Tuple[Dict[str, object], str]] = []
        saved = self.inst.timeout
        try:
            self.inst.timeout = 5000
            for n in targets:
                original = modes.get(n)
                entry: Dict[str, object] = dict(trace=n, screen=self.screen_letter(number),
                                                original=original, restored=original,
                                                ok=False, note="")
                results.append(entry)
                if original is None:
                    entry["note"] = "mode unreadable; left unchanged"
                    continue
                if original == "BLAN":
                    entry.update(ok=True, note="blank; left unchanged")
                    continue
                if original not in self.MODE_TOKENS:
                    entry["note"] = f"unknown mode {original!r}; left unchanged"
                    continue
                header = self._trace_header(n, number, self._mode_query_style.get(number, "window"))
                try:
                    self.write(f"{header}:MODE WRIT")
                    switched.append((entry, header))
                except Exception as exc:
                    entry["note"] = f"WRIT not accepted: {exc}"
            errors = self._safe_drain()
            if errors:
                for entry, _header in switched:
                    entry["note"] = f"errors after WRIT: {errors}"
            if any(entry["original"] == "VIEW" for entry, _header in switched):
                total = self._sweep_total_s()
                wait = (view_settle_s if view_settle_s is not None
                        else min(self.RESET_VIEW_SETTLE_MAX_S, 1.1 * total + 0.1))
                self._sleep_interruptible(wait, stop_event)
                try:
                    self.trigger_and_wait(max(0.05, total))
                except Exception as exc:
                    self._log(f"sweep boundary before VIEW restore failed: {exc}")
            for entry, header in switched:
                if entry["original"] != "WRIT":
                    try:
                        self.write(f"{header}:MODE {entry['original']}")
                    except Exception as exc:
                        entry["note"] = f"restore not accepted: {exc}"
            errors = self._safe_drain()
            for entry, _header in switched:
                now = self.trace_mode(int(entry["trace"]), number)
                entry["restored"] = now
                entry["ok"] = now == entry["original"]
                if errors:
                    entry["note"] = (str(entry["note"]) + f" errors after restore: {errors}").strip()
                if not entry["ok"] and not entry["note"]:
                    entry["note"] = f"reads back {now!r}, expected {entry['original']!r}"
        finally:
            self.inst.timeout = saved
        self.last_trace_modes = dict(modes)
        self.last_trace_modes_screen = number
        return results


# ===========================================================================
# Legacy mock instrument (kept for scripts; Demo Mode no longer uses it)
# ===========================================================================
# %% LEGACY MOCK INSTRUMENT
class MockFSPInstrument:
    """
    Single-screen stand-in kept for scripts that construct it directly.

    0.9.0: Demo Mode no longer uses this class. It runs the real
    FSPInstrument over fsp_simulator.SimulatedFSPSession (two screens, trace
    modes, error queue), so screen selection and the trace reset are
    exercised by the same code as on hardware. The screen and reset methods
    below only keep this class interface-compatible with the GUI.
    """
    MAX_TRACES = 3
    _MOCK_MODES = {1: "WRIT", 2: "MAXH", 3: "AVER"}

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
        self.active_screen = 1
        self.screen_mode = "auto"
        self.last_trace_modes = {n: (self._MOCK_MODES[n] if n in self._active else "BLAN")
                                 for n in (1, 2, 3)}
        self.last_trace_modes_screen = 1

    # interface compatibility
    @property
    def screen_description(self) -> str:
        return "Screen A (single-screen mock)"

    def set_screen_mode(self, mode) -> None:
        self.screen_mode = "auto" if str(mode).upper() in ("AUTO", "") else str(mode)

    def refresh_screen_selection(self) -> None:
        pass

    def reset_active_traces(self, traces=None, stop_event=None, view_settle_s=None):
        targets = list(self._active) if traces is None else [int(n) for n in traces]
        return [dict(trace=n, screen="A", original=self.last_trace_modes.get(n),
                     restored=self.last_trace_modes.get(n), ok=True, note="mock: no instrument")
                for n in targets]

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
# %% Acquisition worker (runs in a QThread)
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
    traceResetFinished = Signal(object)        # list[dict] results, or str error
    finished = Signal()

    def __init__(self, instrument, config: RunConfig, parent=None):
        super().__init__(parent)
        self.inst = instrument
        self.cfg = config
        self._stop_event = threading.Event()
        self._capture_idx = 0
        self._freq_axis: Optional[np.ndarray] = None
        self._active: List[int] = []
        self._sweep_total: float = 1.0
        self._csv_path = config.filename
        self._csv_writer = None
        self.display_mailbox = LatestCaptureMailbox()
        # 0.9.0: a trace reset asked for while recording runs on THIS thread
        # (the VISA owner) between captures; requests are a thread-safe flag.
        self._reset_request = threading.Event()
        self._event_log = CaptureEventLog(config.filename)

    def request_trace_reset(self) -> None:
        """Thread-safe: ask for a trace reset at the next point between
        captures (also served during scheduled waiting)."""
        self._reset_request.set()

    @property
    def trace_reset_pending(self) -> bool:
        return self._reset_request.is_set()

    def _service_trace_reset(self) -> None:
        """Run a requested trace reset; called only between captures."""
        if not self._reset_request.is_set() or self._stop_event.is_set():
            return
        self._reset_request.clear()
        if not hasattr(self.inst, "reset_active_traces"):
            self.traceResetFinished.emit("This instrument object cannot reset traces.")
            return
        self.statusMessage.emit("Resetting active traces (Clear/Write, then original mode)…")
        instant = datetime.now()
        try:
            results = self.inst.reset_active_traces(stop_event=self._stop_event)
        except Exception as exc:
            message = f"Trace reset failed: {exc}"
            self._record_event(instant, "trace_reset_failed", [dict(note=str(exc))])
            self.traceResetFinished.emit(message)
            return
        self._record_event(instant, "trace_reset", [
            dict(screen=r.get("screen"), trace=r.get("trace"), original_mode=r.get("original"),
                 restored_mode=r.get("restored"), ok=r.get("ok"), note=r.get("note"))
            for r in results])
        self.traceResetFinished.emit(results)

    def _record_event(self, instant, event, rows) -> None:
        try:
            self._event_log.record(instant, event, rows)
        except Exception as exc:
            self.statusMessage.emit(f"Could not write the events file: {exc}")

    # ----- control -----
    @Slot()
    def stop(self):
        self._stop_event.set()

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
                if self._csv_writer is not None:
                    self.statusMessage.emit("Draining queued CSV captures…")
                    self._csv_writer.close()
            except Exception as output_error:
                self.errorOccurred.emit("CSV drain failed: " + str(output_error))
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
            if self._stop_event.is_set():
                return

        self.statusMessage.emit("Recording…")
        self.recordingStateChanged.emit(True)

        # Existing instrument abstraction preserves continuous sweep by
        # default. arm_single() only changes mode when explicitly configured.
        self.inst.arm_single()

        next_trigger = _perf()
        while not self._stop_event.is_set():
            self._csv_writer.raise_if_failed()
            self._service_trace_reset()
            # Wait until it's time for the next capture
            now = _perf()
            if now < next_trigger:
                # Sleep in small slices so Stop is responsive
                self._sleep_responsive(next_trigger - now)
                if self._stop_event.is_set():
                    break

            self._capture_idx += 1
            idx = self._capture_idx
            self.captureStarted.emit(idx, self._sweep_total)

            # Trigger sweep + drive progress bar based on elapsed time
            self._trigger_with_progress(idx)
            if self._stop_event.is_set():
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

            # Timestamp read completion, not later formatting/disk output.
            self._csv_writer.submit(datetime.now(), traces)
            self.display_mailbox.publish(idx, self._freq_axis, traces)

            # Schedule next trigger (drift-free cadence)
            next_trigger += self.cfg.interval_s
            # If we fell behind, snap forward but keep cadence tight
            if _perf() > next_trigger + self.cfg.interval_s:
                next_trigger = _perf()

        self.statusMessage.emit("Stopped.")

    # ----- helpers -----
    def _open_csv(self):
        self._csv_writer = AsyncCaptureCsvWriter(self._csv_path, self._freq_axis, self._active)

    def _wait_until(self, target: datetime):
        self.statusMessage.emit(f"Waiting until {target.strftime('%H:%M:%S')}…")
        while not self._stop_event.is_set():
            self._service_trace_reset()
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def _sleep_responsive(self, seconds: float):
        end = _perf() + seconds
        while not self._stop_event.is_set() and _perf() < end:
            self._service_trace_reset()
            time.sleep(max(0.0, min(0.1, end - _perf())))

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
        """One serial VISA owner; progress animation belongs to the GUI timer.

        Stop is cooperative: the current trigger call finishes or times out.
        Never leave a detached SCPI thread or close its VISA handle underneath
        a pending read. GUI progress does not send analyzer queries.
        """
        total_sweep_seconds = max(0.05, self._sweep_total)
        self.inst.trigger_and_wait(total_sweep_seconds * 3.0 + 5.0)
        self.captureProgress.emit(idx, 1.0)


class TraceResetWorker(QtCore.QObject):
    """Runs FSPInstrument.reset_active_traces() off the GUI thread while no
    acquisition is running (0.9.0). The GUI keeps every other VISA action
    disabled until it finishes, so the session still has one owner."""
    finished = Signal(object)                  # list[dict] results, or str error

    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self.inst = instrument

    @Slot()
    def run(self):
        try:
            result = self.inst.reset_active_traces()
        except Exception as exc:
            result = f"Trace reset failed: {exc}"
        self.finished.emit(result)


# ===========================================================================
# %% Custom LED widget
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


# %% MAIN GUI AND ISOLATED REPORTING
class MainWindow(QtWidgets.QMainWindow):
    requestStop = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"R&S FSP Trace Logger v{APP_VERSION}")
        self.resize(1100, 720)

        self.instrument = None  # FSPInstrument or MockFSPInstrument
        self.thread: Optional[QThread] = None
        self.worker: Optional[AcquisitionWorker] = None
        # 0.9.0: idle-time trace reset worker, and a reset requested from a
        # running acquisition that has not been served yet.
        self.reset_thread: Optional[QThread] = None
        self.reset_worker: Optional[TraceResetWorker] = None
        self._reset_pending = False
        self._sweep_settings: Dict[str, float] = {}
        self._active_traces: List[int] = []
        self.display_mailbox = None
        self.report_process = None
        self.report_stdout = bytearray()
        self.report_stderr = bytearray()
        self.report_output_directory = ""
        self.report_result_message = ""
        self.last_acquisition_error = ""
        self.close_after_acquisition = False
        self.capture_progress_started = None
        self.capture_progress_duration = 1.0
        self.settings = QtCore.QSettings("William W Wallace", "R&S FSP Trace Logger")
        self.base_palette = QtGui.QPalette(self.palette())
        self.display_trace_colors = list(TRACE_COLORS)
        self._build_ui()
        self._wire_signals()
        self.acquisition_locked_controls = (self.screen_auto_rb, self.screen_a_rb, self.screen_b_rb,
                                            self.file_edit, self.browse_btn, self.interval_spin, self.start_dt, self.now_btn, self.debug_check)
        self._build_menus()
        saved_renderer = str(self.settings.value("veusz_executable", ""))
        if saved_renderer and Path(saved_renderer).is_file() and not os.environ.get("VEUSZ_EXE"):
            os.environ["VEUSZ_EXE"] = saved_renderer
        self.apply_theme(str(self.settings.value("theme", "system")), persist=False)
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(100)
        self.display_timer.timeout.connect(self._refresh_live_display)
        self.display_timer.start()
        self.report_timer = QTimer(self)
        self.report_timer.setInterval(500)
        self.report_timer.timeout.connect(self._update_report_availability)
        self.report_timer.start()
        self._update_report_availability()

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
        version_lbl.setObjectName("versionLabel")
        version_lbl.setStyleSheet("font-family: monospace;")
        version_lbl.setToolTip(
            "0.9.0: Reset Active Traces; traces read from the selected screen;\n"
            "       Screen choice applied at connect; Auto re-detects on refresh.\n"
            "0.8.3: frequency-time pages; text menus; dark/light themes.\n"
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
        self.idn_label.setObjectName("instrumentIdentity")
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
        # 0.9.0: which screen the logger is actually reading, so a mismatch
        # with the analyzer is visible before Start.
        self.screen_in_use_label = QtWidgets.QLabel("In use: (not connected)")
        self.screen_in_use_label.setObjectName("screenInUse")
        self.screen_in_use_label.setToolTip(
            "Screen the logger reads sweep settings, trace modes and trace data from.")
        cl.addWidget(self.screen_in_use_label, 2, 6, 1, 3)

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
        self.report_btn = QtWidgets.QPushButton("Create Veusz Plots / Reports…")
        self.report_btn.setEnabled(False)
        self.render_reports_check = QtWidgets.QCheckBox("Also render PDF + PNG (requires Veusz)")
        sl.addWidget(self.report_btn, 3, 1, 1, 2)
        sl.addWidget(self.render_reports_check, 3, 3, 1, 3)
        self.report_status_label = QtWidgets.QLabel("Reports require a completed CSV and idle acquisition.")
        self.report_status_label.setWordWrap(True)
        sl.addWidget(self.report_status_label, 4, 0, 1, 6)
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
        # 0.9.0: restart every displayed trace (Clear/Write, then back to
        # its own mode) - restarts max hold, min hold and average.
        self.reset_traces_btn = QtWidgets.QPushButton("Reset Active Traces")
        self.reset_traces_btn.setEnabled(False)
        self.reset_traces_btn.setToolTip(
            "Switch every displayed trace on the selected screen to Clear/Write,\n"
            "then back to its own mode (Max Hold, Min Hold, Average, View).\n"
            "Restarts the analyzer's max-hold / min-hold / average accumulation.\n"
            "While recording it runs between captures and is logged to <csv>_events.csv.")
        stl.addWidget(self.reset_traces_btn, 1, 4)

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
        self.reset_traces_btn.clicked.connect(self.on_reset_traces)
        self.browse_btn.clicked.connect(self.on_browse)
        self.now_btn.clicked.connect(
            lambda: self.start_dt.setDateTime(QDateTime.currentDateTime()))
        self.start_manual_btn.clicked.connect(lambda: self.on_start(scheduled=False))
        self.start_scheduled_btn.clicked.connect(lambda: self.on_start(scheduled=True))
        self.stop_btn.clicked.connect(self.on_stop)
        self.report_btn.clicked.connect(self.on_create_reports)
        self.file_edit.textChanged.connect(self._update_report_availability)
        # Screen selector: when the user picks Auto / A / B, push the
        # choice to the instrument and refresh sweep settings.
        self.screen_auto_rb.toggled.connect(self._on_screen_changed)
        self.screen_a_rb.toggled.connect(self._on_screen_changed)
        self.screen_b_rb.toggled.connect(self._on_screen_changed)

    # -------- Slots --------
    def _visa_busy(self) -> bool:
        """True while a worker thread owns the VISA session (0.9.0)."""
        return self.thread is not None or self.reset_thread is not None

    def _selected_screen_mode(self) -> str:
        """The Screen radio choice as 'auto', 'A' or 'B'."""
        if self.screen_a_rb.isChecked():
            return "A"
        if self.screen_b_rb.isChecked():
            return "B"
        return "auto"

    def _update_screen_label(self) -> None:
        """Show the screen the logger reads, e.g. 'In use: Screen B (auto)'."""
        if self.instrument is None:
            self.screen_in_use_label.setText("In use: (not connected)")
            return
        description = getattr(self.instrument, "screen_description", "")
        self.screen_in_use_label.setText("In use: " + (description or "?"))

    @Slot()
    def _on_screen_changed(self):
        """Handle a click on the Screen radio group (Auto / A / B).

        0.9.0: pushes the choice to the instrument AND re-reads sweep
        settings, trace modes and LEDs, so what the window shows is what a
        Start will record. Toggling fires the slot twice (off + on); the off
        side is ignored. The choice made while disconnected is applied by
        on_connect().
        """
        if self._visa_busy():
            return
        sender = self.sender()
        if sender is None or not sender.isChecked():
            return
        if self.instrument is None:
            return
        try:
            self.instrument.set_screen_mode(self._selected_screen_mode())
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self, "Screen change failed",
                f"Could not switch FSP screen: {exc}")
            return
        self._refresh_instrument_state(interactive=False)
        s = self._sweep_settings
        if isinstance(s, dict):
            fc = s.get("f_center")
            fsp = s.get("f_span")
            src = s.get("freq_source", "?")
            if fc is not None and fc == fc and fsp is not None and fsp == fsp:
                self.statusBar().showMessage(
                    f"{getattr(self.instrument, 'screen_description', '')}: "
                    f"center={fc/1e6:.3f} MHz, span={fsp/1e6:.3f} MHz ({src}); "
                    f"traces={self._active_traces or 'none'}", 8000)

    @Slot()
    def on_diagnostics(self):
        """Probe the instrument and show what SCPI is actually returning.

        Wrapped in an outer try/finally that ALWAYS shows the dialog — even
        if the probe code itself crashes — so the user always gets visible
        feedback. Also disables the Diagnostics button for the duration to
        prevent reentrant clicks.

        0.9.0: shows both screens side by side (frequencies, every trace's
        MODE? through DISP:WIND<n>, STAT?), which screen is selected and
        why, and the trace-fetch syntax cached for each screen.
        """
        if self._visa_busy() or self.instrument is None:
            return
        try:
            self.diag_btn.setEnabled(False)
        except Exception:
            pass
        lines: List[str] = []
        try:
            lines.append(f"*IDN?         -> {self.instrument.idn()}")
        except Exception as exc:
            lines.append(f"*IDN?         -> ERROR: {exc}")

        inst = self.instrument
        if isinstance(inst, FSPInstrument):
            if isinstance(inst.inst, SimulatedFSPSession):
                lines.append("DEMO MODE: simulated FSP session, synthetic data.")
            lines.append("")
            mode_label = "continuous" if inst.continuous_sweep else "single"
            lines.append(f"Sweep handling: {mode_label} (continuous_sweep={inst.continuous_sweep})")

            # Instrument personality — critical for diagnosing the
            # "FREQ:* returns wrong values + TRAC? -100" failure mode.
            # INST:LIST? is intentionally omitted — on FSP-38 firmware 4.50
            # it hangs until VI_ERROR_TMO.
            lines.append("")
            lines.append("Instrument personality (must be SAN for spectrum traces):")
            for cmd in ("INST?", "INST:NSEL?"):
                try:
                    ans = inst.inst.query(cmd).strip()
                    errs = inst._drain_error_queue()
                    suffix = f"  [errors: {errs}]" if errs else ""
                    lines.append(f"  {cmd:14s} -> {ans!r}{suffix}")
                except Exception as exc:
                    lines.append(f"  {cmd:14s} -> EXC: {exc}")

            # Screen selection.
            inst.refresh_screen_selection()
            try:
                inst.sweep_settings()
            except Exception as exc:
                lines.append(f"  sweep_settings() failed: {exc}")
            lines.append("")
            lines.append(f"Screen choice: {self._selected_screen_mode()}  ->  in use: "
                         f"{inst.screen_description}  (1=A/WIND1/SENS1/TRAC1, 2=B/WIND2/SENS2/TRAC2)")
            if inst.screen_mode == "auto":
                lines.append("  Auto rule: the screen with the higher centre frequency wins; "
                             "force A or B when both screens are configured.")
            lines.append("")
            lines.append("Per-screen settings and trace modes:")
            lines.append(f"  {'':10s} {'Screen A (1)':>26s} {'Screen B (2)':>26s}")
            freq = {}
            for number in (1, 2):
                freq[number] = inst._read_screen_freq(number)
                inst._safe_drain()
            for key, label in (("f_center", "center Hz"), ("f_span", "span Hz"),
                               ("f_start_raw", "start Hz"), ("f_stop_raw", "stop Hz")):
                lines.append(f"  {label:10s} {freq[1][key]:>26.3f} {freq[2][key]:>26.3f}")
            saved = inst.inst.timeout
            try:
                inst.inst.timeout = max(2000, int(saved or 0)) if saved else 2000
                for n in (1, 2, 3):
                    cells = []
                    for number in (1, 2):
                        t0 = time.perf_counter()
                        token = inst.trace_mode(n, number)
                        dt = (time.perf_counter() - t0) * 1000.0
                        shown = "hidden" if (not token or token.startswith("BLAN")) else "DISPLAYED"
                        cells.append(f"{(token or '(no answer)'):>6s} {shown:9s} {dt:5.0f} ms")
                    lines.append(f"  trace {n} MODE {cells[0]:>21s} {cells[1]:>26s}")
                answered = ", ".join(
                    f"Screen {inst.screen_letter(k)} via "
                    f"{'DISP:WIND%d:TRAC<n>' % k if v == 'window' else 'DISP:TRAC<n>'}"
                    for k, v in sorted(inst._mode_query_style.items()))
                lines.append("  Mode queries: " + (answered or "none answered"))
                lines.append("")
                lines.append("Reference (DISP:WIND<s>:TRAC<n>:STAT? — only flags currently selected):")
                for number in (1, 2):
                    for n in (1, 2, 3):
                        cmd = f"DISP:WIND{number}:TRAC{n}:STAT?"
                        try:
                            ans = inst.inst.query(cmd).strip()
                            errs = inst._drain_error_queue()
                            suffix = f"  [errors: {errs}]" if errs else ""
                            lines.append(f"  {cmd:25s} -> {ans!r}{suffix}")
                        except Exception as exc:
                            inst._safe_drain()
                            lines.append(f"  {cmd:25s} -> EXC: {exc.__class__.__name__}")
            finally:
                inst.inst.timeout = saved
            lines.append("")
            lines.append("Cached trace-fetch syntax: " + (", ".join(
                f"Screen {inst.screen_letter(k)}: {v}" for k, v in sorted(inst._trace_fetch_templates.items()))
                or "none yet (found at the first capture)"))
        else:
            lines.append(f"  active_traces() -> {inst.active_traces()}")

        # Sweep settings of the screen in use
        lines.append("")
        lines.append("Sweep settings (screen in use):")
        try:
            s = inst.sweep_settings()
            for k, v in s.items():
                lines.append(f"  {k:12s} = {v}")
        except Exception as exc:
            lines.append(f"  ERROR: {exc}")

        # Active traces (parsed)
        lines.append("")
        try:
            active = inst.active_traces()
            self._active_traces = active
            self._update_trace_leds(active)
            lines.append(f"Parsed active traces ({getattr(inst, 'screen_description', '')}): {active}")
        except Exception as exc:
            lines.append(f"Parsed active traces: ERROR {exc}")
        self._update_screen_label()

        # NOTE: no end-to-end fetch test here (a long fetch on the GUI
        # thread starved Spyder's heartbeat). Use Start to record.
        lines.append("")
        lines.append("(Skipping end-to-end fetch test — use Start to record.)")

        # ALWAYS show a dialog — even if the probe above blew up.
        try:
            if not lines:
                lines = ["Diagnostics produced no output."]
            dlg = QtWidgets.QDialog(self)
            dlg.setWindowTitle("FSP Diagnostics")
            dlg.resize(900, 640)
            dlg.setModal(True)
            v = QtWidgets.QVBoxLayout(dlg)
            text = QtWidgets.QPlainTextEdit("\n".join(lines))
            text.setObjectName("diagnosticsText")
            text.setReadOnly(True)
            text.setFont(QtGui.QFont("Monospace"))
            text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            v.addWidget(text)
            btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
            btns.accepted.connect(dlg.accept)
            v.addWidget(btns)
            dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
            self.last_diagnostics_text = "\n".join(lines)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            (dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec())
        except Exception as exc:
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
        if self._visa_busy() or self.instrument is None:
            return
        self.probe_btn.setEnabled(False)
        original_status = self.status_label.text()
        self.status_label.setText("Probing traces…")
        # Do not pump nested events while this slot owns the VISA session.
        try:
            # 0.9.0: Auto re-detects the screen on every probe.
            self.instrument.refresh_screen_selection()
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
            self._update_screen_label()
            s = self._sweep_settings
            if isinstance(s, dict):
                self.status_label.setText(
                    f"Probe complete ({getattr(self.instrument, 'screen_description', '')}). "
                    f"Sweep: {s['f_start']/1e6:.3f}–"
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
        if self._visa_busy() or self.instrument is not None:
            return
        try:
            if self.demo_check.isChecked():
                # 0.9.0: Demo runs the real FSPInstrument over a simulated
                # two-screen SCPI session (synthetic data only).
                self.instrument = FSPInstrument(
                    "SIMULATED::FSP", session=SimulatedFSPSession(),
                    debug=self.debug_check.isChecked())
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
            # Step 0 (0.9.0): apply the Screen choice shown in the window
            # BEFORE the first query. 0.8.3 left a new connection in Auto
            # whatever was selected, so A/B had to be toggled after Connect.
            self.instrument.set_screen_mode(self._selected_screen_mode())
            # Step 1: identify the instrument. Just one short query.
            idn = self.instrument.idn()
            self.idn_label.setText(idn)
            self.idn_label.setStyleSheet("")
            # Step 2: read sweep settings (cheap). Skip trace probing here.
            try:
                self._sweep_settings = self.instrument.sweep_settings()
                s = self._sweep_settings
                self.status_label.setText(
                    f"Connected. Sweep: {s['f_start']/1e6:.3f}–"
                    f"{s['f_stop']/1e6:.3f} MHz, {int(s['n_pts'])} pts, "
                    f"sweep_time={s['sweep_time']*1000:.1f} ms "
                    f"({getattr(self.instrument, 'screen_description', '')})."
                )
            except Exception as exc:
                self.status_label.setText(
                    f"Connected, but sweep query failed: {exc}")
            # 0.9.0: trace modes are three ~5-byte MODE? answers, so the
            # LEDs are filled at connect (non-fatal if it fails).
            try:
                self._active_traces = self.instrument.active_traces()
            except Exception as exc:
                self._active_traces = []
                self._log_status(f"Trace detection at connect failed: {exc}")
            self._update_trace_leds(self._active_traces)
            self._update_screen_label()

            self.connect_btn.setEnabled(False)
            self.disconnect_btn.setEnabled(True)
            self.diag_btn.setEnabled(True)
            self.probe_btn.setEnabled(True)
            self.start_manual_btn.setEnabled(True)
            self.start_scheduled_btn.setEnabled(True)
            self._update_reset_button()
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
        if self.reset_thread is not None:
            self.status_label.setText("Wait for the trace reset to finish before disconnecting.")
            return
        if self.instrument is not None:
            try:
                self.instrument.close()
            except Exception:
                pass
            self.instrument = None
        self.idn_label.setText("(not connected)")
        self.idn_label.setObjectName("instrumentIdentity")
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
        self._update_trace_leds([])
        self._update_screen_label()
        self._update_reset_button()
        self.status_label.setText("Disconnected.")

    def _refresh_instrument_state(self, interactive: bool = True):
        """Re-read sweep settings and trace modes of the screen in use.

        interactive=False (screen changes) reports problems in the status
        line instead of a dialog.
        """
        # Sweep settings: cheap and essential. If this fails, we surface a
        # warning but don't break the connection.
        try:
            self._sweep_settings = self.instrument.sweep_settings()
        except Exception as exc:
            if interactive:
                QtWidgets.QMessageBox.warning(
                    self, "Sweep query failed",
                    f"Could not read sweep settings: {exc}\n\n"
                    "You can still try Diagnostics or recording.")
            else:
                self.status_label.setText(f"Sweep query failed: {exc}")
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
        self._update_screen_label()
        s = self._sweep_settings
        if s:
            self.status_label.setText(
                f"{getattr(self.instrument, 'screen_description', '')}: "
                f"Sweep: {s['f_start']/1e6:.3f}–{s['f_stop']/1e6:.3f} MHz, "
                f"{int(s['n_pts'])} pts, sweep_time={s['sweep_time']*1000:.1f} ms × "
                f"count={int(s['sweep_count'])} (total {s['sweep_time']*s['sweep_count']*1000:.1f} ms),"
                f" traces={self._active_traces}"
            )

    def _update_trace_leds(self, active: List[int]):
        self.led_t1.setOn(1 in active)
        self.led_t2.setOn(2 in active)
        self.led_t3.setOn(3 in active)
        # 0.9.0: tooltips name each trace's mode and screen.
        modes = getattr(self.instrument, "last_trace_modes", {}) if self.instrument is not None else {}
        screen = FSPInstrument.screen_letter(getattr(self.instrument, "last_trace_modes_screen", 1))
        for number, led in ((1, self.led_t1), (2, self.led_t2), (3, self.led_t3)):
            token = modes.get(number) if isinstance(modes, dict) else None
            if self.instrument is None or token is None:
                led.setToolTip(f"Trace {number}")
            else:
                led.setToolTip(f"Trace {number}: {FSPInstrument.MODE_NAMES.get(token, token)} "
                               f"({token}) on Screen {screen}")

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
        if self._visa_busy() or self.report_process is not None:
            self.status_label.setText("Wait for acquisition/report processing/trace reset to finish.")
            return
        # Refresh once more so the sanity check uses live values. 0.9.0: in
        # Auto the screen is re-detected here, then kept for the whole run.
        self.instrument.refresh_screen_selection()
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

        if os.path.exists(filename):
            answer = QtWidgets.QMessageBox.question(self, "Replace CSV?", "Recording replaces:\n" + os.path.abspath(filename),
                        QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No)
            if answer != QtWidgets.QMessageBox.Yes:
                return
        if self._visa_busy() or self.report_process is not None:
            return
        self.last_acquisition_error = ""
        self.report_result_message = ""
        self.close_after_acquisition = False
        cfg = RunConfig(interval_s=N, filename=filename, start_at=start_at)

        # Build worker + thread
        self.thread = QThread(self)
        self.worker = AcquisitionWorker(self.instrument, cfg)
        self.display_mailbox = self.worker.display_mailbox
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.statusMessage.connect(self.on_status)
        self.worker.activeTracesDetected.connect(self._update_trace_leds)
        self.worker.sweepInfo.connect(self.on_sweep_info)
        self.worker.captureStarted.connect(self.on_capture_started)
        self.worker.captureProgress.connect(self.on_capture_progress)
        self.worker.recordingStateChanged.connect(self.led_rec.setOn)
        self.worker.errorOccurred.connect(self.on_worker_error)
        self.worker.traceResetFinished.connect(self._on_trace_reset_finished)
        self.worker.finished.connect(self.thread.quit, Qt.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.on_worker_finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.requestStop.connect(self.worker.stop, Qt.DirectConnection)
        self.thread.start()

        self.start_manual_btn.setEnabled(False)
        self.start_scheduled_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.disconnect_btn.setEnabled(False)
        self.diag_btn.setEnabled(False)
        self.probe_btn.setEnabled(False)
        for control in self.acquisition_locked_controls:
            control.setEnabled(False)
        self._update_report_availability()
        self._update_reset_button()

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
        self._update_screen_label()

    @Slot(int, float)
    def on_capture_started(self, idx: int, total_s: float):
        self.progress.setValue(0)
        self.capture_progress_started = time.perf_counter()
        self.capture_progress_duration = max(0.05, total_s)
        self.status_label.setText(f"Capture #{idx} — sweeping ({total_s:.2f} s)…")

    @Slot(int, float)
    def on_capture_progress(self, idx: int, frac: float):
        if frac >= 1.0:
            self.capture_progress_started = None
        self.progress.setValue(int(max(0.0, min(1.0, frac)) * 1000))

    @Slot(int, object, dict)
    def on_capture_finished(self, idx: int, freq, traces: dict):
        self.progress.setValue(1000)
        self.status_label.setText(f"Capture #{idx} queued for CSV ({len(freq)} pts × {len(traces)} traces).")
        # Reuse curves; display mailbox bounds queued GUI memory.
        for number in sorted(traces):
            if number not in self._plot_curves:
                color = self.display_trace_colors[(number - 1) % 3]
                self._plot_curves[number] = self.plot.plot(pen=pg.mkPen(color, width=2), name="Trace %d" % number, autoDownsample=False, downsample=1)
            self._plot_curves[number].setData(freq, traces[number])
        for number in set(self._plot_curves) - set(traces):
            self.plot.removeItem(self._plot_curves.pop(number))

    # %% COOPERATIVE ACQUISITION CLEANUP
    @Slot(str)
    def on_worker_error(self, message):
        self.last_acquisition_error = message
        self.status_label.setText("Acquisition/output error; draining CSV…")

    @Slot()
    def on_worker_finished(self):
        # Only QThread.finished releases references; never wait()/terminate()
        # from GUI slots. CSV drain completes before the worker emits finished.
        self._refresh_live_display()
        self.thread = None
        self.worker = None
        if self._reset_pending:
            self._reset_pending = False
            self._log_status("A trace reset requested during the run was not served before it stopped.")
        self.display_mailbox = None
        self.capture_progress_started = None
        self._capture_in_progress = False
        self.led_rec.setOn(False)
        self.progress.setValue(0)
        self.stop_btn.setEnabled(False)
        connected = self.instrument is not None
        self.disconnect_btn.setEnabled(connected)
        self.diag_btn.setEnabled(connected)
        self.probe_btn.setEnabled(connected)
        for control in self.acquisition_locked_controls:
            control.setEnabled(True)
        self._update_report_availability()
        self._update_reset_button()
        self.status_label.setText("Idle; CSV writer closed." if not self.last_acquisition_error else "Stopped with acquisition/output error.")
        if self.last_acquisition_error:
            QtWidgets.QMessageBox.critical(self, "Acquisition error", self.last_acquisition_error)
        if self.close_after_acquisition:
            QTimer.singleShot(0, self.close)

    def _refresh_live_display(self):
        if self.capture_progress_started is not None:
            fraction = min(0.99, (time.perf_counter() - self.capture_progress_started) / self.capture_progress_duration)
            self.progress.setValue(int(1000 * fraction))
        if self.display_mailbox is not None:
            frame = self.display_mailbox.take()
            if frame is not None:
                self.on_capture_finished(*frame)

    # %% TRACE RESET (0.9.0)
    def _update_reset_button(self) -> None:
        """Reset is available when connected, no reset is running or pending,
        and (while recording) the worker can serve it between captures."""
        if not hasattr(self, "reset_traces_btn"):
            return
        enabled = (self.instrument is not None and self.reset_thread is None
                   and not self._reset_pending)
        self.reset_traces_btn.setEnabled(enabled)

    def _set_idle_visa_controls(self, enabled: bool) -> None:
        """Enable/disable everything that talks to the analyzer from the GUI
        thread (used while the idle-time reset worker owns the session)."""
        for widget in (self.disconnect_btn, self.diag_btn, self.probe_btn,
                       self.start_manual_btn, self.start_scheduled_btn,
                       self.screen_auto_rb, self.screen_a_rb, self.screen_b_rb):
            widget.setEnabled(enabled)

    def _confirm_trace_reset(self) -> bool:
        """Ask before discarding accumulated max-hold / average data.

        The prompt has a 'Do not ask again' box; Tools > Confirm before trace
        reset turns the prompt back on.
        """
        if not self._confirm_reset_enabled():
            return True
        modes = getattr(self.instrument, "last_trace_modes", {}) or {}
        screen = getattr(self.instrument, "screen_description", "the selected screen")
        listed = [f"Trace {n}: {FSPInstrument.MODE_NAMES.get(m, m)}"
                  for n, m in sorted(modes.items()) if m and m != "BLAN"]
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setWindowTitle("Reset active traces")
        box.setText(f"Reset every displayed trace on {screen}?")
        box.setInformativeText(
            "Each trace is switched to Clear/Write and then back to its own mode.\n"
            "Max-hold, min-hold and average data accumulated on the analyzer are\n"
            "discarded and start again; View traces are re-frozen after one fresh sweep.\n\n"
            + ("Last read: " + "; ".join(listed) if listed else "Trace modes are read again first.")
            + ("\n\nRecording is running: the reset happens between captures and is\n"
               "written to the run's _events.csv." if self.thread is not None else ""))
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
        box.setDefaultButton(QtWidgets.QMessageBox.Yes)
        dont_ask = QtWidgets.QCheckBox("Do not ask again")
        box.setCheckBox(dont_ask)
        answer = box.exec_() if hasattr(box, "exec_") else box.exec()
        accepted = answer == QtWidgets.QMessageBox.Yes
        if accepted and dont_ask.isChecked():
            self._set_confirm_reset(False)
        return accepted

    def _confirm_reset_enabled(self) -> bool:
        value = self.settings.value("confirm_trace_reset", True)
        return str(value).strip().lower() not in ("false", "0", "no")

    def _set_confirm_reset(self, enabled: bool) -> None:
        self.settings.setValue("confirm_trace_reset", bool(enabled))
        action = getattr(self, "confirm_reset_action", None)
        if action is not None and action.isChecked() != bool(enabled):
            action.setChecked(bool(enabled))

    @Slot()
    def on_reset_traces(self):
        """Reset Active Traces: Clear/Write, then each trace's own mode.

        Idle: a short-lived worker thread owns the VISA session and the
        other analyzer controls are disabled until it finishes. Recording:
        the acquisition worker (the VISA owner) runs it between captures.
        """
        if self.instrument is None or self.reset_thread is not None or self._reset_pending:
            return
        if not self._confirm_trace_reset():
            return
        if self.instrument is None or self.reset_thread is not None or self._reset_pending:
            return                       # state changed while the prompt was open
        if self.thread is not None:
            if self.worker is None:
                return
            self._reset_pending = True
            self.worker.request_trace_reset()
            self.status_label.setText("Trace reset requested; it runs between captures…")
            self._update_reset_button()
            return
        self.instrument.refresh_screen_selection()
        self.reset_thread = QThread(self)
        self.reset_worker = TraceResetWorker(self.instrument)
        self.reset_worker.moveToThread(self.reset_thread)
        self.reset_thread.started.connect(self.reset_worker.run)
        self.reset_worker.finished.connect(self._on_trace_reset_finished)
        self.reset_worker.finished.connect(self.reset_thread.quit, Qt.DirectConnection)
        self.reset_worker.finished.connect(self.reset_worker.deleteLater)
        self.reset_thread.finished.connect(self._on_reset_thread_finished)
        self.reset_thread.finished.connect(self.reset_thread.deleteLater)
        self._set_idle_visa_controls(False)
        self._update_reset_button()
        self._update_report_availability()
        self.status_label.setText("Resetting active traces (Clear/Write, then original mode)…")
        self.reset_thread.start()

    @Slot()
    def _on_reset_thread_finished(self):
        self.reset_thread = None
        self.reset_worker = None
        connected = self.instrument is not None
        self._set_idle_visa_controls(connected)
        self._update_report_availability()
        self._update_reset_button()
        if self.close_after_acquisition:
            QTimer.singleShot(0, self.close)

    @staticmethod
    def format_reset_summary(results) -> str:
        """One line per reset, e.g. 'Screen B: T1 WRIT ok; T2 MAXH->WRIT->MAXH ok'."""
        if not results:
            return "No displayed traces to reset."
        parts = []
        for r in results:
            original = r.get("original")
            if original in (None, "BLAN") or original == r.get("restored") == "WRIT":
                path = f"{original}"
            else:
                path = f"{original}->WRIT->{r.get('restored')}"
            status = "ok" if r.get("ok") else "CHECK"
            note = f" ({r.get('note')})" if r.get("note") else ""
            parts.append(f"T{r.get('trace')} {path} {status}{note}")
        return f"Screen {results[0].get('screen', '?')}: " + "; ".join(parts)

    @Slot(object)
    def _on_trace_reset_finished(self, result):
        """Results of a reset from either worker (list of dicts, or an error)."""
        self._reset_pending = False
        stamp = datetime.now().strftime("%H:%M:%S")
        if isinstance(result, str):
            self.last_trace_reset_summary = result
            self.status_label.setText(f"{stamp} {result}")
            self._update_reset_button()
            if self.thread is None:
                QtWidgets.QMessageBox.warning(self, "Trace reset", result)
            return
        summary = self.format_reset_summary(result)
        self.last_trace_reset_summary = summary
        self.status_label.setText(f"{stamp} Traces reset — {summary}")
        self.statusBar().showMessage(f"Trace reset {stamp}: {summary}", 10000)
        self._update_trace_leds(self._active_traces)
        self._update_reset_button()
        problems = [r for r in result if not r.get("ok")]
        if problems and self.thread is None:
            QtWidgets.QMessageBox.warning(
                self, "Trace reset — check the analyzer",
                "Some traces did not read back their original mode:\n\n" + summary)

    # %% REPORT PROCESS ADMISSION AND COMPLETION
    def _report_unavailable_reason(self):
        if self.thread is not None:
            return "Reports disabled during sampling, scheduled waiting, or CSV drain."
        if self.report_process is not None:
            return "Reports running; acquisition disabled until process exits."
        for filename in ("fsp_reports.py", "vszh5_writer.py"):
            if not Path(__file__).resolve().with_name(filename).is_file():
                return "Keep supplied modules together; missing " + filename
        if importlib.util.find_spec("h5py") is None:
            return "Install h5py in this Python environment to enable reports."
        source = Path(self.file_edit.text().strip()).expanduser()
        try:
            if not source.is_file() or source.stat().st_size == 0:
                return "Select a nonempty, completed logger CSV in Output File."
        except OSError:
            return "Selected CSV is inaccessible."
        return ""

    @Slot()
    def _update_report_availability(self):
        if not hasattr(self, "report_btn"):
            return
        reason = self._report_unavailable_reason()
        self.report_btn.setEnabled(not reason)
        self.report_btn.setToolTip(reason or "All native plots including every frequency versus time.")
        self.render_reports_check.setEnabled(self.thread is None and self.report_process is None)
        can_start = (self.instrument is not None and self.thread is None
                     and self.reset_thread is None and self.report_process is None)
        self.start_manual_btn.setEnabled(can_start)
        self.start_scheduled_btn.setEnabled(can_start)
        self._update_reset_button()
        self.report_status_label.setText(self.report_result_message if self.report_process is None and self.report_result_message
                                         else reason or "Ready: idle-only native Veusz plots and reports.")
        self._sync_menu_actions()

    @Slot()
    def on_create_reports(self):
        reason = self._report_unavailable_reason()
        if reason:
            self.report_status_label.setText(reason)
            return
        source = Path(self.file_edit.text().strip()).expanduser().resolve()
        suggested = source.with_name(source.stem + "_reports_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Choose NEW report folder name (must not exist)", str(suggested), "All files (*)")
        if not selected:
            return
        if Path(selected).exists():
            QtWidgets.QMessageBox.warning(self, "Existing destination", "Choose a new folder; reports are never overwritten.")
            return
        # Modal dialogs pump Qt events. Recheck state before publishing guard.
        reason = self._report_unavailable_reason()
        if reason:
            self.report_status_label.setText(reason)
            return
        self.report_output_directory = str(Path(selected).resolve())
        self.report_stdout.clear()
        self.report_stderr.clear()
        self.report_result_message = ""
        process = QtCore.QProcess(self)
        environment = QtCore.QProcessEnvironment.systemEnvironment()
        for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment.insert(variable, "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(self._read_report_stdout)
        process.readyReadStandardError.connect(self._read_report_stderr)
        process.finished.connect(self._on_report_finished)
        process.errorOccurred.connect(self._on_report_error)
        arguments = [str(Path(__file__).resolve().with_name("fsp_reports.py")), "--csv", str(source), "--output-dir", self.report_output_directory]
        if self.render_reports_check.isChecked():
            arguments.append("--render")
        self.report_process = process
        self._update_report_availability()
        process.start(sys.executable, arguments)

    def _read_report_stdout(self):
        if self.report_process is not None:
            self.report_stdout.extend(bytes(self.report_process.readAllStandardOutput()))
            del self.report_stdout[:-65536]

    def _read_report_stderr(self):
        if self.report_process is not None:
            self.report_stderr.extend(bytes(self.report_process.readAllStandardError()))
            del self.report_stderr[:-65536]

    def _on_report_error(self, process_error):
        if self.report_process is not None and process_error == QtCore.QProcess.FailedToStart:
            self.report_stderr.extend(self.report_process.errorString().encode("utf-8"))
            self._on_report_finished(-1, QtCore.QProcess.CrashExit)

    def _on_report_finished(self, exit_code, exit_status):
        if self.report_process is None:
            return
        self._read_report_stdout()
        self._read_report_stderr()
        old_process = self.report_process
        self.report_process = None
        old_process.deleteLater()
        success = exit_code == 0 and exit_status == QtCore.QProcess.NormalExit
        if success:
            self.report_result_message = "Reports complete: " + self.report_output_directory
            try:
                result = json.loads(self.report_stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
                if result.get("rendering", {}).get("status") == "unavailable_or_failed":
                    self.report_result_message = "Native plots complete; PDF/PNG unavailable. See report.md in " + self.report_output_directory
            except (ValueError, IndexError):
                pass
        else:
            self.report_result_message = "Report generation failed; source CSV unchanged."
        self._update_report_availability()
        if not success:
            QtWidgets.QMessageBox.critical(self, "Report generation failed",
                self.report_stderr.decode("utf-8", errors="replace").strip() or "Report process exited unexpectedly.")

    # %% COMPLETE TEXT MENUS / TOOLBAR
    def _build_menus(self):
        self.menu_button_bindings = []
        self.menu_checkbox_bindings = []
        self.menu_control_bindings = []
        self.menuBar().setNativeMenuBar(False)
        file_menu = self.menuBar().addMenu("&File")
        connection_menu = self.menuBar().addMenu("&Connection")
        acquisition_menu = self.menuBar().addMenu("&Acquisition")
        view_menu = self.menuBar().addMenu("&View")
        tools_menu = self.menuBar().addMenu("&Tools")
        help_menu = self.menuBar().addMenu("&Help")
        action_class = getattr(QtGui, "QAction", None) or QtWidgets.QAction
        group_class = getattr(QtGui, "QActionGroup", None) or QtWidgets.QActionGroup

        def action(menu, text, callback, shortcut=""):
            result = action_class(text, self)
            result.triggered.connect(lambda checked=False: callback())
            if shortcut:
                result.setShortcut(shortcut)
            menu.addAction(result)
            return result

        def button_action(menu, text, button, shortcut=""):
            result = action(menu, text, button.click, shortcut)
            self.menu_button_bindings.append((result, button))
            button.installEventFilter(self)
            return result

        def check_action(menu, text, control):
            result = action_class(text, self)
            result.setCheckable(True)
            result.setChecked(control.isChecked())
            result.toggled.connect(control.setChecked)
            control.toggled.connect(result.setChecked)
            menu.addAction(result)
            self.menu_checkbox_bindings.append((result, control))
            return result

        button_action(file_menu, "Choose output CSV…", self.browse_btn, "Ctrl+O")
        self.report_action = button_action(file_menu, "Create Veusz plots / reports…", self.report_btn, "Ctrl+R")
        self.open_report_action = action(file_menu, "Open last report folder", self._open_report_folder)
        file_menu.addSeparator()
        action(file_menu, "E&xit", self.close, "Ctrl+Q")
        connect_action = button_action(connection_menu, "Connect", self.connect_btn)
        disconnect_action = button_action(connection_menu, "Disconnect", self.disconnect_btn)
        check_action(connection_menu, "Demo mode", self.demo_check)
        check_action(connection_menu, "Log SCPI to stderr", self.debug_check)
        self.resource_action = action(connection_menu, "VISA resource…", self._edit_resource)
        self.menu_control_bindings.append((self.resource_action, self.resource_edit))
        backend_menu = connection_menu.addMenu("VISA backend")
        self.backend_actions = []
        backend_group = group_class(self)
        backend_group.setExclusive(True)
        for index in range(self.backend_combo.count()):
            result = action_class(self.backend_combo.itemText(index), self)
            result.setCheckable(True)
            result.triggered.connect(lambda checked, value=index: self.backend_combo.setCurrentIndex(value) if checked and self.backend_combo.isEnabled() else None)
            backend_group.addAction(result)
            backend_menu.addAction(result)
            self.backend_actions.append(result)
        screen_menu = connection_menu.addMenu("Analyzer screen")
        screen_group = group_class(self)
        screen_group.setExclusive(True)
        for control in (self.screen_auto_rb, self.screen_a_rb, self.screen_b_rb):
            result = check_action(screen_menu, control.text(), control)
            screen_group.addAction(result)
        button_action(connection_menu, "Diagnostics…", self.diag_btn)
        button_action(connection_menu, "Probe traces", self.probe_btn)
        start_action = button_action(acquisition_menu, "Start now", self.start_manual_btn, "F5")
        button_action(acquisition_menu, "Start at planned time", self.start_scheduled_btn)
        stop_action = button_action(acquisition_menu, "Stop and drain CSV", self.stop_btn, "F6")
        # Short text: the action also sits on the toolbar; the button's
        # tooltip (copied by _sync_menu_actions) explains it in full.
        reset_action = button_action(acquisition_menu, "Reset active traces", self.reset_traces_btn, "F7")
        acquisition_menu.addSeparator()
        result = action(acquisition_menu, "Sampling interval…", self._edit_interval)
        self.menu_control_bindings.append((result, self.interval_spin))
        result = action(acquisition_menu, "Planned start time…", self._edit_start_time)
        self.menu_control_bindings.append((result, self.start_dt))
        button_action(acquisition_menu, "Set planned start to now", self.now_btn)
        self.theme_group = group_class(self)
        self.theme_group.setExclusive(True)
        self.theme_actions = {}
        theme_menu = view_menu.addMenu("Theme")
        for mode, label in (("system", "System / application"), ("dark", "Dark"), ("light", "Light")):
            result = action_class(label, self)
            result.setCheckable(True)
            result.triggered.connect(lambda checked, value=mode: self.apply_theme(value) if checked else None)
            self.theme_group.addAction(result)
            theme_menu.addAction(result)
            self.theme_actions[mode] = result
        action(view_menu, "Autoscale live plot", self.plot.enableAutoRange, "Ctrl+0")
        self.toolbar = self.addToolBar("Acquisition and reports")
        self.toolbar.setObjectName("acquisition_reports_toolbar")
        self.toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for result in (connect_action, disconnect_action, start_action, stop_action, reset_action,
                       self.report_action):
            self.toolbar.addAction(result)
        view_menu.addAction(self.toolbar.toggleViewAction())
        self.statusbar_action = action_class("Status bar", self)
        self.statusbar_action.setCheckable(True)
        self.statusbar_action.setChecked(True)
        self.statusbar_action.toggled.connect(self.statusBar().setVisible)
        view_menu.addAction(self.statusbar_action)
        button_action(tools_menu, "Create all Veusz plots / reports…", self.report_btn)
        check_action(tools_menu, "Also render PDF + PNG", self.render_reports_check)
        self.veusz_action = action(tools_menu, "Select standalone Veusz executable…", self._select_veusz)
        button_action(tools_menu, "Instrument diagnostics…", self.diag_btn)
        button_action(tools_menu, "Probe displayed traces", self.probe_btn)
        button_action(tools_menu, "Reset active traces…", self.reset_traces_btn)
        self.confirm_reset_action = action_class("Confirm before trace reset", self)
        self.confirm_reset_action.setCheckable(True)
        self.confirm_reset_action.setChecked(self._confirm_reset_enabled())
        self.confirm_reset_action.toggled.connect(self._set_confirm_reset)
        tools_menu.addAction(self.confirm_reset_action)
        action(help_menu, "Usage / output documentation", self._show_help, "F1")
        action(help_menu, "About R&S FSP Trace Logger…", self._show_about)
        action(help_menu, "About Qt…", lambda: QtWidgets.QMessageBox.aboutQt(self))

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.EnabledChange and hasattr(self, "menu_button_bindings"):
            for action, button in self.menu_button_bindings:
                if watched is button:
                    action.setEnabled(button.isEnabled())
        return super().eventFilter(watched, event)

    def _sync_menu_actions(self):
        if not hasattr(self, "menu_button_bindings"):
            return
        for action, button in self.menu_button_bindings:
            action.setEnabled(button.isEnabled())
            action.setToolTip(button.toolTip())
        for action, control in self.menu_checkbox_bindings:
            action.setEnabled(control.isEnabled())
            action.setChecked(control.isChecked())
        for action, control in self.menu_control_bindings:
            action.setEnabled(control.isEnabled())
        for index, action in enumerate(self.backend_actions):
            action.setEnabled(self.backend_combo.isEnabled())
            action.setChecked(index == self.backend_combo.currentIndex())
        self.open_report_action.setEnabled(bool(self.report_output_directory) and Path(self.report_output_directory).is_dir())
        self.veusz_action.setEnabled(self.thread is None and self.report_process is None)

    def _edit_resource(self):
        if self.resource_edit.isEnabled():
            text, accepted = QtWidgets.QInputDialog.getText(self, "VISA resource", "Resource:", text=self.resource_edit.text())
            if accepted and self.resource_edit.isEnabled():
                self.resource_edit.setText(text.strip())

    def _edit_interval(self):
        if self.interval_spin.isEnabled():
            value, accepted = QtWidgets.QInputDialog.getDouble(self, "Sampling interval", "Interval (s):", self.interval_spin.value(),
                         self.interval_spin.minimum(), self.interval_spin.maximum(), self.interval_spin.decimals())
            if accepted and self.interval_spin.isEnabled():
                self.interval_spin.setValue(value)

    def _edit_start_time(self):
        if not self.start_dt.isEnabled():
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Planned start time")
        layout = QtWidgets.QVBoxLayout(dialog)
        editor = QtWidgets.QDateTimeEdit(self.start_dt.dateTime(), dialog)
        editor.setDisplayFormat(self.start_dt.displayFormat())
        editor.setCalendarPopup(True)
        layout.addWidget(editor)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec_() == QtWidgets.QDialog.Accepted and self.start_dt.isEnabled():
            self.start_dt.setDateTime(editor.dateTime())

    def _select_veusz(self):
        if self.thread is not None or self.report_process is not None:
            return
        executable, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select standalone Veusz executable", os.environ.get("VEUSZ_EXE", ""), "All files (*)")
        if executable:
            os.environ["VEUSZ_EXE"] = executable
            self.settings.setValue("veusz_executable", executable)
            self.statusBar().showMessage("Renderer: " + executable, 8000)

    def _open_report_folder(self):
        if self.report_output_directory and Path(self.report_output_directory).is_dir():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(self.report_output_directory))

    def _show_help(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Logger usage and outputs")
        dialog.resize(820, 650)
        layout = QtWidgets.QVBoxLayout(dialog)
        text = QtWidgets.QTextBrowser(dialog)
        readme = Path(__file__).resolve().with_name("README.md")
        content = readme.read_text(encoding="utf-8") if readme.is_file() else (
            "Connect or enable Demo. Choose CSV, interval and screen; start/stop.\n"
            "Reset Active Traces (F7): Clear/Write, then each trace's own mode.\n"
            "Wait for CSV drain, then Create Veusz Plots / Reports into a new folder.\n"
            "Freq_N_GHz pages and Combined_Freq_vs_Time retain every frequency.\n"
            "Time axes use recorded datetime; means use linear power.\n"
            "Select light/dark/system from View > Theme. Optional PDF/PNG requires Veusz.\n"
            "No hardware/compliance certification; this is a best-effort desktop logger.")
        text.setPlainText(content)
        layout.addWidget(text)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    @staticmethod
    def sibling_module_version(filename: str) -> str:
        """__version__ of a companion module read from its source (no import,
        so h5py is not needed to show it)."""
        import re
        try:
            text = Path(__file__).resolve().with_name(filename).read_text(encoding="utf-8")
        except OSError:
            return "missing"
        match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.M)
        return match.group(1) if match else "?"

    def _show_about(self):
        QtWidgets.QMessageBox.about(self, "About R&S FSP Trace Logger",
            "<b>R&amp;S FSP Trace Logger " + APP_VERSION + "</b><br>"
            "Author / application owner: William W. Wallace<br>"
            "Company: NRAO/GBO<br>Email: wwallace@nrao.edu<br>"
            "Native Veusz writer: " + self.sibling_module_version("vszh5_writer.py")
            + "; report engine: " + self.sibling_module_version("fsp_reports.py")
            + "; background I/O: " + self.sibling_module_version("fsp_background.py")
            + "; simulator: " + self.sibling_module_version("fsp_simulator.py") + "<br>"
            "Python 3.8–3.12; integration update " + APP_DATE + " (AI-assisted).<br>"
            "Source attribution/license notices remain in the supplied modules.")

    # %% PERSISTENT DARK / LIGHT / SYSTEM THEMES
    def apply_theme(self, mode, persist=True):
        """Scope palette/styles to this window, not Spyder's QApplication.

        Axes, legend, plot background and trace pens change along with text,
        controls, menu/toolbar and disabled states. OS-native file dialogs
        may retain the operating-system theme. Document export is independent
        of GUI display theme and stays publication-oriented.
        """
        if mode not in ("dark", "light", "system"):
            mode = "system"
        self.theme_mode = mode
        palette = QtGui.QPalette(self.base_palette)
        if mode == "system":
            dark = palette.color(QtGui.QPalette.Window).lightness() < 128
        else:
            dark = mode == "dark"
            colors = {"window": "#24272e" if dark else "#f3f4f6", "base": "#171a20" if dark else "#ffffff",
                      "text": "#f1f3f7" if dark else "#17212b", "button": "#353b46" if dark else "#e5e9ef",
                      "disabled": "#9098a5" if dark else "#6b7280", "highlight": "#406bb5" if dark else "#245eb4"}
            for role, color in ((QtGui.QPalette.Window, colors["window"]), (QtGui.QPalette.WindowText, colors["text"]),
                                (QtGui.QPalette.Base, colors["base"]), (QtGui.QPalette.AlternateBase, colors["window"]),
                                (QtGui.QPalette.Text, colors["text"]), (QtGui.QPalette.Button, colors["button"]),
                                (QtGui.QPalette.ButtonText, colors["text"]), (QtGui.QPalette.ToolTipBase, colors["base"]),
                                (QtGui.QPalette.ToolTipText, colors["text"]), (QtGui.QPalette.Highlight, colors["highlight"]),
                                (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Link, "#66b7ff" if dark else "#154caa")):
                palette.setColor(role, QtGui.QColor(color))
            for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
                palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(colors["disabled"]))
        self.setPalette(palette)
        foreground = palette.color(QtGui.QPalette.WindowText).name()
        base = palette.color(QtGui.QPalette.Base).name()
        background = palette.color(QtGui.QPalette.Window).name()
        button = palette.color(QtGui.QPalette.Button).name()
        disabled = palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text).name()
        border = "#626b7a" if dark else "#9ba5b4"
        self.setStyleSheet("""
QWidget { background-color: %s; color: %s; }
QProgressBar { background: %s; color: %s; border: 1px solid %s; text-align: center; }
QProgressBar::chunk { background: #406bb5; }
QCheckBox::indicator, QRadioButton::indicator { width: 13px; height: 13px; border: 1px solid #8d99aa; background: palette(base); }
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #406bb5; border: 2px solid #82b8ff; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: #626b7a; }
QMenuBar, QMenu, QToolBar { background: %s; color: %s; }
QMenuBar::item:selected, QMenu::item:selected { background: #406bb5; color: white; }
QMenu::item:disabled { color: %s; }
QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QTextBrowser { background: %s; color: %s; selection-background-color: #406bb5; }
QPushButton, QToolButton { background: %s; color: %s; border: 1px solid %s; border-radius: 3px; padding: 5px; }
QPushButton:disabled, QToolButton:disabled { color: %s; }
QPushButton:hover:enabled, QToolButton:hover:enabled { border: 1px solid #5b9beb; }
QGroupBox { border: 1px solid %s; border-radius: 4px; margin-top: 9px; padding-top: 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QToolTip { background: %s; color: %s; border: 1px solid %s; }
""" % (background, foreground, base, foreground, border, background, foreground, disabled,
       base, foreground, button, foreground, border, disabled, border, base, foreground, border))
        plot_background = "#171a20" if dark else "#ffffff"
        self.plot.setBackground(plot_background)
        for name in ("bottom", "left", "top", "right"):
            axis = self.plot.getAxis(name)
            axis.setPen(pg.mkPen(foreground))
            axis.setTextPen(pg.mkPen(foreground))
        self.plot.setLabel("bottom", "Frequency", units="Hz", color=foreground)
        self.plot.setLabel("left", "Power", units="dBm", color=foreground)
        legend = self.plot.plotItem.legend
        if legend is not None:
            legend.setLabelTextColor(foreground)
            legend.setBrush(pg.mkBrush(plot_background))
            legend.setPen(pg.mkPen(border))
        self.display_trace_colors = (["#f1c40f", "#5bb8ff", "#ff7777"] if dark else ["#875700", "#125fba", "#b12b38"])
        for number, curve in self._plot_curves.items():
            curve.setPen(pg.mkPen(self.display_trace_colors[(number - 1) % 3], width=2))
        for number, led in enumerate((self.led_t1, self.led_t2, self.led_t3)):
            led._on_color = QtGui.QColor(self.display_trace_colors[number])
            led.update()
        for name, action in self.theme_actions.items():
            action.setChecked(name == mode)
        if persist:
            self.settings.setValue("theme", mode)

    # %% COOPERATIVE WINDOW CLOSE
    def closeEvent(self, event):
        if self.reset_thread is not None:
            self.close_after_acquisition = True
            self.status_label.setText("Closing after the trace reset finishes…")
            event.ignore()
            return
        if self.report_process is not None:
            self.report_status_label.setText("Wait for report generation before closing.")
            event.ignore()
            return
        if self.thread is not None:
            self.close_after_acquisition = True
            self.on_stop()
            self.status_label.setText("Stopping and draining CSV before closing…")
            event.ignore()
            return
        if self.instrument is not None:
            try:
                self.instrument.close()
            except Exception:
                pass
            self.instrument = None
        event.accept()


# ===========================================================================
# %% Entry point
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
