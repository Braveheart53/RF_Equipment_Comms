#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Simulated R&S FSP SCPI session (two screens, three traces per screen)
=====================================================================
===============================================================================
 Title          : Simulated R&S FSP SCPI Session
 Filename       : fsp_simulator.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-26
 Modified       : 2026-10-26
 Language       : Python 3.8 through 3.12
 Requires       : numpy
 Licence        : Same terms as rs_fsp_logger.py (not declared by the owner;
                  no grant inferred).
 Attribution    : AI-assisted (Claude) addition to the owner's logger bundle.
 Status         : Internal draft. SOFTWARE TEST FIXTURE - every level it
                  returns is synthetic. It is not a model of FSP accuracy.
===============================================================================

DESCRIPTION
-----------
A stand-in for a pyvisa message-based resource that answers the subset of
FSP SCPI used by rs_fsp_logger.FSPInstrument. Demo Mode and the unit tests
drive the REAL FSPInstrument code through it, so screen routing (Screen A /
Screen B), trace-mode detection and the trace reset are exercised exactly as
they would be against hardware, only with synthetic data.

What it models
* Two independent screens (A = suffix 1, B = suffix 2), each with its own
  frequency settings, sweep settings and three trace modes.
* The R&S numeric-suffix rule: a header without a suffix is treated as
  suffix 1 (FSP Operating Manual, Remote Control - Basics) [1].
  `unsuffixed_screen` can be set to 2 to mimic a firmware that routes bare
  headers to the other screen, for regression tests.
* Trace modes WRIT, MAXH, MINH, AVER, VIEW and BLAN. All traces of a screen
  see the same synthetic input; they differ only by mode, as on the real
  analyzer: max hold keeps the per-bin maximum since the mode was entered,
  average keeps the running mean of the dB values (simulator choice), view
  freezes the trace, clear/write shows the latest sweep.
* Entering WRIT, MAXH, MINH or AVER from another mode restarts the
  accumulation. Re-sending the mode a trace already has does NOT restart it
  (simulator assumption; this is why the logger's reset goes through WRIT).
* An intermittent burst on each screen, so max hold visibly grows and a reset
  visibly clears it in Demo Mode.
* SYST:ERR? queue; unknown commands queue -113 and unknown queries raise a
  VI_ERROR_TMO-style timeout, as a real instrument that never answers would.
* A guard that counts overlapping calls from different threads, so tests can
  prove the logger never shares the VISA session concurrently.

What it does not model: RBW/VBW/detectors, absolute accuracy, split-screen
alternating sweeps, binary trace formats, markers, limit lines, status
registers or service requests.

REFERENCES
----------
[1] Rohde & Schwarz, "R&S FSP Spectrum Analyzer Operating Manual,"
    1164.4556.12, ch. 5 "Remote Control - Basics" (numeric suffixes: entries
    without suffix are interpreted like entries with the suffix 1), and ch. 6
    "Remote Control - Description of Commands" (DISPlay[:WINDow<1|2>],
    SENSe<1|2>, TRACe<1|2>[:DATA]).
    https://www.rohde-schwarz.com/us/manual/fsp/

REVISION HISTORY
----------------
0.0.1  2026-10-26  First version, released with logger bundle 0.9.0: two
                   screens, mode-dependent trace accumulation, error queue,
                   timeouts for unknown queries, concurrency guard, command
                   log.
===============================================================================
"""

from __future__ import annotations

# %% IMPORTS
import collections
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import numpy as np

__version__ = "0.0.1"
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"

__all__ = ["SimulatedScreen", "SimulatedFSPSession", "SimulatedVisaTimeout",
           "demo_screens", "MODE_TOKENS"]

#: Short-form trace modes the FSP reports for DISP:WIND<n>:TRAC<t>:MODE?.
MODE_TOKENS = ("WRIT", "VIEW", "AVER", "MAXH", "MINH", "BLAN")
#: Modes that accumulate sweeps; entering one of them restarts it.
_ACCUMULATING = ("MAXH", "MINH", "AVER")


# %% EXCEPTIONS
class SimulatedVisaTimeout(Exception):
    """Raised for a query the simulated instrument never answers.

    The text carries 'VI_ERROR_TMO', the token the logger's retry logic and
    pyvisa's VisaIOError use for a timeout.
    """


# %% SCREEN MODEL
@dataclass
class SimulatedScreen:
    """Settings, trace modes and trace memory of one FSP screen."""

    f_start: float
    f_stop: float
    n_pts: int = 801
    sweep_time: float = 1.0
    sweep_count: int = 1
    #: Trace number -> mode token (one of MODE_TOKENS).
    modes: Dict[int, str] = field(default_factory=lambda: {1: "WRIT", 2: "MAXH", 3: "BLAN"})
    #: Carriers as (fraction of span, level dBm, width as fraction of span).
    carriers: Tuple[Tuple[float, float, float], ...] = ((0.30, -30.0, 0.004), (0.55, -25.0, 0.003))
    #: Intermittent burst: (fraction of span, level dBm, width, probability per sweep).
    burst: Tuple[float, float, float, float] = (0.75, -38.0, 0.006, 0.25)
    noise_floor_dbm: float = -90.0
    noise_sigma_db: float = 3.0
    # Trace memory (filled lazily).
    data: Dict[int, np.ndarray] = field(default_factory=dict)
    counts: Dict[int, int] = field(default_factory=dict)

    @property
    def center(self) -> float:
        return 0.5 * (self.f_start + self.f_stop)

    @property
    def span(self) -> float:
        return self.f_stop - self.f_start

    def axis(self) -> np.ndarray:
        return np.linspace(self.f_start, self.f_stop, int(self.n_pts))


def demo_screens() -> Dict[int, SimulatedScreen]:
    """The Demo Mode configuration.

    Screen A keeps the 0.8.x demo layout (1-2 GHz, 801 points, trace 1
    clear/write, trace 2 max hold, trace 3 blank), so Auto still selects it.
    Screen B looks like a lightly used screen near the FSP's start-up range
    (9 kHz - 2 MHz) with trace 1 clear/write and trace 3 average; force
    Screen B to see the logger follow it.
    """
    return {
        1: SimulatedScreen(1.0e9, 2.0e9, 801, 1.0, 1,
                           modes={1: "WRIT", 2: "MAXH", 3: "BLAN"}),
        2: SimulatedScreen(9.0e3, 2.0e6, 501, 0.5, 1,
                           modes={1: "WRIT", 2: "BLAN", 3: "AVER"},
                           carriers=((0.25, -45.0, 0.01), (0.60, -52.0, 0.008)),
                           burst=(0.85, -60.0, 0.01, 0.30)),
    }


# %% SESSION
class SimulatedFSPSession:
    """A pyvisa-resource look-alike that speaks a subset of FSP SCPI.

    Parameters
    ----------
    screens:
        {1: SimulatedScreen, 2: SimulatedScreen}; demo_screens() if omitted.
    time_scale:
        Multiplies the simulated sweep duration that *OPC? and INIT:IMM wait
        (1.0 for Demo Mode, 0.0 for fast tests).
    unsuffixed_screen:
        Screen addressed by a header without numeric suffix (1 per the R&S
        rule; 2 only to mimic a deviating firmware in tests).
    seed:
        Seed of the synthetic noise, so tests are reproducible.
    """

    def __init__(self, screens: Optional[Dict[int, SimulatedScreen]] = None,
                 time_scale: float = 1.0, unsuffixed_screen: int = 1,
                 seed: int = 20261026,
                 idn: str = "Rohde&Schwarz,FSP-SIMULATED,000000/000,4.50 (simulated)"):
        self.screens: Dict[int, SimulatedScreen] = screens or demo_screens()
        self.time_scale = float(time_scale)
        self.unsuffixed_screen = int(unsuffixed_screen)
        self.idn = idn
        self.timeout = 30000              # ms, set by the caller like pyvisa
        self.read_termination = "\n"
        self.write_termination = "\n"
        self.selected_window = 1          # DISP:WIND<n>:SEL (front-panel focus)
        self.continuous = True
        self.data_format = "ASC"
        self.errors: Deque[str] = collections.deque(maxlen=100)
        #: Last commands received (bounded), for tests and diagnostics.
        self.command_log: Deque[str] = collections.deque(maxlen=4000)
        self.sweeps_completed = 0
        self.concurrency_violations = 0
        self.closed = False
        self._rng = np.random.default_rng(seed)
        self._busy = threading.Lock()
        for screen in self.screens.values():
            for trace in (1, 2, 3):
                screen.modes.setdefault(trace, "BLAN")
        self._complete_sweep()            # every trace holds one sweep at start

    # ----- pyvisa-like interface ------------------------------------------
    def write(self, command: str) -> None:
        with self._guard():
            for part in self._split(command):
                self._dispatch(part, is_query=False)

    def query(self, command: str) -> str:
        with self._guard():
            answer = ""
            for part in self._split(command):
                result = self._dispatch(part, is_query=part.rstrip().endswith("?")
                                        or "? " in part)
                if result is not None:
                    answer = result
            return answer

    def query_ascii_values(self, command: str, container: Callable = list,
                           separator: str = ",", **_ignored: Any):
        text = self.query(command)
        values = [float(token) for token in text.split(separator) if token.strip()]
        return container(values)

    def close(self) -> None:
        self.closed = True

    # ----- helpers --------------------------------------------------------
    class _Guard:
        def __init__(self, owner: "SimulatedFSPSession"):
            self.owner = owner

        def __enter__(self):
            if not self.owner._busy.acquire(blocking=False):
                self.owner.concurrency_violations += 1
                self.owner._busy.acquire()
            return self

        def __exit__(self, *exc):
            self.owner._busy.release()
            return False

    def _guard(self) -> "SimulatedFSPSession._Guard":
        if self.closed:
            raise RuntimeError("simulated session is closed")
        return SimulatedFSPSession._Guard(self)

    @staticmethod
    def _split(command: str) -> List[str]:
        return [part.strip() for part in str(command).split(";") if part.strip()]

    def _screen(self, suffix: Optional[str]) -> SimulatedScreen:
        number = int(suffix) if suffix else self.unsuffixed_screen
        return self.screens[number]

    def _wait_sweep(self, screen: SimulatedScreen) -> None:
        delay = screen.sweep_time * max(1, screen.sweep_count) * self.time_scale
        if delay > 0:
            time.sleep(min(delay, 60.0))
        self._complete_sweep()

    def _push_error(self, code: int, text: str) -> None:
        self.errors.append(f'{code},"{text}"')

    # ----- synthetic spectrum and trace memory -----------------------------
    def _new_sweep(self, screen: SimulatedScreen) -> np.ndarray:
        x = np.linspace(0.0, 1.0, int(screen.n_pts))
        level = screen.noise_floor_dbm + screen.noise_sigma_db * self._rng.standard_normal(x.size)
        for position, peak, width in screen.carriers:
            shape = peak - 40.0 * (x - position) ** 2 / max(width, 1e-6)
            level = np.maximum(level, shape + 0.5 * self._rng.standard_normal())
        position, peak, width, probability = screen.burst
        if self._rng.random() < probability:
            shape = peak - 40.0 * (x - position) ** 2 / max(width, 1e-6)
            level = np.maximum(level, shape)
        return level

    def _complete_sweep(self) -> None:
        """One sweep finishes on every screen; traces update by mode."""
        self.sweeps_completed += 1
        for screen in self.screens.values():
            sweep = self._new_sweep(screen)
            for trace in (1, 2, 3):
                mode = screen.modes.get(trace, "BLAN")
                old = screen.data.get(trace)
                count = screen.counts.get(trace, 0)
                if old is None or old.shape != sweep.shape:
                    screen.data[trace] = sweep.copy()
                    screen.counts[trace] = 1
                    continue
                if mode == "VIEW":
                    continue
                if mode == "WRIT" or mode == "BLAN" or count == 0:
                    new = sweep.copy()
                elif mode == "MAXH":
                    new = np.maximum(old, sweep)
                elif mode == "MINH":
                    new = np.minimum(old, sweep)
                elif mode == "AVER":
                    new = old + (sweep - old) / float(count + 1)
                else:
                    new = sweep.copy()
                screen.data[trace] = new
                screen.counts[trace] = count + 1

    def _set_mode(self, screen: SimulatedScreen, trace: int, mode: str) -> None:
        mode = mode.upper()
        for token in MODE_TOKENS:
            if mode.startswith(token):
                mode = token
                break
        else:
            self._push_error(-224, "Illegal parameter value")
            return
        old = screen.modes.get(trace, "BLAN")
        if mode == old:
            return                                  # no restart (see module notes)
        screen.modes[trace] = mode
        if mode in _ACCUMULATING or mode == "WRIT":
            screen.counts[trace] = 0                # next sweep starts afresh

    # ----- command dispatcher ---------------------------------------------
    _RE = {
        "freq": re.compile(r"^(?:SENS(?:E)?([12])?:)?FREQ(?:UENCY)?:(STAR|STOP|CENT|SPAN)[A-Z]*\?$"),
        "swe": re.compile(r"^(?:SENS(?:E)?([12])?:)?SWE(?:EP)?:(POIN|TIME|COUN)[A-Z]*\?$"),
        "mode_q": re.compile(r"^DISP(?:LAY)?(?::WIND(?:OW)?([12])?)?:TRAC(?:E)?([1-3]):MODE\?$"),
        "mode_w": re.compile(r"^DISP(?:LAY)?(?::WIND(?:OW)?([12])?)?:TRAC(?:E)?([1-3]):MODE\s+([A-Z]+)$"),
        "stat_q": re.compile(r"^DISP(?:LAY)?(?::WIND(?:OW)?([12])?)?:TRAC(?:E)?([1-3])(?::STAT(?:E)?)?\?$"),
        "sel": re.compile(r"^DISP(?:LAY)?:WIND(?:OW)?([12])?:SEL(?:ECT)?$"),
        "data": re.compile(r"^TRAC(?:E)?([12])?(?::DATA)?\?\s+TRACE([1-3])$"),
    }

    def _dispatch(self, command: str, is_query: bool) -> Optional[str]:
        self.command_log.append(command)
        text = command.strip().lstrip(":").upper()
        if text == "*CLS":
            self.errors.clear()
            return None
        if text == "*IDN?":
            return self.idn
        if text in ("*WAI", "*RST"):
            return None
        if text == "*OPC?":
            self._wait_sweep(self.screens[self.selected_window])
            return "1"
        if text.startswith("SYST:ERR"):
            return self.errors.popleft() if self.errors else '0,"No error"'
        if text in ("INST?", "INST:SEL?"):
            return "SAN"
        if text == "INST:NSEL?":
            return "1"
        if text.startswith("INST:SEL ") or text.startswith("INST "):
            return None
        if text.startswith("FORM:DEXP:DSEP"):
            return None
        if text.startswith("FORM"):
            self.data_format = text.split()[-1] if " " in text else "ASC"
            return None
        if text.startswith("INIT:CONT"):
            self.continuous = text.split()[-1] in ("ON", "1")
            return None
        if text in ("INIT", "INIT:IMM"):
            self._wait_sweep(self.screens[self.selected_window])
            return None
        if text == "DISP:FORM?":
            return "SING"
        match = self._RE["freq"].match(text)
        if match:
            screen = self._screen(match.group(1))
            key = match.group(2)
            value = {"STAR": screen.f_start, "STOP": screen.f_stop,
                     "CENT": screen.center, "SPAN": screen.span}[key]
            return f"{value:.6f}"
        match = self._RE["swe"].match(text)
        if match:
            screen = self._screen(match.group(1))
            key = match.group(2)
            value = {"POIN": screen.n_pts, "TIME": screen.sweep_time,
                     "COUN": screen.sweep_count}[key]
            return f"{value}"
        match = self._RE["mode_q"].match(text)
        if match:
            return self._screen(match.group(1)).modes.get(int(match.group(2)), "BLAN")
        match = self._RE["mode_w"].match(text)
        if match:
            self._set_mode(self._screen(match.group(1)), int(match.group(2)), match.group(3))
            return None
        match = self._RE["stat_q"].match(text)
        if match:
            mode = self._screen(match.group(1)).modes.get(int(match.group(2)), "BLAN")
            return "0" if mode == "BLAN" else "1"
        match = self._RE["sel"].match(text)
        if match:
            self.selected_window = int(match.group(1) or 1)
            return None
        match = self._RE["data"].match(text)
        if match:
            screen = self._screen(match.group(1))
            values = screen.data[int(match.group(2))]
            return ",".join(f"{value:.2f}" for value in values)
        # Not understood: queue the error; a query is never answered.
        self._push_error(-113, "Undefined header;" + command)
        if is_query:
            raise SimulatedVisaTimeout(
                f"VI_ERROR_TMO (-1073807339): Timeout expired before operation completed "
                f"(simulated, no answer to {command!r})")
        return None


# %% INTERACTIVE SCRATCH CELL (Spyder)
# from fsp_simulator import SimulatedFSPSession
# s = SimulatedFSPSession(time_scale=0)
# print(s.query("DISP:WIND2:TRAC3:MODE?"), s.query("SENS2:FREQ:CENT?"))
