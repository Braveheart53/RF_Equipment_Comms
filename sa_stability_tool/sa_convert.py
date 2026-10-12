#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Spectrum/signal analyzer export converter to the canonical CSV.

===============================================================================
 Title          : Spectrum/Signal Analyzer File Converter
 Filename       : sa_convert.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3 (GUI: Time_Stability_App.py)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13 (3.8 syntax kept on purpose)
 Requires       : numpy
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Internal draft - validated on synthetic files only
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
Converts vendor spectrum-analyzer export files (Keysight, Rohde & Schwarz)
into the canonical two-column CSV format consumed by stability_core.py:

    time_s, <phase_s | freq_hz | frac_freq>

and parses vendor phase-noise traces (Fourier offset frequency vs L(f)
dBc/Hz) into the format consumed by
phase_noise.parse_direct_phase_noise_trace():

    freq_hz, l_f_dbc_hz

IMPORTANT CAVEAT: export formats vary by instrument model, firmware
revision and measurement application (e.g. Keysight Phase Noise X-Series
app vs a generic trace CSV; R&S FSWP vs FSW/FSVA "Save Trace" .CSV/.DAT).
This module implements parsers for the common layouts and a tolerant
generic parser; confirm column meaning and units against a small export
from YOUR instrument and firmware before trusting a bulk conversion. Add
a function to `_VENDOR_PARSERS` for another layout.

Supported inputs
----------------
- Generic: any two-column file of (time, value) or (freq_offset, L(f)),
  with a header or metadata lines, delimited by comma, semicolon, tab or
  white space. The delimiter is chosen per file from the data lines.
- Decimal commas (European locale, typical of R&S exports set to German):
  with a semicolon, tab or white-space delimiter, "1,234" reads as 1.234.
  (With a comma delimiter a decimal comma cannot be told apart and is not
  supported.)
- Keysight trace CSV export (X-Series / PXA / phase-noise application and
  generic "Save Trace Data"): metadata lines, then "X,Y" or
  "Frequency,Amplitude"/"Frequency Offset,Phase Noise" columns.
- Rohde & Schwarz trace export (FSW/FSVA/FSWP .DAT/.CSV): ';'-delimited
  metadata block, then "x;y" pairs (trailing ';' allowed).

Column 0 is classified as a time series (uniform spacing) or a frequency
trace (log-uniform spacing over more than a decade, no f <= 0).

Precision (0.0.3): the canonical CSV is written with the shortest decimal
form that reads back to the same double (Python repr), so no digit of the
input is lost; 0.0.1 kept 11 significant digits, which on a 10 GHz
frequency series is a 1 Hz quantum (3.7 mHz error measured on 1.2 mHz
steps).

PARALLEL
--------
batch_extract_marker_time_series() parses the snapshot files in a process
pool (spawn start method, safe next to Qt threads) when there are at least
8 files; if a pool cannot be used it falls back to threads. While the pool
starts, the parent's __main__ is hidden from multiprocessing, so a
cell-style script or a Spyder console is not re-executed in the workers.

REFERENCES (IEEE format)
------------------------
[1] Keysight Technologies, "N9068C Phase Noise Measurement Application,
    Measurement Guide" (X-Series signal analyzers); document number not
    verified - use the guide matching your analyzer and firmware.
    https://www.keysight.com/
[2] Rohde & Schwarz, "R&S FSWP Phase Noise Analyzer and VCO Tester, User
    Manual"; document number not verified - use the manual matching your
    firmware. https://www.rohde-schwarz.com/
[3] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf

REVISION HISTORY
----------------
0.0.1  (baseline)  As received (unversioned archive sa_stability_tool.7z).
0.0.2  2026-10-11  Full header, version dunders, Spyder cells; code unchanged.
0.0.3  2026-10-11  FIX: decimal-comma files (';', tab, space delimited) were
                   split at the comma and read as "no numeric data". FIX:
                   delimiter chosen from the data lines (a ';' file with
                   decimal commas was taken as comma-delimited). FIX: output
                   keeps full double precision (was 11 significant digits).
                   White-space-delimited files accepted. value_column_name
                   checked (only names the loader reads). Batch extraction
                   parallel (process pool, thread fallback). Unused imports
                   and the unused num_re removed. Spawned workers never
                   re-run the caller's __main__ (hidden while the pool
                   starts; a lock serialises concurrent starts).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import contextlib
import csv
import importlib
import multiprocessing
import os
import re
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

# Spyder's runcell defines __file__ only while a cell runs: capture it once
# (the batch process pool imports this module by name in its workers).
_HERE = Path(globals().get("__file__") or "sa_convert.py").resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"        # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"

#: Value columns stability_core.load_canonical_series() reads.
CANONICAL_VALUE_COLUMNS = ("phase_s", "freq_hz", "frac_freq")
#: Batches at least this large are parsed in parallel.
BATCH_PARALLEL_MIN = 8


# %% ===========================================================================
#    TEXT PARSING HELPERS
# =============================================================================
_COMMENT_PREFIXES = ("#", "//", "%", "!")
_HAS_DIGIT = re.compile(r"\d")


def _sniff_delimiter(lines: Sequence[str]) -> str:
    """Delimiter of the data: ';', tab, ',' or ' ' (white space).

    Decided from up to 50 lines that contain digits and are not comments.
    ';' and tab win over ',' because a file using them may also contain
    decimal commas; ',' wins over white space.
    """
    data = [ln for ln in lines if ln.strip() and _HAS_DIGIT.search(ln)
            and not ln.lstrip().startswith(_COMMENT_PREFIXES)][:50]
    if not data:
        return ","
    for delim in (";", "\t", ","):
        if sum(delim in ln for ln in data) >= max(1, len(data) // 2):
            return delim
    return " "


def _to_float(token: str, decimal_comma: bool) -> float:
    """Parse one token; NaN if it is not a number."""
    tok = token.strip()
    if decimal_comma and "," in tok and "." not in tok:
        tok = tok.replace(",", ".")
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def _looks_like_number(tok: str) -> bool:
    """True if ``tok`` parses as a number (decimal point or comma)."""
    return np.isfinite(_to_float(tok, decimal_comma=True)) or tok.strip().lower() in ("nan", "inf", "-inf")


def _read_numeric_rows(path: str) -> Tuple[List[str], List[List[float]]]:
    """Read a text file, skip non-numeric/header/metadata lines, return
    (header_lines_seen, numeric_rows). A row is kept when its first two
    fields are finite numbers. Comment prefixes # // % ! are header."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = f.read().splitlines()
    delim = _sniff_delimiter(lines)
    decimal_comma = delim != ","
    header_lines: List[str] = []
    rows: List[List[float]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_COMMENT_PREFIXES):
            header_lines.append(stripped)
            continue
        parts = stripped.split() if delim == " " else stripped.split(delim)
        parts = [p for p in parts if p.strip() != ""]
        vals = [_to_float(p, decimal_comma) for p in parts]
        if len(vals) >= 2 and np.isfinite(vals[0]) and np.isfinite(vals[1]):
            rows.append(vals)
        else:
            header_lines.append(stripped)
    return header_lines, rows


# %% ===========================================================================
#    GENERIC PARSER AND TIME-SERIES / TRACE CLASSIFIER
# =============================================================================
def generic_csv_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Fallback parser for any two-column comma/semicolon/tab/space file.
    Detects whether column 0 is monotonically increasing time (-> time
    series for stability_core) or a swept Fourier/carrier-offset frequency
    (-> phase-noise trace for phase_noise.py).
    Returns (col0, col1, kind) with kind in {'time_series', 'freq_trace'}.
    """
    _, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric data rows found in {0}; check file format / "
                         "delimiter, or write a custom vendor parser.".format(path))
    arr = np.array([r[:2] for r in rows], dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    return col0, col1, _classify_column0(col0)


def _classify_column0(col0: "np.ndarray") -> str:
    """Heuristic time-series vs frequency-trace classifier for column 0.
    Long-time measurements are sampled at a fixed tau0 (roughly constant
    diff(col0)) and often start at t = 0. Phase-noise sweeps are log-uniform
    in frequency across decades (roughly constant diff(log10(col0))) and
    never start at 0 Hz. Uniform spacing is tested FIRST because a t = 0
    start defeats any span-ratio test.
    """
    if len(col0) < 3 or not np.all(np.diff(col0) > 0):
        return "time_series"  # cannot confirm a monotonic sweep; default to the safer path
    diffs = np.diff(col0)
    uniform_cv = np.std(diffs) / max(np.mean(diffs), 1e-30)
    if uniform_cv < 0.05:
        return "time_series"
    if np.any(col0 <= 0):
        return "time_series"  # frequency traces cannot include f <= 0
    log_diffs = np.diff(np.log10(col0))
    log_uniform_cv = np.std(log_diffs) / max(np.mean(np.abs(log_diffs)), 1e-30)
    span_ratio = col0.max() / col0.min()
    if log_uniform_cv < 0.3 and span_ratio > 10:
        return "freq_trace"
    return "time_series"


# %% ===========================================================================
#    VENDOR PARSERS
# =============================================================================
def keysight_trace_csv_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Parse a Keysight X-Series/PXA-style trace export: metadata lines
    (no consistent comment character across firmware), a header row (e.g.
    "X,Y" or "Frequency Offset (Hz),Phase Noise (dBc/Hz)"), numeric data.
    Header words "phase noise", "dbc" or "offset" mark a phase-noise trace;
    otherwise column 0 is classified. Verify units against your export.
    """
    header_lines, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric trace data found in Keysight export {0}".format(path))
    arr = np.array([r[:2] for r in rows], dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    header_text = " ".join(header_lines).lower()
    if "phase noise" in header_text or "dbc" in header_text or "offset" in header_text:
        kind = "freq_trace"
    else:
        kind = _classify_column0(col0)
    return col0, col1, kind


def rs_trace_export_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Parse a Rohde & Schwarz FSW/FSVA/FSWP "Trace Export" file
    (semicolon-delimited instrument-state block, then the numeric "Values"
    block; decimal commas accepted). Verify the stated x/y units (Hz vs
    dBc/Hz vs dBm) against your firmware version.
    """
    header_lines, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric trace data found in R&S export {0}".format(path))
    arr = np.array([r[:2] for r in rows], dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    header_text = " ".join(header_lines).lower()
    if "phase noise" in header_text or "dbc" in header_text:
        kind = "freq_trace"
    else:
        kind = _classify_column0(col0)
    return col0, col1, kind


_VENDOR_PARSERS = {
    "generic": generic_csv_to_canonical,
    "keysight": keysight_trace_csv_to_canonical,
    "rs": rs_trace_export_to_canonical,
    "rohde_schwarz": rs_trace_export_to_canonical,
}


# %% ===========================================================================
#    CONVERSION TO THE CANONICAL CSV
# =============================================================================
def _exact(v: float) -> str:
    """Shortest decimal text that reads back to the same double."""
    return repr(float(v))


def convert_to_canonical_csv(input_path: str, output_path: str, vendor: str = "generic",
                             value_column_name: str = "phase_s") -> str:
    """Convert a vendor SA export to the canonical CSV.

    Time series: header 'time_s,<value_column_name>' where the value column
    is phase_s (s), freq_hz (Hz) or frac_freq, chosen by the caller - the
    file itself does not say which one an analyzer logged. Frequency traces:
    header 'freq_hz,l_f_dbc_hz'. Values are written at full double
    precision. vendor: 'generic', 'keysight', 'rs'/'rohde_schwarz'.
    Returns the detected kind ('time_series' or 'freq_trace').
    """
    if vendor not in _VENDOR_PARSERS:
        raise ValueError("Unknown vendor '{0}'; choose from {1}".format(
            vendor, list(_VENDOR_PARSERS.keys())))
    if value_column_name not in CANONICAL_VALUE_COLUMNS:
        raise ValueError("value_column_name must be one of {0}".format(CANONICAL_VALUE_COLUMNS))
    col0, col1, kind = _VENDOR_PARSERS[vendor](input_path)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if kind == "time_series":
            w.writerow(["time_s", value_column_name])
        else:
            w.writerow(["freq_hz", "l_f_dbc_hz"])
        w.writerows([_exact(a), _exact(b)] for a, b in zip(col0, col1))
    return kind


# %% ===========================================================================
#    BATCH MARKER / PEAK TIME SERIES
# =============================================================================
def _peak_from_file(job: Tuple[str, str, int]) -> float:
    """Worker: the marker_index-th largest value of one snapshot file."""
    path, vendor, marker_index = job
    _col0, col1, _kind = _VENDOR_PARSERS.get(vendor, generic_csv_to_canonical)(path)
    if len(col1) == 0:
        return float("nan")
    order = np.argsort(col1)[::-1]
    return float(col1[order[min(marker_index, len(order) - 1)]])


_SPAWN_LOCK = threading.RLock()


@contextlib.contextmanager
def _main_hidden_from_spawn() -> Iterator[None]:
    """Stop spawned workers from re-running the parent's __main__ script.

    multiprocessing's spawn start method re-executes the parent's main
    script (or module) in every worker so that functions defined there can
    be unpickled. Our worker functions live in this module, imported by
    name, so that is not needed - and it is harmful: a cell-style script
    without an ``if __name__ == "__main__"`` guard (validation scripts, a
    Spyder console whose namespace holds __file__ during runcell) would run
    again in each worker, and the GUI script would import Qt in each. While
    the pool starts, __main__.__spec__ is None and __main__.__file__ is
    hidden; both are restored afterwards. A lock makes two pool starts on
    different threads (GUI) take turns, so neither restores the other's
    saved values.
    """
    with _SPAWN_LOCK:
        main = sys.modules.get("__main__")
        saved: Dict[str, Any] = {}
        if main is not None:
            try:
                for name in ("__file__", "__spec__"):
                    if name in vars(main):
                        saved[name] = vars(main)[name]
                main.__spec__ = None
                if "__file__" in vars(main):
                    del main.__file__
            except (AttributeError, TypeError):  # pragma: no cover - exotic __main__
                pass
        try:
            yield
        finally:
            if main is not None:
                for name, value in saved.items():
                    setattr(main, name, value)
                if "__spec__" not in saved and "__spec__" in vars(main):
                    try:
                        del main.__spec__
                    except AttributeError:  # pragma: no cover
                        pass


def _importable_worker():
    """_peak_from_file from the module imported BY NAME, so it pickles as
    'sa_convert._peak_from_file' even when this file runs as __main__ (a
    spawned worker can import that, not the parent's console namespace)."""
    return getattr(importlib.import_module("sa_convert"), "_peak_from_file")


def batch_extract_marker_time_series(paths: List[str], vendor: str = "generic",
                                     marker_index: int = 0,
                                     workers: Optional[int] = None
                                     ) -> Tuple["np.ndarray", "np.ndarray"]:
    """Build a long-time-measurement series from individual SA trace
    snapshots (e.g. repeated marker/peak captures saved as separate files),
    taking the peak (or the marker_index-th largest value) of each file as
    one sample. ``paths`` must be in time order; without per-file time
    stamps uniform capture spacing is assumed - re-map the returned index
    array to elapsed time if the spacing was not uniform.

    Files are parsed in parallel (process pool, threads as fallback) when
    there are at least BATCH_PARALLEL_MIN of them.
    """
    jobs = [(str(p), vendor, int(marker_index)) for p in paths]
    n_work = workers or (len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity")
                         else (os.cpu_count() or 1))
    values: List[float]
    if len(jobs) < BATCH_PARALLEL_MIN or n_work <= 1:
        values = [_peak_from_file(j) for j in jobs]
    else:
        try:
            ctx = multiprocessing.get_context("spawn")
            with _main_hidden_from_spawn(), \
                    ProcessPoolExecutor(max_workers=n_work, mp_context=ctx) as pool:
                values = list(pool.map(_importable_worker(), jobs,
                                       chunksize=max(1, len(jobs) // (4 * n_work))))
        except Exception:  # noqa: BLE001 - no usable process pool: threads
            with ThreadPoolExecutor(max_workers=n_work) as pool:
                values = list(pool.map(_peak_from_file, jobs))
    arr = np.array(values, dtype=float)
    return np.arange(len(arr), dtype=float), arr


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# kind = convert_to_canonical_csv("my_export.csv", "canonical.csv", vendor="generic",
#                                 value_column_name="freq_hz")
# print(kind)
# t_idx, peaks = batch_extract_marker_time_series(["snap_000.csv", "snap_001.csv"])
