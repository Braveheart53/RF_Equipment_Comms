"""
Spectrum/Signal Analyzer File Converter
============================================================================
Converts vendor spectrum-analyzer export files (Keysight, Rohde & Schwarz)
into the canonical two-column CSV format consumed by stability_core.py:

    time_s, <phase_s | freq_hz | frac_freq>

and also parses vendor phase-noise-personality traces (Fourier offset
frequency vs L(f) dBc/Hz) into the format consumed by
phase_noise.parse_direct_phase_noise_trace().

IMPORTANT CAVEAT: exact export formats vary significantly by instrument
model, firmware revision, and measurement application (e.g. Keysight
Phase Noise X-Series app vs a generic trace CSV; R&S FSWP vs FSW/FSVA
"Save Trace" as .CSV/.DAT). This module implements parsers for the most
common documented layouts and a robust generic/fallback CSV parser, but
you should verify column meaning against a small sample export from your
specific instrument/firmware before trusting a bulk conversion. Extend
`_VENDOR_PARSERS` with a new function if your file layout doesn't match.

Supported inputs
-----------------
- Generic / fallback CSV: any 2-column CSV of (time, value) or
  (freq_offset, L(f)); auto-detects header row, delimiter (comma/tab/
  semicolon), and whether the first column is monotonically increasing
  time (-> time series) or frequency (-> phase-noise trace).
- Keysight trace CSV export (X-Series / PXA / N5183 phase noise apps,
  and generic "Save Trace Data" CSV from Keysight benchtop analyzers):
  header rows prefixed with '#' or text metadata, then
  "X,Y" or "Frequency,Amplitude"/"Frequency,Phase Noise" columns.
- Rohde & Schwarz trace export (FSW/FSVA/FSWP "Trace Export" .DAT/.CSV):
  ';'-delimited, with a metadata header block terminated by a
  "Values" or blank-line marker, then "x;y" pairs.

References (IEEE format)
-------------------------
[1] Keysight Technologies, "PXA/MXA Signal Analyzer Phase Noise
    Measurement Application User's Guide," Keysight Technologies.
[2] Rohde & Schwarz, "R&S FSWP Phase Noise Analyzer and VCO Tester User
    Manual," Rohde & Schwarz GmbH & Co. KG.
[3] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST
    Special Publication 1065, Jul. 2008.
    Available: https://tf.nist.gov/general/pdf/2220.pdf

Python 3.8 / 3.12 compatible.
"""

from __future__ import annotations

import csv
import io
import re
from typing import List, Optional, Tuple

import numpy as np


def _sniff_delimiter(sample: str) -> str:
    for delim in (",", ";", "\t"):
        if sample.count(delim) >= 2:
            return delim
    return ","


def _read_numeric_rows(path: str) -> Tuple[List[str], List[List[float]]]:
    """Read a text file, skip non-numeric/header/metadata lines, return
    (header_lines_seen, numeric_rows). Tolerant of '#'/';;' comment
    prefixes and mixed metadata blocks common in vendor exports."""
    with open(path, "r", errors="replace") as f:
        raw = f.read()
    lines = raw.splitlines()
    delim = _sniff_delimiter("\n".join(lines[:20]))
    header_lines: List[str] = []
    rows: List[List[float]] = []
    num_re = re.compile(r"^[\s\+\-\.\d,;eE]+$")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", "//", "%")):
            header_lines.append(stripped)
            continue
        parts = [p.strip() for p in re.split(re.escape(delim) + r"|,", stripped) if p.strip() != ""]
        try:
            vals = [float(p.replace(",", ".")) if _looks_like_number(p) else float("nan") for p in parts]
        except ValueError:
            header_lines.append(stripped)
            continue
        if len(vals) >= 2 and all(np.isfinite(v) for v in vals[:2]):
            rows.append(vals)
        else:
            header_lines.append(stripped)
    return header_lines, rows


def _looks_like_number(tok: str) -> bool:
    try:
        float(tok.replace(",", "."))
        return True
    except ValueError:
        return False


def generic_csv_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Fallback parser for any 2-column CSV/TSV/semicolon-delimited file.
    Auto-detects whether column 0 represents monotonically increasing
    time (-> time-series data for stability_core) or a swept Fourier/
    carrier-offset frequency (-> phase-noise trace for phase_noise.py).
    Returns (col0, col1, kind) where kind in {'time_series', 'freq_trace'}.
    """
    _, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric data rows found in {0}; check file format / "
                          "delimiter, or write a custom vendor parser.".format(path))
    arr = np.array(rows, dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    kind = _classify_column0(col0)
    return col0, col1, kind


def _classify_column0(col0: "np.ndarray") -> str:
    """Heuristic time-series vs frequency-trace classifier for column 0.
    SA long-time measurements are uniformly sampled at a fixed tau0
    (roughly constant diff(col0)) and commonly start at t=0. Phase-noise
    / spectrum sweeps are swept log-uniformly in frequency across decades
    (roughly constant diff(log10(col0))) and never start at 0 Hz. Uniform
    spacing is checked FIRST because a t=0 start defeats any span-ratio-
    based test.
    """
    if len(col0) < 3 or not np.all(np.diff(col0) > 0):
        return "time_series"  # cannot confirm monotonic sweep; default to safer path
    diffs = np.diff(col0)
    uniform_cv = np.std(diffs) / max(np.mean(diffs), 1e-30)
    if uniform_cv < 0.05:
        return "time_series"
    if np.any(col0 <= 0):
        return "time_series"  # frequency traces cannot include f<=0
    log_diffs = np.diff(np.log10(col0))
    log_uniform_cv = np.std(log_diffs) / max(np.mean(np.abs(log_diffs)), 1e-30)
    span_ratio = col0.max() / col0.min()
    if log_uniform_cv < 0.3 and span_ratio > 10:
        return "freq_trace"
    return "time_series"


def keysight_trace_csv_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Parse a Keysight X-Series/PXA-style trace export. These exports
    typically place metadata in leading lines beginning with plain text
    (no consistent comment character across firmware versions) followed
    by a header row (e.g. "X,Y" or "Frequency Offset (Hz),Phase Noise
    (dBc/Hz)") and then numeric data. This function locates the first
    contiguous block of >=2-column numeric rows, which is robust across
    firmware variants; verify units in the header row against your
    specific export before trusting results -- see module docstring.
    """
    header_lines, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric trace data found in Keysight export {0}".format(path))
    arr = np.array(rows, dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    header_text = " ".join(header_lines).lower()
    if "phase noise" in header_text or "dbc" in header_text or "offset" in header_text:
        kind = "freq_trace"
    else:
        _, _, kind = generic_csv_to_canonical(path)
    return col0, col1, kind


def rs_trace_export_to_canonical(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Parse a Rohde & Schwarz FSW/FSVA/FSWP "Trace Export" file
    (semicolon-delimited, with an instrument-state metadata header block
    before the numeric "Values" section). Locates the numeric block the
    same way as the Keysight parser; verify the header's stated x/y units
    (e.g. Hz vs dBc/Hz vs dBm) against your firmware version.
    """
    header_lines, rows = _read_numeric_rows(path)
    if not rows:
        raise ValueError("No numeric trace data found in R&S export {0}".format(path))
    arr = np.array(rows, dtype=float)
    col0, col1 = arr[:, 0], arr[:, 1]
    header_text = " ".join(header_lines).lower()
    if "phase noise" in header_text or "dbc" in header_text:
        kind = "freq_trace"
    else:
        _, _, kind = generic_csv_to_canonical(path)
    return col0, col1, kind


_VENDOR_PARSERS = {
    "generic": generic_csv_to_canonical,
    "keysight": keysight_trace_csv_to_canonical,
    "rs": rs_trace_export_to_canonical,
    "rohde_schwarz": rs_trace_export_to_canonical,
}


def convert_to_canonical_csv(input_path: str, output_path: str, vendor: str = "generic",
                              value_column_name: str = "phase_s") -> str:
    """Convert a vendor SA export file to the canonical CSV format used by
    stability_core.load_canonical_csv(): header 'time_s,<value_column_name>'
    for time-series data, or a frequency-trace CSV with header
    'freq_hz,l_f_dbc_hz' for phase-noise traces (consumed via
    phase_noise.parse_direct_phase_noise_trace after np.loadtxt/pandas read).
    vendor: one of 'generic', 'keysight', 'rs'/'rohde_schwarz'.
    Returns the detected kind ('time_series' or 'freq_trace').
    """
    if vendor not in _VENDOR_PARSERS:
        raise ValueError("Unknown vendor '{0}'; choose from {1}".format(
            vendor, list(_VENDOR_PARSERS.keys())))
    col0, col1, kind = _VENDOR_PARSERS[vendor](input_path)
    with open(output_path, "w", newline="") as f:
        w = csv.writer(f)
        if kind == "time_series":
            w.writerow(["time_s", value_column_name])
        else:
            w.writerow(["freq_hz", "l_f_dbc_hz"])
        for a, b in zip(col0, col1):
            w.writerow(["{0:.10E}".format(a), "{0:.10E}".format(b)])
    return kind


def batch_extract_marker_time_series(paths: List[str], vendor: str = "generic",
                                      marker_index: int = 0) -> Tuple["np.ndarray", "np.ndarray"]:
    """Build a long-time-measurement time series from a batch of individual
    SA trace-snapshot files (e.g. repeated marker/peak captures saved as
    separate timestamped files), taking the peak (or the marker_index-th
    largest value) from each snapshot as one sample. `paths` should be
    given in time order; without embedded per-file timestamps this
    assumes uniform capture spacing (caller should verify against the SA's
    sweep/dwell settings and re-map the returned index array to real
    elapsed time if spacing was not uniform).
    """
    values = []
    for p in paths:
        col0, col1, kind = _VENDOR_PARSERS.get(vendor, generic_csv_to_canonical)(p)
        if len(col1) == 0:
            values.append(float("nan"))
            continue
        order = np.argsort(col1)[::-1]
        idx = order[min(marker_index, len(order) - 1)]
        values.append(float(col1[idx]))
    values = np.array(values, dtype=float)
    idx_time = np.arange(len(values), dtype=float)
    return idx_time, values
