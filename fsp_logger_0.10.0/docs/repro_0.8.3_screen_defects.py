#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Reproduce the 0.8.3 screen / trace-selection defects (evidence for 0.9.0)
========================================================================
 Filename       : docs/repro_0.8.3_screen_defects.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-26
 Language       : Python 3.8 through 3.12
 Status         : Evidence script - synthetic data from fsp_simulator.

Usage
    python docs/repro_0.8.3_screen_defects.py <folder with 0.8.3 rs_fsp_logger.py> <folder with fsp_simulator.py>

Screen A is left near start-up defaults (one clear/write trace); Screen B
holds the user's set-up (clear/write, max hold, average). The 0.8.3
FSPInstrument is built without its constructor because it has no session
hook; every method then runs unchanged. Output of the 2026-10-26 run is in
docs/DEFECT_ANALYSIS_0.9.0.md.
"""

# %% IMPORTS
import os
import sys

old_logger_folder, simulator_folder = sys.argv[1], sys.argv[2]
# The old logger folder goes first so its rs_fsp_logger / fsp_background win
# over the 0.9.0 copies that sit next to fsp_simulator.py.
sys.path.insert(0, simulator_folder)
sys.path.insert(0, old_logger_folder)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import rs_fsp_logger as L                                    # noqa: E402  (0.8.3)
from fsp_simulator import SimulatedFSPSession, SimulatedScreen  # noqa: E402


# %% FIXTURE
def make_083_instrument():
    screens = {1: SimulatedScreen(9e3, 2e6, 501, 0.1, 1, modes={1: "WRIT", 2: "BLAN", 3: "BLAN"}),
               2: SimulatedScreen(13.0e9, 14.8e9, 801, 0.1, 1, modes={1: "WRIT", 2: "MAXH", 3: "AVER"})}
    session = SimulatedFSPSession(screens, time_scale=0)
    inst = L.FSPInstrument.__new__(L.FSPInstrument)
    inst.resource = "SIM"
    inst.debug = False
    inst.continuous_sweep = True
    inst._cached_n_pts = None
    inst._trace_fetch_cmd_template = None
    inst.active_screen = 1
    inst._screen_discovered = False
    inst.rm = None
    inst.inst = session
    inst._configured = False
    return inst, session


# %% DEFECT 1: trace modes always read from Screen A
print("logger version under test:", L.APP_VERSION)
inst, session = make_083_instrument()
settings = inst.sweep_settings()
print("1) Auto selects screen", settings["active_screen"], "centre", settings["f_center"], "Hz")
print("   active_traces() ->", inst.active_traces(), "   (Screen B shows traces 1, 2, 3)")
print("   MODE queries sent:", [c for c in session.command_log if c.endswith("MODE?")])

# %% DEFECT 4: fetch template survives a screen change (and falls back across screens)
inst, session = make_083_instrument()
inst.force_screen(1)
inst.fetch_trace(1)
inst.active_screen = 2              # what _discover_active_screen() does on a later change
inst._screen_discovered = True
data = inst.fetch_trace(1)
print("4) cached template", repr(inst._trace_fetch_cmd_template), "used on Screen B ->",
      data.size, "points (Screen B has 801, Screen A 501)")
import inspect  # noqa: E402
source = inspect.getsource(L.FSPInstrument._fetch_trace_with_syntax_discovery)
screen_b_list = source.split("== 2:", 1)[1].split("]", 1)[0]
print("   Screen B candidates include Screen A forms:",
      [form for form in ('"TRAC? TRACE{n}"', '"TRAC1? TRACE{n}"') if form in screen_b_list])

# %% DEFECT 2: the radio choice is not applied to a new connection
print("2) on_connect() in 0.8.3 never calls force_screen():",
      "force_screen" not in inspect.getsource(L.MainWindow.on_connect))

# %% DEFECT 3: Auto detects once per connection
inst, session = make_083_instrument()
inst.sweep_settings()
session.screens[1].f_start, session.screens[1].f_stop = 20.0e9, 21.0e9   # user moves to A
inst.sweep_settings()
print("3) after the front-panel change Auto still uses screen", inst.active_screen,
      "(A now has the higher centre); probe/start do not re-detect")
