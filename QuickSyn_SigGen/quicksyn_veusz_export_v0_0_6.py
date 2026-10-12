#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""QuickSyn session reduction and Veusz HDF5 (.vszh5) plot export.

===============================================================================
 Title          : QuickSyn Session Reduction and Veusz Export
 Filename       : quicksyn_veusz_export_v0_0_6.py
 Version        : 0.0.6  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-09
 Modified       : 2026-10-11
 Language       : Python 3.12
 Companion to   : quicksyn_scpi_gui_v0_0_6.py
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Internal draft - NOT yet verified against hardware
===============================================================================

LICENCE
-------
Copyright (C) 2026 William W. Wallace <wwallace@nrao.edu>

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

The full licence text is in the file LICENSE distributed with this
program. Veusz is GPL-2.0-or-later and is only imported (to render), never
bundled; h5py and NumPy (BSD-3-Clause) and CuPy (MIT) are compatible.

DESCRIPTION
-----------
Post-session reduction for the logs written by the QuickSyn SCPI controller.
Reads a session directory, loads whichever telemetry representation is
present, computes timing and stability statistics, and writes a Veusz
HDF5 document (.vszh5) DIRECTLY with h5py through vszh5_writer.py (the
writer from isp_speed_monitor.py) - Veusz is not needed to create it. The
document holds every telemetry field, UTC and local date axes, the
commanded changes from state_events.csv, the ADEV and the metadata as
tagged Veusz datasets, plus an overview page and one page per quantity.
When Veusz is installed, a multipage PDF and PNGs are rendered FROM the
.vszh5 by driving the Veusz program, which also proves the file opens in
Veusz. No text .vsz is written:
a .vsz stores embedded data as text with 7 significant digits, an error of
up to 500 Hz below 10 GHz and 5 kHz from 10 GHz up; the .vszh5 keeps float64.

The rendered PDF carries a bookmark hierarchy (session > overview, time
series > one entry per quantity, stability > ADEV; needs pypdf). Alongside
it a LuaLaTeX report is written and, when lualatex is installed, compiled:
the same plots as vector graphics, with the statistics tables, the
equations, the instrument identity and references, and the section
structure as its own bookmark hierarchy.

Two telemetry representations are written by the controller and either can
be used here:

* ``telemetry.csv``              streamed row by row, human readable
* ``telemetry_chunk_####.pkl.gz`` gzip-pickled NumPy record blocks

The chunk files are preferred because they are already typed and are read
in parallel; the CSV is the fallback and the audit copy. Loading is
parallelised across processes with ``ProcessPoolExecutor``, which is the
right primitive here because gzip decompression is CPU bound and releases
no useful concurrency under the GIL.

GPU ACCELERATION
----------------
Optional and automatic. If CuPy is importable and a device is visible, the
Allan-deviation and moving-statistic reductions run on the GPU; otherwise
the identical NumPy path runs on the host. The crossover is around a few
hundred thousand samples, which a multi-hour session at 10 Hz reaches, so
the choice is reported rather than assumed. Set ``--no-gpu`` to force the
host path, which is also what the regression comparison uses.

OUTPUTS (written into the session directory)
--------------------------------------------
    reduction_summary.json        Every computed statistic, machine readable
    reduction_summary.md          The same, as an Obsidian-ready table
    telemetry_reduced.npz         Concatenated records plus derived series
    quicksyn_session.vszh5        Veusz HDF5 document: data + pages.
                                  Open it in Veusz (File > Open) to restyle.
    quicksyn_session.pdf          Every page, rendered from the .vszh5, with
                                  a bookmark hierarchy (pypdf)
    quicksyn_session_pNN_*.png    Page PNGs (overview only by default)
    quicksyn_session_report.tex   LuaLaTeX report: statistics, equations and
                                  every plot page; written when rendering
    quicksyn_session_report.pdf   The compiled report, with bookmarks (only
                                  when lualatex is found; .log kept beside it)

USAGE
-----
    python quicksyn_veusz_export_v0_0_6.py <session_dir> [options]

        --no-gpu            force the NumPy host path
        --no-veusz          compute and tabulate only: no .vszh5, no plots
        --no-render         write the .vszh5 but do not render PDF/PNG
        --no-compress       store .vszh5 datasets uncompressed
        --time-axis A       local (default), utc or elapsed
        --png-pages P       first (default), all or none
        --veusz-exe PATH    Veusz program used to render (default: search
                            QUICKSYN_VEUSZ, VEUSZ_EXE, PATH, install folders)
        --render-method M   auto (default), program or inprocess
        --workers N         process-pool size (default: CPUs available to this
                            process, see available_cpus())
        --dpi N             PNG render resolution (default 150)
        --no-latex          do not write or compile the LuaLaTeX report
        --lualatex PATH     lualatex to use (default: search QUICKSYN_LUALATEX,
                            PATH, C:\\texlive\\<year>\\bin\\windows, MiKTeX)
        --version, -V       print version, copyright and licence, then exit

REQUIREMENTS
------------
    python >= 3.12
    numpy >= 1.26
    h5py  >= 3.0      (writes the .vszh5; no Veusz needed for that)
    vszh5_writer.py   (shipped beside this script)
    veusz >= 3.6      (optional; program or package, only to render)
    pypdf >= 4        (optional; bookmarks in the rendered PDF)
    LuaLaTeX          (optional; TeX Live or MiKTeX, compiles the report)
    cupy  >= 13       (optional; GPU reductions)

REFERENCES
----------
[R1] National Instruments, "QuickSyn Microwave Synthesizers: Communications
     Specifications," Doc. No. 5580510-01, 2014.
[R4] National Instruments, "QuickSyn Frequency Synthesizers," product
     brochure and datasheet, Oct. 2017.
[R8] J. Veusz Developers, "Veusz: a scientific plotting package,"
     https://veusz.github.io/
[R9] IEEE Std 1139-2008, "IEEE Standard Definitions of Physical Quantities
     for Fundamental Frequency and Time Metrology - Random Instabilities."
[R10] Veusz Developers, Veusz 4.2.1 source distribution: veusz/document/
     doc.py (saveToHDF5File), veusz/document/loader.py (loadHDF5Doc),
     veusz/datasets/oned.py, veusz/utils/utilfuncs.py (escapeHDFDataName).
     https://pypi.org/project/veusz/4.2.1/
[R11] W. W. Wallace, isp_speed_monitor.py 1.3.0 (VeuszWriter, VszDoc,
     export_veusz), Adaptive Electrodynamics LLC dba AdaptEd, 2026.

THEORY OF THE REPORTED STATISTICS
---------------------------------
Fractional frequency error of sample i against the commanded carrier f_c:

    y_i = (f_i - f_c) / f_c                                            (1)

Overlapping Allan deviation at averaging time tau = m * tau_0, where tau_0
is the sample interval and N is the number of samples [R9]:

    sigma_y^2(tau) = 1 / (2 (N - 2m + 1) m^2)
                     * sum_{j=1}^{N-2m+1} ( sum_{i=j}^{j+m-1} (y_{i+m} - y_i) )^2
                                                                       (2)

    ADEV(tau) = sqrt( sigma_y^2(tau) )                                 (3)

Note that this estimates the stability of the synthesiser AS REPORTED BY
ITS OWN FREQ? QUERY, which returns the commanded setting rather than a
measurement of the output. It is therefore a measure of command fidelity
and of the logging time base, NOT of carrier phase noise; [R4] specifies
phase noise separately and it cannot be inferred from this log. The
statistic is still useful: a non-zero ADEV here means commands were lost,
retimed, or applied late.

Sampling jitter, from the monotonic time base:

    tau_0,i = t_i - t_{i-1},   jitter = std(tau_0,i)                   (4)

REVISION HISTORY
----------------
0.0.1  2026-10-09  Not released (the controller's 0.0.1 shipped alone).
0.0.2  2026-10-09  First release, matched to controller revision 0.0.2.
0.0.3  2026-10-09  Release metadata: author, company, email, GPL-3.0-or-later
                   header and SPDX tags, module dunders, --version flag.
                   FIX: os.process_cpu_count() exists only from Python 3.13,
                   so the default worker count raised AttributeError on the
                   declared 3.12 target; replaced by available_cpus().
0.0.4  2026-10-11  Veusz output is a .vszh5 (HDF5) document written directly
                   with h5py through vszh5_writer.py, the author's writer from
                   isp_speed_monitor.py 1.3.0; no text .vsz (that kept only 7
                   significant digits: up to 500 Hz error below 10 GHz, 5 kHz
                   above). export_veusz() follows the speed monitor's layout:
                   tagged raw/, events/, stability/, meta/ datasets, UTC and
                   local Veusz date axes, an overview page and one page per
                   quantity, commanded values overlaid as markers, atomic
                   write. PDF (all pages) and PNG are rendered from the .vszh5
                   by driving the Veusz program in --listen mode (neither
                   `veusz --export` nor the embedded Load opens a .vszh5),
                   with the veusz package as a fallback. Labels escaped
                   exactly as Veusz latexEscape. New options --time-axis,
                   --png-pages, --veusz-exe, --render-method, --no-render,
                   --no-compress. Checked against real Veusz 3.6.2 and 4.2.1.
0.0.5  2026-10-11  Released with controller 0.0.5. No change to the reduction
                   or to the document written. Rendering gains the
                   vszh5_writer 0.0.5 fixes: Windows paths in the PNG
                   names, --render-method auto falls back to the veusz
                   package when the Veusz program fails (not only when it is
                   missing), and a program that cannot start is reported as
                   a render failure while the .vszh5 is kept.
0.0.6  2026-10-11  Released with controller 0.0.6 (0.0.5 was never
                   packaged; its changes ship here). The rendered PDF gets a
                   bookmark hierarchy: session > Overview, Time series (one
                   entry per quantity), Stability (session_outline(), written
                   by vszh5_writer.add_pdf_bookmarks) plus title, subject and
                   keywords. New LuaLaTeX report quicksyn_session_report.tex,
                   compiled to PDF when lualatex is found (find_lualatex()
                   also searches the TeX Live and MiKTeX folders on Windows):
                   instrument, timing, signal, thermal and stability tables
                   with their equations, every plot page as vector graphics
                   from the Veusz PDF, the session's files and IEEE-style
                   references; hyperref bookmarks follow the sections and the
                   bookmark pane opens on load. New options --no-latex and
                   --lualatex. No change to the reduction or the .vszh5.
===============================================================================
"""

# %% ===========================================================================
#    INTERPRETER GUARD
# =============================================================================
import sys

MIN_PYTHON: tuple[int, int] = (3, 12)
if sys.version_info < MIN_PYTHON:  # pragma: no cover
    raise RuntimeError(
        f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; "
        f"this interpreter is {sys.version.split()[0]}."
    )

# %% ===========================================================================
#    IMPORTS
# =============================================================================
import argparse
import csv
import datetime
import glob
import importlib.util
import gzip
import json
import math
import os
import pickle
import re
import shutil
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

import numpy as np

# --- Optional GPU backend ---------------------------------------------------
# CuPy mirrors the NumPy API closely enough that the reduction code below is
# written once against a module alias. The import is deliberately broad:
# CuPy raises several unrelated exception types when no driver is present.
try:  # pragma: no cover - depends on host hardware
    import cupy as _cp

    _cp.zeros(1).sum()          # force context creation to catch driver gaps
    HAVE_CUPY = True
    GPU_NAME = _cp.cuda.runtime.getDeviceProperties(0)["name"].decode()
except Exception:  # pragma: no cover
    _cp = None
    HAVE_CUPY = False
    GPU_NAME = ""

# --- Optional packages, detected without importing them -------------------
# h5py writes the .vszh5. Veusz is only needed to render, and is driven as
# a separate program (or imported inside vszh5_writer.render_pages as a
# fallback), so a reduction never pays for Qt start-up unless it renders.
HAVE_H5PY = importlib.util.find_spec("h5py") is not None

# --- Veusz HDF5 writer (vszh5_writer.py, shipped beside this script) --------
# Added to sys.path explicitly: under `python -I` the script's own folder is
# not on the import path.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
try:
    import vszh5_writer as vw
except ImportError:  # pragma: no cover - reported by export_veusz()
    vw = None

__version__ = "0.0.6"                 # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"      # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"
__status__ = "Internal draft - not yet verified against hardware"
PROGRAM_NAME = "QuickSyn Session Reduction and Veusz Export"

#: Record layout written by the controller. Kept in step with
#: quicksyn_scpi_gui_v0_0_6.TELEMETRY_DTYPE.
TELEMETRY_DTYPE = np.dtype(
    [
        ("idx", "i8"),
        ("t_unix", "f8"),
        ("t_mono", "f8"),
        ("freq_hz", "f8"),
        ("power_dbm", "f4"),
        ("temp_c", "f4"),
        ("status", "u2"),
        ("modmask", "u2"),
        ("latency_s", "f4"),
        ("rate_hz", "f4"),
    ]
)


# %% ===========================================================================
#    HOST HELPERS
# =============================================================================
def available_cpus() -> int:
    """Return the number of CPUs this process may actually use.

    ``os.process_cpu_count()`` would be the natural call, but it was only
    added in Python 3.13 and this program targets 3.12. The portable
    equivalent is the scheduler affinity mask, which respects cgroup and
    ``taskset`` limits (containers, HPC job slots) that plain
    ``os.cpu_count()`` ignores. ``sched_getaffinity`` is Linux-only, so on
    Windows and macOS the code falls back to ``os.cpu_count()``.

    Returns
    -------
    int
        A positive CPU count; 1 if nothing better can be determined.
    """
    getter = getattr(os, "sched_getaffinity", None)
    if getter is not None:
        try:
            return max(1, len(getter(0)))
        except OSError:  # pragma: no cover - unusual kernels only
            pass
    return max(1, os.cpu_count() or 1)


def version_banner() -> str:
    """Return the text printed by ``--version`` (no display or deps needed)."""
    return (
        f"{PROGRAM_NAME} {__version__}\n"
        f"{__copyright__}\n"
        f"Author:  {__author__} <{__email__}>, {__company__}\n"
        f"Licence: {__license__} (GNU GPL v3 or later). "
        f"This program comes with ABSOLUTELY NO WARRANTY."
    )


# %% ===========================================================================
#    PARALLEL LOADERS
# =============================================================================
def _load_chunk(path_str: str) -> np.ndarray:
    """Load one gzip-pickle telemetry chunk. Runs in a worker process.

    Defined at module level because a ``ProcessPoolExecutor`` payload must
    be picklable by reference, which a closure or a bound method is not.

    Parameters
    ----------
    path_str:
        Absolute path to a ``telemetry_chunk_####.pkl.gz`` file.

    Returns
    -------
    numpy.ndarray
        The records it contained, as ``TELEMETRY_DTYPE``.
    """
    with gzip.open(path_str, "rb") as handle:
        blob = pickle.load(handle)
    records = np.asarray(blob["records"])
    if records.dtype != TELEMETRY_DTYPE:
        records = records.astype(TELEMETRY_DTYPE)
    return records


def load_session_records(
    session_dir: Path, workers: int | None = None
) -> tuple[np.ndarray, str]:
    """Load a session's telemetry, preferring the binary chunks.

    Parameters
    ----------
    session_dir:
        A session directory written by the controller.
    workers:
        Process-pool size. ``None`` uses the interpreter's view of the
        available CPUs.

    Returns
    -------
    tuple
        ``(records, source)`` where source is ``"chunks"`` or ``"csv"``.

    Raises
    ------
    FileNotFoundError
        If neither representation is present.
    """
    chunks = sorted(session_dir.glob("telemetry_chunk_*.pkl.gz"))
    if chunks:
        # Decompression is CPU bound, so processes rather than threads.
        with ProcessPoolExecutor(max_workers=workers) as pool:
            blocks = list(pool.map(_load_chunk, [str(p) for p in chunks]))
        records = np.concatenate(blocks) if blocks else np.zeros(0, TELEMETRY_DTYPE)
        # Chunks are written in order, but a manual flush can interleave, so
        # sort on the monotonic sample index to be certain.
        return np.sort(records, order="idx"), "chunks"

    csv_path = session_dir / "telemetry.csv"
    if not csv_path.exists():
        # A common mistake is passing the log ROOT rather than one session,
        # so name the sessions found underneath it instead of just failing.
        nested = sorted(
            child.name
            for child in session_dir.iterdir()
            if child.is_dir() and (child / "telemetry.csv").exists()
        )
        hint = (
            "\nThis looks like a log root. Sessions found here:\n  "
            + "\n  ".join(nested[:10])
            if nested
            else ""
        )
        raise FileNotFoundError(
            f"{session_dir} holds neither telemetry chunks nor "
            f"telemetry.csv.{hint}"
        )
    return load_telemetry_csv(csv_path), "csv"


def load_telemetry_csv(csv_path: Path) -> np.ndarray:
    """Parse telemetry.csv into the binary record layout.

    Blank numeric cells, which the controller writes when a field was not
    polled on that sample, become NaN rather than zero so that they are
    excluded from statistics instead of dragging them down.
    """
    out: list[tuple] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            def num(key: str, default: float = math.nan) -> float:
                """Read one cell as a float, tolerating blanks."""
                text = (row.get(key) or "").strip()
                return float(text) if text else default

            out.append(
                (
                    int(row.get("idx") or 0),
                    num("t_unix", 0.0),
                    num("t_mono_s", 0.0),
                    num("freq_hz"),
                    num("power_dbm"),
                    num("temp_c"),
                    int(row.get("status_hex") or "0", 16),
                    int(row.get("mod_hex") or "0", 16),
                    num("latency_s", 0.0),
                    num("rate_hz", 0.0),
                )
            )
    return np.array(out, dtype=TELEMETRY_DTYPE)


# %% ===========================================================================
#    REDUCTIONS
# =============================================================================
def _xp(use_gpu: bool):
    """Return the array module to compute with: CuPy or NumPy."""
    return _cp if (use_gpu and HAVE_CUPY) else np


def overlapping_adev(
    y: np.ndarray, tau0: float, use_gpu: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Overlapping Allan deviation of a fractional-frequency series.

    Implements equations (2) and (3) of the module header. The inner double
    sum is evaluated as a cumulative sum of the phase residuals, which turns
    the O(N*m) sum into O(N) per averaging factor:

        x_k = tau0 * sum_{i<k} y_i                      (phase residual)
        sigma_y(tau) = sqrt( sum (x_{k+2m} - 2 x_{k+m} + x_k)^2
                             / (2 (N - 2m + 1) tau^2) )

    Parameters
    ----------
    y:
        Fractional frequency error series, equation (1). NaNs are dropped.
    tau0:
        Base sample interval in seconds.
    use_gpu:
        Compute on the GPU when CuPy is available.

    Returns
    -------
    tuple of numpy.ndarray
        ``(tau, adev)``. Both are empty when there are too few samples.
    """
    xp = _xp(use_gpu)
    y = y[np.isfinite(y)]
    n = y.size
    if n < 4 or tau0 <= 0.0:
        return np.zeros(0), np.zeros(0)

    y_dev = xp.asarray(y, dtype=xp.float64)
    # Phase residuals: x has N+1 entries, x[0] = 0.
    x = xp.concatenate((xp.zeros(1, dtype=xp.float64), xp.cumsum(y_dev) * tau0))

    # Octave-spaced averaging factors, the usual choice for a log-log plot.
    max_m = (n - 1) // 2
    if max_m < 1:
        return np.zeros(0), np.zeros(0)
    m_values = [1]
    while m_values[-1] * 2 <= max_m:
        m_values.append(m_values[-1] * 2)

    taus: list[float] = []
    devs: list[float] = []
    for m in m_values:
        count = n - 2 * m + 1
        if count < 1:
            continue
        second_difference = x[2 * m : 2 * m + count] \
            - 2.0 * x[m : m + count] + x[:count]
        tau = m * tau0
        variance = float(
            (second_difference ** 2).sum() / (2.0 * count * tau * tau)
        )
        taus.append(tau)
        devs.append(math.sqrt(max(variance, 0.0)))
    return np.asarray(taus), np.asarray(devs)


def moving_statistics(
    values: np.ndarray, window: int, use_gpu: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    """Moving mean and population standard deviation over a fixed window.

    Evaluated from cumulative sums of the values and their squares, so the
    cost is independent of the window length:

        mean  = (S1[k+w] - S1[k]) / w
        var   = (S2[k+w] - S2[k]) / w - mean^2

    Parameters
    ----------
    values:
        Input series. NaNs propagate into the windows that contain them,
        which is intentional: a window spanning missing data has no mean.
    window:
        Window length in samples, clamped to the series length.
    use_gpu:
        Compute on the GPU when CuPy is available.

    Returns
    -------
    tuple of numpy.ndarray
        ``(mean, std)``, each of length ``len(values) - window + 1``.
    """
    xp = _xp(use_gpu)
    window = int(max(1, min(window, values.size)))
    if values.size == 0:
        return np.zeros(0), np.zeros(0)
    v = xp.asarray(values, dtype=xp.float64)
    s1 = xp.concatenate((xp.zeros(1, dtype=xp.float64), xp.cumsum(v)))
    s2 = xp.concatenate((xp.zeros(1, dtype=xp.float64), xp.cumsum(v * v)))
    mean = (s1[window:] - s1[:-window]) / window
    var = (s2[window:] - s2[:-window]) / window - mean * mean
    std = xp.sqrt(xp.maximum(var, 0.0))
    if xp is not np:  # pragma: no cover - GPU path
        mean, std = _cp.asnumpy(mean), _cp.asnumpy(std)
    return np.asarray(mean), np.asarray(std)


@dataclass(slots=True)
class SessionStatistics:
    """Everything the reduction computes, ready for JSON or a table."""

    n_samples: int = 0
    source: str = ""
    duration_s: float = 0.0
    requested_rate_hz: float = math.nan
    achieved_rate_hz: float = math.nan
    interval_mean_s: float = math.nan
    interval_std_s: float = math.nan
    interval_min_s: float = math.nan
    interval_max_s: float = math.nan
    jitter_ppm_of_period: float = math.nan
    latency_mean_ms: float = math.nan
    latency_p95_ms: float = math.nan
    latency_max_ms: float = math.nan
    freq_unique_count: int = 0
    freq_min_ghz: float = math.nan
    freq_max_ghz: float = math.nan
    power_min_dbm: float = math.nan
    power_max_dbm: float = math.nan
    temp_min_c: float = math.nan
    temp_max_c: float = math.nan
    temp_rise_c: float = math.nan
    temp_margin_to_75c: float = math.nan
    rf_on_fraction: float = math.nan
    rf_unlocked_samples: int = 0
    ref_unlocked_samples: int = 0
    voltage_error_samples: int = 0
    adev_tau_s: list[float] = None
    adev: list[float] = None
    compute_backend: str = "numpy"
    compute_seconds: float = math.nan


def reduce_session(
    records: np.ndarray,
    source: str,
    metadata: dict[str, Any] | None = None,
    use_gpu: bool = False,
) -> SessionStatistics:
    """Compute every reported statistic for one session.

    Parameters
    ----------
    records:
        Telemetry records in ``TELEMETRY_DTYPE``.
    source:
        Where they came from, for the report.
    metadata:
        Parsed ``session_metadata.json``, used for the requested rate.
    use_gpu:
        Request the CuPy path for the heavy reductions.

    Returns
    -------
    SessionStatistics
        Populated statistics. Fields that cannot be computed stay NaN.
    """
    t_start = time.perf_counter()
    stats = SessionStatistics(n_samples=int(records.size), source=source)
    stats.compute_backend = (
        f"cupy ({GPU_NAME})" if (use_gpu and HAVE_CUPY) else "numpy"
    )
    if metadata:
        stats.requested_rate_hz = float(
            metadata.get("sampler", {}).get("rate_hz", math.nan)
        )
    if records.size == 0:
        stats.compute_seconds = time.perf_counter() - t_start
        return stats

    # --- Timing, equation (4) ---------------------------------------------
    t = records["t_mono"].astype(np.float64)
    stats.duration_s = float(t[-1] - t[0]) if records.size > 1 else 0.0
    if records.size > 1:
        intervals = np.diff(t)
        intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
        if intervals.size:
            stats.interval_mean_s = float(intervals.mean())
            stats.interval_std_s = float(intervals.std())
            stats.interval_min_s = float(intervals.min())
            stats.interval_max_s = float(intervals.max())
            stats.achieved_rate_hz = 1.0 / stats.interval_mean_s
            stats.jitter_ppm_of_period = float(
                1e6 * stats.interval_std_s / stats.interval_mean_s
            )

    latency_ms = records["latency_s"].astype(np.float64) * 1e3
    latency_ms = latency_ms[np.isfinite(latency_ms)]
    if latency_ms.size:
        stats.latency_mean_ms = float(latency_ms.mean())
        stats.latency_p95_ms = float(np.percentile(latency_ms, 95))
        stats.latency_max_ms = float(latency_ms.max())

    # --- Signal state ------------------------------------------------------
    freq = records["freq_hz"].astype(np.float64)
    finite_freq = freq[np.isfinite(freq) & (freq > 0)]
    if finite_freq.size:
        stats.freq_unique_count = int(np.unique(finite_freq).size)
        stats.freq_min_ghz = float(finite_freq.min() / 1e9)
        stats.freq_max_ghz = float(finite_freq.max() / 1e9)

    power = records["power_dbm"].astype(np.float64)
    finite_power = power[np.isfinite(power)]
    if finite_power.size:
        stats.power_min_dbm = float(finite_power.min())
        stats.power_max_dbm = float(finite_power.max())

    temp = records["temp_c"].astype(np.float64)
    finite_temp = temp[np.isfinite(temp)]
    if finite_temp.size:
        stats.temp_min_c = float(finite_temp.min())
        stats.temp_max_c = float(finite_temp.max())
        stats.temp_rise_c = float(finite_temp[-1] - finite_temp[0])
        # [R2] caps the internal temperature at +75 C.
        stats.temp_margin_to_75c = float(75.0 - finite_temp.max())

    # --- Status-bit tallies, same bit map as the controller ----------------
    status = records["status"].astype(np.uint16)
    stats.rf_on_fraction = float(((status >> 3) & 1).mean())
    stats.rf_unlocked_samples = int(((status >> 1) & 1).sum())
    stats.ref_unlocked_samples = int(((status >> 2) & 1).sum())
    stats.voltage_error_samples = int(((status >> 4) & 1).sum())

    # --- Allan deviation of the reported carrier, equations (1) to (3) -----
    stats.adev_tau_s, stats.adev = [], []
    if finite_freq.size >= 8 and math.isfinite(stats.interval_mean_s):
        f_c = float(np.median(finite_freq))
        if f_c > 0:
            y = (freq - f_c) / f_c
            tau, dev = overlapping_adev(y, stats.interval_mean_s, use_gpu)
            stats.adev_tau_s = [float(v) for v in tau]
            stats.adev = [float(v) for v in dev]

    stats.compute_seconds = time.perf_counter() - t_start
    return stats


# %% ===========================================================================
#    REPORTING
# =============================================================================
def write_markdown_summary(
    path: Path,
    stats: SessionStatistics,
    metadata: dict[str, Any] | None,
    session_dir: Path,
) -> None:
    """Write an Obsidian-ready summary with LaTeX for the equations.

    Equations use ``$$`` blocks and inline ``$`` so that they render in
    Obsidian's MathJax preview without further processing.
    """
    ident = (metadata or {}).get("identity", {})
    cap = (metadata or {}).get("capability", {})

    def row(label: str, value: Any, unit: str = "", fmt: str = "{:.6g}") -> str:
        """Format one table row, blanking values that are not finite."""
        if isinstance(value, float) and not math.isfinite(value):
            rendered = "not available"
        elif isinstance(value, float):
            rendered = fmt.format(value)
        else:
            rendered = str(value)
        return f"| {label} | {rendered} | {unit} |"

    lines: list[str] = [
        f"# QuickSyn session reduction - {session_dir.name}",
        "",
        f"Produced by `quicksyn_veusz_export_v{__version__.replace('.', '_')}.py` "
        f"on {time.strftime('%Y-%m-%d %H:%M:%S %Z')}.",
        "",
        "## Instrument",
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| `*IDN?` | `{ident.get('raw', 'unknown')}` |",
        f"| Model | {ident.get('model', 'unknown')} |",
        f"| Option field | `{ident.get('options', '')}` |",
        f"| Software version field | `{ident.get('firmware', '')}` "
        f"(= {ident.get('firmware_value')}, {ident.get('firmware_base', '')}) |",
        f"| Serial field | `{ident.get('serial', '')}` |",
        f"| Datasheet coverage | {cap.get('f_min_hz', 0) / 1e9:g} - "
        f"{cap.get('f_max_hz', 0) / 1e9:g} GHz |",
        f"| Transport | {(metadata or {}).get('transport', {}).get('port', '?')} "
        f"at {(metadata or {}).get('transport', {}).get('baudrate', '?')} baud"
        f"{' (SIMULATED)' if (metadata or {}).get('transport', {}).get('simulated') else ''} |",
        "",
        "> The `*IDN?` field order is inferred from the native Get ID order in",
        "> [R1] Table 4; it is not specified for the SCPI form.",
        "",
        "## Acquisition timing",
        "",
        "| Quantity | Value | Unit |",
        "| --- | --- | --- |",
        row("Samples", stats.n_samples),
        row("Loaded from", stats.source),
        row("Duration", stats.duration_s, "s"),
        row("Requested sample rate", stats.requested_rate_hz, "Hz"),
        row("Achieved sample rate", stats.achieved_rate_hz, "Hz"),
        row("Mean sample interval", stats.interval_mean_s * 1e3
            if math.isfinite(stats.interval_mean_s) else math.nan, "ms"),
        row("Interval std (jitter)", stats.interval_std_s * 1e3
            if math.isfinite(stats.interval_std_s) else math.nan, "ms"),
        row("Interval min / max",
            f"{stats.interval_min_s * 1e3:.3f} / {stats.interval_max_s * 1e3:.3f}"
            if math.isfinite(stats.interval_min_s) else math.nan, "ms"),
        row("Jitter relative to period", stats.jitter_ppm_of_period, "ppm"),
        row("Device I/O latency, mean", stats.latency_mean_ms, "ms"),
        row("Device I/O latency, p95", stats.latency_p95_ms, "ms"),
        row("Device I/O latency, max", stats.latency_max_ms, "ms"),
        "",
        "The sample period is the reciprocal of the requested rate,",
        "",
        r"$$ \tau_0 = \frac{1}{f_s} $$",
        "",
        "and the achievable rate is bounded by the number of serial round",
        "trips each sample costs. With $N_q$ queries per sample and a mean",
        "round-trip time $t_q$,",
        "",
        r"$$ f_{s,\max} = \frac{1}{N_q \, t_q} $$",
        "",
        "so a sample that polls frequency, power, status, modulation and",
        "temperature (the last counting twice when the conservative",
        r"double-issue rule is enabled) costs $N_q = 6$, and at",
        r"$t_q \approx 8$ ms gives $f_{s,\max} \approx 21$ Hz.",
        "",
        "## Generated signal",
        "",
        "| Quantity | Value | Unit |",
        "| --- | --- | --- |",
        row("Distinct frequencies observed", stats.freq_unique_count),
        row("Frequency min", stats.freq_min_ghz, "GHz", "{:.9f}"),
        row("Frequency max", stats.freq_max_ghz, "GHz", "{:.9f}"),
        row("Power min", stats.power_min_dbm, "dBm", "{:+.1f}"),
        row("Power max", stats.power_max_dbm, "dBm", "{:+.1f}"),
        row("RF output on, fraction of samples", stats.rf_on_fraction, "-",
            "{:.3f}"),
        row("Samples with RF unlocked", stats.rf_unlocked_samples),
        row("Samples with reference unlocked", stats.ref_unlocked_samples),
        row("Samples with voltage error", stats.voltage_error_samples),
        "",
        "## Thermal",
        "",
        "| Quantity | Value | Unit |",
        "| --- | --- | --- |",
        row("Internal temperature min", stats.temp_min_c, "degC", "{:.1f}"),
        row("Internal temperature max", stats.temp_max_c, "degC", "{:.1f}"),
        row("Rise over session", stats.temp_rise_c, "degC", "{:+.1f}"),
        row("Margin to the +75 degC limit", stats.temp_margin_to_75c, "degC",
            "{:.1f}"),
        "",
        "## Stability of the reported carrier",
        "",
        "Fractional frequency error against the median commanded carrier",
        r"$f_c$ is $y_i = (f_i - f_c)/f_c$, and the overlapping Allan",
        "deviation follows IEEE Std 1139-2008:",
        "",
        r"$$ \sigma_y^2(\tau) = \frac{1}{2\,(N-2m+1)\,\tau^2}"
        r" \sum_{k=1}^{N-2m+1} \left( x_{k+2m} - 2x_{k+m} + x_k \right)^2 ,"
        r" \qquad \tau = m\,\tau_0 $$",
        "",
        r"with phase residuals $x_k = \tau_0 \sum_{i<k} y_i$.",
        "",
        "> This characterises command fidelity and the logging time base, not",
        "> carrier phase noise: `FREQ?` returns the commanded setting, not a",
        "> measurement of the output. Phase noise is specified separately in",
        "> the datasheet and cannot be inferred from this log.",
        "",
    ]
    if stats.adev_tau_s:
        lines += [
            "| Averaging time tau (s) | ADEV |",
            "| --- | --- |",
            *[
                f"| {tau:.4g} | {dev:.3e} |"
                for tau, dev in zip(stats.adev_tau_s, stats.adev)
            ],
            "",
        ]
    else:
        lines += ["Too few samples for an Allan deviation estimate.", ""]

    lines += [
        "## Reduction",
        "",
        "| Quantity | Value |",
        "| --- | --- |",
        f"| Compute backend | {stats.compute_backend} |",
        f"| Reduction wall time | {stats.compute_seconds * 1e3:.1f} ms |",
        f"| Script revision | {__version__} |",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


# %% ===========================================================================
#    VEUSZ HDF5 EXPORT  (vszh5_writer - no Veusz needed to write)
# =============================================================================
# The file format lives in vszh5_writer.py (VeuszWriter, VszDoc, vz_text),
# taken from isp_speed_monitor.py 1.3.0. This cell only decides WHAT goes in
# the document, following the structure of isp_speed_monitor's export_veusz():
#
#   raw/*        every telemetry field, float64, plus Veusz date axes
#                raw/time_utc and raw/time_local          tag "raw"
#   events/*     commanded state changes from state_events.csv     "events"
#   stability/*  overlapping ADEV of the reported carrier          "stability"
#   meta/*       session metadata, reduction summary, generator    "meta"
#
#   page_overview          3 x 2 grid mirroring the reduction panels
#   page_carrier ... page_stability   one page per quantity

#: Panels: (page/graph name, y dataset, axis label, colour, commanded-event dataset)
VEUSZ_PANELS: tuple[tuple[str, str, str, str, str], ...] = (
    ("carrier", "raw/freq_ghz", "Carrier (GHz)", "#1f4e9c", "events/freq_ghz"),
    ("level", "raw/power_dbm", "Level (dBm)", "#2e7d32", "events/power_dbm"),
    ("thermal", "raw/temp_c", "Internal temp. (°C)", "#c62828", ""),
    ("latency", "raw/latency_ms", "I/O latency (ms)", "#8e24aa", ""),
    ("interval", "raw/interval_ms", "Sample interval (ms)", "#ef6c00", ""),
)
TIME_AXES = ("local", "utc", "elapsed")


def status_flags(status: np.ndarray) -> dict[str, np.ndarray]:
    """Decode the STAT? word, same bit map as the controller [R1, Table 5].

    Lock bits are set when UNlocked. Returned as 0/1 floats for plotting.
    """
    s = np.asarray(status).astype(np.uint16)
    return {
        "rf_unlocked": ((s >> 1) & 1).astype(float),
        "ref_unlocked": ((s >> 2) & 1).astype(float),
        "rf_on": ((s >> 3) & 1).astype(float),
        "voltage_error": ((s >> 4) & 1).astype(float),
    }


def load_state_events(session_dir: Path) -> list[dict[str, str]]:
    """Read state_events.csv (commanded changes); empty list if absent."""
    path = session_dir / "state_events.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row.get("t_unix")]


def _add_graph(doc: Any, gname: str, x_label: str, x_is_date: bool,
               y_label: str, series: list[dict[str, Any]], log_x: bool = False,
               log_y: bool = False, with_key: bool = True) -> None:
    """One graph, styled like isp_speed_monitor's _add_time_graph.

    ``series`` items: dict(name, x, y, color, key, kind) with kind "line"
    (measured trace) or "marker" (commanded values).
    """
    doc.add("graph", gname)
    doc.to(gname)
    doc.set("leftMargin", "2.0cm")
    doc.set("rightMargin", "0.4cm")
    doc.set("topMargin", "0.6cm")
    doc.set("bottomMargin", "1.6cm" if x_is_date else "1.3cm")
    doc.add("axis", "x")
    doc.add("axis", "y")
    if x_is_date:
        doc.set("x/mode", "datetime")
        doc.set("x/TickLabels/rotate", "-45")
    doc.set("x/label", x_label)
    doc.set("x/log", log_x)
    doc.set("x/TickLabels/size", "7pt")
    doc.set("y/direction", "vertical")
    doc.set("y/label", y_label)
    doc.set("y/log", log_y)
    doc.set("y/autoRange", "+5%")
    doc.set("y/TickLabels/size", "7pt")
    doc.set("y/GridLines/hide", False)
    doc.set("y/GridLines/color", "#c8c8c8")
    doc.set("y/GridLines/style", "dotted")
    for s in series:
        doc.add("xy", s["name"])
        doc.to(s["name"])
        doc.set("xData", s["x"])
        doc.set("yData", s["y"])
        doc.set("key", s["key"])
        if s["kind"] == "marker":
            doc.set("marker", "diamond")
            doc.set("markerSize", "4pt")
            doc.set("PlotLine/hide", True)
            doc.set("MarkerFill/color", "#000000")
            doc.set("MarkerLine/hide", True)
        else:
            doc.set("marker", s.get("marker", "none"))
            doc.set("markerSize", "2pt")
            doc.set("PlotLine/width", "0.8pt")
            doc.set("PlotLine/color", s["color"])
            doc.set("MarkerFill/color", s["color"])
            doc.set("MarkerLine/hide", True)
        doc.up()
    if with_key and len(series) > 1:
        # Boxed and opaque, so the key's marker sample is not read as data.
        doc.add("key", "key1")
        doc.set("key1/horzPosn", "left")
        doc.set("key1/vertPosn", "top")
        doc.set("key1/Text/size", "7pt")
        doc.set("key1/Border/hide", False)
        doc.set("key1/Background/transparency", 0)
    doc.up()


def export_veusz(
    session_dir: Path,
    records: np.ndarray,
    stats: SessionStatistics,
    metadata: dict[str, Any] | None = None,
    time_axis: str = "local",
    compress: bool = True,
    path: Path | None = None,
) -> Path:
    """Write the session as a native Veusz HDF5 document (no Veusz needed).

    Parameters
    ----------
    session_dir:
        Session folder (source of state_events.csv and the default output).
    records:
        Telemetry records, TELEMETRY_DTYPE, in time order.
    stats:
        Reduction results (ADEV and summary).
    metadata:
        session_metadata.json contents, stored under meta/.
    time_axis:
        "local" (wall clock, DST-aware), "utc", or "elapsed" (seconds).
    compress:
        gzip+shuffle for long arrays.
    path:
        Output file; default <session_dir>/quicksyn_session.vszh5.

    Returns
    -------
    pathlib.Path
        The .vszh5 written (atomically: readers never see a partial file).
    """
    if vw is None:
        raise RuntimeError("vszh5_writer.py is missing from the program folder")
    if time_axis not in TIME_AXES:
        raise ValueError(f"time_axis must be one of {TIME_AXES}")
    path = Path(path) if path else session_dir / "quicksyn_session.vszh5"
    title_base = (f"{session_dir.name}  -  {stats.n_samples} samples, "
                  f"{stats.achieved_rate_hz:.2f} Hz achieved "
                  f"({stats.requested_rate_hz:.2f} Hz requested)"
                  if math.isfinite(stats.achieved_rate_hz) else session_dir.name)

    t_unix = records["t_unix"].astype(np.float64)
    t_mono = records["t_mono"].astype(np.float64)
    offset = vw.local_utc_offsets(t_unix)
    elapsed = t_mono - t_mono[0] if t_mono.size else t_mono
    interval_ms = np.concatenate(([np.nan], np.diff(t_mono) * 1e3)) if t_mono.size else t_mono
    t0_unix = float(t_unix[0]) if t_unix.size else 0.0
    x_name = {"local": "time_local", "utc": "time_utc", "elapsed": "elapsed_s"}[time_axis]
    x_label = {"local": "Local time", "utc": "Time (UTC)", "elapsed": "Elapsed time (s)"}[time_axis]
    is_date = time_axis != "elapsed"

    w = vw.VeuszWriter(path, compress=compress, writer_tag=f"{PROGRAM_NAME} {__version__}")
    doc = vw.VszDoc(generator=f"quicksyn_veusz_export_v{__version__.replace('.', '_')}.py "
                              f"{__version__} via vszh5_writer {vw.__version__}")
    with w:
        # ---- raw telemetry -------------------------------------------------
        raw = ("raw",)
        w.dataset_date("raw/time_utc", vw.epoch_to_veusz(t_unix), raw)
        w.dataset_date("raw/time_local", vw.epoch_to_veusz(t_unix, offset), raw)
        w.dataset_1d("raw/elapsed_s", elapsed, tags=raw)
        w.dataset_1d("raw/epoch_s", t_unix, tags=raw)
        w.dataset_1d("raw/utc_offset_s", offset, tags=raw)
        w.dataset_1d("raw/index", records["idx"], tags=raw)
        w.dataset_1d("raw/freq_hz", records["freq_hz"], tags=raw)
        w.dataset_1d("raw/freq_ghz", records["freq_hz"].astype(np.float64) / 1e9, tags=raw)
        w.dataset_1d("raw/power_dbm", records["power_dbm"], tags=raw)
        w.dataset_1d("raw/temp_c", records["temp_c"], tags=raw)
        w.dataset_1d("raw/latency_ms", records["latency_s"].astype(np.float64) * 1e3, tags=raw)
        w.dataset_1d("raw/interval_ms", interval_ms, tags=raw)
        w.dataset_1d("raw/rate_hz", records["rate_hz"], tags=raw)
        w.dataset_1d("raw/status_word", records["status"], tags=raw)
        w.dataset_1d("raw/modulation_word", records["modmask"], tags=raw)
        for key, values in status_flags(records["status"]).items():
            w.dataset_1d(f"raw/{key}", values, tags=raw)

        # ---- commanded state changes ------------------------------------------
        events = load_state_events(session_dir)
        overlays: dict[str, bool] = {}
        if events:
            ev = ("events",)
            e_t = np.array([float(r["t_unix"]) for r in events])
            w.dataset_date("events/time_utc", vw.epoch_to_veusz(e_t), ev)
            w.dataset_date("events/time_local",
                           vw.epoch_to_veusz(e_t, vw.local_utc_offsets(e_t)), ev)
            w.dataset_1d("events/elapsed_s", e_t - t0_unix, tags=ev)
            w.dataset_text("events/parameter", [r.get("parameter", "") for r in events], ev)
            w.dataset_text("events/value", [r.get("value", "") for r in events], ev)
            w.dataset_text("events/source", [r.get("source", "") for r in events], ev)
            w.dataset_text("events/ts_utc_iso", [r.get("iso_utc", "") for r in events], ev)
            # Same arithmetic as raw/freq_ghz (divide by 1e9, not multiply by
            # 1e-9), so a commanded value compares equal to the reported one.
            for param, name, divisor in (("frequency_hz", "freq_ghz", 1e9),
                                         ("power_dbm", "power_dbm", 1.0)):
                sel = [r for r in events if r.get("parameter") == param]
                vals = []
                for r in sel:
                    try:
                        vals.append(float(r["value"]) / divisor)
                    except (TypeError, ValueError):
                        vals.append(math.nan)
                if sel:
                    t_sel = np.array([float(r["t_unix"]) for r in sel])
                    w.dataset_1d(f"events/{name}", vals, tags=ev)
                    w.dataset_date(f"events/{name}_time_utc", vw.epoch_to_veusz(t_sel), ev)
                    w.dataset_date(f"events/{name}_time_local",
                                   vw.epoch_to_veusz(t_sel, vw.local_utc_offsets(t_sel)), ev)
                    w.dataset_1d(f"events/{name}_elapsed_s", t_sel - t0_unix, tags=ev)
                    overlays[f"events/{name}"] = True

        # ---- stability -----------------------------------------------------------
        has_adev = bool(stats.adev_tau_s) and min(stats.adev) > 0.0
        if has_adev:
            st = ("stability",)
            w.dataset_1d("stability/tau_s", stats.adev_tau_s, tags=st)
            w.dataset_1d("stability/adev", stats.adev, tags=st)

        # ---- metadata ------------------------------------------------------------
        meta = ("meta",)
        w.dataset_text("meta/session", [session_dir.name], meta)
        w.dataset_text("meta/session_metadata_json", [json.dumps(metadata or {}, default=str)], meta)
        w.dataset_text("meta/reduction_summary_json", [json.dumps(asdict(stats), default=str)], meta)
        w.dataset_text("meta/generator", [
            f"{PROGRAM_NAME} {__version__} ({__license__})",
            f"written {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}",
            "raw/time_utc and raw/time_local are Veusz dates (s since 2009-01-01); "
            "time_local follows the host's UTC offset per sample",
            "raw/rf_unlocked, ref_unlocked, rf_on, voltage_error are decoded from raw/status_word",
            "events/* are the commanded changes logged in state_events.csv",
        ], meta)

        # ---- pages -----------------------------------------------------------------
        def series_for(y_ds: str, colour: str, ev_ds: str) -> list[dict[str, Any]]:
            out = [{"name": "measured", "x": f"raw/{x_name}", "y": y_ds, "color": colour,
                    "key": "Reported by instrument", "kind": "line"}]
            if ev_ds and overlays.get(ev_ds):
                ev_x = f"{ev_ds}_{x_name}" if x_name != "elapsed_s" else f"{ev_ds}_elapsed_s"
                out.append({"name": "commanded", "x": ev_x, "y": ev_ds, "color": "#000000",
                            "key": "Commanded", "kind": "marker"})
            return out

        adev_series = [{"name": "adev", "x": "stability/tau_s", "y": "stability/adev",
                        "color": "#000000", "key": "ADEV", "kind": "line", "marker": "circle"}]

        doc.add("page", "page_overview")
        doc.to("page_overview")
        doc.set("width", "30cm")
        doc.set("height", "24cm")
        doc.add("label", "title")
        doc.set("title/label", vw.vz_text(f"Overview  -  {title_base}"))
        doc.set("title/xPos", [0.5])
        doc.set("title/yPos", [0.98])
        doc.set("title/alignHorz", "centre")
        doc.set("title/Text/size", "11pt")
        doc.add("grid", "grid1")
        doc.to("grid1")
        doc.set("rows", 3)
        doc.set("columns", 2)
        doc.set("topMargin", "1.0cm")
        doc.set("bottomMargin", "0.3cm")
        doc.set("leftMargin", "0.3cm")
        doc.set("rightMargin", "0.3cm")
        for k, (pname, y_ds, label, colour, ev_ds) in enumerate(VEUSZ_PANELS):
            _add_graph(doc, f"g_{pname}", x_label, is_date, label,
                       series_for(y_ds, colour, ev_ds), with_key=(k == 0))
        if has_adev:
            _add_graph(doc, "g_stability", "Averaging time \\tau (s)", False,
                       "ADEV \\sigma_{y}(\\tau) of reported f", adev_series,
                       log_x=True, log_y=True, with_key=False)
        doc.up()
        doc.up()

        singles = [(p, y, l, c, e) for p, y, l, c, e in VEUSZ_PANELS]
        for pname, y_ds, label, colour, ev_ds in singles:
            doc.add("page", f"page_{pname}")
            doc.to(f"page_{pname}")
            doc.set("width", "25cm")
            doc.set("height", "15cm")
            doc.add("label", "title")
            doc.set("title/label", vw.vz_text(f"{label}  -  {title_base}"))
            doc.set("title/xPos", [0.5])
            doc.set("title/yPos", [0.965])
            doc.set("title/alignHorz", "centre")
            doc.set("title/Text/size", "10pt")
            _add_graph(doc, f"g_{pname}", x_label, is_date, label,
                       series_for(y_ds, colour, ev_ds))
            doc.up()
        if has_adev:
            doc.add("page", "page_stability")
            doc.to("page_stability")
            doc.set("width", "25cm")
            doc.set("height", "15cm")
            doc.add("label", "title")
            doc.set("title/label", vw.vz_text(f"Allan deviation of the reported carrier  -  {title_base}"))
            doc.set("title/xPos", [0.5])
            doc.set("title/yPos", [0.965])
            doc.set("title/alignHorz", "centre")
            doc.set("title/Text/size", "10pt")
            _add_graph(doc, "g_stability", "Averaging time \\tau (s)", False,
                       "ADEV \\sigma_{y}(\\tau) of reported f", adev_series,
                       log_x=True, log_y=True, with_key=False)
            doc.up()
        return w.finish(doc.text())


# %% ===========================================================================
#    PDF BOOKMARKS AND THE LUALATEX SESSION REPORT
# =============================================================================
# Veusz writes the plot pages as one PDF without an outline; render_pages()
# gives it the bookmark hierarchy built by session_outline().
#
# The LuaLaTeX report is the LaTeX version of that PDF: the instrument
# identity, the timing, signal, thermal and stability statistics with their
# equations, and every plot page, included as vector graphics straight from
# the Veusz PDF. hyperref turns the sections and subsections into the PDF
# bookmark hierarchy and opens the bookmark pane on load. The .tex is written
# whenever the plots are rendered, so it can be compiled (lualatex, twice) or
# edited on a machine with TeX even when this one has none.

#: File stem of the LaTeX report written into the session folder.
REPORT_STEM = "quicksyn_session_report"

#: Bookmark and section titles for the Veusz pages written by export_veusz().
PAGE_TITLES: dict[str, str] = {
    "page_overview": "Overview (all quantities)",
    "page_carrier": "Carrier frequency",
    "page_level": "Output level",
    "page_thermal": "Internal temperature",
    "page_latency": "Serial I/O latency",
    "page_interval": "Sample interval",
    "page_stability": "Allan deviation of the reported carrier",
}


def session_outline(names: Sequence[str], session_name: str) -> list[tuple]:
    """Bookmark hierarchy for the session PDF, from its Veusz page names.

    QuickSyn session <name>
        Overview (all quantities)
        Time series
            Carrier frequency, Output level, ... (one per quantity page)
        Stability
            Allan deviation of the reported carrier

    Entries follow vszh5_writer.OutlineEntry: (title, page index, children).
    Pages this function does not know are listed under Time series by name.
    """
    index = {name: i for i, name in enumerate(names)}
    series = [(PAGE_TITLES.get(name, name), index[name]) for name in names
              if name not in ("page_overview", "page_stability")]
    children: list[tuple] = []
    if "page_overview" in index:
        children.append((PAGE_TITLES["page_overview"], index["page_overview"]))
    if series:
        children.append(("Time series", None, series))
    if "page_stability" in index:
        children.append(("Stability", None,
                         [(PAGE_TITLES["page_stability"], index["page_stability"])]))
    if not children:
        return [(name, i) for i, name in enumerate(names)]
    return [(f"QuickSyn session {session_name}", 0, children)]


def vszh5_page_names(vszh5: Path) -> list[str]:
    """Page names, in order, from the document script stored in a .vszh5."""
    import h5py

    with h5py.File(vszh5, "r") as handle:
        script = handle["Veusz/Document/document"][0]
    script = script.decode("utf-8") if isinstance(script, bytes) else str(script)
    return re.findall(r"Add\('page', name='([^']*)'", script)


#: Characters with a meaning in LaTeX, and how to print them literally.
_TEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def tex_escape(text: Any) -> str:
    """Make any text print literally in LaTeX (LuaLaTeX handles Unicode)."""
    return "".join(_TEX_SPECIAL.get(ch, ch) for ch in str(text))


def find_lualatex(explicit: str = "") -> str:
    """Locate lualatex: explicit path, QUICKSYN_LUALATEX, PATH, usual folders.

    On Windows the TeX Live default folders (C:\\texlive\\<year>\\bin\\windows,
    or bin\\win64 before TeX Live 2023) and MiKTeX are searched when lualatex
    is not on the PATH. Returns "" when none is found.
    """
    if explicit:
        return explicit if os.path.isfile(explicit) else ""
    env = os.environ.get("QUICKSYN_LUALATEX", "").strip().strip('"')
    if env and os.path.isfile(env):
        return env
    found = shutil.which("lualatex")
    if found:
        return found
    if os.name == "nt":
        candidates = sorted(glob.glob(r"C:\texlive\*\bin\windows\lualatex.exe"), reverse=True)
        candidates += sorted(glob.glob(r"C:\texlive\*\bin\win64\lualatex.exe"), reverse=True)
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(os.path.join(local, "Programs", "MiKTeX", "miktex", "bin",
                                           "x64", "lualatex.exe"))
        candidates.append(r"C:\Program Files\MiKTeX\miktex\bin\x64\lualatex.exe")
        return next((c for c in candidates if os.path.isfile(c)), "")
    return ""


def _fmt(value: Any, fmt: str = "{:.6g}") -> str:
    """One table cell: 'not available' for NaN, the format for floats."""
    if isinstance(value, float) and not math.isfinite(value):
        return r"\emph{not available}"
    if isinstance(value, float):
        return tex_escape(fmt.format(value))
    return tex_escape(value)


def _table(caption: str, rows: Sequence[tuple[str, str, str]]) -> list[str]:
    """A three-column booktabs table (quantity, value, unit) as LaTeX lines."""
    out = [r"\begin{center}", r"\begin{tabular}{@{}p{0.52\linewidth}p{0.28\linewidth}l@{}}",
           r"\toprule", r"\textbf{Quantity} & \textbf{Value} & \textbf{Unit} \\", r"\midrule"]
    out += [f"{label} & {value} & {unit} \\\\" for label, value, unit in rows]
    out += [r"\bottomrule", r"\end{tabular}", "", rf"\emph{{{caption}}}", r"\end{center}", ""]
    return out


def write_latex_report(session_dir: Path, records: np.ndarray, stats: SessionStatistics,
                       metadata: dict[str, Any] | None, plots_pdf: Path | None,
                       page_names: Sequence[str], render_note: str = "") -> Path:
    """Write <session_dir>/quicksyn_session_report.tex (LuaLaTeX).

    Parameters
    ----------
    session_dir:
        Session folder; the .tex goes here and refers to files beside it.
    records:
        Telemetry records (for the session start and end times).
    stats:
        Reduction results.
    metadata:
        session_metadata.json contents (identity, capability, transport).
    plots_pdf:
        The multipage Veusz PDF rendered in this run, or None when the
        render did not happen; its pages become the plot subsections.
    page_names:
        Veusz page names in page order (see vszh5_page_names).
    render_note:
        Why the plots are missing, if they are.

    Returns
    -------
    pathlib.Path
        The .tex file.
    """
    meta = metadata or {}
    ident = meta.get("identity", {})
    cap = meta.get("capability", {})
    transport = meta.get("transport", {})
    name = tex_escape(session_dir.name)
    t_unix = records["t_unix"].astype(np.float64) if records.size else np.zeros(0)

    def local_time(epoch: float) -> str:
        stamp = datetime.datetime.fromtimestamp(epoch).astimezone()
        return stamp.strftime("%Y-%m-%d %H:%M:%S %Z (UTC%z)")

    start = local_time(float(t_unix[0])) if t_unix.size else "not available"
    end = local_time(float(t_unix[-1])) if t_unix.size else "not available"
    generator = tex_escape(f"quicksyn_veusz_export_v{__version__.replace('.', '_')}.py {__version__}")
    lines: list[str] = [
        "% !TeX program = lualatex",
        f"% QuickSyn session report for {session_dir.name}",
        f"% Written by quicksyn_veusz_export_v{__version__.replace('.', '_')}.py "
        f"{__version__} ({__license__}). Compile with LuaLaTeX, twice:",
        f"%     lualatex {REPORT_STEM}.tex",
        r"\documentclass[11pt]{article}",
        r"\usepackage[letterpaper,margin=2cm]{geometry}",
        r"\usepackage{fontspec}",
        r"\usepackage{amsmath}",
        r"\usepackage{booktabs}",
        r"\usepackage{array}",
        r"\usepackage{graphicx}",
        r"\usepackage{xcolor}",
        r"\usepackage{fancyhdr}",
        r"\usepackage[bookmarks=true,bookmarksnumbered=true,bookmarksopen=true,"
        r"bookmarksopenlevel=2,hidelinks]{hyperref}",
        r"\usepackage{bookmark}",
        r"\hypersetup{",
        rf"  pdftitle={{QuickSyn session report: {name}}},",
        rf"  pdfauthor={{{tex_escape(PROGRAM_NAME)} {__version__}}},",
        r"  pdfsubject={QuickSyn telemetry session: statistics and plots},",
        r"  pdfkeywords={QuickSyn, SCPI, telemetry, Allan deviation, Veusz},",
        r"  pdfcreator={LuaLaTeX},",
        r"  pdfpagemode=UseOutlines, pdfstartview=FitH}",
        r"\setlength{\parindent}{0pt}",
        r"\setlength{\parskip}{0.5\baselineskip}",
        r"\setlength{\headheight}{14pt}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        rf"\lhead{{\small QuickSyn session {name}}}",
        r"\rhead{\small\thepage}",
        rf"\lfoot{{\scriptsize Generated by {generator}}}",
        r"\title{QuickSyn session report\\[0.3em]\large " + name + "}",
        rf"\author{{{tex_escape(PROGRAM_NAME)} {__version__}}}",
        rf"\date{{Session {tex_escape(start)} to {tex_escape(end)}}}",
        r"\begin{document}",
        r"\maketitle",
        r"\thispagestyle{fancy}",
    ]
    if transport.get("simulated"):
        lines += [r"\begin{center}\fcolorbox{red}{white}{\parbox{0.9\linewidth}{\centering",
                  r"\textbf{SIMULATED SESSION:} no instrument was connected; every value",
                  r"below comes from the controller's built-in simulator.}}\end{center}", ""]
    lines += [r"\pdfbookmark[1]{Contents}{contents}", r"\tableofcontents", r"\clearpage", ""]

    # ---- instrument -----------------------------------------------------------
    lines += [r"\section{Instrument}", "",
              r"\begin{center}", r"\begin{tabular}{@{}p{0.3\linewidth}p{0.62\linewidth}@{}}",
              r"\toprule", r"\textbf{Field} & \textbf{Value} \\", r"\midrule",
              rf"\texttt{{*IDN?}} reply & \texttt{{{tex_escape(ident.get('raw', 'unknown'))}}} \\",
              rf"Model & {tex_escape(ident.get('model', 'unknown'))} \\",
              rf"Option field & \texttt{{{tex_escape(ident.get('options', ''))}}} \\",
              rf"Software version field & \texttt{{{tex_escape(ident.get('firmware', ''))}}} "
              rf"(= {tex_escape(ident.get('firmware_value'))}) \\",
              rf"Serial field & \texttt{{{tex_escape(ident.get('serial', ''))}}} \\",
              rf"Datasheet coverage & {cap.get('f_min_hz', 0) / 1e9:g} to "
              rf"{cap.get('f_max_hz', 0) / 1e9:g} GHz \\",
              rf"Transport & {tex_escape(transport.get('port', '?'))} at "
              rf"{tex_escape(transport.get('baudrate', '?'))} baud"
              + (r" (simulated)" if transport.get("simulated") else "") + r" \\",
              r"\bottomrule", r"\end{tabular}", r"\end{center}", "",
              r"The \texttt{*IDN?} field order is inferred from the native Get ID order in",
              r"\cite{nicomms}; it is not specified for the SCPI form.", ""]

    # ---- timing -------------------------------------------------------------------
    def ms(value: float) -> float:
        return value * 1e3 if math.isfinite(value) else math.nan

    lines += [r"\section{Acquisition timing}", ""]
    lines += _table("Timing of the telemetry stream.", [
        ("Samples", _fmt(stats.n_samples), ""),
        ("Loaded from", _fmt(stats.source), ""),
        ("Duration", _fmt(stats.duration_s), "s"),
        ("Requested sample rate", _fmt(stats.requested_rate_hz), "Hz"),
        ("Achieved sample rate", _fmt(stats.achieved_rate_hz), "Hz"),
        ("Mean sample interval", _fmt(ms(stats.interval_mean_s)), "ms"),
        ("Interval standard deviation (jitter)", _fmt(ms(stats.interval_std_s)), "ms"),
        ("Interval minimum", _fmt(ms(stats.interval_min_s)), "ms"),
        ("Interval maximum", _fmt(ms(stats.interval_max_s)), "ms"),
        ("Jitter relative to the period", _fmt(stats.jitter_ppm_of_period), "ppm"),
        ("Device I/O latency, mean", _fmt(stats.latency_mean_ms), "ms"),
        ("Device I/O latency, 95th percentile", _fmt(stats.latency_p95_ms), "ms"),
        ("Device I/O latency, maximum", _fmt(stats.latency_max_ms), "ms"),
    ])
    lines += [
        r"The sample period is the reciprocal of the requested rate $f_s$,",
        r"\begin{equation}", r"  \tau_0 = \frac{1}{f_s},", r"\end{equation}",
        r"and the achievable rate is bounded by the serial round trips each sample",
        r"costs. With $N_q$ queries per sample and a mean round-trip time $t_q$,",
        r"\begin{equation}", r"  f_{s,\max} = \frac{1}{N_q\,t_q}.", r"\end{equation}",
        r"The jitter is the standard deviation of the measured intervals,",
        r"\begin{equation}",
        r"  \sigma_{\tau_0} = \operatorname{std}\left(t_i - t_{i-1}\right),",
        r"\end{equation}",
        r"taken from the monotonic clock of the logging computer.", ""]

    # ---- signal and thermal -----------------------------------------------------------
    lines += [r"\section{Generated signal}", ""]
    lines += _table("Signal state reported by the instrument.", [
        ("Distinct frequencies observed", _fmt(stats.freq_unique_count), ""),
        ("Frequency minimum", _fmt(stats.freq_min_ghz, "{:.9f}"), "GHz"),
        ("Frequency maximum", _fmt(stats.freq_max_ghz, "{:.9f}"), "GHz"),
        ("Power minimum", _fmt(stats.power_min_dbm, "{:+.1f}"), "dBm"),
        ("Power maximum", _fmt(stats.power_max_dbm, "{:+.1f}"), "dBm"),
        ("RF output on, fraction of samples", _fmt(stats.rf_on_fraction, "{:.3f}"), ""),
        ("Samples with RF unlocked", _fmt(stats.rf_unlocked_samples), ""),
        ("Samples with reference unlocked", _fmt(stats.ref_unlocked_samples), ""),
        ("Samples with voltage error", _fmt(stats.voltage_error_samples), ""),
    ])
    lines += [r"Status bits are decoded from \texttt{STAT?} with the bit map of",
              r"\cite[Table 5]{nicomms}; the lock bits are set when \emph{unlocked}.", ""]
    lines += [r"\section{Thermal}", ""]
    lines += _table("Internal temperature (DIAG:MEAS? 21).", [
        ("Internal temperature minimum", _fmt(stats.temp_min_c, "{:.1f}"), r"\textdegree{}C"),
        ("Internal temperature maximum", _fmt(stats.temp_max_c, "{:.1f}"), r"\textdegree{}C"),
        ("Rise over the session", _fmt(stats.temp_rise_c, "{:+.1f}"), r"\textdegree{}C"),
        ("Margin to the +75 \\textdegree{}C limit", _fmt(stats.temp_margin_to_75c, "{:.1f}"),
         r"\textdegree{}C"),
    ])
    lines += [r"The +75\,\textdegree{}C internal limit is the caution in \cite{niguide}.", ""]

    # ---- stability ------------------------------------------------------------------------
    lines += [
        r"\section{Stability of the reported carrier}", "",
        r"The fractional frequency error of sample $i$ against the median",
        r"commanded carrier $f_c$ is",
        r"\begin{equation}", r"  y_i = \frac{f_i - f_c}{f_c},", r"\end{equation}",
        r"and the overlapping Allan deviation at averaging time $\tau = m\,\tau_0$",
        r"follows IEEE Std 1139-2008 \cite{ieee1139}:",
        r"\begin{equation}",
        r"  \sigma_y^2(\tau) = \frac{1}{2\,(N-2m+1)\,\tau^2}",
        r"  \sum_{k=1}^{N-2m+1}\left(x_{k+2m} - 2x_{k+m} + x_k\right)^2,",
        r"\end{equation}",
        r"with the phase residuals",
        r"\begin{equation}", r"  x_k = \tau_0 \sum_{i<k} y_i .", r"\end{equation}",
        r"This characterises command fidelity and the logging time base, not the",
        r"phase noise of the carrier: \texttt{FREQ?} returns the commanded setting,",
        r"not a measurement of the output. Phase noise is specified separately in",
        r"the datasheet \cite{nidatasheet} and cannot be inferred from this log.", ""]
    if stats.adev_tau_s:
        lines += [r"\begin{center}", r"\begin{tabular}{@{}rr@{}}", r"\toprule",
                  r"\textbf{Averaging time $\tau$ (s)} & \textbf{ADEV $\sigma_y(\tau)$} \\",
                  r"\midrule"]
        lines += [f"{tau:.4g} & {dev:.3e} \\\\" for tau, dev in zip(stats.adev_tau_s, stats.adev)]
        lines += [r"\bottomrule", r"\end{tabular}", r"\end{center}", ""]
    else:
        lines += [r"Too few samples for an Allan deviation estimate.", ""]

    # ---- plots ------------------------------------------------------------------------------
    lines += [r"\clearpage", r"\section{Plots}", ""]
    if plots_pdf is not None and page_names:
        lines += [r"Every page of \texttt{" + tex_escape(plots_pdf.name) + r"}, rendered by",
                  r"Veusz \cite{veusz} from \texttt{quicksyn\_session.vszh5}, included as vector",
                  r"graphics. Commanded values are drawn as black diamonds.", ""]
        for number, page in enumerate(page_names, start=1):
            height = r"0.78\textheight" if page == "page_overview" else r"0.40\textheight"
            lines += [rf"\subsection{{{tex_escape(PAGE_TITLES.get(page, page))}}}",
                      r"\begin{center}",
                      rf"\includegraphics[page={number},width=\linewidth,height={height},"
                      rf"keepaspectratio]{{{plots_pdf.name}}}",
                      r"\end{center}", ""]
            if page == "page_overview":
                lines.append(r"\clearpage")
    else:
        reason = tex_escape(render_note) if render_note else "the render was not run"
        lines += [r"The plots were not rendered (" + reason + r"). Open",
                  r"\texttt{quicksyn\_session.vszh5} in Veusz, or render it again.", ""]

    # ---- files and provenance ------------------------------------------------------------
    lines += [r"\section{Files in the session folder}", "", r"\begin{itemize}"]
    names = sorted(p.name for p in session_dir.iterdir() if p.is_file())
    chunks = [item for item in names if re.fullmatch(r"telemetry_chunk_\d+\.pkl\.gz", item)]
    for item in names:
        if item.startswith(REPORT_STEM) or item in chunks[1:]:
            continue
        if chunks and item == chunks[0] and len(chunks) > 1:
            lines.append(rf"  \item \texttt{{{tex_escape(chunks[0])}}} to "
                         rf"\texttt{{{tex_escape(chunks[-1])}}} ({len(chunks)} files)")
        else:
            lines.append(rf"  \item \texttt{{{tex_escape(item)}}}")
    stem = tex_escape(REPORT_STEM)
    lines += [rf"  \item \texttt{{{stem}.tex}} and \texttt{{{stem}.pdf}} (this report)",
              r"\end{itemize}", "",
              r"\section{Provenance}", "",
              rf"Statistics computed with the {tex_escape(stats.compute_backend)} backend in",
              rf"{stats.compute_seconds * 1e3:.1f}\,ms by {generator}. The same numbers are",
              r"in \texttt{reduction\_summary.json} and \texttt{reduction\_summary.md}.", "",
              r"\phantomsection",
              r"\addcontentsline{toc}{section}{References}",
              r"\begin{thebibliography}{9}",
              r"\bibitem{nicomms} National Instruments, ``QuickSyn Microwave Synthesizers:",
              r"  Communications Specifications,'' Doc. No. 5580510-01, Santa Clara, CA, USA, 2014.",
              r"\bibitem{niguide} National Instruments, ``QuickSyn Microwave Frequency",
              r"  Synthesizer: User Guide,'' Doc. No. 5580513-01, Rev. F.",
              r"\bibitem{nidatasheet} National Instruments, ``QuickSyn Frequency Synthesizers,''",
              r"  product brochure and datasheet, Oct. 2017.",
              r"\bibitem{ieee1139} \emph{IEEE Standard Definitions of Physical Quantities for",
              r"  Fundamental Frequency and Time Metrology---Random Instabilities}, IEEE Std",
              r"  1139-2008, 2008. [Online]. Available: \url{https://ieeexplore.ieee.org/document/4797525}",
              r"\bibitem{veusz} Veusz Developers, ``Veusz---a scientific plotting package.''",
              r"  [Online]. Available: \url{https://veusz.github.io/}",
              r"\end{thebibliography}", "",
              r"\end{document}", ""]
    tex = session_dir / f"{REPORT_STEM}.tex"
    tex.write_text("\n".join(lines), encoding="utf-8")
    return tex


def _latex_error(tex: Path, output: str) -> str:
    """The first error line of a failed LaTeX run (log file, else console)."""
    log = tex.with_suffix(".log")
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else output
    for line in text.splitlines():
        if line.startswith("!") or re.search(r":\d+: ", line):
            return line.strip()[:200]
    return (output.strip().splitlines() or ["no output"])[-1][:200]


def compile_latex(tex: Path, lualatex: str, runs: int = 2,
                  timeout: float = 300.0) -> tuple[Path | None, str]:
    """Compile a .tex with LuaLaTeX in its own folder.

    Two runs resolve the table of contents and the bookmarks. Auxiliary
    files are removed after a successful build; the .log is kept.

    Returns
    -------
    tuple
        (the PDF, or None on failure; on failure the first error line from
        the LaTeX log, otherwise the tail of LuaLaTeX's output).
    """
    command = [lualatex, "-interaction=nonstopmode", "-halt-on-error",
               "-file-line-error", tex.name]
    flags = {"creationflags": 0x08000000} if os.name == "nt" else {}
    output = ""
    for _ in range(runs):
        try:
            proc = subprocess.run(command, cwd=tex.parent, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, **flags)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"{type(exc).__name__}: {exc}"
        output = proc.stdout + proc.stderr
        if proc.returncode != 0:
            return None, _latex_error(tex, output)
    for suffix in (".aux", ".out", ".toc"):
        tex.with_suffix(suffix).unlink(missing_ok=True)
    pdf = tex.with_suffix(".pdf")
    return (pdf if pdf.is_file() else None), output[-1500:]


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Reduce a QuickSyn telemetry session and export plots.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("session_dir", type=Path,
                        help="session directory written by the controller")
    parser.add_argument("--no-gpu", action="store_true",
                        help="force the NumPy host path")
    parser.add_argument("--no-veusz", action="store_true",
                        help="write no .vszh5 and render nothing")
    parser.add_argument("--no-render", action="store_true",
                        help="write the .vszh5 but skip the PDF/PNG render")
    parser.add_argument("--no-compress", action="store_true",
                        help="store .vszh5 datasets uncompressed")
    parser.add_argument("--time-axis", choices=TIME_AXES, default="local",
                        help="x axis of the time panels (default: local)")
    parser.add_argument("--png-pages", choices=("first", "all", "none"), default="first",
                        help="which pages to render as PNG (default: first = overview)")
    parser.add_argument("--veusz-exe", default="",
                        help="Veusz program used to render (default: search)")
    parser.add_argument("--render-method", choices=("auto", "program", "inprocess"),
                        default="auto", help="how to render (default: auto)")
    parser.add_argument("--workers", type=int, default=None,
                        help="process-pool size for chunk loading")
    parser.add_argument("--dpi", type=int, default=150,
                        help="PNG render resolution")
    parser.add_argument("--no-latex", action="store_true",
                        help="do not write or compile the LuaLaTeX report")
    parser.add_argument("--lualatex", default="",
                        help="lualatex program (default: search)")
    parser.add_argument("--version", "-V", action="version",
                        version=version_banner(),
                        help="print version, copyright and licence, then exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Load, reduce, tabulate and plot one session.

    Returns
    -------
    int
        Process exit status.
    """
    args = build_parser().parse_args(argv)
    session_dir: Path = args.session_dir.expanduser().resolve()
    if not session_dir.is_dir():
        print(f"error: {session_dir} is not a directory", file=sys.stderr)
        return 2

    metadata: dict[str, Any] | None = None
    meta_path = session_dir / "session_metadata.json"
    if meta_path.exists():
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    workers = args.workers or available_cpus()
    records, source = load_session_records(session_dir, workers)
    use_gpu = HAVE_CUPY and not args.no_gpu
    stats = reduce_session(records, source, metadata, use_gpu)

    (session_dir / "reduction_summary.json").write_text(
        json.dumps(asdict(stats), indent=2, default=str), encoding="utf-8"
    )
    write_markdown_summary(
        session_dir / "reduction_summary.md", stats, metadata, session_dir
    )
    np.savez_compressed(
        session_dir / "telemetry_reduced.npz",
        records=records,
        adev_tau_s=np.asarray(stats.adev_tau_s or [], dtype=float),
        adev=np.asarray(stats.adev or [], dtype=float),
    )

    # The .vszh5 is written (atomically) before any rendering, so a Veusz
    # failure can never cost the data file.
    vszh5: Path | None = None
    plots: list[Path] = []
    plot_note = ""
    if args.no_veusz:
        plot_note = "skipped (--no-veusz)"
    elif not HAVE_H5PY:
        plot_note = ("SKIPPED - h5py is not installed "
                     "(mamba install -c conda-forge h5py)")
    elif vw is None:
        plot_note = "SKIPPED - vszh5_writer.py is missing from the program folder"
    else:
        vszh5 = export_veusz(session_dir, records, stats, metadata,
                             time_axis=args.time_axis, compress=not args.no_compress)
        if args.no_render:
            plot_note = "render skipped (--no-render)"
        else:
            try:
                plots = vw.render_pages(
                    vszh5, dpi=args.dpi, pdf=True, png_pages=args.png_pages,
                    veusz_exe=args.veusz_exe, method=args.render_method,
                    bookmarks=lambda names: session_outline(names, session_dir.name),
                    pdf_info={"title": f"QuickSyn session {session_dir.name}",
                              "subject": "QuickSyn telemetry session plots, rendered by "
                                         "Veusz from quicksyn_session.vszh5",
                              "keywords": "QuickSyn, SCPI, telemetry, Veusz"})
                if importlib.util.find_spec("pypdf") is None:
                    plot_note = ("PDF has no bookmarks: pypdf is not installed "
                                 "(mamba install -c conda-forge pypdf)")
            except Exception as exc:  # noqa: BLE001 - report, keep the data
                plot_note = (f"render not done ({type(exc).__name__}: {exc}); "
                             f"the .vszh5 is complete - open it in Veusz")

    # LuaLaTeX report: written whenever the plots were meant to be rendered,
    # compiled when lualatex is available. Failure never touches the data.
    report_pdf: Path | None = None
    report_note = ""
    if vszh5 is not None and not args.no_render and not args.no_latex:
        plots_pdf = vszh5.with_suffix(".pdf")
        rendered = plots_pdf if plots_pdf in plots else None
        try:
            tex = write_latex_report(session_dir, records, stats, metadata, rendered,
                                     vszh5_page_names(vszh5), render_note=plot_note)
            exe = find_lualatex(args.lualatex)
            if exe:
                report_pdf, latex_log = compile_latex(tex, exe)
                if report_pdf is None:
                    report_note = (f"{tex.name} written; LuaLaTeX failed ({latex_log}) - "
                                   f"see {tex.with_suffix('.log').name}")
            else:
                report_note = (f"{tex.name} written; lualatex not found - compile it with "
                               f"`lualatex {tex.name}` (twice) or set QUICKSYN_LUALATEX")
        except Exception as exc:  # noqa: BLE001 - report, keep the data
            report_note = f"LaTeX report not written ({type(exc).__name__}: {exc})"

    print(f"session        : {session_dir}")
    print(f"samples        : {stats.n_samples} (from {source}, "
          f"{workers} loader processes)")
    print(f"duration       : {stats.duration_s:.2f} s")
    print(f"rate           : {stats.achieved_rate_hz:.3f} Hz achieved vs "
          f"{stats.requested_rate_hz:.3f} Hz requested")
    print(f"jitter         : {stats.interval_std_s * 1e3:.3f} ms "
          f"({stats.jitter_ppm_of_period:.0f} ppm of period)")
    print(f"backend        : {stats.compute_backend} in "
          f"{stats.compute_seconds * 1e3:.1f} ms")
    print(f"summary        : reduction_summary.md, reduction_summary.json, "
          f"telemetry_reduced.npz")
    if vszh5 is not None:
        print(f"veusz document : {vszh5.name} ({vszh5.stat().st_size / 1024:.1f} KiB)")
    if plots:
        print(f"plots          : {', '.join(p.name for p in plots)}")
    if plot_note:
        print(f"plots          : {plot_note}")
    if report_pdf is not None:
        print(f"report         : {report_pdf.name} (LuaLaTeX, bookmarks), "
              f"{report_pdf.with_suffix('.tex').name}")
    if report_note:
        print(f"report         : {report_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# Reduce the most recent session without leaving the IDE, and check the
# GPU and host reduction paths against each other.
#
# from pathlib import Path
# root = Path.home() / "quicksyn_logs"
# latest = max((p for p in root.iterdir() if p.is_dir()),
#              key=lambda p: p.stat().st_mtime)
# recs, src = load_session_records(latest)
# host = reduce_session(recs, src, use_gpu=False)
# print(host.achieved_rate_hz, host.adev[:3] if host.adev else "no ADEV")
# if HAVE_CUPY:
#     dev = reduce_session(recs, src, use_gpu=True)
#     import numpy as _np
#     print("max |GPU - CPU| ADEV:",
#           _np.abs(_np.asarray(dev.adev) - _np.asarray(host.adev)).max())
