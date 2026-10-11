#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Veusz HDF5 (.vszh5) export written directly with h5py - no embedded Veusz.

===============================================================================
 Title          : Veusz HDF5 Plot Export
 Filename       : veusz_export.py
 Version        : 0.0.2  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.2 (GUI: Time_Stability_App.py)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13 (3.8 syntax kept on purpose)
 Requires       : numpy, h5py, vszh5_writer.py 0.0.5 (shipped beside this file)
 Optional       : Veusz >= 3.6 (program or Python package) - only to render
                  PDF/PNG from the .vszh5; never needed to write it
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Internal draft - checked against real Veusz 3.6.2 and 4.2.1
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
The full text is in the file LICENSE distributed with this program.

DESCRIPTION
-----------
Writes the input series, every analysis result and the plot pages of one
stability analysis into ONE native Veusz HDF5 document (.vszh5). The file
is built with h5py through vszh5_writer.py, the writer taken from
isp_speed_monitor.py 1.3.0 and shared with the QuickSyn controller [R3]:
the data become typed Veusz datasets and the plots become the Veusz command
script stored inside the file. Nothing from Veusz (and therefore no PyQt)
is imported to write it, so this module is safe to import inside the
PySide6 GUI and needs no process isolation.

Why 0.0.1 had to change: 0.0.1 built the plots with veusz.embed and called
Embedded.Save(path). Save() defaults to mode='vsz', so 0.0.1 wrote a TEXT
.vsz document under the .vszh5 name, with the data printed to 7
significant digits. Veusz's File > Open selects the HDF5 loader for a
.vszh5 extension and fails with "file signature not found" (checked with
Veusz 3.6.2), so the 0.0.1 file could not be opened in Veusz.

DATASETS  (every numeric dataset is float64; tag in brackets)
--------
  raw/time_s, raw/phase_s                 input x(t)                  [raw]
  raw/residual_s                          drift-removed x(t)          [raw]
  raw/freq_time_s, raw/frac_freq          y(t), see equation (1)      [raw]
  raw/frac_freq_residual                  y(t) of the residual        [raw]
  stability/tau_s, m, n_used, adev,       AVAR-family sweep           [stability]
            oadev, mdev, ohdev, tdev_s
  stability/theoh_tau_s, theoh_dev,       ThêoH hybrid curve and the  [stability]
            theoh_m, theoh_source         estimator of each point
  noise_id/tau_s, m, slope_adev,          time-domain noise ID        [noise_id]
           slope_mdev, noise_type, confidence
  phase_noise/freq_hz, phase_noise/l_dbc_hz   SSB L(f)                [phase_noise]
  phase_noise_id/f_lo_hz, f_hi_hz,        frequency-domain noise ID   [noise_id]
           slope_db_per_decade, noise_type
  curves/<label>_tau_s, curves/<label>_dev    extra sigma-tau curves  [curves]
                                          (0.0.1 sigma_tau_series)
  meta/title, meta/source, meta/generator, meta/parameters_json,
  meta/datasets                           run description             [meta]

PAGES
-----
  page_overview     2 x 2 grid: x(t), residual or y(t), sigma-tau, L(f) or TDEV
  page_phase        x(t) and, after drift removal, the residual
  page_frequency    y(t) of the input and of the residual
  page_sigma_tau    ADEV, OADEV, MDEV, OHDEV, ThêoH (dimensionless, log-log)
  page_tdev         TDEV in seconds (log-log); kept off the dimensionless axes
  page_phase_noise  L(f) in dBc/Hz against log f
Pages without data are left out.

Fractional frequency is formed exactly as stability_core.phase_to_freq():

    y_k = (x_{k+1} - x_k) / tau0 ,   plotted at (t_k + t_{k+1}) / 2      (1)

RENDERING  (optional, needs Veusz)
---------
render_vszh5() renders one multipage PDF and per-page PNGs FROM the .vszh5
with vszh5_writer.render_pages(): the Veusz program is driven in
`--listen --quiet` mode with loader.loadHDF5Doc (`veusz --export` cannot
open a .vszh5), and the veusz Python package is the fallback. The program
is looked up in TIME_STABILITY_VEUSZ, then VEUSZ_EXE, then PATH and the
usual install folders. Veusz renders a temporary plain-named copy and the
results are moved to "<stem>.pdf" and "<stem>_pNN_<page>.png" beside the
document (render_pages() 0.0.5 would name the PDF of "run v0.0.2.vszh5"
"run v0.0.pdf"). The GUI runs the render in a child process
(render_vszh5_subprocess) so Veusz's own Qt binding never loads next to
PySide6.

USAGE
-----
    from veusz_export import export_vszh5, render_vszh5
    path = export_vszh5("run.vszh5", t, x, x_residual=r, tau0=1.0,
                        dev_points=pts, theoh_points=th, phase_noise=pn)
    render_vszh5(path)                     # optional, needs Veusz

    python veusz_export.py --render run.vszh5 [--png-pages all|first|none]
                           [--dpi 150] [--no-pdf] [--outdir DIR]
                           [--veusz-exe PATH] [--render-method auto|program|inprocess]
    python veusz_export.py --payload run.json [--and-render]   (0.0.1 JSON)
    python veusz_export.py --version

REFERENCES
----------
[R1] Veusz Developers, Veusz 4.2.1 source: veusz/document/doc.py
     (save, saveToHDF5File), veusz/document/loader.py (loadHDF5Doc),
     veusz/document/commandinterface.py (Save, mode='vsz' default),
     veusz/windows/mainwindow.py (loader chosen by file extension).
     https://pypi.org/project/veusz/4.2.1/
[R2] Veusz Developers, "Veusz - a scientific plotting package."
     https://veusz.github.io/
[R3] W. W. Wallace, vszh5_writer.py 0.0.5 (from isp_speed_monitor.py 1.3.0,
     Adaptive Electrodynamics LLC dba AdaptEd; shipped with QuickSyn 0.0.5).
[R4] h5py developers, "h5py." https://pypi.org/project/h5py/
[R5] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
     Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf

REVISION HISTORY
----------------
0.0.1  (baseline)  veusz.embed build of three pages (raw/residual, sigma-tau,
                   phase noise), saved with Embedded.Save() - which wrote a
                   text .vsz under the .vszh5 name; run in a subprocess to
                   keep PyQt6 away from the PySide6 GUI.
0.0.2  2026-10-11  Rewritten on vszh5_writer.py 0.0.5: a real Veusz HDF5
                   document written with h5py, no Veusz/PyQt/qmake needed.
                   Stores every result at float64 with tags; six pages
                   (overview, phase, frequency, sigma-tau, TDEV, L(f)); TDEV
                   moved to its own axes (seconds, not dimensionless).
                   Atomic write. Optional PDF/PNG render from the .vszh5
                   (render_vszh5, render_vszh5_subprocess, --render). The
                   0.0.1 functions export_all_plots() and
                   export_all_plots_subprocess() kept as wrappers. Spyder
                   cells; full header.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND PATHS
# =============================================================================
from __future__ import annotations

import argparse
import builtins
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np

# Spyder's runcell defines __file__ only while a cell runs, so the path of
# this file is captured once here and never read from __file__ later.
_THIS_FILE = Path(globals().get("__file__") or "veusz_export.py").resolve()
_HERE = _THIS_FILE.parent
if str(_HERE) not in sys.path:          # sibling modules, also under python -I
    sys.path.insert(0, str(_HERE))

import vszh5_writer as vw  # noqa: E402  (needs the path set above)

__version__ = "0.0.2"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"        # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"
__status__ = "Internal draft"

PACKAGE_NAME = "SA Time Stability Tools"
PROGRAM_NAME = "Veusz HDF5 Plot Export"

__all__ = [
    "export_vszh5", "render_vszh5", "render_vszh5_subprocess", "render_command",
    "find_veusz", "export_all_plots", "export_all_plots_subprocess",
    "VEUSZ_ENV_VARS", "PALETTE",
]

# %% ===========================================================================
#    CONSTANTS
# =============================================================================
#: Environment variables naming the Veusz program, searched in this order.
VEUSZ_ENV_VARS = ("TIME_STABILITY_VEUSZ", "VEUSZ_EXE")

#: Same palette as the GUI, so the Veusz pages match the on-screen plots.
PALETTE = {
    "blue": "#2b6cb0", "orange": "#dd6b20", "green": "#38a169",
    "purple": "#805ad5", "red": "#e53e3e", "navy": "#2c5282",
    "orange_dark": "#c05621",
}
_CYCLE = ("#2b6cb0", "#dd6b20", "#38a169", "#805ad5", "#e53e3e", "#2c5282", "#c05621")

#: Sigma-tau curves from the AVAR-family sweep: (column, key text, colour,
#: Veusz marker). Markers follow the GUI (OADEV o, MDEV s, OHDEV d).
SIGMA_TAU_CURVES = (
    ("adev", "ADEV", PALETTE["navy"], "plus"),
    ("oadev", "OADEV", PALETTE["blue"], "circle"),
    ("mdev", "MDEV", PALETTE["orange"], "square"),
    ("ohdev", "OHDEV", PALETTE["purple"], "diamond"),
)

#: Extensions Veusz opens with its HDF5 loader (mainwindow.py [R1]).
HDF5_SUFFIXES = (".vszh5", ".h5", ".hdf5", ".he5")

#: Plain-language description of every dataset, stored as meta/datasets.
DATASET_NOTES = (
    "raw/time_s: elapsed time of each phase sample (s)",
    "raw/phase_s: input phase / time error x(t) (s)",
    "raw/residual_s: x(t) after polynomial drift removal (s)",
    "raw/freq_time_s, raw/frac_freq: y_k = (x_k+1 - x_k)/tau0 at interval midpoints",
    "raw/frac_freq_residual: y(t) of the drift-removed residual",
    "stability/*: AVAR-family sweep on tau = m*tau0; tdev_s in seconds",
    "stability/theoh_*: ThêoH = AVAR below the splice, bias-removed Thêo1 above",
    "noise_id/*: power-law noise type from local OADEV/MDEV log-log slopes",
    "phase_noise/*: SSB phase noise L(f) in dBc/Hz",
    "phase_noise_id/*: noise type from the local L(f) slope in dB/decade",
    "curves/*: extra sigma-tau curves passed as sigma_tau_series",
)


# %% ===========================================================================
#    SMALL HELPERS
# =============================================================================
def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a dataclass/object attribute or a mapping key."""
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _f64(values: Any) -> np.ndarray:
    """Any sequence -> contiguous 1-D float64 array (None -> NaN)."""
    if isinstance(values, np.ndarray):
        return np.ascontiguousarray(values, dtype=np.float64).ravel()
    return np.array([np.nan if v is None else v for v in values], dtype=np.float64).ravel()


def _any_finite(values: np.ndarray) -> bool:
    """True when at least one element is finite (and positive for log axes)."""
    return bool(np.any(np.isfinite(values)))


def _safe_name(label: str) -> str:
    """Dataset-name-safe version of a free-text curve label."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", str(label)).strip("_")
    return name or "curve"


def _json_default(obj: Any) -> Any:
    """json.dumps fallback for NumPy scalars/arrays and paths."""
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    return str(obj)


def _running_in_ipython() -> bool:
    """True inside IPython/Spyder, where sys.exit() should not be called."""
    return bool(getattr(builtins, "__IPYTHON__", False))


# %% ===========================================================================
#    VEUSZ PAGE AND GRAPH BUILDERS
# =============================================================================
def _begin_page(doc: "vw.VszDoc", name: str, title: str,
                width: str = "27cm", height: str = "19cm") -> None:
    """Add a page with a centred title label and make it current."""
    doc.add("page", name)
    doc.to(name)
    doc.set("width", width)
    doc.set("height", height)
    doc.add("label", "title")
    doc.set("title/label", title)
    doc.set("title/xPos", [0.5])
    doc.set("title/yPos", [0.985])
    doc.set("title/alignHorz", "centre")
    doc.set("title/alignVert", "top")
    doc.set("title/Text/size", "11pt")


def _begin_grid(doc: "vw.VszDoc", rows: int, columns: int) -> None:
    """Add a grid below the page title and make it current."""
    doc.add("grid", "grid1")
    doc.to("grid1")
    doc.set("rows", int(rows))
    doc.set("columns", int(columns))
    doc.set("topMargin", "1.1cm")
    doc.set("bottomMargin", "0.2cm")
    doc.set("leftMargin", "0.2cm")
    doc.set("rightMargin", "0.2cm")


def _add_graph(doc: "vw.VszDoc", name: str, x_label: str, y_label: str,
               series: Sequence[Dict[str, Any]], log_x: bool = False,
               log_y: bool = False, key: bool = False, top_margin: str = "0.4cm") -> None:
    """One graph with x/y axes, dotted grid lines and the given xy series.

    ``series`` items: name, x, y (dataset names), color, key (legend text),
    marker ('none' for a plain line), line (bool), size, width.
    """
    doc.add("graph", name)
    doc.to(name)
    doc.set("leftMargin", "2.3cm")
    doc.set("rightMargin", "0.5cm")
    doc.set("topMargin", top_margin)
    doc.set("bottomMargin", "1.5cm")
    doc.add("axis", "x")
    doc.add("axis", "y")
    doc.set("x/label", x_label)
    doc.set("x/log", bool(log_x))
    doc.set("y/direction", "vertical")
    doc.set("y/label", y_label)
    doc.set("y/log", bool(log_y))
    for axis in ("x", "y"):
        doc.set(f"{axis}/TickLabels/size", "8pt")
        doc.set(f"{axis}/Label/size", "9pt")
        doc.set(f"{axis}/GridLines/hide", False)
        doc.set(f"{axis}/GridLines/color", "#c8c8c8")
        doc.set(f"{axis}/GridLines/style", "dotted")
    for s in series:
        doc.add("xy", s["name"])
        doc.to(s["name"])
        doc.set("xData", s["x"])
        doc.set("yData", s["y"])
        doc.set("key", s.get("key", ""))
        doc.set("marker", s.get("marker", "none"))
        doc.set("markerSize", s.get("size", "3pt"))
        doc.set("PlotLine/color", s["color"])
        doc.set("PlotLine/width", s.get("width", "1pt"))
        doc.set("PlotLine/hide", not s.get("line", True))
        doc.set("MarkerFill/color", s["color"])
        doc.set("MarkerLine/color", s["color"])
        doc.up()
    if key and len(series) > 1:
        doc.add("key", "key1")
        # Lower left: a sigma-tau curve falls with tau, so that corner is
        # normally empty (upper right is where long-tau points scatter).
        doc.set("key1/horzPosn", "left")
        doc.set("key1/vertPosn", "bottom")
        doc.set("key1/Text/size", "8pt")
        doc.set("key1/Border/hide", False)
        doc.set("key1/Background/transparency", 0)
    doc.up()


# %% ===========================================================================
#    EXPORT
# =============================================================================
def export_vszh5(output_path: "str | os.PathLike",
                 t_s: Sequence[float],
                 x_raw: Sequence[float],
                 *,
                 x_residual: Optional[Sequence[float]] = None,
                 tau0: Optional[float] = None,
                 f0_hz: Optional[float] = None,
                 dev_points: Optional[Sequence[Any]] = None,
                 theoh_points: Optional[Sequence[Sequence[Any]]] = None,
                 noise_classes: Optional[Sequence[Any]] = None,
                 phase_noise: Any = None,
                 freq_classes: Optional[Sequence[Any]] = None,
                 sigma_tau_series: Optional[Mapping[str, Mapping[str, Sequence[float]]]] = None,
                 drift: Any = None,
                 title: str = "SA time-stability analysis",
                 source: str = "",
                 compress: bool = True) -> Path:
    """Write one stability analysis as a native Veusz HDF5 document.

    Parameters
    ----------
    output_path:
        Target file. A name without an HDF5 extension (.vszh5, .h5, .hdf5,
        .he5) gets ".vszh5" appended, because Veusz chooses its loader from
        the extension.
    t_s, x_raw:
        Sample times (s) and phase / time error x(t) (s), equal length >= 2.
    x_residual:
        Drift-removed x(t), same length, or None.
    tau0:
        Sample interval (s) used for y(t); default median(diff(t_s)).
    f0_hz:
        Nominal carrier, recorded in the metadata.
    dev_points:
        stability_core.StabilityPoint list (tau, m, n_used, adev, oadev,
        mdev, tdev, ohdev); objects or mappings.
    theoh_points:
        stability_core.compute_theoh_family() rows (tau, m, dev, source).
    noise_classes, freq_classes:
        stability_core.NoiseClassification / phase_noise.FreqNoiseClassification
        lists, stored as tables.
    phase_noise:
        phase_noise.PhaseNoiseResult (or mapping with freq_hz, l_f_dbc_hz).
    sigma_tau_series:
        Extra curves {label: {"tau": [...], "dev": [...]}} (0.0.1 API). A
        label "TDEV" goes on the TDEV page.
    drift:
        stability_core.DriftFitResult (order, coeffs, drift_rate, r_squared)
        for the metadata.
    title, source:
        Page title text (printed literally) and the input file name.
    compress:
        gzip+shuffle for arrays of 4096 elements or more.

    Returns
    -------
    pathlib.Path
        The file written (atomically: a reader never sees a partial file).

    Raises
    ------
    ValueError
        Length mismatch, fewer than two samples, or a non-positive tau0.
    """
    # ---- inputs -----------------------------------------------------------
    t = _f64(t_s)
    x = _f64(x_raw)
    if t.size != x.size:
        raise ValueError(f"t_s has {t.size} samples but x_raw has {x.size}")
    if t.size < 2:
        raise ValueError("at least two samples are needed")
    xr = None if x_residual is None else _f64(x_residual)
    if xr is not None and xr.size != x.size:
        raise ValueError(f"x_residual has {xr.size} samples, x_raw has {x.size}")
    tau0 = float(np.median(np.diff(t))) if tau0 is None else float(tau0)
    if not math.isfinite(tau0) or tau0 <= 0.0:
        raise ValueError(f"tau0 must be finite and positive, got {tau0!r}")

    out = Path(output_path)
    if out.suffix.lower() not in HDF5_SUFFIXES:
        out = out.with_name(out.name + ".vszh5")

    # Fractional frequency, equation (1) of the module header.
    y_t = t[:-1] + 0.5 * np.diff(t)
    y = np.diff(x) / tau0
    yr = None if xr is None else np.diff(xr) / tau0

    has_dev = bool(dev_points)
    has_theoh = bool(theoh_points)
    pn_f = pn_l = None
    if phase_noise is not None:
        pn_f = _f64(_get(phase_noise, "freq_hz", []))
        pn_l = _f64(_get(phase_noise, "l_f_dbc_hz", []))
        if pn_f.size == 0 or pn_f.size != pn_l.size:
            pn_f = pn_l = None

    curves: List[Dict[str, Any]] = []
    for label, ser in (sigma_tau_series or {}).items():
        c_tau, c_dev = _f64(ser["tau"]), _f64(ser["dev"])
        if c_tau.size and c_tau.size == c_dev.size:
            curves.append({"label": str(label), "name": _safe_name(label),
                           "tau": c_tau, "dev": c_dev,
                           "tdev": str(label).strip().upper() == "TDEV"})
    # Two labels that sanitise to the same name get a numeric suffix.
    seen: Dict[str, int] = {}
    for c in curves:
        k = seen.get(c["name"], 0)
        seen[c["name"]] = k + 1
        if k:
            c["name"] = f"{c['name']}_{k}"

    generator = (f"veusz_export.py {__version__} ({PACKAGE_NAME}) "
                 f"via vszh5_writer {vw.__version__}")
    doc = vw.VszDoc(generator=generator)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    with vw.VeuszWriter(out, compress=compress,
                        writer_tag=f"{PACKAGE_NAME} veusz_export {__version__}") as w:
        # ---- raw series ------------------------------------------------------
        raw = ("raw",)
        w.dataset_1d("raw/time_s", t, tags=raw)
        w.dataset_1d("raw/phase_s", x, tags=raw)
        if xr is not None:
            w.dataset_1d("raw/residual_s", xr, tags=raw)
        w.dataset_1d("raw/freq_time_s", y_t, tags=raw)
        w.dataset_1d("raw/frac_freq", y, tags=raw)
        if yr is not None:
            w.dataset_1d("raw/frac_freq_residual", yr, tags=raw)

        # ---- AVAR-family sweep -----------------------------------------------
        st = ("stability",)
        has_tdev = False
        if has_dev:
            cols = {k: _f64([_get(p, k) for p in dev_points])
                    for k in ("tau", "m", "n_used", "adev", "oadev", "mdev", "tdev", "ohdev")}
            w.dataset_1d("stability/tau_s", cols["tau"], tags=st)
            w.dataset_1d("stability/m", cols["m"], tags=st)
            w.dataset_1d("stability/n_used", cols["n_used"], tags=st)
            for key in ("adev", "oadev", "mdev", "ohdev"):
                w.dataset_1d(f"stability/{key}", cols[key], tags=st)
            w.dataset_1d("stability/tdev_s", cols["tdev"], tags=st)
            has_tdev = _any_finite(cols["tdev"])

        if has_theoh:
            rows = sorted(theoh_points, key=lambda r: float(r[0]))
            w.dataset_1d("stability/theoh_tau_s", [float(r[0]) for r in rows], tags=st)
            w.dataset_1d("stability/theoh_m", [float(r[1]) for r in rows], tags=st)
            w.dataset_1d("stability/theoh_dev", [float(r[2]) for r in rows], tags=st)
            w.dataset_text("stability/theoh_source", [str(r[3]) for r in rows], st)

        # ---- noise identification -------------------------------------------
        nid = ("noise_id",)
        if noise_classes:
            w.dataset_1d("noise_id/tau_s", [_get(c, "tau") for c in noise_classes], tags=nid)
            w.dataset_1d("noise_id/m", [_get(c, "m") for c in noise_classes], tags=nid)
            w.dataset_1d("noise_id/slope_adev", [_get(c, "slope_adev") for c in noise_classes], tags=nid)
            w.dataset_1d("noise_id/slope_mdev", [_get(c, "slope_mdev") for c in noise_classes], tags=nid)
            w.dataset_text("noise_id/noise_type", [_get(c, "noise_type", "") for c in noise_classes], nid)
            w.dataset_text("noise_id/confidence", [_get(c, "confidence", "") for c in noise_classes], nid)

        # ---- phase noise -----------------------------------------------------
        if pn_f is not None:
            pn = ("phase_noise",)
            w.dataset_1d("phase_noise/freq_hz", pn_f, tags=pn)
            w.dataset_1d("phase_noise/l_dbc_hz", pn_l, tags=pn)
        if freq_classes:
            w.dataset_1d("phase_noise_id/f_lo_hz", [_get(c, "f_lo_hz") for c in freq_classes], tags=nid)
            w.dataset_1d("phase_noise_id/f_hi_hz", [_get(c, "f_hi_hz") for c in freq_classes], tags=nid)
            w.dataset_1d("phase_noise_id/slope_db_per_decade",
                         [_get(c, "slope_db_per_decade") for c in freq_classes], tags=nid)
            w.dataset_text("phase_noise_id/noise_type",
                           [_get(c, "noise_type", "") for c in freq_classes], nid)

        # ---- extra curves (0.0.1 sigma_tau_series) ----------------------------
        for c in curves:
            w.dataset_1d(f"curves/{c['name']}_tau_s", c["tau"], tags=("curves",))
            w.dataset_1d(f"curves/{c['name']}_dev", c["dev"], tags=("curves",))

        # ---- metadata --------------------------------------------------------
        params: Dict[str, Any] = {
            "package": PACKAGE_NAME, "package_version": __version__,
            "vszh5_writer_version": vw.__version__, "written_utc": now,
            "title": title, "source": source, "n_points": int(t.size),
            "tau0_s": tau0, "f0_hz": f0_hz, "span_s": float(t[-1] - t[0]),
            "residual_present": xr is not None,
            "n_sigma_tau_points": len(dev_points or []),
            "n_theoh_points": len(theoh_points or []),
        }
        if drift is not None:
            params["drift"] = {k: _get(drift, k) for k in ("order", "coeffs", "drift_rate", "r_squared")}
        if pn_f is not None:
            params["phase_noise"] = {k: _get(phase_noise, k)
                                     for k in ("method", "f0_hz", "window", "nperseg")}
        meta = ("meta",)
        w.dataset_text("meta/title", [title], meta)
        w.dataset_text("meta/source", [source or "(not recorded)"], meta)
        w.dataset_text("meta/parameters_json",
                       [json.dumps(params, default=_json_default, sort_keys=True)], meta)
        w.dataset_text("meta/generator", [generator, f"written {now}", f"licence {__license__}"], meta)
        w.dataset_text("meta/datasets", DATASET_NOTES, meta)

        # ---- pages -----------------------------------------------------------
        n_txt = (f"N = {t.size}, \\tau_{{0}} = {tau0:.6g} s, "
                 f"span = {float(t[-1] - t[0]):.6g} s")
        head = f"{vw.vz_text(title)}  -  {n_txt}"
        t_label = "Elapsed time (s)"

        phase_series = [{"name": "x_raw", "x": "raw/time_s", "y": "raw/phase_s",
                         "color": PALETTE["blue"], "key": "x(t)"}]
        resid_series = [{"name": "x_resid", "x": "raw/time_s", "y": "raw/residual_s",
                         "color": PALETTE["orange"], "key": "residual"}]
        freq_series = [{"name": "y_raw", "x": "raw/freq_time_s", "y": "raw/frac_freq",
                        "color": PALETTE["blue"], "key": "y(t)"}]
        freq_r_series = [{"name": "y_resid", "x": "raw/freq_time_s",
                          "y": "raw/frac_freq_residual", "color": PALETTE["orange"],
                          "key": "y(t) of residual"}]

        sigma_series: List[Dict[str, Any]] = []
        if has_dev:
            for key, text, colour, marker in SIGMA_TAU_CURVES:
                sigma_series.append({"name": f"c_{key}", "x": "stability/tau_s",
                                     "y": f"stability/{key}", "color": colour,
                                     "key": text, "marker": marker})
        if has_theoh:
            sigma_series.append({"name": "c_theoh", "x": "stability/theoh_tau_s",
                                 "y": "stability/theoh_dev", "color": PALETTE["red"],
                                 "key": "ThêoH", "marker": "cross"})
        tdev_series: List[Dict[str, Any]] = []
        if has_tdev:
            tdev_series.append({"name": "c_tdev", "x": "stability/tau_s",
                                "y": "stability/tdev_s", "color": PALETTE["green"],
                                "key": "TDEV", "marker": "triangle"})
        for i, c in enumerate(curves):
            entry = {"name": f"u_{c['name']}", "x": f"curves/{c['name']}_tau_s",
                     "y": f"curves/{c['name']}_dev", "color": _CYCLE[i % len(_CYCLE)],
                     "key": vw.vz_text(c["label"]), "marker": "circle"}
            (tdev_series if c["tdev"] else sigma_series).append(entry)
        pn_series = []
        if pn_f is not None:
            pn_series.append({"name": "lf", "x": "phase_noise/freq_hz",
                              "y": "phase_noise/l_dbc_hz", "color": PALETTE["navy"],
                              "key": "L(f)"})

        sig_x, sig_y = "Averaging time \\tau (s)", "Deviation \\sigma_{y}(\\tau)"
        tdev_y = "Time deviation \\sigma_{x}(\\tau) (s)"
        pn_x, pn_y = "Fourier frequency offset f (Hz)", "L(f) (dBc/Hz)"

        # Overview: up to four panels in a 2-column grid.
        panels = [("g_phase", t_label, "x(t) (s)", phase_series, False, False)]
        if xr is not None:
            panels.append(("g_resid", t_label, "Residual x(t) (s)", resid_series, False, False))
        else:
            panels.append(("g_freq", t_label, "y(t)", freq_series, False, False))
        if sigma_series:
            panels.append(("g_sigma", sig_x, sig_y, sigma_series, True, True))
        if pn_series:
            panels.append(("g_pn", pn_x, pn_y, pn_series, True, False))
        elif tdev_series:
            panels.append(("g_tdev", sig_x, tdev_y, tdev_series, True, True))
        _begin_page(doc, "page_overview", f"Overview  -  {head}", "29.7cm", "21cm")
        _begin_grid(doc, rows=(len(panels) + 1) // 2, columns=2)
        for gname, xl, yl, ser, lx, ly in panels:
            _add_graph(doc, gname, xl, yl, ser, log_x=lx, log_y=ly, key=(gname == "g_sigma"))
        doc.up()   # grid
        doc.up()   # page

        # Phase page.
        _begin_page(doc, "page_phase", f"Phase / time error  -  {head}")
        if xr is not None:
            _begin_grid(doc, rows=2, columns=1)
            _add_graph(doc, "g_phase", t_label, "x(t) (s)", phase_series)
            _add_graph(doc, "g_resid", t_label, "Drift-removed residual x(t) (s)", resid_series)
            doc.up()
        else:
            _add_graph(doc, "g_phase", t_label, "x(t) (s)", phase_series, top_margin="1.2cm")
        doc.up()

        # Fractional-frequency page.
        _begin_page(doc, "page_frequency", f"Fractional frequency  -  {head}")
        if yr is not None:
            _begin_grid(doc, rows=2, columns=1)
            _add_graph(doc, "g_freq", t_label, "y(t)", freq_series)
            _add_graph(doc, "g_freq_resid", t_label, "y(t) of residual", freq_r_series)
            doc.up()
        else:
            _add_graph(doc, "g_freq", t_label, "y(t)", freq_series, top_margin="1.2cm")
        doc.up()

        if sigma_series:
            _begin_page(doc, "page_sigma_tau", f"Frequency stability (sigma-tau)  -  {head}")
            _add_graph(doc, "g_sigma", sig_x, sig_y, sigma_series, log_x=True,
                       log_y=True, key=True, top_margin="1.2cm")
            doc.up()
        if tdev_series:
            _begin_page(doc, "page_tdev", f"Time deviation  -  {head}")
            _add_graph(doc, "g_tdev", sig_x, tdev_y, tdev_series, log_x=True,
                       log_y=True, key=True, top_margin="1.2cm")
            doc.up()
        if pn_series:
            _begin_page(doc, "page_phase_noise", f"SSB phase noise  -  {head}")
            _add_graph(doc, "g_pn", pn_x, pn_y, pn_series, log_x=True, top_margin="1.2cm")
            doc.up()

        return w.finish(doc.text())


# %% ===========================================================================
#    RENDERING (optional - needs Veusz)
# =============================================================================
def find_veusz(explicit: str = "") -> str:
    """Veusz program path: explicit, TIME_STABILITY_VEUSZ, VEUSZ_EXE, PATH..."""
    return vw.find_veusz_exe(explicit, env_vars=VEUSZ_ENV_VARS)


#: Name of the temporary copy that Veusz renders (see render_vszh5).
_RENDER_STEM = "vszh5_render"


def render_vszh5(vszh5_path: "str | os.PathLike", outdir: "str | os.PathLike | None" = None,
                 dpi: int = 150, png_pages: str = "all", pdf: bool = True,
                 veusz_exe: str = "", method: str = "auto",
                 timeout: float = 600.0) -> List[Path]:
    """Render a .vszh5 to a multipage PDF and per-page PNGs (needs Veusz).

    Wraps vszh5_writer.render_pages() [R3] with this package's Veusz search
    order (VEUSZ_ENV_VARS). Veusz renders a temporary copy with a plain
    name in a private folder; the results are then moved next to the
    document as "<stem>.pdf" and "<stem>_pNN_<page>.png". This avoids two
    render_pages() 0.0.5 limitations: it names the PDF stem.with_suffix(),
    so "run v0.0.2.vszh5" gave "run v0.0.pdf", and it lists only files
    that did not exist before, so a re-render returned nothing.

    Parameters
    ----------
    vszh5_path:
        Document to render.
    outdir:
        Output folder (default: the document's folder).
    dpi:
        PNG resolution.
    png_pages:
        "all", "first" or "none".
    pdf:
        Also write "<stem>.pdf" with every page.
    veusz_exe:
        Veusz program; searched for when empty.
    method:
        "auto" (program, falling back to the veusz package), "program" or
        "inprocess".
    timeout:
        Seconds before a hung Veusz program is killed.

    Returns
    -------
    list of pathlib.Path
        PDF/PNG files written or rewritten.

    Raises
    ------
    RuntimeError
        Veusz is not available or the render failed.
    """
    src = Path(vszh5_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(src)
    out = Path(outdir).resolve() if outdir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    if veusz_exe and not os.path.isfile(veusz_exe):
        raise RuntimeError(f"Veusz program {veusz_exe!r} does not exist")
    exe = "" if method == "inprocess" else find_veusz(veusz_exe)
    if method == "program" and not exe:
        raise RuntimeError("Veusz program not found: set TIME_STABILITY_VEUSZ (or "
                           "VEUSZ_EXE) to the veusz executable, or pass --veusz-exe")
    if png_pages not in ("all", "first", "none"):
        raise ValueError(f"png_pages must be all, first or none, not {png_pages!r}")
    n_pages = _page_count(src)
    tmp = Path(tempfile.mkdtemp(prefix=".vszh5_render_", dir=str(out)))
    try:
        work = tmp / (_RENDER_STEM + ".vszh5")
        shutil.copyfile(src, work)
        # "first" is rendered as "all" and trimmed below: render_pages()
        # 0.0.5 limits the page loop with min(1, len(names)), and Veusz 4.2.1
        # evaluates its scripts with NumPy's names imported, so that min is
        # numpy.min(1, axis=n) -> AxisError, swallowed by --listen: no PNG.
        try:
            vw.render_pages(work, tmp, dpi=int(dpi), pdf=pdf,
                            png_pages="all" if png_pages == "first" else png_pages,
                            veusz_exe=exe, timeout=timeout,
                            method=method if exe or method != "auto" else "inprocess")
        except RuntimeError as exc:
            # vszh5_writer names QuickSyn's variable; point at this package's.
            raise RuntimeError(str(exc).replace("QUICKSYN_VEUSZ", "TIME_STABILITY_VEUSZ")
                               .replace(str(work), str(src))) from exc
        made = sorted(p for p in tmp.iterdir()
                      if p.suffix.lower() in (".pdf", ".png") and p.name.startswith(_RENDER_STEM))
        pngs = [p for p in made if p.suffix.lower() == ".png"]
        if png_pages == "first":
            for p in pngs[1:]:
                p.unlink()
            pngs = pngs[:1]
        # A Veusz script error in --listen mode is printed, not raised, and
        # the done marker still arrives - so check that the files exist.
        want_png = {"all": n_pages, "first": min(1, n_pages), "none": 0}[png_pages]
        has_pdf = any(p.suffix.lower() == ".pdf" for p in made)
        if (pdf and not has_pdf) or len(pngs) < want_png:
            raise RuntimeError(f"Veusz finished without writing every file: PDF "
                               f"{'ok' if has_pdf or not pdf else 'missing'}, "
                               f"{len(pngs)} of {want_png} PNG")
        written: List[Path] = []
        for p in sorted(p for p in tmp.iterdir() if p.suffix.lower() in (".pdf", ".png")):
            final = out / (src.stem + p.name[len(_RENDER_STEM):])
            os.replace(p, final)         # same folder tree: atomic replace
            written.append(final)
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _page_count(path: Path) -> int:
    """Number of pages the document script of a .vszh5 creates."""
    try:
        import h5py
        with h5py.File(path, "r") as f:
            script = f["Veusz/Document/document"][0]
        script = script.decode("utf-8") if isinstance(script, bytes) else str(script)
        return len(re.findall(r"""Add\(['"]page['"]""", script))
    except Exception:  # noqa: BLE001 - unknown layout: do not verify pages
        return 0


def _python_for_child() -> str:
    """Interpreter for child processes; python.exe rather than pythonw.exe."""
    exe = sys.executable or "python"
    if os.name == "nt" and exe.lower().endswith("pythonw.exe"):
        console = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.isfile(console):
            return console
    return exe


def render_command(vszh5_path: "str | os.PathLike", outdir: "str | os.PathLike | None" = None,
                   dpi: int = 150, png_pages: str = "all", pdf: bool = True,
                   veusz_exe: str = "", method: str = "auto") -> List[str]:
    """Command line that renders ``vszh5_path`` in a separate Python process."""
    cmd = [_python_for_child(), str(_THIS_FILE), "--render", str(Path(vszh5_path).resolve()),
           "--dpi", str(int(dpi)), "--png-pages", png_pages, "--render-method", method]
    if outdir:
        cmd += ["--outdir", str(outdir)]
    if not pdf:
        cmd.append("--no-pdf")
    if veusz_exe:
        cmd += ["--veusz-exe", str(veusz_exe)]
    return cmd


def render_vszh5_subprocess(vszh5_path: "str | os.PathLike", outdir: "str | os.PathLike | None" = None,
                            dpi: int = 150, png_pages: str = "all", pdf: bool = True,
                            veusz_exe: str = "", method: str = "auto",
                            timeout: float = 900.0) -> List[Path]:
    """render_vszh5() in a child process, so Veusz's Qt never loads here.

    Use this from a PySide6 program (the GUI): an in-process fallback render
    would import veusz.qtall, i.e. a second Qt binding, into the caller.

    Returns
    -------
    list of pathlib.Path
        Files reported by the child ("RENDERED <path>" lines).

    Raises
    ------
    RuntimeError
        The child failed; the message carries the tail of its output.
    """
    cmd = render_command(vszh5_path, outdir, dpi, png_pages, pdf, veusz_exe, method)
    kwargs: Dict[str, Any] = {"creationflags": 0x08000000} if os.name == "nt" else {}
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, **kwargs)
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip()[-1500:]
        raise RuntimeError(f"render failed (exit {res.returncode}): {tail}")
    return [Path(line[len("RENDERED "):].strip()) for line in res.stdout.splitlines()
            if line.startswith("RENDERED ")]


# %% ===========================================================================
#    0.0.1-COMPATIBLE WRAPPERS
# =============================================================================
def export_all_plots(output_path: str,
                     t_s: Sequence[float], x_raw: Sequence[float],
                     x_residual: Optional[Sequence[float]],
                     sigma_tau_series: Mapping[str, Mapping[str, Sequence[float]]],
                     phase_noise_freq: Optional[Sequence[float]] = None,
                     phase_noise_lf: Optional[Sequence[float]] = None,
                     title: str = "SA Stability Analysis") -> str:
    """0.0.1 signature, now writing a real .vszh5 through export_vszh5().

    sigma_tau_series: {label: {"tau": [...], "dev": [...]}}; a "TDEV" label
    is drawn on the TDEV page. Returns the path written as a string.
    """
    pn = None
    if phase_noise_freq is not None and phase_noise_lf is not None:
        pn = {"freq_hz": phase_noise_freq, "l_f_dbc_hz": phase_noise_lf,
              "method": "supplied by caller"}
    return str(export_vszh5(output_path, t_s, x_raw, x_residual=x_residual,
                            sigma_tau_series=sigma_tau_series, phase_noise=pn,
                            title=title))


def export_all_plots_subprocess(output_path: str,
                                t_s: Sequence[float], x_raw: Sequence[float],
                                x_residual: Optional[Sequence[float]],
                                sigma_tau_series: Mapping[str, Mapping[str, Sequence[float]]],
                                phase_noise_freq: Optional[Sequence[float]] = None,
                                phase_noise_lf: Optional[Sequence[float]] = None,
                                title: str = "SA Stability Analysis",
                                timeout_s: int = 300) -> str:
    """Deprecated 0.0.1 name, kept for callers.

    0.0.1 ran the export in a child process to keep veusz.embed's PyQt6 out
    of the PySide6 GUI. Writing no longer imports Veusz or any Qt binding,
    so this now runs in-process; ``timeout_s`` is accepted and ignored.
    """
    del timeout_s
    return export_all_plots(output_path, t_s, x_raw, x_residual, sigma_tau_series,
                            phase_noise_freq, phase_noise_lf, title)


# %% ===========================================================================
#    COMMAND LINE
# =============================================================================
def version_banner() -> str:
    """Text printed by --version."""
    return (f"{PROGRAM_NAME} {__version__} ({PACKAGE_NAME}); "
            f"vszh5_writer {vw.__version__}\n{__copyright__}\n"
            f"Author: {__author__} <{__email__}>, {__company__}\n"
            f"Licence: {__license__}. This program comes with ABSOLUTELY NO WARRANTY.")


def build_parser() -> argparse.ArgumentParser:
    """Command-line parser (render an existing .vszh5, or a 0.0.1 payload)."""
    p = argparse.ArgumentParser(
        prog="veusz_export.py",
        description="Write or render Veusz HDF5 (.vszh5) documents of a "
                    "time-stability analysis.")
    p.add_argument("--render", metavar="VSZH5", help="render this .vszh5 to PDF/PNG")
    p.add_argument("--payload", metavar="JSON", help="0.0.1 JSON payload to export")
    p.add_argument("--and-render", action="store_true",
                   help="with --payload: render the written file as well")
    p.add_argument("--outdir", default=None, help="render output folder")
    p.add_argument("--dpi", type=int, default=150, help="PNG resolution (default 150)")
    p.add_argument("--png-pages", choices=("all", "first", "none"), default="all")
    p.add_argument("--no-pdf", action="store_true", help="skip the multipage PDF")
    p.add_argument("--veusz-exe", default="", help="Veusz program (default: search)")
    p.add_argument("--render-method", choices=("auto", "program", "inprocess"),
                   default="auto")
    p.add_argument("--timeout", type=float, default=600.0,
                   help="seconds before a hung Veusz is killed")
    p.add_argument("--version", "-V", action="version", version=version_banner())
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point. Returns the process exit status."""
    args = build_parser().parse_args(argv)
    if not args.render and not args.payload:
        build_parser().print_help()
        return 0
    try:
        target = args.render
        if args.payload:
            with open(args.payload, "r", encoding="utf-8") as fh:
                pl = json.load(fh)
            target = export_all_plots(
                pl["output_path"], pl["t_s"], pl["x_raw"], pl.get("x_residual"),
                pl.get("sigma_tau_series") or {}, pl.get("phase_noise_freq"),
                pl.get("phase_noise_lf"), pl.get("title", "SA Stability Analysis"))
            print(f"WROTE {target}")
            print(f"OK: wrote {target}")            # 0.0.1 wording, for old callers
            if not args.and_render:
                return 0
        files = render_vszh5(target, outdir=args.outdir, dpi=args.dpi,
                             png_pages=args.png_pages, pdf=not args.no_pdf,
                             veusz_exe=args.veusz_exe, method=args.render_method,
                             timeout=args.timeout)
        for f in files:
            print(f"RENDERED {f}")
        return 0
    except Exception as exc:  # noqa: BLE001 - report, exit non-zero
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    _status = main()
    if not _running_in_ipython():       # Spyder/IPython: keep the console alive
        sys.exit(_status)


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# import numpy as np, stability_core as sc, phase_noise as pn
# x = sc.generate_power_law_phase(4096, 1.0, alpha=-1, seed=5)
# t = np.arange(x.size) * 1.0
# d = sc.fit_and_remove_drift(x, t, order=1)
# pts = sc.compute_all_deviations(d.residual_x, 1.0)
# th = sc.compute_theoh_family(d.residual_x, 1.0)
# res = pn.ssb_phase_noise_from_time_series(d.residual_x, 1.0, 1e7)
# p = export_vszh5("scratch.vszh5", t, x, x_residual=d.residual_x, tau0=1.0,
#                  dev_points=pts, theoh_points=th, phase_noise=res, drift=d)
# print(p, render_vszh5(p, png_pages="first"))
