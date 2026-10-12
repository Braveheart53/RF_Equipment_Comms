#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Stable32-compatible ASCII data-file export.

===============================================================================
 Title          : Stable32-Compatible Data File Export
 Filename       : stable32_export.py
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
 Status         : Internal draft - files not yet read back in Stable32
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
Writes phase or frequency time-series data (and deviation results) as
plain ASCII files for Stable32 (Hamilton Technical Services; now
distributed by the IEEE UFFC Society) [1], so results can be cross-checked
in Stable32 or shared with Stable32 users.

Format written (per the Stable32 documentation [1], [2]):
  - Plain ASCII, one record per line, tab-delimited.
        phase data (.PHD):  [timetag]  phase_s
        freq  data (.FRD):  [timetag]  frac_freq
  - Values in exponential notation, 16 significant digits (Stable32 lists
    data with 15-digit precision [2]); time tags 11 significant digits.
  - "Gap = 0": a missing/invalid point is written as exactly 0; the first
    and last points of a file must not be gaps. Checked BEFORE the file is
    opened (0.0.1 wrote the file up to the bad last point, then raised).
  - Optional '#' comment header (File/Date/Type/Title/Columns). Stable32
    accepts comments and non-numeric time tags in data files [2]; check
    your version if strict compliance matters.
  - Extensions: .PHD (phase), .FRD (frequency), .DAT (general).

DATA GAP - TIME TAGS: the time-tag column holds elapsed seconds, as in
0.0.1. Whether Stable32 interprets numeric time tags as MJD (days) when it
derives tau from them could not be confirmed from the available Stable32
documentation. Enter tau in Stable32 yourself, or write the file with
timetags=False (value column only).

The file is written to "<name>.part" and renamed, so an error never leaves
a truncated file.

REFERENCES (IEEE format)
------------------------
[1] W. J. Riley, "Stable32 User Manual," Hamilton Technical Services.
    Stable32 is distributed by the IEEE UFFC Society:
    https://ieee-uffc.org/technical-committees/frequency-control/educational-resources/frequency-control-software
    (0.0.1 cited http://www.stable32.com/Manual154.pdf, not verified.)
[2] W. J. Riley, "Stable32 Tour - Data Listing," Hamilton Technical
    Services. https://wriley.com/Tour004.htm

REVISION HISTORY
----------------
0.0.1  (baseline)  As received (unversioned archive sa_stability_tool.7z).
0.0.2  2026-10-11  Full header, version dunders, Spyder cells; code unchanged.
0.0.3  2026-10-11  FIX: a gap at the first/last point is rejected before the
                   file is opened (0.0.1 left a partial file). Atomic write
                   (.part + rename). File name in the header via
                   os.path.basename (0.0.1 printed the whole Windows path).
                   Vectorised formatting (one pass, no per-line Python).
                   timetags=False writes the value column only. Sigma-tau
                   table: rows with non-finite values are skipped and
                   counted in the header (Stable32 cannot read NaN).
                   Time-tag units documented as a data gap. References
                   updated.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import datetime
import os
from typing import Iterable, List, Optional, Sequence

import numpy as np

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"        # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"


# %% ===========================================================================
#    PHASE AND FREQUENCY DATA FILES
# =============================================================================
def write_stable32_phase_file(path: str, t_s: Sequence[float], x_phase_s: Sequence[float],
                              title: Optional[str] = None, include_header: bool = True,
                              timetags: bool = True) -> None:
    """Write a Stable32-compatible phase-data file (.PHD convention).
    First and last points are never written as a gap [1]."""
    t_s = np.asarray(t_s, dtype=float)
    x = np.asarray(x_phase_s, dtype=float)
    if len(t_s) != len(x):
        raise ValueError("t_s and x_phase_s must be the same length")
    _write_two_column(path, t_s, x, kind="Phase", title=title,
                      include_header=include_header, timetags=timetags)


def write_stable32_freq_file(path: str, t_s: Sequence[float], y_frac_freq: Sequence[float],
                             title: Optional[str] = None, include_header: bool = True,
                             timetags: bool = True) -> None:
    """Write a Stable32-compatible fractional-frequency data file (.FRD)."""
    t_s = np.asarray(t_s, dtype=float)
    y = np.asarray(y_frac_freq, dtype=float)
    if len(t_s) != len(y):
        raise ValueError("t_s and y_frac_freq must be the same length")
    _write_two_column(path, t_s, y, kind="Frequency", title=title,
                      include_header=include_header, timetags=timetags)


# %% ===========================================================================
#    TWO-COLUMN WRITER (GAP = 0 CONVENTION)
# =============================================================================
def _header(path: str, kind: str, title: Optional[str], columns: str) -> List[str]:
    """Comment lines that document the file."""
    lines = [
        "# File: {0}".format(os.path.basename(path)),
        "# Date: {0}".format(datetime.datetime.now().isoformat(timespec="seconds")),
        "# Type: {0}".format(kind),
    ]
    if title:
        lines.append("# Title: {0}".format(title))
    lines.append("# Columns: {0}".format(columns))
    return lines


def _atomic_write(path: str, text_lines: Iterable[str], table: Optional[np.ndarray] = None,
                  fmt: str = "") -> None:
    """Write header lines and an optional numeric table via '<path>.part'."""
    part = path + ".part"
    try:
        with open(part, "w", encoding="ascii", errors="replace", newline="\n") as f:
            for line in text_lines:
                f.write(line + "\n")
            if table is not None and table.size:
                np.savetxt(f, table, fmt=fmt, delimiter="\t")
        os.replace(part, path)
    except BaseException:
        if os.path.exists(part):
            os.remove(part)
        raise


def _write_two_column(path: str, t_s: "np.ndarray", v: "np.ndarray", kind: str,
                      title: Optional[str], include_header: bool, timetags: bool = True) -> None:
    """Gap = 0 two-column writer. Validates everything before writing."""
    n = len(v)
    if n == 0:
        raise ValueError("no data to write")
    finite = np.isfinite(v)
    for i in (0, n - 1):
        if not finite[i]:
            raise ValueError(
                "Stable32 format forbids a gap at the first or last data "
                "point (index {0}); trim or interpolate the series first.".format(i))
    if timetags and not np.all(np.isfinite(t_s)):
        raise ValueError("time tags must be finite (or write with timetags=False)")
    values = np.where(finite, v, 0.0)                    # gap = 0
    lines: List[str] = []
    if include_header:
        col = "phase_s" if kind == "Phase" else "frac_freq"
        lines = _header(path, kind, title, ("timetag_s  " if timetags else "") + col)
        lines.append("# Generated per Stable32 ASCII data-file convention, Ref. [1] "
                     "(gap=0, non-gap first/last point).")
        n_gap = int(np.count_nonzero(~finite))
        if n_gap:
            lines.append("# Gaps written as 0: {0}".format(n_gap))
    if timetags:
        _atomic_write(path, lines, np.column_stack((t_s, values)), fmt="%.10E\t%.15E")
    else:
        _atomic_write(path, lines, values.reshape(-1, 1), fmt="%.15E")


# %% ===========================================================================
#    SIGMA-TAU RESULTS TABLE
# =============================================================================
def write_stable32_sigma_tau_table(path: str, tau_m_dev_rows, columns=("tau_s", "m", "n", "adev"),
                                   title: Optional[str] = None) -> None:
    """Write a multi-column sigma-tau results table in Stable32-readable
    ASCII (at most 8 columns per line [1]) for comparison with a Stable32
    "Run". tau_m_dev_rows: iterable of tuples in ``columns`` order. Rows
    with a non-finite value are skipped (Stable32 cannot read NaN) and
    counted in the header.
    """
    if len(columns) > 8:
        raise ValueError("Stable32 ASCII format supports at most 8 columns per line")
    body: List[str] = []
    skipped = 0
    for row in tau_m_dev_rows:
        vals = list(row)
        if any(isinstance(v, float) and not np.isfinite(v) for v in vals):
            skipped += 1
            continue
        body.append("\t".join(str(int(v)) if isinstance(v, (int, np.integer))
                              else "{0:.10E}".format(float(v)) for v in vals))
    lines = _header(path, "Sigma-Tau results table", title, "  ".join(columns))
    if skipped:
        lines.append("# Rows skipped (non-finite value): {0}".format(skipped))
    _atomic_write(path, lines + body)


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# import numpy as np
# t = np.arange(100.0); x = 1e-9 * np.sin(t / 10.0)
# write_stable32_phase_file("scratch.PHD", t, x, title="scratch")
