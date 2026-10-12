#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Validation of veusz_export.py: native .vszh5 layout and bit-exact data.

===============================================================================
 Title          : Veusz HDF5 Export Validation
 Filename       : validate_veusz_export.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : numpy, scipy, h5py (Veusz NOT needed)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Development validation script (not part of the GUI)
===============================================================================

LICENCE
-------
This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. It is distributed WITHOUT ANY WARRANTY; see the GNU
General Public License (file LICENSE) for details.

DESCRIPTION
-----------
Runs real stability_core and phase_noise results through
veusz_export.export_vszh5() and checks the file WITHOUT Veusz:

  * it is an HDF5 file with the Veusz document-format-1 layout
    (/Veusz attrs, /Veusz/Data, /Veusz/Document/document, Tags);
  * every input array and result is stored bit-exact as float64;
  * the stored command script compiles as Python and creates the pages;
  * the 0.0.1 wrappers export_all_plots() and
    export_all_plots_subprocess() now also write real HDF5;
  * a failed write leaves the previous file untouched (atomic write);
  * a long series (300 000 points) keeps every sample in raw/* while the
    pages plot the min/max envelope plot/* (0.0.3);
  * the OHDEV slope of the noise identification is stored (0.0.3).

The Veusz-side round trip (Veusz's own loader, bit-exact after load,
renders) is validate_vszh5_in_veusz.py, run with a Python that has Veusz.

0.0.1 only asserted the file size (> 1000 bytes); that check passed on a
text .vsz written under the .vszh5 name, which Veusz could not open.

Exit status 0 = pass, 1 = fail.

REVISION HISTORY
----------------
0.0.1  (baseline)  Size check of the export_all_plots_subprocess() output.
0.0.2  2026-10-11  Rewritten for the native HDF5 export: structure, bit-exact
                   data, script, wrappers, atomic write; exit status; own
                   folder and a temporary folder; full header; Spyder cells.
0.0.3  2026-10-11  Long-series envelope (plot/*) and noise_id/slope_hdev checks.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND SET-UP
# =============================================================================
from __future__ import annotations

import builtins
import shutil
import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np

_HERE = Path(globals().get("__file__") or "validate_veusz_export.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import phase_noise as pn      # noqa: E402
import stability_core as sc   # noqa: E402
import veusz_export as ve     # noqa: E402

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

TMP = Path(tempfile.mkdtemp(prefix="vszh5_check_"))
FAILURES = []


def check(ok: bool, label: str) -> None:
    """Print one PASS/FAIL line and remember failures."""
    print(("PASS  " if ok else "FAIL  ") + label)
    if not ok:
        FAILURES.append(label)


def read_1d(f: "h5py.File", name: str) -> np.ndarray:
    """A numeric Veusz dataset from an open .vszh5."""
    return f["Veusz/Data/" + name.replace("`", "`BT").replace("/", "`SL") + "/data"][()]


def same(a, b) -> bool:
    """Bit-exact float64 equality with NaN == NaN."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all((a == b) | (np.isnan(a) & np.isnan(b))))


# %% ===========================================================================
#    ANALYSIS RESULTS TO EXPORT
# =============================================================================
TAU0 = 1.0
N = 4096
x = sc.generate_power_law_phase(N, TAU0, alpha=-1, seed=5)  # flicker FM-like
t = np.arange(len(x)) * TAU0
drift = sc.fit_and_remove_drift(x, t, order=1)
points = sc.compute_all_deviations(drift.residual_x, TAU0)
theoh = sc.compute_theoh_family(drift.residual_x, TAU0)
classes = sc.classify_noise(points)
pn_res = pn.ssb_phase_noise_from_time_series(drift.residual_x, TAU0, 1e7, window="hann")
f_classes = pn.classify_freq_domain_noise(pn_res)

# %% ===========================================================================
#    EXPORT AND CHECK THE FILE WITH h5py ONLY
# =============================================================================
out_path = TMP / "test_export.vszh5"
written = ve.export_vszh5(out_path, t, x, x_residual=drift.residual_x, tau0=TAU0,
                          f0_hz=1e7, dev_points=points, theoh_points=theoh,
                          noise_classes=classes, phase_noise=pn_res,
                          freq_classes=f_classes, drift=drift,
                          title="Validation_Run [x^2]", source="synthetic")
check(written == out_path and h5py.is_hdf5(str(written)), "file is HDF5 (0.0.1 wrote text)")
check(not Path(str(out_path) + ".part").exists(), "no .part file left behind")
with h5py.File(written, "r") as f:
    check(int(f["Veusz"].attrs["vsz_format"]) == 1, "Veusz document format 1")
    check("Data" in f["Veusz"] and "document" in f["Veusz/Document"], "Veusz/Data and Document")
    check(same(read_1d(f, "raw/time_s"), t), "raw/time_s bit-exact")
    check(same(read_1d(f, "raw/phase_s"), x), "raw/phase_s bit-exact")
    check(same(read_1d(f, "raw/residual_s"), drift.residual_x), "raw/residual_s bit-exact")
    check(same(read_1d(f, "raw/frac_freq"), np.diff(x) / TAU0), "raw/frac_freq = diff(x)/tau0")
    check(same(read_1d(f, "stability/oadev"), [p.oadev for p in points]), "stability/oadev bit-exact")
    check(same(read_1d(f, "stability/tdev_s"), [p.tdev for p in points]), "stability/tdev_s bit-exact")
    check(same(read_1d(f, "stability/theoh_dev"),
               [r[2] for r in sorted(theoh, key=lambda r: r[0])]), "ThêoH bit-exact")
    check(same(read_1d(f, "phase_noise/l_dbc_hz"), pn_res.l_f_dbc_hz), "L(f) bit-exact")
    check(len(read_1d(f, "noise_id/tau_s")) == len(classes), "noise-ID table length")
    check(same(read_1d(f, "noise_id/slope_hdev"), [c.slope_hdev for c in classes]),
          "noise_id/slope_hdev stored (drift detection)")
    tags = sorted(f["Veusz/Document/Tags"].keys())
    check(tags == ["meta", "noise_id", "phase_noise", "raw", "stability"], "tags " + ", ".join(tags))
    script = f["Veusz/Document/document"][0].decode("utf-8")
compile(script, "document", "exec")
check(True, "stored command script compiles")
pages = [ln for ln in script.splitlines() if ln.startswith("Add('page'")]
check(len(pages) == 6, f"{len(pages)} pages in the script (expect 6)")
check("Validation\\\\_Run \\\\[x\\\\^2\\\\]" in script, "title text escaped for Veusz")

# %% ===========================================================================
#    0.0.1 WRAPPERS AND ATOMIC WRITE
# =============================================================================
sigma_tau_series = {
    "OADEV": {"tau": [p.tau for p in points], "dev": [p.oadev for p in points]},
    "MDEV": {"tau": [p.tau for p in points], "dev": [p.mdev for p in points]},
    "TDEV": {"tau": [p.tau for p in points], "dev": [p.tdev for p in points]},
}
legacy = TMP / "legacy.vszh5"
ve.export_all_plots_subprocess(str(legacy), t, x, drift.residual_x, sigma_tau_series,
                               phase_noise_freq=pn_res.freq_hz.tolist(),
                               phase_noise_lf=pn_res.l_f_dbc_hz.tolist(), title="Legacy")
check(h5py.is_hdf5(str(legacy)), "export_all_plots_subprocess() writes HDF5")
with h5py.File(legacy, "r") as f:
    s = f["Veusz/Document/document"][0].decode("utf-8")
check("Add('page', name='page_tdev'" in s, "legacy TDEV curve on its own page")

before = out_path.read_bytes()
try:
    ve.export_vszh5(out_path, t, x[:-1])          # length mismatch -> ValueError
    check(False, "length mismatch rejected")
except ValueError:
    check(True, "length mismatch rejected")
check(out_path.read_bytes() == before, "failed export leaves the old file intact")

# %% ===========================================================================
#    LONG SERIES: FULL DATA, ENVELOPE ON THE PAGES
# =============================================================================
NL = 300_000
xl = sc.generate_power_law_phase(NL - 1, 1.0, alpha=-1, seed=11)
tl = np.arange(NL, dtype=float)
long_path = ve.export_vszh5(TMP / "long.vszh5", tl, xl, tau0=1.0, title="long")
with h5py.File(long_path, "r") as f:
    raw_l = read_1d(f, "raw/phase_s")
    env = read_1d(f, "plot/phase")
    script = f["Veusz/Document/document"][0].decode("utf-8")
    plot_tag = sorted(v.decode() for v in f["Veusz/Document/Tags/plot"][()])
check(len(raw_l) == NL and same(raw_l, xl),
      f"raw/phase_s keeps all {NL} samples")
check(len(env) <= ve.DEFAULT_MAX_PLOT_POINTS and np.nanmax(env) == np.max(xl) and np.nanmin(env) == np.min(xl),
      f"plot/phase envelope: {len(env)} points, extremes kept")
check("Set('yData', 'plot/phase')" in script and "Set('yData', 'raw/phase_s')" not in script,
      "pages draw the envelope, not the raw series")
check("plot/frac_freq" in plot_tag, "plot/* datasets tagged 'plot'")

shutil.rmtree(TMP, ignore_errors=True)
print("\n{0} failure(s)".format(len(FAILURES)))
if not getattr(builtins, "__IPYTHON__", False):
    sys.exit(1 if FAILURES else 0)
