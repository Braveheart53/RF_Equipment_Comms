"""
Stable32-Compatible Data File Export
============================================================================
Writes phase or frequency time-series data (and, optionally, deviation
results) to the ASCII data-file format read natively by Stable32
(Hamilton Technical Services), so results computed by this tool can be
cross-checked directly in Stable32 or shared with colleagues who use it.

Format rules implemented (per the Stable32 manual, Ref. [1]):
  - Plain ASCII, one data record per line.
  - Up to 8 space- or comma-delimited columns per line; this exporter
    writes the simplest widely-compatible layout:
        phase data (.PHD):  <timetag_s>  <phase_s>
        freq  data (.FRD):  <timetag_s>  <frac_freq>
  - Values in double-precision exponential notation (e.g. 1.234567890123E+00).
  - "Gap = 0" convention: a missing/invalid point is written as exactly
    "0" (not blank, not NaN) except that the first and last points of a
    phase-data file must never be a gap (Stable32 requirement).
  - Optional header block (lines beginning with a recognized keyword are
    treated as metadata by Stable32 and skipped on import): File:, Date:,
    Type:, and free-text comment lines beginning with '#' (a Stable32-
    tolerated convention for extra documentation -- verify with your
    Stable32 version if strict compliance matters, since the base format
    technically does not require or define comment lines).
  - Recommended file extensions: .DAT (general/mixed), .PHD (phase),
    .FRD (frequency).

References (IEEE format)
-------------------------
[1] "Stable32 Software Manual," Hamilton Technical Services, rev. 1.54.
    [Online]. Available: http://www.stable32.com/Manual154.pdf
[2] W. J. Riley, "Stable32 Frequency Stability Analysis," Hamilton
    Technical Services application note. [Online].
    Available: http://www.wriley.com/Learn%20Frequency%20Stability%20Analysis%20Using%20Stable32.pdf

Python 3.8 / 3.12 compatible.
"""

from __future__ import annotations

import datetime
from typing import Optional, Sequence

import numpy as np


def write_stable32_phase_file(path: str, t_s: Sequence[float], x_phase_s: Sequence[float],
                               title: Optional[str] = None, include_header: bool = True) -> None:
    """Write a Stable32-compatible phase-data file (.PHD convention).
    First and last points are never written as a gap, per Ref. [1]."""
    t_s = np.asarray(t_s, dtype=float)
    x = np.asarray(x_phase_s, dtype=float)
    if len(t_s) != len(x):
        raise ValueError("t_s and x_phase_s must be the same length")
    _write_two_column(path, t_s, x, kind="Phase", title=title, include_header=include_header)


def write_stable32_freq_file(path: str, t_s: Sequence[float], y_frac_freq: Sequence[float],
                              title: Optional[str] = None, include_header: bool = True) -> None:
    """Write a Stable32-compatible fractional-frequency data file (.FRD)."""
    t_s = np.asarray(t_s, dtype=float)
    y = np.asarray(y_frac_freq, dtype=float)
    if len(t_s) != len(y):
        raise ValueError("t_s and y_frac_freq must be the same length")
    _write_two_column(path, t_s, y, kind="Frequency", title=title, include_header=include_header)


def _write_two_column(path: str, t_s: "np.ndarray", v: "np.ndarray", kind: str,
                       title: Optional[str], include_header: bool) -> None:
    n = len(v)
    finite = np.isfinite(v)
    with open(path, "w") as f:
        if include_header:
            f.write("# File: {0}\n".format(path.split("/")[-1]))
            f.write("# Date: {0}\n".format(datetime.datetime.now().isoformat(timespec="seconds")))
            f.write("# Type: {0}\n".format(kind))
            if title:
                f.write("# Title: {0}\n".format(title))
            f.write("# Columns: timetag_s  {0}\n".format(
                "phase_s" if kind == "Phase" else "frac_freq"))
            f.write("# Generated per Stable32 ASCII data-file convention, Ref. [1] "
                    "(gap=0, non-gap first/last point).\n")
        for i in range(n):
            is_gap = (not finite[i]) and 0 < i < n - 1
            val = 0.0 if is_gap else float(v[i])
            if not finite[i] and (i == 0 or i == n - 1):
                raise ValueError(
                    "Stable32 format forbids a gap at the first or last data "
                    "point (index {0}); trim or interpolate the series first.".format(i)
                )
            f.write("{0:.10E}\t{1:.15E}\n".format(float(t_s[i]), val))


def write_stable32_sigma_tau_table(path: str, tau_m_dev_rows, columns=("tau_s", "m", "n", "adev"),
                                    title: Optional[str] = None) -> None:
    """Write a generic multi-column Sigma-Tau results table in
    Stable32-readable ASCII (up to 8 columns/line per Ref. [1]) -- useful
    for exporting this tool's OADEV/MDEV/TDEV/OHDEV sweep results for
    direct tabular comparison against a Stable32 "Run" computation.
    tau_m_dev_rows: iterable of tuples matching `columns` order.
    """
    if len(columns) > 8:
        raise ValueError("Stable32 ASCII format supports at most 8 columns per line")
    with open(path, "w") as f:
        f.write("# File: {0}\n".format(path.split("/")[-1]))
        f.write("# Date: {0}\n".format(datetime.datetime.now().isoformat(timespec="seconds")))
        f.write("# Type: Sigma-Tau results table\n")
        if title:
            f.write("# Title: {0}\n".format(title))
        f.write("# Columns: {0}\n".format("  ".join(columns)))
        for row in tau_m_dev_rows:
            f.write("\t".join("{0:.10E}".format(float(v)) if not isinstance(v, int) else str(v)
                               for v in row) + "\n")
