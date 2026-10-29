#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Signal Hound Spike .shr sweep files to CSV and Veusz .vszh5 (engine, no Qt).

===============================================================================
 Title          : SHR Converter - conversion engine
 Filename       : shr_converter_core.py
 Version        : 0.0.2 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12 (3.10 or later)
 Requires       : numpy, h5py, shr_reader.py >= 0.0.1 and vszh5_writer.py
                  >= 0.0.21 (both by the same author, shipped beside it)
 Optional       : cupy (GPU statistics and spectrogram reduction), psutil
                  (memory read-out), Veusz + pypdf (PDF/PNG with bookmarks),
                  py-shr-parser 1.0.0 (only as an independent cross-check in
                  the tests; it cannot open recordings made with Spike's Max
                  or Min detector [R10])
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Companion      : shr_converter_gui.py 0.0.2 (Qt.py / PySide6 GUI)
 Status         : Internal draft - checked on an SM200C recording from Spike
                  4.0.x (detector code 2, which py-shr-parser rejects), on
                  Spike's sweep0v2.shr (bit-exact against py-shr-parser) and
                  on synthetic files (tests/, --selftest).
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

DESCRIPTION
-----------
Spike (Signal Hound's analyzer software) records sweeps to .shr files: one
file header, then for every sweep a 48-byte sweep header (time stamp, GPS
latitude/longitude/altitude, ADC-overflow flag) and sweep_length float32
amplitudes [R1], [R2]. This module reads them with shr_reader (the author's
NumPy reader, built from Signal Hound's SDK definition) and writes

  * CSV  - the amplitudes in one of three layouts (below), plus three small
           companion tables: _header.csv (every file-header field with its
           unit), _sweeps.csv (one row per sweep: time, GPS, overflow, peak,
           peak frequency, power-mean level) and _statistics.csv (one row
           per frequency bin: max hold, min hold, power mean, dB mean,
           standard deviation, sample count);
  * .vszh5 - a native Veusz document written with vszh5_writer [R3]:
           spectrogram, statistics spectrum, selected sweeps, level versus
           time, GPS track (when present) and a header page;
  * PDF/PNG - optional, rendered by Veusz, with a PDF bookmark tree.

Everything is streamed in blocks of sweeps, so memory use is set by the RAM
budget, not by the file size, and the blocks are processed in parallel
worker processes (each maps the file itself; see shr_reader).

FILE FORMAT (Signal Hound SDK shr_parse.h [R1]; details in shr_reader.py)
-----------
    file header  472 bytes, little-endian, signature 0xAA10, version <= 2
    sweep k      at dataOffset + k * (48 + 4 * sweepLength):
                 uint64 time stamp (ms since 1970-01-01 UTC, system clock of
                 the recording PC [R2]), float64 latitude, longitude,
                 altitude (m), uint8 ADC overflow, 15 reserved bytes, then
                 sweepLength x float32 amplitudes (dBm, or mV when the
                 reference scale is mV)
Enumerated fields are kept as numbers and labelled with their confidence:
Spike 3.5.7 added Max and Min sweep detectors [R9] whose codes the SDK does
not list (an SM200C recording carries code 2, read as "Max (inferred)").

FREQUENCY AXIS
--------------
Bin i lies at  f_i = first_bin_freq_hz + i * bin_size_hz,  the definition in
the file header [R1]. (py-shr-parser's plotting helpers instead spread the
bins with linspace(center - span/2, center + span/2, n); on sweep0v2.shr the
two differ by up to one bin, and on the SM200C sample the first bin lies 1.9
bins above center - span/2. This module always uses the header's spacing.)

ROBUST OPENING
--------------
A recording cut short by a crash or a full disk, or one whose header still
says 0 sweeps, is read up to the last COMPLETE sweep; a partial final sweep
is skipped and the notes say so (shr_reader.ShrFile). Unknown header values
never stop a conversion: they are reported in the notes and the header page.

MULTI-FILE RECORDINGS (join_files)
---------------------
Since Spike 3.9.7 a long recording continues in a new, sequentially numbered
file when the maximum file size is reached [R9], [R11]. With join_files the
selected files are grouped by content (shr_reader.group_recordings: same bin
axis and unit, each file starting within max(10 s, 50 sweep intervals) of
the end of the previous one) and every group is converted as ONE recording:
continuous sweep numbers, one CSV/.vszh5 named <first file>_joined. Files
that do not group are converted on their own.

CSV TIME DECIMATION (csv_decimate)
-------------------
csv_decimate = N > 1 combines every N selected sweeps into one CSV row (one
column in the frequencies_as_rows layout): peak hold (default), power mean
or minimum hold per bin. The row carries the sweep index and time stamp of
the FIRST sweep of its group, the first GPS fix, ADC overflow if any sweep
overflowed, and a "sweeps_combined" column. Only the main CSV is decimated:
the statistics, the spectrogram, _sweeps.csv and the .vszh5 always use every
selected sweep. A 3-hour SM200C recording at 30 sweeps/s x 8384 bins (about
10.9 GB) is about 32 GB of lossless CSV; csv_decimate = 30 makes that ~1 GB.

STATISTICS  (x = amplitude per bin and sweep)
----------
For dBm data the power mean is taken in linear power, never as a mean of
dB values [R4]:
    P_mean(f) = 10 log10( (1/N) sum_k 10^(x_k(f)/10) )            [dBm]
the dB mean is the plain mean of the dB values (Spike's "log" averaging),
    L_mean(f) = (1/N) sum_k x_k(f)                                  [dBm]
and std is the sample standard deviation of x (in dB). For mV data the
power mean is the RMS value  sqrt( (1/N) sum_k x_k(f)^2 )  [mV]. Max and
min hold are per bin over the selected sweeps. Per sweep, the "power mean
level" is the same power mean taken over the selected bins (a mean power
per bin, NOT a channel power: that would also need the RBW filter's noise
bandwidth). Sums are accumulated in float64. With a Max detector each stored
value is already a max hold of many FFTs [R11], so these statistics describe
the recorded (max-detected) values, not the underlying noise power.

CSV LAYOUTS
-----------
sweeps_as_rows     one row per sweep: sweep_index, time columns, latitude,
                   longitude, altitude, adc_overflow, then one column per
                   frequency (the header row holds the frequencies in Hz).
frequencies_as_rows one row per frequency bin: frequency_hz, then one column
                   per sweep (sweep_<index>). Transposing needs every sweep
                   of a column block at once, so the file is read once per
                   column block (the log says how many passes).
long               one row per sample: sweep_index, time columns,
                   frequency_hz, amplitude - for databases and pandas.
Numbers: "lossless" writes %.9g, which round-trips every float32 exactly
(9 significant digits suffice for IEEE 754 binary32 [R5]); "fixed" writes a
chosen number of decimals (smaller files; note that SM min/max recordings
lie on a 0.01 dB grid shifted by a constant, e.g. +0.00824 dB, so 2 decimals
moves every value by up to 0.005 dB). Time columns: epoch_ms, utc_iso,
local_iso, elapsed_s. Excel opens at most 16,384 columns and 1,048,576
rows [R6]; the plan reports when a layout exceeds either.

VEUSZ DOCUMENT
--------------
The spectrogram is reduced to at most image_max_rows x image_max_columns
pixels: peak hold (default; a short burst or a narrow carrier survives),
minimum hold, or power mean per block of sweeps x bins, accumulated
exactly across worker blocks. Its time axis is UTC or local date/time,
elapsed seconds or sweep index ("auto": date/time for captures of a minute
or longer, else elapsed seconds). Statistics traces longer than
stats_max_points are reduced the same way (max for max hold, min for min
hold, power mean for the means). Text datasets "shr_header_key" and
"shr_header_value" keep the file header inside the document.

LONG CAPTURES (hours)
---------------------
A 3-hour recording can hold millions of sweeps and tens of GB:
* csv_split_minutes > 0 writes <stem>_part001.csv, _part002.csv, ... - one
  file per N minutes of recording (sweeps_as_rows and long layouts), each
  with the header line; a pause longer than a slice starts the next file.
  _header.csv lists every part with its time span and sweep count.
* csv_decimate (above) shrinks the main CSV by N.
* Before writing, the CSV size is estimated (shown by Inspect and the plan)
  and the conversion refuses to start when the drive cannot hold it
  (check_disk_space).
* The per-sweep table (57 bytes per sweep) is memory-mapped from a private
  temporary folder when it exceeds a quarter of the RAM budget
  (sweep_table_storage = auto | memory | disk).
* The .vszh5 level-versus-time and GPS series are thinned to
  time_series_max_points (default 100 000) with reduce_series(): peak hold
  for the peak level, power mean for the band level, the frequency of the
  strongest sweep, overflow if any sweep overflowed - a single short burst
  is never averaged away. The spectrogram rows go onto an even time grid
  (vszh5_writer.regularize_rows): recording pauses (and the gaps of Spike
  4.0.17's limit-line-triggered recordings [R9]) show as blank bands and
  Veusz draws the image on its fast path.
* The plan reports the seconds of recording per spectrogram row (2000 rows
  over 3 h = 5.4 s per row); raise image_max_rows for finer time.
Measured (tests/long_capture_check.py, 2 CPU cores, 2 workers): see
docs/validation/long_capture_and_memory_<version>.txt.

PERFORMANCE AND MEMORY
----------------------
* Worker processes (spawn context on every platform, so a Qt GUI is never
  forked) each read and format their own blocks; the main process writes
  them in order with at most 2 x workers blocks in flight, and adds up the
  partial statistics. A block is ONE vectorised read from the memory-mapped
  file (shr_reader), not one read per sweep. The _sweeps.csv of a long
  capture is formatted in parallel chunks as well.
* Block size follows ram_budget_mb (BYTES_PER_SAMPLE per sample in flight);
  the statistics work in sub-blocks of STATS_CHUNK_SAMPLES, so their
  float64 temporaries never grow with the block. Nothing is held for the
  whole file except the per-sweep table and the reduced image.
* GPU: with compute="gpu" (or "auto" and CuPy with a CUDA device), the
  statistics and the spectrogram reduction of each sub-block run in CuPy;
  the CSV text is always formatted on the CPU (text formatting has no GPU
  path). Any GPU error (out of memory, driver) repeats that block on the
  CPU, and without CuPy everything runs on NumPy - the result is the same.
* flush_memory() runs the garbage collector, frees CuPy pools and returns
  freed heap to the OS (malloc_trim on Linux, EmptyWorkingSet on Windows);
  save_pickle()/load_pickle() offload results (e.g. GUI previews) to disk.

REFERENCES
----------
[R1] Signal Hound, "SHR parsing example" (shr_parse.h, shr_parse.cpp), in the
     Signal Hound Software Development Kit, release of 2026-10-05.
     https://signalhound.com/software/signal-hound-software-development-kit-sdk/
[R2] Signal Hound, ".shr file format specification," BB Series Discussions
     forum, May-Aug. 2018. https://signalhound.com/?p=158701
[R3] W. W. Wallace, "vszh5_writer.py - Veusz HDF5 document writer,"
     v0.0.21, NRAO/GBO, 2026 (shipped with this program).
[R4] Hewlett-Packard, "Measuring Noise and Noise-like Digital Communications
     Signals with a Spectrum Analyzer," Application Note 1303, lit. no.
     5966-4008E ("log processing causes an under-response to noise of
     2.51 dB"). https://www.hpmemoryproject.org/an/pdf/an_1303.pdf
     Background: Keysight Technologies, "Spectrum Analysis Basics,"
     Application Note 150, 5952-0292.
     https://www.keysight.com/us/en/assets/7018-06714/application-notes/5952-0292.pdf
[R5] IEEE, "IEEE Standard for Floating-Point Arithmetic," IEEE Std 754-2019,
     pp. 1-84, Jul. 2019, doi: 10.1109/IEEESTD.2019.8766229 (Sec. 5.12.2:
     conversions that round-trip need ceil(p log10 2) + 1 = 9 significant
     digits for binary32, p = 24; see also R. Regan, "Number of digits
     required for round-trip conversions," Exploring Binary).
     https://doi.org/10.1109/IEEESTD.2019.8766229
[R6] Microsoft, "Excel specifications and limits."
     https://support.microsoft.com/en-us/office/1672b34d-7043-467e-8e27-269d656771c3
[R7] Python Software Foundation, "concurrent.futures - ProcessPoolExecutor"
     (spawn context, max_tasks_per_child, Python 3.11+).
     https://docs.python.org/3.12/library/concurrent.futures.html
[R8] Preferred Networks, "CuPy documentation." https://docs.cupy.dev/
[R9] Signal Hound, "Technical Software and Hardware Change Log" (Spike),
     version 4.0.17, 2026-09-21: max/min detectors 3.5.7, multi-file sweep
     recording 3.9.7, limit-line triggering of sweep recording 4.0.17.
     https://signalhound.com/sigdownloads/Spike/change_log.txt
[R10] T. Schmitz, "py-shr-parser: Python library for parsing Signal Hound
     SHR files," v1.0.0, WiSE Lab, Carnegie Mellon University, 2025.
     https://github.com/WiseLabCMU/py-shr-parser
[R11] Signal Hound, "SM200A/B/C - SM435B/C Product Manual," 2025-01-27
     (min/max processing at 0.01 dB resolution); "Spike Software
     Documentation" (Sweep Record and Playback).
     https://signalhound.com/sigdownloads/SM200A/SM-User-Manual.pdf
     https://signalhound.com/sigdownloads/Spike/docs/html/index.html

REVISION HISTORY (newest first)
----------------
0.0.2  2026-10-28  Reads with shr_reader 0.0.1 instead of py-shr-parser,
                   which cannot open SM200C recordings made with Spike's
                   Max/Min detectors (detector code 2): every header value
                   is kept and labelled, unknown ones become notes. Blocks
                   are one memory-mapped read each. New: multi-file
                   recordings joined as one (join_files), CSV time
                   decimation (csv_decimate, max | power_mean | min),
                   detector shown on the statistics and header pages, a
                   note when amplitudes lie on the 0.01 dB grid of the SM
                   min/max path, time stamps going backwards noted. The
                   _header.csv lists every file of a joined recording.
                   Needs vszh5_writer 0.0.21 (regularize_rows no longer
                   leaves false blank spectrogram rows with jittered time
                   stamps, as real Spike recordings have). Frequency axes
                   switch to a larger unit before Veusz would print
                   scientific tick labels (13.9 GHz in MHz); long Spike
                   file names are shortened in page titles.
                   Self-test extended (detector 2, joined files, CSV
                   decimation in every layout and worker count).
0.0.1  2026-10-28  First internal draft, with GUI 0.0.1 and vszh5_writer
                   0.0.20: robust opening (cut-short recordings), three CSV
                   layouts and three companion tables, streamed statistics,
                   reduced spectrogram, .vszh5 pages with optional PDF/PNG
                   and bookmarks, sweep and frequency sub-ranges, parallel
                   workers, RAM budget, optional CuPy with per-block CPU
                   fallback, long captures (CSV split by time, disk-space
                   check, disk-mapped per-sweep table, thinned series, even
                   spectrogram grid with blank pauses), locked-file
                   fallback, command line and self-test (38 checks).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import argparse
import concurrent.futures as cf
import ctypes
import datetime as _dt
import gc
import io
import json
import math
import multiprocessing as mp
import os
import pickle
import re
import shutil
import sys
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence

import numpy as np

# The author's writer ships beside this module; put this folder first so that
# copy wins over an older one elsewhere on sys.path (Spyder's runcell sets
# __file__; a bare interpreter falls back to the working folder).
_MODULE_FOLDER = Path(globals().get("__file__", Path.cwd() / "_")).resolve().parent
if str(_MODULE_FOLDER) not in sys.path:
    sys.path.insert(0, str(_MODULE_FOLDER))

import vszh5_writer  # noqa: E402 - needs the path set above
from vszh5_writer import (Panel, Trace, VeuszWriter, VszDoc, block_reduce,  # noqa: E402
                          epoch_to_veusz, grid_page, image_page, local_utc_offsets,
                          render_pages, text_page, xy_page)

# The author's SHR reader (shr_reader.py, shipped beside this module): NumPy
# only, built from Signal Hound's SDK definition [R1]. It replaces
# py-shr-parser [R10], which rejects detector codes it does not know.
import shr_reader  # noqa: E402 - needs the path set above
from shr_reader import (ENUM_FIELDS, ShrFile, ShrFileSet, ShrFormatError,  # noqa: E402
                        ShrHeader, SweepBlock, enum_confidence, group_recordings,
                        sweep_record_dtype)

SHR_READER_VERSION = shr_reader.__version__

# %% ===========================================================================
#    VERSION AND CONSTANTS
# =============================================================================
__version__ = "0.0.2"                  # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"
__copyright__ = "Copyright (C) 2026 William W. Wallace"

PROGRAM_NAME = "SHR Converter"
#: Oldest writer with everything used here (date-axis images, block_reduce,
#: regularize_rows with jittered time stamps - 0.0.21).
MIN_WRITER_VERSION = (0, 0, 21)


def _version_tuple(text: str) -> tuple[int, ...]:
    """'0.0.20' -> (0, 0, 20); numeric, never lexicographic."""
    return tuple(int(part) for part in re.findall(r"\d+", str(text))[:3])


if _version_tuple(vszh5_writer.__version__) < MIN_WRITER_VERSION:
    raise ImportError(f"vszh5_writer {vszh5_writer.__version__} ({vszh5_writer.__file__}) is too old: "
                      f"0.0.21 or later, shipped with this program, is needed (restart the kernel "
                      f"if Spyder imported an older copy first)")

#: Oldest reader with everything used here (ShrFileSet, group_recordings).
MIN_READER_VERSION = (0, 0, 1)
if _version_tuple(SHR_READER_VERSION) < MIN_READER_VERSION:
    raise ImportError(f"shr_reader {SHR_READER_VERSION} ({shr_reader.__file__}) is too old: 0.0.1 or "
                      f"later, shipped with this program, is needed")

#: CSV layouts: key -> description.
CSV_LAYOUTS = {
    "sweeps_as_rows": "one row per sweep, one column per frequency",
    "frequencies_as_rows": "one row per frequency, one column per sweep",
    "long": "one row per sample (sweep, time, frequency, amplitude)",
}
#: CSV delimiters: key -> character.
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t"}
#: Time columns that can be written: key -> description.
TIME_COLUMNS = {
    "epoch_ms": "milliseconds since 1970-01-01 UTC (as recorded)",
    "utc_iso": "UTC date and time, ISO 8601 (millisecond resolution)",
    "local_iso": "local date and time of this computer, ISO 8601 with offset",
    "elapsed_s": "seconds since the first selected sweep",
}
#: CSV time decimation: how the sweeps of one CSV row (csv_decimate > 1) are combined.
CSV_DECIMATE_DETECTORS = {
    "max": "peak hold (bursts and narrow carriers survive)",
    "power_mean": "power mean (linear power, or RMS for mV)",
    "min": "minimum hold (noise floor)",
}
#: Spectrogram reduction: key -> description.
IMAGE_REDUCTIONS = {
    "max": "peak hold (bursts and narrow carriers survive)",
    "power_mean": "power mean (linear power, or RMS for mV)",
    "min": "minimum hold (noise floor)",
}
#: Time axis of the spectrogram and level-vs-time pages.
TIME_AXES = {
    "auto": "date/time for captures of 60 s or more, else elapsed seconds",
    "utc": "UTC date and time",
    "local": "local date and time",
    "elapsed": "seconds since the first selected sweep",
    "index": "sweep index",
}
#: Colour-scale limits of the spectrogram.
Z_MODES = {
    "data": "1st percentile of the image to its maximum",
    "reference": "Spike's display: reference level - 10 div to reference level",
    "manual": "z_min to z_max",
    "veusz": "Veusz Auto",
}
#: Veusz colour maps offered by the GUI (all exist in Veusz 3.6 and 4.2).
COLORMAPS = ("viridis", "magma", "inferno", "plasma", "heat", "spectrum2", "grey", "blue-darkred")
#: Excel worksheet limits [R6].
EXCEL_MAX_COLUMNS = 16_384
EXCEL_MAX_ROWS = 1_048_576
#: Blocks processed by one worker process before it is replaced (bounds any
#: slow growth of a long batch; Python 3.11+ ProcessPoolExecutor [R7]).
MAX_TASKS_PER_CHILD = 200
#: Below this many samples a file is converted in-process (no worker start-up).
IN_PROCESS_MAX_SAMPLES = 4_000_000
#: Upper limit of sweeps per block (keeps progress reports and cancel prompt).
MAX_BLOCK_SWEEPS = 4096
#: Blocks this large or larger go to the GPU when compute="auto".
GPU_MIN_SAMPLES = 1_000_000
#: Bytes per sample a block holds while it is processed and while it waits to
#: be written: the float32 block (4) plus its CSV text twice (the per-sweep
#: strings and the joined bytes; ~12 characters per lossless value, ~45 per
#: line of the long layout). The statistics work in sub-blocks of
#: STATS_CHUNK_SAMPLES, so their float64 temporaries do not grow with the
#: block. Measured with tests/memory_check.py and tests/long_capture_check.py.
BYTES_PER_SAMPLE = {"sweeps_as_rows": 30, "frequencies_as_rows": 30, "long": 100, "none": 6}
#: Samples per statistics sub-block (float64 temporaries ~40 bytes per sample:
#: 2 M samples = ~80 MB per worker, also a good size for one GPU transfer).
STATS_CHUNK_SAMPLES = 2_000_000


class ConversionCancelled(Exception):
    """Raised when the caller's cancel() returns True between blocks."""


# %% ===========================================================================
#    SMALL HELPERS
# =============================================================================
#: Frequency display units, largest first.
FREQUENCY_UNITS = (("GHz", 1e9), ("MHz", 1e6), ("kHz", 1e3), ("Hz", 1.0))


def frequency_unit(span_hz: float, f_max_hz: float) -> tuple[str, float]:
    """Display unit for a frequency axis: ('MHz', 1e6) etc.

    Chosen by the span, then moved to a larger unit while the axis values
    would have five or more digits before the point: Veusz writes such tick
    labels in scientific form (an SM200C span of 128 MHz at 13.9 GHz showed
    "1.39x10^4" MHz; it is now drawn as 13.84 .. 13.96 GHz).
    """
    reference = span_hz if span_hz > 0 else f_max_hz
    index = next((k for k, (_n, scale) in enumerate(FREQUENCY_UNITS) if reference >= scale),
                 len(FREQUENCY_UNITS) - 1)
    while index > 0 and abs(f_max_hz) / FREQUENCY_UNITS[index][1] >= 1e4:
        index -= 1
    return FREQUENCY_UNITS[index]


def short_name(name: str, limit: int = 32) -> str:
    """A file name shortened in the middle for page titles ("75fb3092-2026...01h01m58s.shr")."""
    if len(name) <= limit:
        return name
    keep = max(4, (limit - 3) // 2)
    return name[:keep] + "..." + name[-keep:]


def frequency_text(frequency_hz: float) -> str:
    """Exact, short decimal text of a frequency in Hz (no exponent)."""
    text = f"{frequency_hz:.6f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def utc_iso(epoch_ms: np.ndarray) -> list[str]:
    """ISO 8601 UTC strings with millisecond resolution, e.g. 2025-07-23T22:39:00.767Z."""
    stamps = np.asarray(epoch_ms, dtype="int64").astype("datetime64[ms]")
    return [s + "Z" for s in np.datetime_as_string(stamps, unit="ms")]


def local_iso(epoch_ms: np.ndarray) -> list[str]:
    """ISO 8601 local times of this computer, with UTC offset (DST-aware)."""
    return [_dt.datetime.fromtimestamp(int(v) / 1000.0, _dt.timezone.utc).astimezone()
            .isoformat(timespec="milliseconds") for v in np.asarray(epoch_ms, dtype="int64")]


def number_format(style: str, decimals: int) -> str:
    """printf format of the amplitudes: lossless %.9g or fixed decimals."""
    if style == "lossless":
        return "%.9g"
    if style == "fixed":
        return f"%.{int(max(0, min(decimals, 12)))}f"
    raise ValueError(f"number format must be lossless or fixed, not {style!r}")


def human_bytes(n_bytes: float) -> str:
    """1536 -> '1.5 KiB'."""
    value = float(n_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} TiB"


def default_workers() -> int:
    """CPU count minus one (the GUI and the writer keep one), at least 1."""
    return max(1, (os.cpu_count() or 2) - 1)


def _atomic_part(path: Path) -> Path:
    """Same-folder temporary name for an atomic write of ``path``.

    mkstemp() creates it with mode 0600; it is given the mode of the file it
    will replace, or the usual 0666 minus the umask (as vszh5_writer 0.0.20
    does), so the published CSV files are readable as any other file.
    """
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".part", dir=str(path.parent))
    os.close(descriptor)
    if os.name != "nt":
        try:
            mode = path.stat().st_mode & 0o7777 if path.exists() else vszh5_writer._default_file_mode()
            os.chmod(name, mode)
        except OSError:
            pass
    return Path(name)


# %% ===========================================================================
#    FILE INFORMATION AND OPENING (shr_reader)
# =============================================================================
#: File-header fields in file order with units and descriptions (shr_reader
#: ShrHeader attribute names, snake_case of the SDK names [R1]). Enumerated
#: fields are shown as labels with their confidence (shr_reader.enum_label).
HEADER_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("signature", "", "file signature (0xAA10)"),
    ("version", "", "SHR format version"),
    ("data_offset", "byte", "offset of the first sweep"),
    ("sweep_count", "", "sweeps according to the header"),
    ("sweep_length", "bin", "bins per sweep"),
    ("first_bin_freq_hz", "Hz", "frequency of bin 0"),
    ("bin_size_hz", "Hz", "bin spacing"),
    ("center_freq_hz", "Hz", "centre frequency"),
    ("span_hz", "Hz", "span"),
    ("rbw_hz", "Hz", "resolution bandwidth"),
    ("vbw_hz", "Hz", "video bandwidth"),
    ("ref_level", "dBm or mV", "reference level"),
    ("ref_scale", "", "reference scale (dBm or mV)"),
    ("div", "dB", "display division"),
    ("window", "", "RBW window"),
    ("attenuation", "dB", "attenuation setting (as stored by Spike)"),
    ("gain", "", "gain setting (as stored by Spike)"),
    ("detector", "", "video detector (Max/Min codes are not in the SDK)"),
    ("processing_units", "", "video processing units"),
    ("window_bandwidth", "bin", "window bandwidth in bins (RBW / bin spacing)"),
    ("decimation_type", "", "time averaging type"),
    ("decimation_detector", "", "time averaging detector"),
    ("decimation_count", "", "sweeps per output trace (count decimation)"),
    ("decimation_time_ms", "ms", "time averaging interval (time decimation)"),
    ("channelize_enabled", "", "channelizer enabled (1) or not (0)"),
    ("channel_output_units", "", "channelizer units"),
    ("channel_center_hz", "Hz", "channelizer centre"),
    ("channel_width_hz", "Hz", "channelizer width"),
)


def decode_title(raw: bytes) -> str:
    """A 256-byte title field as text (for callers holding raw bytes).

    shr_reader decodes the title itself (ShrHeader.title, UTF-16LE: the SDK
    declares uint16_t title[128] [R1]). This helper keeps the 0.0.1
    behaviour for raw bytes: UTF-16LE when the bytes look like it (zero high
    bytes), else UTF-8. A titled Spike recording has not been seen yet.
    """
    data = bytes(raw or b"")
    if not data.strip(b"\x00"):
        return ""
    looks_utf16 = len(data) >= 2 and data[1] == 0 and data[0] != 0
    if looks_utf16:
        units = data[: len(data) // 2 * 2]
        end = next((i for i in range(0, len(units), 2) if units[i:i + 2] == b"\x00\x00"), len(units))
        return units[:end].decode("utf-16-le", errors="replace").strip()
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


@dataclass
class ShrInfo:
    """Everything known about one recording (one file, or a multi-file set) before reading."""
    path: str                     # first (or only) file of the recording
    file_size: int                # bytes, all files
    header: dict[str, Any]        # HEADER_FIELDS values; enumerations as labels
    title: str
    n_sweeps_header: int          # sweep counts as written in the header(s)
    n_sweeps: int                 # complete sweeps that will be read
    n_bins: int
    first_bin_hz: float
    bin_hz: float
    amplitude_unit: str           # "dBm" or "mV"
    is_db: bool
    first_timestamp_ms: int = 0
    last_timestamp_ms: int = 0
    notes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)       # every file, in recording order
    file_sweeps: list[int] = field(default_factory=list)  # sweeps read from each file (worker bound)
    detector: str = ""            # detector label, e.g. "Max (code 2, inferred)"
    amplitude_grid: dict[str, Any] = field(default_factory=dict)   # shr_reader.detect_amplitude_grid

    @property
    def name(self) -> str:
        """Display name: the first file, plus how many more files a joined recording has."""
        extra = len(self.paths) - 1
        return Path(self.path).name + (f" (+{extra} file{'s' if extra > 1 else ''})" if extra > 0 else "")

    @property
    def is_set(self) -> bool:
        """True for a multi-file recording read as one (join_files)."""
        return len(self.paths) > 1

    def frequencies(self, start: int = 0, stop: int | None = None) -> np.ndarray:
        """Bin frequencies in Hz: first_bin + i * bin_size [R1]."""
        stop = self.n_bins if stop is None else stop
        return self.first_bin_hz + np.arange(start, stop, dtype=np.float64) * self.bin_hz

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.last_timestamp_ms - self.first_timestamp_ms) / 1000.0)

    def summary_lines(self) -> list[str]:
        """Human-readable description (GUI info pane, header page, log)."""
        f0, f1 = self.first_bin_hz, self.first_bin_hz + (self.n_bins - 1) * self.bin_hz
        lines = [
            f"File            : {self.name}",
            f"Size            : {human_bytes(self.file_size)} ({self.file_size} bytes)",
            f"Title           : {self.title or '(none)'}",
            f"Sweeps          : {self.n_sweeps} readable (header says {self.n_sweeps_header})",
            f"Bins per sweep  : {self.n_bins}",
            f"Frequency       : {f0 / 1e6:.6f} to {f1 / 1e6:.6f} MHz, bin {self.bin_hz:.6f} Hz",
            f"RBW / VBW       : {self.header['rbw_hz']:.6g} Hz / {self.header['vbw_hz']:.6g} Hz",
            f"Reference level : {self.header['ref_level']:.6g} {self.amplitude_unit}, "
            f"{self.header['div']:.6g} dB/div",
            f"Window          : {self.header['window']}",
            f"Detector        : {self.detector or self.header['detector']} "
            f"({self.header['processing_units']} units)",
            f"Spike decimation: {self.header['decimation_type']} / {self.header['decimation_detector']}, "
            f"count {self.header['decimation_count']}, time {self.header['decimation_time_ms']} ms",
        ]
        if self.is_set:
            lines.append(f"Files           : {len(self.paths)} joined "
                         f"({', '.join(f'{Path(p).name} [{n}]' for p, n in zip(self.paths, self.file_sweeps))})")
        if self.first_timestamp_ms:
            first = utc_iso(np.array([self.first_timestamp_ms]))[0]
            last = utc_iso(np.array([self.last_timestamp_ms]))[0]
            lines.append(f"Time (UTC)      : {first} to {last} ({self.duration_s:.3f} s)")
        lines += [f"Note            : {note}" for note in self.notes]
        return lines


def as_path_list(source: str | os.PathLike | Sequence[str | os.PathLike]) -> list[str]:
    """One path or a sequence of paths as a list of strings."""
    if isinstance(source, (str, os.PathLike)):
        return [str(source)]
    return [str(p) for p in source]


def open_source(source: str | os.PathLike | Sequence[str | os.PathLike],
                file_sweeps: Sequence[int] | None = None) -> ShrFile | ShrFileSet:
    """Open one .shr file (ShrFile) or the files of one recording (ShrFileSet).

    ``file_sweeps`` - the per-file sweep counts the main process decided
    (ShrInfo.file_sweeps). Worker processes pass them so every process reads
    the same sweeps even if a file is still growing, and a set keeps the
    order the main process chose. The caller must close() the source (or use
    it as a context manager).
    """
    paths = as_path_list(source)
    if len(paths) == 1:
        return ShrFile(paths[0], sweep_limit=None if file_sweeps is None else int(file_sweeps[0]))
    return ShrFileSet(paths, sweep_limits=None if file_sweeps is None else [int(n) for n in file_sweeps],
                      order_by_time=file_sweeps is None)


def read_info(source: str | os.PathLike | Sequence[str | os.PathLike]) -> ShrInfo:
    """Header, readable sweep count, time span and notes of one recording.

    ``source`` is one .shr path, or the paths of one multi-file recording
    (read as a ShrFileSet, ordered by time). Reads the header(s), the first
    and last time stamps and the first 32 sweeps (amplitude-grid check); it
    never reads the whole file, so Inspect stays quick on a 10 GB recording.
    """
    with open_source(source) as shr:
        header: ShrHeader = shr.header
        values: dict[str, Any] = {}
        for name, _unit, _text in HEADER_FIELDS:
            values[name] = header.label(name) if name in ENUM_FIELDS else getattr(header, name)
        values["sweep_count"] = int(shr.stated_sweep_count)          # as written in the file(s)
        notes = list(shr.notes)
        if isinstance(shr, ShrFileSet):
            notes += [f"{g['after']} -> {g['before']}: {g['gap_ms']} ms between the files" for g in shr.gaps]
        grid = shr.amplitude_grid() if shr.n_sweeps else {}
        code = int(header.detector)
        if grid.get("on_grid"):
            if code == 1:
                notes.append("amplitudes lie on a 0.01 dB grid although the detector is Average (unexpected)")
            elif enum_confidence("detector", code) != "documented":
                notes.append(f"amplitudes lie on a 0.01 dB grid (+{grid['offset_db']:.5f} dB), as the SM "
                             f"series min/max detector path produces [R11]; consistent with "
                             f"{header.label('detector')}")
        unit = header.amplitude_unit if int(header.ref_scale) in (0, 1) else "dB"
        paths = [str(Path(p).resolve()) for p in shr.paths]
        file_sweeps = ([int(f.n_sweeps) for f in shr.files] if isinstance(shr, ShrFileSet) else [int(shr.n_sweeps)])
        info = ShrInfo(path=paths[0], file_size=int(shr.file_size), header=values, title=header.title,
                       n_sweeps_header=values["sweep_count"], n_sweeps=int(shr.n_sweeps),
                       n_bins=int(header.sweep_length), first_bin_hz=float(header.first_bin_freq_hz),
                       bin_hz=float(header.bin_size_hz), amplitude_unit=unit, is_db=bool(header.is_db),
                       notes=notes, paths=paths, file_sweeps=file_sweeps,
                       detector=header.label("detector"), amplitude_grid=grid)
        if info.n_sweeps:
            info.first_timestamp_ms = int(shr.timestamps_ms(0, 1)[0])
            info.last_timestamp_ms = int(shr.timestamps_ms(info.n_sweeps - 1, info.n_sweeps)[0])
        return info


def _read_sweeps(shr: ShrFile | ShrFileSet, indices: np.ndarray, col_start: int, col_stop: int) -> SweepBlock:
    """Sweeps ``indices`` (an arithmetic progression) in one vectorised read."""
    indices = np.asarray(indices, dtype=np.int64)
    step = int(indices[1] - indices[0]) if indices.size > 1 else 1
    block = shr.read(int(indices[0]), int(indices[-1]) + 1, step, col_start, col_stop)
    if len(block) != indices.size or not np.array_equal(block.sweep_index, indices):
        raise ShrFormatError(f"read {len(block)} sweeps where {indices.size} were planned "
                             f"(the file changed during the conversion?)")
    return block


# %% ===========================================================================
#    OPTIONS AND PLAN
# =============================================================================
@dataclass
class ConvertOptions:
    """What to write and how. Every field has a GUI control and a CLI flag."""
    output_dir: str = ""                    # "" = beside each input file
    # -- CSV
    write_csv: bool = True
    csv_layout: str = "sweeps_as_rows"
    csv_number_format: str = "lossless"     # lossless (%.9g) | fixed
    csv_decimals: int = 3
    csv_delimiter: str = "comma"
    csv_time_columns: tuple[str, ...] = ("epoch_ms", "utc_iso")
    csv_header_table: bool = True
    csv_sweeps_table: bool = True
    csv_statistics_table: bool = True
    csv_split_minutes: float = 0.0          # > 0: a new CSV file every N minutes of recording
    csv_decimate: int = 1                   # selected sweeps combined per CSV row (1 = every sweep)
    csv_decimate_detector: str = "max"      # max | power_mean | min (CSV_DECIMATE_DETECTORS)
    check_disk_space: bool = True           # refuse when the estimated CSV does not fit
    # -- Veusz
    write_vszh5: bool = True
    vszh5_compress: bool = True
    image_max_rows: int = 2000
    image_max_columns: int = 2000
    image_reduction: str = "max"
    colormap: str = "viridis"
    z_mode: str = "data"
    z_min: float = -120.0
    z_max: float = -20.0
    time_axis: str = "auto"
    selected_sweeps: str = "first,last,peak"
    stats_max_points: int = 200_000         # statistics traces longer than this are reduced
    time_series_max_points: int = 100_000   # per-sweep series (level vs time, GPS) thinned to this
    page_spectrogram: bool = True
    page_statistics: bool = True
    page_selected_sweeps: bool = True
    page_level_vs_time: bool = True
    page_gps: bool = True
    page_header: bool = True
    render: bool = False
    render_png: str = "first"               # all | first | none
    render_dpi: int = 150
    veusz_exe: str = ""
    # -- selection
    sweep_start: int = 0
    sweep_stop: int = 0                     # 0 = to the end (exclusive index otherwise)
    sweep_step: int = 1
    freq_min_hz: float = 0.0                # 0 = from the first bin
    freq_max_hz: float = 0.0                # 0 = to the last bin
    join_files: bool = False                # files of one recording (multi-file Spike set) as one input
    # -- performance
    workers: int = 0                        # 0 = default_workers()
    ram_budget_mb: int = 1024
    compute: str = "auto"                   # auto | cpu | gpu
    sweep_table_storage: str = "auto"       # auto | memory | disk (per-sweep table)
    flush_after_file: bool = True

    def validate(self) -> None:
        """Raise ValueError naming the first bad option."""
        checks = [
            (self.csv_layout in CSV_LAYOUTS, f"csv_layout {self.csv_layout!r}"),
            (self.csv_number_format in ("lossless", "fixed"), f"csv_number_format {self.csv_number_format!r}"),
            (self.csv_delimiter in DELIMITERS, f"csv_delimiter {self.csv_delimiter!r}"),
            (all(c in TIME_COLUMNS for c in self.csv_time_columns), f"csv_time_columns {self.csv_time_columns}"),
            (self.image_reduction in IMAGE_REDUCTIONS, f"image_reduction {self.image_reduction!r}"),
            (self.time_axis in TIME_AXES, f"time_axis {self.time_axis!r}"),
            (self.z_mode in Z_MODES, f"z_mode {self.z_mode!r}"),
            (self.render_png in ("all", "first", "none"), f"render_png {self.render_png!r}"),
            (self.compute in ("auto", "cpu", "gpu"), f"compute {self.compute!r}"),
            (self.sweep_step >= 1, "sweep_step must be >= 1"),
            (self.sweep_start >= 0 and self.sweep_stop >= 0, "sweep_start/stop must be >= 0"),
            (self.image_max_rows >= 1 and self.image_max_columns >= 1, "image size must be >= 1"),
            (self.stats_max_points >= 2, "stats_max_points must be >= 2"),
            (self.time_series_max_points >= 2, "time_series_max_points must be >= 2"),
            (self.csv_split_minutes >= 0, "csv_split_minutes must be >= 0"),
            (int(self.csv_decimate) >= 1, "csv_decimate must be >= 1"),
            (self.csv_decimate_detector in CSV_DECIMATE_DETECTORS,
             f"csv_decimate_detector {self.csv_decimate_detector!r}"),
            (self.sweep_table_storage in ("auto", "memory", "disk"),
             f"sweep_table_storage {self.sweep_table_storage!r}"),
            (self.ram_budget_mb >= 16, "ram_budget_mb must be >= 16"),
            (self.workers >= 0, "workers must be >= 0"),
            (self.freq_min_hz >= 0 and self.freq_max_hz >= 0, "frequencies must be >= 0"),
            (self.z_mode != "manual" or self.z_max > self.z_min, "z_max must exceed z_min"),
        ]
        for ok, text in checks:
            if not ok:
                raise ValueError(f"invalid option: {text}")

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_mapping(cls, mapping: dict[str, Any]) -> "ConvertOptions":
        """Options from a dict (settings file, QSettings); unknown keys ignored."""
        names = {f.name: f for f in fields(cls)}
        values = {}
        for key, value in mapping.items():
            if key in names:
                values[key] = tuple(value) if key == "csv_time_columns" else value
        return cls(**values)


@dataclass
class Plan:
    """How one file will be processed (shown by Inspect, logged by Convert)."""
    n_sweeps: int                  # selected sweeps
    sweep_start: int
    sweep_step: int
    col_start: int
    col_stop: int
    row_factor: int                # sweeps per spectrogram row
    col_factor: int                # bins per spectrogram column
    image_rows: int
    image_cols: int
    block_sweeps: int
    n_blocks: int
    workers: int
    in_process: bool
    transpose_passes: int
    warnings: list[str] = field(default_factory=list)
    duration_s: float = 0.0        # time span of the selected sweeps (from the file's first/last)
    est_csv_bytes: int = 0         # estimated size of the main CSV file(s)
    est_csv_files: int = 0         # CSV files (more than one with csv_split_minutes)
    sweep_table_bytes: int = 0     # per-sweep table (RAM, or disk-mapped when large)
    csv_decimate: int = 1          # selected sweeps per CSV row (column when transposed)
    csv_rows: int = 0              # sweep rows (columns) of the main CSV

    @property
    def n_cols(self) -> int:
        return self.col_stop - self.col_start

    def csv_group_starts(self) -> np.ndarray:
        """Selection position of the first sweep of every CSV row (csv_decimate groups)."""
        return np.arange(0, self.n_sweeps, max(1, self.csv_decimate), dtype=np.int64)

    def sweep_indices(self, pos0: int = 0, pos1: int | None = None) -> np.ndarray:
        """File sweep indices of selection positions [pos0, pos1)."""
        pos1 = self.n_sweeps if pos1 is None else pos1
        return self.sweep_start + self.sweep_step * np.arange(pos0, pos1, dtype=np.int64)

    def lines(self) -> list[str]:
        out = [
            f"Selected        : {self.n_sweeps} sweep(s) (start {self.sweep_start}, step {self.sweep_step}) "
            f"x {self.n_cols} bin(s) (bins {self.col_start}..{self.col_stop - 1})",
            f"Spectrogram     : {self.image_rows} x {self.image_cols} pixels "
            f"({self.row_factor} sweep(s) x {self.col_factor} bin(s) per pixel)",
            f"Processing      : {self.n_blocks} block(s) of up to {self.block_sweeps} sweep(s), "
            + ("in this process" if self.in_process else f"{self.workers} worker process(es)"),
        ]
        if self.duration_s > 0:
            out.append(f"Capture         : {format_duration(self.duration_s)} selected, about "
                       f"{self.duration_s / max(self.image_rows, 1):.3g} s per spectrogram row")
        if self.csv_decimate > 1:
            out.append(f"CSV decimation  : {self.csv_decimate} sweeps per CSV row -> {self.csv_rows} row(s)")
        if self.est_csv_bytes:
            out.append(f"CSV estimate    : {human_bytes(self.est_csv_bytes)} in {self.est_csv_files} file(s)")
        out.append(f"Per-sweep table : {human_bytes(self.sweep_table_bytes)}")
        if self.transpose_passes:
            out.append(f"Transposed CSV  : {self.transpose_passes} column pass(es) over the file")
        out += [f"Warning         : {w}" for w in self.warnings]
        return out


def make_plan(info: ShrInfo, opts: ConvertOptions) -> Plan:
    """Selection, spectrogram reduction and block sizes for one file."""
    opts.validate()
    stop = info.n_sweeps if opts.sweep_stop == 0 else min(opts.sweep_stop, info.n_sweeps)
    start = min(opts.sweep_start, info.n_sweeps)
    n_sel = len(range(start, stop, opts.sweep_step))
    if n_sel == 0:
        raise ValueError(f"{info.name}: the sweep selection is empty "
                         f"(start {start}, stop {stop}, step {opts.sweep_step}, file has {info.n_sweeps})")
    col_start, col_stop = 0, info.n_bins
    if opts.freq_min_hz > 0:
        col_start = int(math.ceil((opts.freq_min_hz - info.first_bin_hz) / info.bin_hz - 1e-9))
    if opts.freq_max_hz > 0:
        col_stop = int(math.floor((opts.freq_max_hz - info.first_bin_hz) / info.bin_hz + 1e-9)) + 1
    col_start, col_stop = max(0, col_start), min(info.n_bins, col_stop)
    if col_stop <= col_start:
        raise ValueError(f"{info.name}: no bin lies in the frequency range "
                         f"{opts.freq_min_hz:g}..{opts.freq_max_hz:g} Hz")
    n_cols = col_stop - col_start
    row_factor = max(1, math.ceil(n_sel / opts.image_max_rows))
    col_factor = max(1, math.ceil(n_cols / opts.image_max_columns))
    workers = opts.workers or default_workers()
    total = n_sel * n_cols
    in_process = workers <= 1 or total <= IN_PROCESS_MAX_SAMPLES
    layout = opts.csv_layout if opts.write_csv else "none"
    first_pass_layout = "none" if layout == "frequencies_as_rows" else layout
    per_sweep = n_cols * BYTES_PER_SAMPLE[first_pass_layout]
    slots = 1 if in_process else 2 * workers + 1
    # The statistics sub-blocks need ~40 bytes per sample in each process at
    # once; that fixed part comes off the budget before the blocks are sized.
    stats_bytes = STATS_CHUNK_SAMPLES * 40 * (1 if in_process else workers)
    budget = max(opts.ram_budget_mb * 1024 * 1024 - stats_bytes, opts.ram_budget_mb * 1024 * 1024 // 4)
    block = max(1, int(budget // slots // max(per_sweep, 1)))
    if not in_process:                     # at least ~4 blocks per worker for balance
        block = min(block, max(1, math.ceil(n_sel / (4 * workers))))
    block = max(1, min(block, n_sel, MAX_BLOCK_SWEEPS))
    # CSV time decimation: the sweeps of one CSV row must lie in one block, so
    # blocks are whole multiples of csv_decimate (a group larger than the
    # block size becomes a block of its own).
    decimate = max(1, int(opts.csv_decimate)) if opts.write_csv else 1
    if decimate > 1 and block < n_sel:
        block = max(decimate, block // decimate * decimate)
    n_blocks = math.ceil(n_sel / block)
    csv_rows = math.ceil(n_sel / decimate)
    passes = 0
    warnings: list[str] = []
    if opts.write_csv and layout == "frequencies_as_rows":
        per_column = n_sel * BYTES_PER_SAMPLE["frequencies_as_rows"]
        cols_per_pass = max(1, int(budget // slots // max(per_column, 1)))
        passes = math.ceil(n_cols / cols_per_pass)
        if csv_rows + 1 > EXCEL_MAX_COLUMNS:
            warnings.append(f"{csv_rows + 1} columns: more than Excel's {EXCEL_MAX_COLUMNS}")
        if n_cols + 1 > EXCEL_MAX_ROWS:
            warnings.append(f"{n_cols + 1} rows: more than Excel's {EXCEL_MAX_ROWS}")
    elif opts.write_csv and layout == "sweeps_as_rows":
        extra = 4 + len(opts.csv_time_columns)
        if n_cols + extra > EXCEL_MAX_COLUMNS:
            warnings.append(f"{n_cols + extra} columns: more than Excel's {EXCEL_MAX_COLUMNS} "
                            f"(pandas/Veusz/MATLAB read it; or use a frequency range)")
        if csv_rows + 1 > EXCEL_MAX_ROWS:
            warnings.append(f"{csv_rows + 1} rows: more than Excel's {EXCEL_MAX_ROWS}")
    elif opts.write_csv and layout == "long" and csv_rows * n_cols + 1 > EXCEL_MAX_ROWS:
        warnings.append(f"{csv_rows * n_cols + 1} rows: more than Excel's {EXCEL_MAX_ROWS}")
    # Time span of the selection, from the file's first/last time stamps
    # (assumes an even sweep rate; exact values come with the conversion).
    span = info.duration_s * ((start + (n_sel - 1) * opts.sweep_step) - start) / max(info.n_sweeps - 1, 1)
    est_bytes = estimate_csv_bytes(opts, csv_rows, n_cols) if opts.write_csv else 0
    files = 1
    if opts.write_csv and opts.csv_split_minutes > 0 and layout in ("sweeps_as_rows", "long"):
        files = max(1, math.ceil(span / (60.0 * opts.csv_split_minutes)))
    return Plan(n_sweeps=n_sel, sweep_start=start, sweep_step=opts.sweep_step,
                col_start=col_start, col_stop=col_stop, row_factor=row_factor, col_factor=col_factor,
                image_rows=math.ceil(n_sel / row_factor), image_cols=math.ceil(n_cols / col_factor),
                block_sweeps=block, n_blocks=n_blocks, workers=1 if in_process else workers,
                in_process=in_process, transpose_passes=passes, warnings=warnings, duration_s=span,
                est_csv_bytes=est_bytes, est_csv_files=files if opts.write_csv else 0,
                sweep_table_bytes=n_sel * SWEEP_ROW_BYTES,   # SWEEP_ROW_BYTES: see SweepTable
                csv_decimate=decimate, csv_rows=csv_rows if opts.write_csv else 0)

#: Characters of each time column per row (with its delimiter).
TIME_COLUMN_CHARS = {"epoch_ms": 14, "utc_iso": 25, "local_iso": 30, "elapsed_s": 11}


def estimate_csv_bytes(opts: ConvertOptions, n_sweeps: int, n_bins: int) -> int:
    """Approximate size of the main CSV (+/- 15 %), for the plan and the disk check.

    ``n_sweeps`` is the number of sweep rows the CSV will have (after
    csv_decimate).

    A lossless dBm value ("-87.1234589") is about 11 characters plus the
    delimiter; a fixed one is sign + 3 digits + point + decimals + delimiter.
    """
    value = 12 if opts.csv_number_format == "lossless" else 6 + int(opts.csv_decimals)
    times = sum(TIME_COLUMN_CHARS.get(c, 12) for c in opts.csv_time_columns)
    if opts.csv_layout == "sweeps_as_rows":
        return int(n_bins * 20 + n_sweeps * (n_bins * value + 8 + times + 60))
    if opts.csv_layout == "long":
        return int(n_sweeps * n_bins * (value + 8 + times + 21))
    return int(n_sweeps * 12 + n_bins * (n_sweeps * value + 21))


def format_duration(seconds: float) -> str:
    """3725.2 -> '1 h 02 min 05.2 s'; 12.3 -> '12.3 s'."""
    seconds = float(seconds)
    if seconds < 60:
        return f"{seconds:.3g} s"
    hours, rest = divmod(seconds, 3600.0)
    minutes, secs = divmod(rest, 60.0)
    return (f"{int(hours)} h {int(minutes):02d} min {secs:04.1f} s" if hours
            else f"{int(minutes)} min {secs:04.1f} s")


# %% ===========================================================================
#    COMPUTE BACKEND (NumPy, optional CuPy)
# =============================================================================
_BACKEND_CACHE: dict[str, tuple[Any, str]] = {}


def get_backend(compute: str) -> tuple[Any, str]:
    """(array module, description) for compute = auto | cpu | gpu.

    "gpu" and "auto" use CuPy when it imports and sees a CUDA device; else
    NumPy (a conversion never fails for want of a GPU). The environment
    variable SHR_CONVERTER_FAKE_CUPY=1 substitutes a NumPy-backed stand-in
    so the tests can run the GPU code path on any machine.
    """
    if compute in _BACKEND_CACHE:
        return _BACKEND_CACHE[compute]
    result: tuple[Any, str] = (np, "NumPy (CPU)")
    if compute in ("auto", "gpu"):
        fake = os.environ.get("SHR_CONVERTER_FAKE_CUPY", "")
        if fake in ("1", "fail"):
            result = (_FakeCupy(fail=fake == "fail"), "fake CuPy (NumPy stand-in, tests only)")
        else:
            try:
                import cupy
                if cupy.cuda.runtime.getDeviceCount() > 0:
                    name = cupy.cuda.runtime.getDeviceProperties(0)["name"]
                    name = name.decode() if isinstance(name, bytes) else str(name)
                    result = (cupy, f"CuPy {cupy.__version__} on {name}")
            except Exception as exc:  # noqa: BLE001 - fall back to NumPy
                result = (np, f"NumPy (CPU; CuPy unavailable: {type(exc).__name__})")
    _BACKEND_CACHE[compute] = result
    return result


class _FakeCupy:
    """NumPy with CuPy's asnumpy(): exercises the GPU code path in tests.

    fail=True makes asarray() raise MemoryError, like cupy.cuda.memory.
    OutOfMemoryError, to test the per-block fallback to the CPU.
    """

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def __getattr__(self, name: str) -> Any:
        return getattr(np, name)

    def asarray(self, *args: Any, **kwargs: Any) -> np.ndarray:
        if self.fail:
            raise MemoryError("fake GPU out of memory")
        return np.asarray(*args, **kwargs)

    @staticmethod
    def asnumpy(array: Any) -> np.ndarray:
        return np.asarray(array)


def _to_host(xp: Any, array: Any) -> np.ndarray:
    """A device array as a NumPy array (no copy for NumPy)."""
    return xp.asnumpy(array) if xp is not np and hasattr(xp, "asnumpy") else np.asarray(array)


# %% ===========================================================================
#    BLOCK PROCESSING (runs in worker processes)
# =============================================================================
# A "block" is a run of consecutive SELECTED sweeps: selection positions
# pos0 .. pos1-1, i.e. file sweeps sweep_start + sweep_step * pos. Every block
# is handled by process_block() on its own - in a worker process when the plan
# asks for workers - which
#   1. maps the file(s) itself with shr_reader (file handles and memory maps
#      are never shared between processes),
#   2. reads the block's sweeps (time stamp, GPS, overflow flag, amplitudes)
#      in ONE vectorised read,
#   3. formats the block's CSV text (the slowest step, pure CPU), after
#      combining every csv_decimate sweeps into one row when asked,
#   4. reduces the block to partial results that the main process merges
#      EXACTLY: per-bin maxima/minima/sums, per-sweep scalars, and spectrogram
#      accumulators (maxima, minima or sums of linear power per pixel).
# No block depends on another, so the blocks run in parallel; the main
# process only writes the text in order and adds the partial results up.
@dataclass
class BlockTask:
    """One block of sweeps for process_block(); everything a worker needs (picklable)."""
    paths: tuple[str, ...]        # the .shr file, or the files of a joined recording (in order)
    file_sweeps: tuple[int, ...]  # sweeps read from each file (the main process's decision)
    is_db: bool                   # amplitudes in dBm (True) or mV (False)
    pos0: int                     # first selection position of the block
    pos1: int                     # one past the last selection position
    sweep_start: int              # selection: first file sweep
    sweep_step: int               # selection: every Nth sweep
    col_start: int                # first selected bin
    col_stop: int                 # one past the last selected bin
    first_bin_hz: float           # frequency of bin 0 (file header)
    bin_hz: float                 # bin spacing (file header)
    row_factor: int               # selected sweeps per spectrogram row
    col_factor: int               # selected bins per spectrogram column
    image_reduction: str          # max | min | power_mean
    compute: str                  # auto | cpu | gpu
    text_layout: str              # sweeps_as_rows | long | none (no text in this pass)
    numfmt: str = "%.9g"          # printf format of the amplitudes
    delimiter: str = ","
    time_columns: tuple[str, ...] = ()
    t0_ms: int = 0                # time stamp of the first selected sweep (elapsed_s)
    csv_decimate: int = 1         # selected sweeps per CSV row (blocks are whole multiples)
    csv_decimate_detector: str = "max"


@dataclass
class BlockResult:
    """What one block contributes: CSV text, statistics, per-sweep rows, image rows."""
    pos0: int
    pos1: int
    text: bytes                   # CSV text of the block ("" when text_layout == "none")
    row_offsets: np.ndarray       # byte offset of each CSV row's text, plus the end (rows + 1)
    text_timestamp_ms: np.ndarray # time stamp of each CSV row (its first sweep; CSV split by time)
    stat_max: np.ndarray          # per bin: maximum over the block's sweeps
    stat_min: np.ndarray          # per bin: minimum
    stat_sum: np.ndarray          # per bin: sum of x
    stat_sum2: np.ndarray         # per bin: sum of x^2
    stat_power: np.ndarray        # per bin: sum of 10^(x/10) (dB) or x^2 (mV)
    stat_count: np.ndarray        # per bin: finite samples
    timestamp_ms: np.ndarray      # per sweep ...
    latitude: np.ndarray
    longitude: np.ndarray
    altitude: np.ndarray
    overflow: np.ndarray
    peak: np.ndarray
    peak_bin: np.ndarray          # absolute bin index of the sweep's maximum
    power_mean: np.ndarray        # dB power mean over the bins, or RMS for mV
    image_group0: int             # first spectrogram row (global index) touched
    image_acc: np.ndarray         # (rows touched, image columns) accumulator
    image_count: np.ndarray       # sweeps of this block in each row touched
    n_nonfinite: int              # NaN/inf samples (skipped by the statistics)
    backend: str                  # which array library did the statistics
    seconds: float                # worker time for this block


def csv_groups(positions: np.ndarray, decimate: int) -> np.ndarray:
    """Index (into ``positions``) of the first sweep of every CSV row.

    A CSV row combines the selected sweeps whose selection position lies in
    the same multiple of ``decimate``; blocks are whole multiples of it
    (make_plan), so a row never spans two blocks.
    """
    groups = np.asarray(positions, dtype=np.int64) // max(1, int(decimate))
    return np.flatnonzero(np.r_[True, groups[1:] != groups[:-1]]).astype(np.int64)


def decimate_sweeps(amplitudes: np.ndarray, starts: np.ndarray, detector: str, is_db: bool) -> np.ndarray:
    """Combine groups of consecutive sweeps (rows) into one row each (CSV time decimation).

    ``starts`` - first row of every group (csv_groups). detector: "max" /
    "min" per bin (exact float32 values, NaN ignored unless a whole group
    is NaN), or "power_mean": 10 log10 of the mean linear power for dB
    data, RMS for mV data, computed in float64 in sub-blocks of about
    STATS_CHUNK_SAMPLES and returned as float32.
    """
    starts = np.asarray(starts, dtype=np.int64)
    if detector == "max":
        return np.fmax.reduceat(amplitudes, starts, axis=0)
    if detector == "min":
        return np.fmin.reduceat(amplitudes, starts, axis=0)
    if detector != "power_mean":
        raise ValueError(f"csv_decimate_detector must be one of {list(CSV_DECIMATE_DETECTORS)}")
    ends = np.r_[starts[1:], amplitudes.shape[0]]
    out = np.empty((starts.size, amplitudes.shape[1]), dtype=np.float32)
    group_rows = max(1, int(np.max(ends - starts)))
    groups_per_chunk = max(1, STATS_CHUNK_SAMPLES // max(1, group_rows * amplitudes.shape[1]))
    for g0 in range(0, starts.size, groups_per_chunk):
        g1 = min(g0 + groups_per_chunk, starts.size)
        rows = slice(int(starts[g0]), int(ends[g1 - 1]))
        x = amplitudes[rows].astype(np.float64)
        finite = np.isfinite(x)
        linear = np.where(finite, np.power(10.0, x / 10.0) if is_db else x * x, 0.0)
        local = starts[g0:g1] - starts[g0]
        sums = np.add.reduceat(linear, local, axis=0)
        counts = np.add.reduceat(finite, local, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            mean = sums / np.where(counts > 0, counts, np.nan)
            out[g0:g1] = 10.0 * np.log10(mean) if is_db else np.sqrt(mean)
    return out


def _time_strings(columns: Sequence[str], ts: np.ndarray, t0_ms: int) -> list[list[str]]:
    """For each requested time column, the text of every sweep of the block."""
    out = []
    for column in columns:
        if column == "epoch_ms":
            out.append([str(int(v)) for v in ts])
        elif column == "utc_iso":
            out.append(utc_iso(ts))
        elif column == "local_iso":
            out.append(local_iso(ts))
        elif column == "elapsed_s":
            out.append([f"{(int(v) - t0_ms) / 1000.0:.3f}" for v in ts])
    return out


def _format_text(task: BlockTask, indices: np.ndarray, ts: np.ndarray, lat: np.ndarray,
                 lon: np.ndarray, alt: np.ndarray, overflow: np.ndarray,
                 amplitudes: np.ndarray, combined: np.ndarray | None = None) -> tuple[bytes, np.ndarray]:
    """CSV text of one block and the byte offset where each row's text starts.

    One row per sweep, or per group of csv_decimate sweeps; ``combined``
    (sweeps per row) is then written as the "sweeps_combined" column. The
    offsets let the main process split the CSV between any two rows
    (csv_split_minutes) without re-parsing the text. Every character is
    ASCII, so string length equals byte length.
    """
    d = task.delimiter
    times = _time_strings(task.time_columns, ts, task.t0_ms)
    if combined is not None:            # the combined count follows the time columns
        times = times + [[str(int(c)) for c in combined]]
    # Each row is converted to Python floats (exact copies of the float32
    # values) only when it is formatted: a whole block as Python floats would
    # take ~32 bytes per value instead of 4.
    parts: list[str] = []
    if task.text_layout == "sweeps_as_rows":
        # One printf format for a whole row: one "%" operation per sweep is
        # far faster than formatting the values one by one.
        row_format = d.join([task.numfmt] * amplitudes.shape[1])
        for k, index in enumerate(indices):
            prefix = [str(int(index))] + [column[k] for column in times] + [
                repr(float(lat[k])), repr(float(lon[k])), repr(float(alt[k])), "1" if overflow[k] else "0"]
            parts.append(d.join(prefix) + d + (row_format % tuple(amplitudes[k].tolist())) + "\n")
    elif task.text_layout == "long":
        # One line per sample. The frequency text is fixed per column, so it is
        # baked into a template once; per sweep only the prefix (sweep index
        # and time) and the amplitudes are substituted.
        freq_text = [frequency_text(f) for f in
                     task.first_bin_hz + np.arange(task.col_start, task.col_stop) * task.bin_hz]
        template = "".join("%s" + text + d + task.numfmt + "\n" for text in freq_text)
        n_cols = len(freq_text)
        arguments: list[Any] = [None] * (2 * n_cols)
        for k, index in enumerate(indices):
            prefix = d.join([str(int(index))] + [column[k] for column in times]) + d
            arguments[0::2] = [prefix] * n_cols
            arguments[1::2] = amplitudes[k].tolist()
            parts.append(template % tuple(arguments))
    offsets = np.zeros(len(parts) + 1, dtype=np.int64)
    if parts:
        np.cumsum([len(p) for p in parts], out=offsets[1:])
    return "".join(parts).encode("ascii"), offsets


def _block_statistics(xp: Any, amplitudes: np.ndarray, is_db: bool, col_factor: int,
                      reduction: str) -> dict[str, Any]:
    """Statistics and spectrogram columns of one block, on NumPy or CuPy (``xp``).

    The heavy, data-parallel part of a block (float64 conversion, 10^(x/10),
    reductions over both axes, column decimation) - this is what runs on the
    GPU when CuPy is used. Returns device arrays; the caller copies them to
    the host.
    """
    x = xp.asarray(amplitudes, dtype=xp.float64)
    finite = xp.isfinite(x)
    n_nonfinite = int(_to_host(xp, finite.size - finite.sum()))
    if n_nonfinite:
        x = xp.where(finite, x, xp.nan)     # NaN is skipped by the nan* reductions below
    # Power domain: 10^(x/10) for dB data, x^2 for linear (mV) data.
    power = xp.power(10.0, x / 10.0) if is_db else x * x
    out: dict[str, Any] = {"n_nonfinite": n_nonfinite}
    if n_nonfinite:
        with np.errstate(all="ignore"):
            out["stat_max"], out["stat_min"] = xp.nanmax(x, axis=0), xp.nanmin(x, axis=0)
            out["stat_sum"], out["stat_sum2"] = xp.nansum(x, axis=0), xp.nansum(x * x, axis=0)
            out["stat_power"] = xp.nansum(power, axis=0)
            out["stat_count"] = finite.sum(axis=0)
            out["peak"] = xp.nanmax(x, axis=1)
            out["peak_bin"] = xp.argmax(xp.where(xp.isnan(x), -xp.inf, x), axis=1)
            sweep_power = xp.nanmean(power, axis=1)
    else:
        out["stat_max"], out["stat_min"] = x.max(axis=0), x.min(axis=0)
        out["stat_sum"], out["stat_sum2"] = x.sum(axis=0), (x * x).sum(axis=0)
        out["stat_power"] = power.sum(axis=0)
        out["stat_count"] = xp.full(x.shape[1], x.shape[0], dtype=xp.int64)
        out["peak"], out["peak_bin"] = x.max(axis=1), x.argmax(axis=1)
        sweep_power = power.mean(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        out["power_mean"] = 10.0 * xp.log10(sweep_power) if is_db else xp.sqrt(sweep_power)
    # Spectrogram columns: each sweep reduced in blocks of col_factor bins, in
    # the domain that accumulates exactly across sweeps (values for max/min,
    # linear power for the power mean).
    if reduction == "power_mean":
        out["columns"] = block_reduce(power, 1, col_factor, "mean", xp=xp)
    else:
        out["columns"] = block_reduce(x, 1, col_factor, reduction, xp=xp)
    return out


def _chunked_statistics(xp: Any, amplitudes: np.ndarray, is_db: bool, col_factor: int,
                        reduction: str) -> tuple[dict[str, np.ndarray], Any]:
    """_block_statistics() over sub-blocks of rows, merged on the host.

    Bounds the float64 temporaries to STATS_CHUNK_SAMPLES per worker whatever
    the block size, and sends the GPU one sub-block at a time. Per-bin
    results merge exactly (max/min/sums); per-sweep results and spectrogram
    columns are simply stacked.
    """
    rows_per_chunk = max(1, STATS_CHUNK_SAMPLES // max(amplitudes.shape[1], 1))
    merged: dict[str, Any] = {}
    stacked: dict[str, list[np.ndarray]] = {"peak": [], "peak_bin": [], "power_mean": [], "columns": []}
    for r0 in range(0, amplitudes.shape[0], rows_per_chunk):
        part = _block_statistics(xp, amplitudes[r0:r0 + rows_per_chunk], is_db, col_factor, reduction)
        host = {k: (v if k == "n_nonfinite" else _to_host(xp, v)) for k, v in part.items()}
        for key in stacked:
            stacked[key].append(host[key])
        if not merged:
            merged = {k: host[k] for k in ("stat_max", "stat_min", "stat_sum", "stat_sum2", "stat_power",
                                           "stat_count", "n_nonfinite")}
            continue
        np.fmax(merged["stat_max"], host["stat_max"], out=merged["stat_max"])
        np.fmin(merged["stat_min"], host["stat_min"], out=merged["stat_min"])
        for key in ("stat_sum", "stat_sum2", "stat_power", "stat_count"):
            merged[key] = merged[key] + host[key]
        merged["n_nonfinite"] += host["n_nonfinite"]
    for key, pieces in stacked.items():
        merged[key] = np.concatenate(pieces, axis=0)
    return merged, xp


def process_block(task: BlockTask) -> BlockResult:
    """Read one block with shr_reader; CSV text, statistics and image rows.

    Top-level (picklable) so ProcessPoolExecutor can run it in a worker. The
    statistics run on the GPU when task.compute selects CuPy; any GPU error
    (out of memory, driver) repeats them on the CPU for this block, so a
    conversion never fails because of the GPU. With csv_decimate > 1 only
    the CSV text is decimated; statistics and image use every sweep.
    """
    started = time.perf_counter()
    positions = np.arange(task.pos0, task.pos1, dtype=np.int64)
    indices = task.sweep_start + task.sweep_step * positions
    with open_source(task.paths, task.file_sweeps) as shr:
        block = _read_sweeps(shr, indices, task.col_start, task.col_stop)
    ts, lat, lon, alt = block.timestamp_ms, block.latitude, block.longitude, block.altitude_m
    overflow = block.adc_overflow.astype(bool)
    amplitudes = block.amplitudes
    del block
    text, offsets, text_ts = b"", np.zeros(1, dtype=np.int64), np.empty(0, dtype=np.int64)
    if task.text_layout in ("sweeps_as_rows", "long"):
        if task.csv_decimate > 1:
            # One CSV row per group: first sweep's index, time and GPS fix,
            # overflow if any sweep overflowed, amplitudes combined per bin.
            starts = csv_groups(positions, task.csv_decimate)
            combined = np.diff(np.r_[starts, positions.size])
            text, offsets = _format_text(
                task, indices[starts], ts[starts], lat[starts], lon[starts], alt[starts],
                np.logical_or.reduceat(overflow, starts),
                decimate_sweeps(amplitudes, starts, task.csv_decimate_detector, task.is_db), combined)
            text_ts = ts[starts]
        else:
            text, offsets = _format_text(task, indices, ts, lat, lon, alt, overflow, amplitudes)
            text_ts = ts

    # -- statistics: GPU when selected and worthwhile, else CPU ------------------------
    xp, backend = get_backend(task.compute)
    if task.compute == "auto" and xp is not np and amplitudes.size < GPU_MIN_SAMPLES:
        xp, backend = np, "NumPy (CPU; block below the GPU threshold)"
    try:
        stats, xp = _chunked_statistics(xp, amplitudes, task.is_db, task.col_factor, task.image_reduction)
    except Exception as exc:  # noqa: BLE001 - GPU out of memory / driver error: use the CPU
        if xp is np:
            raise
        xp, backend = np, f"NumPy (CPU; GPU failed: {type(exc).__name__})"
        stats, xp = _chunked_statistics(np, amplitudes, task.is_db, task.col_factor, task.image_reduction)
    host = lambda a: np.asarray(a)  # noqa: E731 - already on the host (merged above)

    # -- spectrogram rows: accumulate the block's sweeps into the GLOBAL rows
    #    they belong to (row = selection position // row_factor). A block may
    #    start or end inside a row; the main process adds the partial rows.
    columns = host(stats["columns"])
    groups = np.arange(task.pos0, task.pos1) // task.row_factor
    starts = np.flatnonzero(np.r_[True, groups[1:] != groups[:-1]])   # first sweep of each row
    counts = np.diff(np.r_[starts, len(groups)])                      # sweeps per row
    if task.image_reduction == "max":
        acc = np.fmax.reduceat(columns, starts, axis=0)
    elif task.image_reduction == "min":
        acc = np.fmin.reduceat(columns, starts, axis=0)
    else:                                   # sums of linear power; divided by the count at the end
        acc = np.add.reduceat(np.nan_to_num(columns, nan=0.0), starts, axis=0)

    return BlockResult(
        pos0=task.pos0, pos1=task.pos1, text=text, row_offsets=offsets, text_timestamp_ms=text_ts,
        stat_max=host(stats["stat_max"]), stat_min=host(stats["stat_min"]),
        stat_sum=host(stats["stat_sum"]), stat_sum2=host(stats["stat_sum2"]),
        stat_power=host(stats["stat_power"]), stat_count=host(stats["stat_count"]).astype(np.int64),
        timestamp_ms=ts, latitude=lat, longitude=lon, altitude=alt, overflow=overflow,
        peak=host(stats["peak"]), peak_bin=host(stats["peak_bin"]).astype(np.int64) + task.col_start,
        power_mean=host(stats["power_mean"]), image_group0=int(groups[0]), image_acc=acc,
        image_count=counts.astype(np.int64), n_nonfinite=stats["n_nonfinite"], backend=backend,
        seconds=time.perf_counter() - started)


@dataclass
class ColumnTask:
    """One column block of the transposed (frequencies_as_rows) CSV (picklable)."""
    paths: tuple[str, ...]
    file_sweeps: tuple[int, ...]
    n_sel: int
    sweep_start: int
    sweep_step: int
    col0: int
    col1: int
    first_bin_hz: float
    bin_hz: float
    numfmt: str
    delimiter: str
    is_db: bool = True
    csv_decimate: int = 1
    csv_decimate_detector: str = "max"


def process_columns(task: ColumnTask) -> bytes:
    """Rows (one per frequency) of the transposed CSV for bins [col0, col1).

    Needs every selected sweep of these bins at once, so each column block
    reads the whole selection once (the plan reports how many passes) - one
    vectorised read of just these columns. With csv_decimate > 1 the sweeps
    (columns of the CSV) are combined in groups first.
    """
    indices = task.sweep_start + task.sweep_step * np.arange(task.n_sel, dtype=np.int64)
    with open_source(task.paths, task.file_sweeps) as shr:
        block = _read_sweeps(shr, indices, task.col0, task.col1).amplitudes
    if task.csv_decimate > 1:
        block = decimate_sweeps(block, csv_groups(np.arange(task.n_sel), task.csv_decimate),
                                task.csv_decimate_detector, task.is_db)
    d = task.delimiter
    row_format = d.join([task.numfmt] * block.shape[0])
    columns = block.T.tolist()
    frequencies = task.first_bin_hz + np.arange(task.col0, task.col1) * task.bin_hz
    return "".join(frequency_text(f) + d + (row_format % tuple(columns[j])) + "\n"
                   for j, f in enumerate(frequencies)).encode("ascii")


# %% ===========================================================================
#    PER-SWEEP TABLE (in memory, or memory-mapped on disk for long captures)
# =============================================================================
# One row per selected sweep: 57 bytes. A 3-hour capture at 1000 sweeps/s is
# 10.8 million sweeps = 615 MB, so above a threshold the table is a set of
# .npy files memory-mapped from a private temporary folder: the operating
# system pages it in and out, and the process's resident memory stays small.
#: (column, dtype) of the per-sweep table.
SWEEP_COLUMNS: tuple[tuple[str, Any], ...] = (
    ("timestamp_ms", np.int64), ("latitude", np.float64), ("longitude", np.float64),
    ("altitude", np.float64), ("overflow", np.bool_), ("peak", np.float64),
    ("peak_bin", np.int64), ("power_mean", np.float64))
#: Bytes per sweep of the table.
SWEEP_ROW_BYTES = sum(np.dtype(dtype).itemsize for _name, dtype in SWEEP_COLUMNS)


class SweepTable:
    """Per-sweep columns filled block by block, in RAM or on disk.

    ``storage``: "memory", "disk" or "auto" (disk when the table is larger
    than a quarter of the RAM budget). close() releases the memory maps and
    deletes the temporary folder; replace any references to the arrays
    first (Windows cannot delete a mapped file).
    """

    def __init__(self, n_rows: int, storage: str, ram_budget_mb: int) -> None:
        self.n_rows = int(n_rows)
        size = self.n_rows * SWEEP_ROW_BYTES
        self.on_disk = storage == "disk" or (storage == "auto" and size > ram_budget_mb * 2 ** 20 / 4)
        self.folder: Path | None = None
        self.columns: dict[str, np.ndarray] = {}
        if self.on_disk:
            self.folder = Path(tempfile.mkdtemp(prefix="shr_sweeps_"))
            for name, dtype in SWEEP_COLUMNS:
                self.columns[name] = np.lib.format.open_memmap(
                    self.folder / f"{name}.npy", mode="w+", dtype=dtype, shape=(self.n_rows,))
        else:
            for name, dtype in SWEEP_COLUMNS:
                self.columns[name] = np.empty(self.n_rows, dtype=dtype)

    def put(self, result: BlockResult) -> None:
        """Copy a block's per-sweep values into rows [pos0, pos1)."""
        for name, _dtype in SWEEP_COLUMNS:
            self.columns[name][result.pos0:result.pos1] = getattr(result, name)

    def close(self) -> None:
        """Release the maps and delete the temporary folder (idempotent)."""
        if self.folder is None:
            self.columns = {}
            return
        for array in self.columns.values():
            try:
                array.flush()
            except Exception:  # noqa: BLE001 - already closed
                pass
        self.columns = {}
        gc.collect()                         # drop the last mmap references (Windows)
        shutil.rmtree(self.folder, ignore_errors=True)
        self.folder = None


def _block_starts(n: int, factor: int) -> np.ndarray:
    """Start index of every block of ``factor`` consecutive elements of n."""
    return np.arange(0, n, max(1, int(factor)), dtype=np.int64)


def reduce_series(series: dict[str, np.ndarray], factor: int, is_db: bool) -> dict[str, np.ndarray]:
    """Thin per-sweep series to one value per ``factor`` sweeps, keeping what matters.

    Rules (a reader of a level-versus-time plot must not lose a burst):
        peak             maximum of the block (peak hold)
        peak_bin         bin of that maximum (the frequency of the strongest sweep)
        power_mean       power mean of the block (dB) or RMS (mV)
        overflow         True when any sweep of the block overflowed
        timestamp_ms     mean time of the block (float ms)
        sweep_index,
        latitude/longitude/altitude   first sweep of the block (a GPS fix)
    factor <= 1 returns copies (never memory maps).
    """
    if factor <= 1:
        return {name: np.array(values) for name, values in series.items()}
    n = len(next(iter(series.values())))
    starts = _block_starts(n, factor)
    counts = np.diff(np.r_[starts, n]).astype(float)
    out: dict[str, np.ndarray] = {}
    peak = np.asarray(series["peak"], dtype=float)
    out["peak"] = np.fmax.reduceat(peak, starts)
    # index of each block's maximum: the position of the peak inside the block
    winners = np.empty(len(starts), dtype=np.int64)
    for k, (s, e) in enumerate(zip(starts, np.r_[starts[1:], n])):
        segment = peak[s:e]
        finite = np.isfinite(segment)
        winners[k] = s + (int(np.argmax(np.where(finite, segment, -np.inf))) if finite.any() else 0)
    for name, values in series.items():
        if name == "peak":
            continue
        array = np.asarray(values)
        if name == "peak_bin":
            out[name] = array[winners].astype(np.int64)
        elif name == "power_mean":
            if is_db:
                linear = np.power(10.0, array.astype(float) / 10.0)
                out[name] = 10.0 * np.log10(np.add.reduceat(linear, starts) / counts)
            else:
                out[name] = np.sqrt(np.add.reduceat(array.astype(float) ** 2, starts) / counts)
        elif name == "overflow":
            out[name] = np.logical_or.reduceat(array.astype(bool), starts)
        elif name == "timestamp_ms":
            out[name] = np.add.reduceat(array.astype(float), starts) / counts
        else:
            out[name] = array[starts]
    return {name: np.array(values) for name, values in out.items()}   # plain ndarray copies


# %% ===========================================================================
#    CSV SINK (one file, or one file per time slice)
# =============================================================================
class CsvSink:
    """Writes the main CSV in order; optionally a new file every split_minutes.

    Files are written to private .part names (registered in ``parts`` so a
    failure or a cancel deletes them) and published by the caller. With a
    split, files are numbered in order of creation: <stem>_part001.csv, ...,
    each with the header line; a pause in the recording longer than a slice
    simply starts the next file. Slices are measured from the first selected
    sweep on the running maximum of the time stamps, so a clock step back
    never sends a sweep to an earlier file.
    """

    def __init__(self, stem: Path, header: str, split_minutes: float, t0_ms: int,
                 parts: dict[Path, Path]) -> None:
        self.stem = stem
        self.header = header.encode("ascii", errors="replace")
        self.split_ms = float(split_minutes) * 60_000.0 if split_minutes and split_minutes > 0 else 0.0
        self.t0_ms = int(t0_ms)
        self.parts = parts
        self.handle: Any = None
        self.slice: int | None = None
        self.files: list[dict[str, Any]] = []      # final path, first/last time, sweeps, bytes
        self.running_max = -np.inf

    def _open(self, slice_index: int, first_ms: int) -> None:
        """Close the current file and start the next one."""
        self.close()
        number = len(self.files) + 1
        final = (self.stem.with_name(self.stem.name + ".csv") if not self.split_ms
                 else self.stem.with_name(f"{self.stem.name}_part{number:03d}.csv"))
        part = _atomic_part(final)
        self.parts[final] = part
        self.handle = open(part, "wb")
        self.handle.write(self.header)
        self.files.append({"final": final, "first_ms": first_ms, "last_ms": first_ms, "sweeps": 0,
                           "bytes": len(self.header)})
        self.slice = slice_index

    def write(self, text: bytes, offsets: np.ndarray, ts: np.ndarray) -> None:
        """Append one block's text (sweep k is text[offsets[k]:offsets[k + 1]])."""
        n = len(ts)
        if n == 0:
            return
        if not self.split_ms:
            slices = np.zeros(n, dtype=np.int64)
        else:
            monotonic = np.maximum.accumulate(np.r_[self.running_max, ts.astype(float)])[1:]
            self.running_max = monotonic[-1]
            slices = np.floor((monotonic - self.t0_ms) / self.split_ms).astype(np.int64)
        changes = np.flatnonzero(np.diff(slices)) + 1
        for start, end in zip(np.r_[0, changes], np.r_[changes, n]):
            if self.handle is None or slices[start] != self.slice:
                self._open(int(slices[start]), int(ts[start]))
            chunk = text[offsets[start]:offsets[end]]
            self.handle.write(chunk)
            entry = self.files[-1]
            entry["last_ms"] = int(ts[end - 1])
            entry["sweeps"] += int(end - start)
            entry["bytes"] += len(chunk)

    def write_raw(self, text: bytes) -> None:
        """Append text that is not split (the transposed layout)."""
        if self.handle is None:
            self._open(0, self.t0_ms)
        self.handle.write(text)
        self.files[-1]["bytes"] += len(text)

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None


# %% ===========================================================================
#    RESULTS
# =============================================================================
@dataclass
class ConvertResult:
    """Outcome of convert_file(): files, statistics and a preview for the GUI.

    Per-sweep arrays hold one value per selected sweep, or - after slim() -
    one value per ``sweeps_per_point`` sweeps (see reduce_series()).
    """
    info: ShrInfo
    plan: Plan
    outputs: list[str]
    frequency_hz: np.ndarray
    stat_max: np.ndarray
    stat_min: np.ndarray
    stat_power_mean: np.ndarray
    stat_db_mean: np.ndarray
    stat_std: np.ndarray
    stat_count: np.ndarray
    sweep_index: np.ndarray
    timestamp_ms: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    altitude: np.ndarray
    overflow: np.ndarray
    peak: np.ndarray
    peak_frequency_hz: np.ndarray
    power_mean: np.ndarray
    image: np.ndarray                  # (image_rows, image_cols), data units
    image_time_ms: np.ndarray          # mean time stamp per image row
    image_edges_hz: np.ndarray         # image_cols + 1 column edges
    seconds: float
    backend: str
    n_nonfinite: int
    log: list[str] = field(default_factory=list)
    csv_files: list[dict[str, Any]] = field(default_factory=list)
    sweeps_per_point: int = 1
    t0_ms: int = 0                     # time stamp of the first selected sweep (time-axis origin)

    def series(self) -> dict[str, np.ndarray]:
        """The per-sweep arrays as a dict (reduce_series() input)."""
        return {"sweep_index": self.sweep_index, "timestamp_ms": self.timestamp_ms,
                "latitude": self.latitude, "longitude": self.longitude, "altitude": self.altitude,
                "overflow": self.overflow, "peak": self.peak, "peak_bin": self._peak_bins(),
                "power_mean": self.power_mean}

    def _peak_bins(self) -> np.ndarray:
        return np.rint((np.asarray(self.peak_frequency_hz) - self.info.first_bin_hz)
                       / self.info.bin_hz).astype(np.int64)

    def slim(self, max_points: int) -> "ConvertResult":
        """A copy with per-sweep arrays thinned to <= max_points (GUI, batches)."""
        n = len(self.sweep_index)
        factor = max(1, math.ceil(n / max(1, int(max_points))))
        reduced = reduce_series(self.series(), factor, self.info.is_db)
        clone = ConvertResult(**{f.name: getattr(self, f.name) for f in fields(self)})
        clone.sweep_index = reduced["sweep_index"]
        clone.timestamp_ms = reduced["timestamp_ms"]
        clone.latitude, clone.longitude = reduced["latitude"], reduced["longitude"]
        clone.altitude, clone.overflow = reduced["altitude"], reduced["overflow"]
        clone.peak, clone.power_mean = reduced["peak"], reduced["power_mean"]
        clone.peak_frequency_hz = self.info.first_bin_hz + reduced["peak_bin"] * self.info.bin_hz
        clone.sweeps_per_point = self.sweeps_per_point * factor
        clone.log = list(self.log)
        clone.outputs = list(self.outputs)
        return clone

    def summary_lines(self) -> list[str]:
        unit = self.info.amplitude_unit
        finite = np.isfinite(self.peak)
        k = int(np.argmax(np.where(finite, self.peak, -np.inf))) if finite.any() else -1
        lines = [f"Converted in {self.seconds:.2f} s ({self.backend})" if self.seconds
                 else f"Converted ({self.backend})"]
        if k >= 0:
            lines.append(f"Highest level   : {self.peak[k]:.2f} {unit} at "
                         f"{self.peak_frequency_hz[k] / 1e6:.6f} MHz, sweep {int(self.sweep_index[k])}")
        n_overflow = int(np.count_nonzero(self.overflow))
        lines.append(f"ADC overflows   : {n_overflow} of {len(self.overflow)} "
                     + ("sweeps" if self.sweeps_per_point == 1 else
                        f"points ({self.sweeps_per_point} sweeps each)"))
        if self.n_nonfinite:
            lines.append(f"Non-finite      : {self.n_nonfinite} sample(s) skipped in the statistics")
        if len(self.csv_files) > 1:
            lines.append(f"CSV files       : {len(self.csv_files)} (split by time)")
        lines += [f"Output          : {p}" for p in self.outputs]
        return lines


def flush_memory() -> int:
    """Collect garbage, free CuPy pools, return freed heap to the OS.

    Returns the number of objects collected. malloc_trim (glibc) on Linux and
    EmptyWorkingSet (psapi) on Windows; both are harmless where unsupported.
    """
    n_collected = gc.collect()
    if "cupy" in sys.modules:
        try:
            cupy_module = sys.modules["cupy"]
            cupy_module.get_default_memory_pool().free_all_blocks()
            cupy_module.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:  # noqa: BLE001 - optional
            pass
    try:
        if sys.platform.startswith("linux"):
            ctypes.CDLL("libc.so.6").malloc_trim(0)          # give freed heap back to Linux
        elif os.name == "nt":
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.psapi.EmptyWorkingSet(handle)      # trim the Windows working set
    except Exception:  # noqa: BLE001 - best effort
        pass
    return n_collected


def memory_mb() -> float:
    """Resident memory of this process in MiB (psutil), or NaN without it."""
    try:
        import psutil
        return psutil.Process().memory_info().rss / 2 ** 20
    except Exception:  # noqa: BLE001 - optional dependency
        return float("nan")


def save_pickle(obj: Any, path: str | os.PathLike) -> Path:
    """Offload an object (e.g. a ConvertResult preview) to disk, protocol 5."""
    target = Path(path)
    part = target.with_name(target.name + ".part")
    with open(part, "wb") as handle:
        pickle.dump(obj, handle, protocol=5)
    os.replace(part, target)
    return target


def load_pickle(path: str | os.PathLike) -> Any:
    """Load an object written by save_pickle (only files you wrote yourself)."""
    with open(path, "rb") as handle:
        return pickle.load(handle)


# %% ===========================================================================
#    ORCHESTRATION
# =============================================================================
#: ProcessPoolExecutor's limit on Windows (WaitForMultipleObjects) [R7].
WINDOWS_MAX_WORKERS = 61
#: Below this many per-sweep rows the _sweeps.csv is formatted in-process.
SWEEPS_TABLE_PARALLEL_ROWS = 200_000
#: Rows per chunk of the _sweeps.csv (one task each when parallel).
SWEEPS_TABLE_CHUNK_ROWS = 50_000


def make_pool(workers: int) -> cf.ProcessPoolExecutor:
    """Worker processes, spawn context on every platform (never fork a GUI)."""
    count = max(1, int(workers))
    if os.name == "nt":
        count = min(count, WINDOWS_MAX_WORKERS)
    kwargs: dict[str, Any] = {"max_workers": count,
                              "mp_context": mp.get_context("spawn")}
    if sys.version_info >= (3, 11):
        kwargs["max_tasks_per_child"] = MAX_TASKS_PER_CHILD
    return cf.ProcessPoolExecutor(**kwargs)


def _run_ordered(function: Callable[[Any], Any], tasks: Sequence[Any], pool: cf.Executor | None,
                 max_in_flight: int, cancel: Callable[[], bool]) -> Iterator[Any]:
    """Results of ``function(task)`` in task order, at most ``max_in_flight`` pending.

    The bound is what keeps memory flat: a finished block waits in memory only
    until the blocks before it are written. Without a pool the tasks run here.
    """
    if pool is None:
        for task in tasks:
            if cancel():
                raise ConversionCancelled()
            yield function(task)
        return
    pending: deque[cf.Future] = deque()
    iterator = iter(tasks)
    try:
        for task in iterator:
            pending.append(pool.submit(function, task))
            if len(pending) >= max_in_flight:
                break
        while pending:
            result = pending.popleft().result()
            if cancel():
                raise ConversionCancelled()
            following = next(iterator, None)
            if following is not None:
                pending.append(pool.submit(function, following))
            yield result
    finally:
        for future in pending:
            future.cancel()


def output_stem(path: str | os.PathLike, opts: ConvertOptions, joined: bool = False) -> Path:
    """<output folder>/<input stem>, or <first file stem>_joined for a joined recording.

    The folder is created.
    """
    source = Path(path)
    folder = Path(opts.output_dir) if opts.output_dir else source.parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (source.stem + ("_joined" if joined else ""))


def disk_free_bytes(folder: str | os.PathLike) -> int:
    """Free bytes on the drive of ``folder`` (its nearest existing parent)."""
    target = Path(folder).resolve()
    while not target.exists() and target.parent != target:
        target = target.parent
    return int(shutil.disk_usage(target).free)


def _csv_header(opts: ConvertOptions, info: ShrInfo, plan: Plan, indices: np.ndarray) -> str:
    """Header line of the main CSV for the chosen layout."""
    d = DELIMITERS[opts.csv_delimiter]
    unit = info.amplitude_unit
    # With csv_decimate > 1 a row (or, transposed, a column) combines a group
    # of sweeps: it is named after the group's first sweep, and a
    # "sweeps_combined" column follows the time columns.
    combined = ["sweeps_combined"] if plan.csv_decimate > 1 else []
    if opts.csv_layout == "sweeps_as_rows":
        names = ["sweep_index", *opts.csv_time_columns, *combined, "latitude_deg", "longitude_deg",
                 "altitude_m", "adc_overflow"]
        names += [frequency_text(f) for f in info.frequencies(plan.col_start, plan.col_stop)]
    elif opts.csv_layout == "long":
        names = ["sweep_index", *opts.csv_time_columns, *combined, "frequency_hz", f"amplitude_{unit}"]
    else:
        first = np.asarray(indices)[plan.csv_group_starts()] if plan.csv_decimate > 1 else indices
        names = ["frequency_hz"] + [f"sweep_{int(i)}" for i in first]
    return d.join(names) + "\n"


def convert_file(path: str | os.PathLike | Sequence[str | os.PathLike], opts: ConvertOptions,
                 pool: cf.Executor | None = None,
                 progress: Callable[[float, str], None] | None = None,
                 cancel: Callable[[], bool] | None = None,
                 log: Callable[[str], None] | None = None) -> ConvertResult:
    """Convert one recording; see the module docstring for the outputs.

    ``path`` - one .shr file, or the files of ONE multi-file recording (read
    as a single recording, ordered by time; outputs named
    <first file>_joined). convert_files() makes such groups from a file
    list when opts.join_files is set.

    ``pool`` - an executor from make_pool() to reuse across files (None: one
    is made for this file when the plan asks for workers). ``progress(f, s)``
    gets the fraction done; ``cancel()`` is polled between blocks and makes
    the conversion raise ConversionCancelled, leaving no partial files.
    The returned result's per-sweep arrays are thinned to
    opts.time_series_max_points (ConvertResult.slim) so a batch of long
    captures never accumulates millions of rows per file in memory.
    """
    started = time.perf_counter()
    progress = progress or (lambda _f, _s: None)
    cancel = cancel or (lambda: False)
    messages: list[str] = []

    def note(text: str) -> None:
        messages.append(text)
        if log:
            log(text)

    # -- 1. header, plan and the output names --------------------------------------
    info = read_info(path)
    plan = make_plan(info, opts)
    for line in info.notes + plan.warnings:
        note(f"{info.name}: {line}")
    stem = output_stem(info.path, opts, joined=info.is_set)
    numfmt = number_format(opts.csv_number_format, opts.csv_decimals)
    delimiter = DELIMITERS[opts.csv_delimiter]
    layout = opts.csv_layout if opts.write_csv else "none"
    indices_all = plan.sweep_indices()

    # -- 2. disk space: refuse before writing anything that cannot fit -----------------
    if opts.write_csv and opts.check_disk_space:
        free = disk_free_bytes(stem.parent)
        if plan.est_csv_bytes > 0.95 * free:
            raise OSError(f"{info.name}: the CSV would need about {human_bytes(plan.est_csv_bytes)} but "
                          f"only {human_bytes(free)} is free on {stem.parent}. Choose another output "
                          f"folder, fixed decimals, a sweep step or a frequency range, or untick CSV.")

    # -- 3. time origin of the selection (elapsed_s, CSV time slices) -------------------
    with open_source(info.paths, info.file_sweeps) as shr:
        t0_ms = int(shr.timestamps_ms(int(indices_all[0]), int(indices_all[0]) + 1)[0])

    owned_pool = None
    if pool is None and not plan.in_process:
        owned_pool = pool = make_pool(plan.workers)
    use_pool = None if plan.in_process else pool
    parts: dict[Path, Path] = {}            # final path -> .part path (deleted unless published)
    sink: CsvSink | None = None
    table = SweepTable(plan.n_sweeps, opts.sweep_table_storage, opts.ram_budget_mb)
    if table.on_disk:
        note(f"{info.name}: per-sweep table ({human_bytes(plan.n_sweeps * SWEEP_ROW_BYTES)}) "
             f"memory-mapped in {table.folder}")
    try:
        if layout != "none":
            sink = CsvSink(stem, _csv_header(opts, info, plan, indices_all),
                           opts.csv_split_minutes if layout != "frequencies_as_rows" else 0.0, t0_ms, parts)
        # -- 4. accumulators of the merged results -------------------------------------------
        n_cols = plan.n_cols
        stat_max = np.full(n_cols, -np.inf)
        stat_min = np.full(n_cols, np.inf)
        stat_sum = np.zeros(n_cols)
        stat_sum2 = np.zeros(n_cols)
        stat_power = np.zeros(n_cols)
        stat_count = np.zeros(n_cols, dtype=np.int64)
        fill = {"max": -np.inf, "min": np.inf, "power_mean": 0.0}[opts.image_reduction]
        image_acc = np.full((plan.image_rows, plan.image_cols), fill)
        image_count = np.zeros(plan.image_rows, dtype=np.int64)
        n_nonfinite, backends = 0, set()

        # -- 5. the blocks, in parallel, merged in order -----------------------------------------
        tasks = [BlockTask(paths=tuple(info.paths), file_sweeps=tuple(info.file_sweeps), is_db=info.is_db,
                           pos0=p0, pos1=min(p0 + plan.block_sweeps, plan.n_sweeps),
                           sweep_start=plan.sweep_start, sweep_step=plan.sweep_step,
                           col_start=plan.col_start, col_stop=plan.col_stop,
                           first_bin_hz=info.first_bin_hz, bin_hz=info.bin_hz,
                           row_factor=plan.row_factor, col_factor=plan.col_factor,
                           image_reduction=opts.image_reduction, compute=opts.compute,
                           text_layout=layout if layout in ("sweeps_as_rows", "long") else "none",
                           numfmt=numfmt, delimiter=delimiter,
                           time_columns=tuple(opts.csv_time_columns), t0_ms=t0_ms,
                           csv_decimate=plan.csv_decimate, csv_decimate_detector=opts.csv_decimate_detector)
                 for p0 in range(0, plan.n_sweeps, plan.block_sweeps)]
        total_steps = len(tasks) + plan.transpose_passes
        done = 0
        for result in _run_ordered(process_block, tasks, use_pool, 2 * plan.workers, cancel):
            if sink is not None and result.text:
                sink.write(result.text, result.row_offsets, result.text_timestamp_ms)
            np.fmax(stat_max, result.stat_max, out=stat_max)      # fmax/fmin ignore NaN
            np.fmin(stat_min, result.stat_min, out=stat_min)
            stat_sum += result.stat_sum
            stat_sum2 += result.stat_sum2
            stat_power += result.stat_power
            stat_count += result.stat_count
            g0, g1 = result.image_group0, result.image_group0 + len(result.image_count)
            if opts.image_reduction == "max":
                np.fmax(image_acc[g0:g1], result.image_acc, out=image_acc[g0:g1])
            elif opts.image_reduction == "min":
                np.fmin(image_acc[g0:g1], result.image_acc, out=image_acc[g0:g1])
            else:
                image_acc[g0:g1] += result.image_acc
            image_count[g0:g1] += result.image_count
            table.put(result)
            n_nonfinite += result.n_nonfinite
            backends.add(result.backend)
            done += 1
            progress(done / total_steps, f"{info.name}: block {done}/{len(tasks)}")
        # -- 6. the transposed CSV (one row per frequency): column passes --------------------
        if layout == "frequencies_as_rows":
            if opts.csv_split_minutes:
                note(f"{info.name}: CSV split by time applies to sweeps_as_rows and long; "
                     f"frequencies_as_rows is written as one file")
            budget = opts.ram_budget_mb * 2 ** 20 // (1 if plan.in_process else 2 * plan.workers + 1)
            cols_per_pass = max(1, int(budget // max(plan.n_sweeps * BYTES_PER_SAMPLE[layout], 1)))
            column_tasks = [ColumnTask(paths=tuple(info.paths), file_sweeps=tuple(info.file_sweeps),
                                       n_sel=plan.n_sweeps,
                                       sweep_start=plan.sweep_start, sweep_step=plan.sweep_step,
                                       col0=c0, col1=min(c0 + cols_per_pass, plan.col_stop),
                                       first_bin_hz=info.first_bin_hz, bin_hz=info.bin_hz,
                                       numfmt=numfmt, delimiter=delimiter, is_db=info.is_db,
                                       csv_decimate=plan.csv_decimate,
                                       csv_decimate_detector=opts.csv_decimate_detector)
                            for c0 in range(plan.col_start, plan.col_stop, cols_per_pass)]
            for text in _run_ordered(process_columns, column_tasks, use_pool, 2 * plan.workers, cancel):
                sink.write_raw(text)
                done += 1
                progress(done / max(total_steps, done), f"{info.name}: column pass {done - len(tasks)}")
        if sink is not None:
            sink.close()

        # -- 7. final statistics from the merged sums (see STATISTICS) -------------------
        frequencies = info.frequencies(plan.col_start, plan.col_stop)
        with np.errstate(divide="ignore", invalid="ignore"):
            count = np.where(stat_count > 0, stat_count, np.nan)
            mean_power = stat_power / count
            power_mean = 10.0 * np.log10(mean_power) if info.is_db else np.sqrt(mean_power)
            db_mean = stat_sum / count
            # sample variance from the sums: (S2 - S1^2 / N) / (N - 1)
            variance = (stat_sum2 - stat_sum * stat_sum / count) / np.where(stat_count > 1, stat_count - 1, np.nan)
            std = np.sqrt(np.maximum(variance, 0.0))
            if opts.image_reduction == "power_mean":
                linear = image_acc / np.where(image_count > 0, image_count, np.nan)[:, None]
                image = 10.0 * np.log10(linear) if info.is_db else np.sqrt(linear)
            else:
                image = image_acc.copy()
        image[~np.isfinite(image)] = np.nan
        stat_max[~np.isfinite(stat_max)] = np.nan
        stat_min[~np.isfinite(stat_min)] = np.nan
        sweeps = table.columns
        steps_back = np.diff(np.asarray(sweeps["timestamp_ms"]))
        if steps_back.size and (steps_back < 0).any():
            note(f"{info.name}: time stamps go backwards {int((steps_back < 0).sum())} time(s) "
                 f"(largest step {int(-steps_back.min())} ms; PC clock adjusted?)")
        del steps_back
        group_of = np.arange(plan.n_sweeps) // plan.row_factor              # spectrogram row of each sweep
        image_time = (np.bincount(group_of, weights=np.asarray(sweeps["timestamp_ms"], dtype=float),
                                  minlength=plan.image_rows) / np.maximum(image_count, 1))
        # Pixel edges on an EVEN grid of col_factor bins (half a bin outside the
        # bin centres); a partial last pixel is drawn full width, at most one
        # pixel past the last bin. Even axes keep Veusz on its fast image path
        # (see vszh5_writer.regularize_rows).
        edges_bins = plan.col_start + np.arange(plan.image_cols + 1) * plan.col_factor
        image_edges = info.first_bin_hz + (edges_bins - 0.5) * info.bin_hz
        result = ConvertResult(
            info=info, plan=plan, outputs=[], frequency_hz=frequencies, stat_max=stat_max,
            stat_min=stat_min, stat_power_mean=power_mean, stat_db_mean=db_mean, stat_std=std,
            stat_count=stat_count, sweep_index=indices_all, timestamp_ms=sweeps["timestamp_ms"],
            latitude=sweeps["latitude"], longitude=sweeps["longitude"], altitude=sweeps["altitude"],
            overflow=sweeps["overflow"], peak=sweeps["peak"],
            peak_frequency_hz=info.first_bin_hz + sweeps["peak_bin"] * info.bin_hz,
            power_mean=sweeps["power_mean"], image=image, image_time_ms=image_time,
            image_edges_hz=image_edges, seconds=0.0, t0_ms=t0_ms,
            backend=" / ".join(sorted(backends)) or "NumPy (CPU)", n_nonfinite=n_nonfinite, log=messages,
            csv_files=[{k: (str(v) if k == "final" else v) for k, v in f.items()} for f in sink.files]
            if sink is not None else [])
        result.seconds = time.perf_counter() - started      # data pass (final value below)

        # -- 8. companion tables and the Veusz document --------------------------------------
        if opts.write_csv:
            for name, writer, wanted in (("_header.csv", _write_header_table, opts.csv_header_table),
                                         ("_sweeps.csv", _write_sweeps_table, opts.csv_sweeps_table),
                                         ("_statistics.csv", _write_statistics_table,
                                          opts.csv_statistics_table)):
                if not wanted:
                    continue
                final = stem.with_name(stem.name + name)
                parts[final] = _atomic_part(final)
                writer(parts[final], result, opts, use_pool, cancel)
        if opts.write_vszh5:
            progress(min(0.99, done / max(total_steps, 1)), f"{info.name}: writing .vszh5")
            vszh5_path = stem.with_name(stem.name + ".vszh5")
            write_vszh5(vszh5_path, result, opts)          # atomic inside VeuszWriter
            result.outputs.append(str(vszh5_path))
        # -- 9. publish every finished file (a locked one gets a new name) ---------------
        renamed: dict[str, str] = {}
        for final, part in parts.items():
            published = _publish(part, final, note)
            renamed[str(final)] = str(published)
            result.outputs.append(str(published))
        parts.clear()
        for entry in result.csv_files:
            entry["final"] = renamed.get(entry["final"], entry["final"])
        result.outputs.sort()
        if opts.write_vszh5 and opts.render:
            try:
                rendered = render_vszh5(stem.with_name(stem.name + ".vszh5"), result, opts)
                result.outputs += [str(p) for p in rendered]
            except Exception as exc:  # noqa: BLE001 - the data files are already written
                note(f"{info.name}: render failed: {type(exc).__name__}: {exc}")
        # -- 10. thin the per-sweep arrays (copies, never memory maps) and finish ---------
        result = result.slim(opts.time_series_max_points)
        result.seconds = time.perf_counter() - started
        progress(1.0, f"{info.name}: done in {result.seconds:.2f} s")
        return result
    finally:
        if sink is not None:
            sink.close()
        for part in parts.values():          # anything not published: failed or cancelled
            try:
                part.unlink()
            except OSError:
                pass
        table.close()
        if owned_pool is not None:
            owned_pool.shutdown(wait=True, cancel_futures=True)
        if opts.flush_after_file:
            flush_memory()


def _publish(part: Path, final: Path, note: Callable[[str], None]) -> Path:
    """Move a finished .part onto its final name; never lose it.

    On Windows a file open in another program (Excel locks an open CSV)
    cannot be replaced: the result is then kept as <stem>_<YYYYmmdd-HHMMSS>
    <suffix> beside it and the log says so.
    """
    try:
        os.replace(part, final)
        return final
    except PermissionError:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        alternative = final.with_name(f"{final.stem}_{stamp}{final.suffix}")
        os.replace(part, alternative)
        note(f"{final.name} is open in another program (locked); written as {alternative.name}")
        return alternative


def convert_files(paths: Sequence[str | os.PathLike], opts: ConvertOptions,
                  progress: Callable[[float, str], None] | None = None,
                  cancel: Callable[[], bool] | None = None,
                  log: Callable[[str], None] | None = None,
                  deliver: Callable[[Any], None] | None = None) -> list[ConvertResult]:
    """Convert several files with one shared worker pool.

    With opts.join_files the files of a multi-file recording are grouped and
    converted as one (convert_file() with a list of paths); the log names
    every group. ``deliver(result_or_error)`` gets each ConvertResult (or an Exception
    for a file that failed) as soon as it is done; the batch continues after
    a failed file and stops at the next block after cancel(). The workers
    are started once for the whole batch (spawning is the expensive part).
    """
    log = log or (lambda _s: None)
    cancel = cancel or (lambda: False)
    workers = opts.workers or default_workers()
    # join_files: group the files of each multi-file recording (by content,
    # shr_reader.group_recordings); every group is converted as one input.
    inputs: list[Any] = list(paths)
    if opts.join_files and len(paths) > 1:
        groups = group_recordings(paths)
        inputs = [g[0] if len(g) == 1 else g for g in groups]
        for group in groups:
            if len(group) > 1:
                log(f"joined as one recording: {', '.join(Path(p).name for p in group)}")
    paths = inputs
    pool = make_pool(workers) if workers > 1 and len(paths) else None
    results: list[ConvertResult] = []

    def label(item: Any) -> str:
        names = as_path_list(item)
        return Path(names[0]).name + (f" (+{len(names) - 1} file(s))" if len(names) > 1 else "")
    try:
        for number, path in enumerate(paths, start=1):
            if cancel():
                log("stopped by the user")
                break
            log(f"[{number}/{len(paths)}] {label(path)}")

            def file_progress(fraction: float, text: str, _n: int = number) -> None:
                if progress:
                    progress(((_n - 1) + fraction) / len(paths), text)
            try:
                result = convert_file(path, opts, pool=pool, progress=file_progress, cancel=cancel, log=log)
                results.append(result)
                for line in result.summary_lines():
                    log("  " + line)
                if deliver:
                    deliver(result)
            except ConversionCancelled:
                log(f"  {label(path)}: cancelled - no partial files kept")
                break
            except Exception as exc:  # noqa: BLE001 - next file
                log(f"  ERROR {label(path)}: {type(exc).__name__}: {exc}")
                if deliver:
                    deliver(exc)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
    return results


# %% ===========================================================================
#    COMPANION CSV TABLES
# =============================================================================
def _quote(text: Any, delimiter: str) -> str:
    """CSV quoting of one field (RFC 4180 style) when it needs it."""
    value = str(text)
    return '"' + value.replace('"', '""') + '"' if any(c in value for c in (delimiter, '"', "\n")) else value


def _write_header_table(target: Path, result: ConvertResult, opts: ConvertOptions,
                        pool: cf.Executor | None = None, cancel: Callable[[], bool] | None = None) -> None:
    """key, value, unit, description - every header field, derived values, CSV parts."""
    d = DELIMITERS[opts.csv_delimiter]
    info, plan = result.info, result.plan
    rows: list[tuple[Any, ...]] = [("key", "value", "unit", "description")]
    for name, unit, text in HEADER_FIELDS:
        value = info.header[name]
        rows.append((name, repr(value) if isinstance(value, float) else value, unit, text))
    rows.append(("sweep_count_readable", info.n_sweeps, "", "complete sweeps read (see notes)"))
    f_sel = result.frequency_hz
    ts = np.asarray(result.timestamp_ms)
    rows += [
        ("title", info.title, "", "title (decoded; see the manual)"),
        ("source_file", info.path, "", "input file"),
        ("file_size", info.file_size, "byte", "input size"),
        ("sweeps_selected", plan.n_sweeps, "", f"start {plan.sweep_start}, step {plan.sweep_step}"),
        ("bins_selected", plan.n_cols, "bin", f"bins {plan.col_start}..{plan.col_stop - 1}"),
        ("frequency_first_hz", repr(float(f_sel[0])), "Hz", "first selected bin"),
        ("frequency_last_hz", repr(float(f_sel[-1])), "Hz", "last selected bin"),
        ("amplitude_unit", info.amplitude_unit, "", "unit of every amplitude"),
        ("time_first_utc", utc_iso(ts[:1])[0] if ts.size else "", "", "first selected sweep"),
        ("time_last_utc", utc_iso(ts[-1:])[0] if ts.size else "", "", "last selected sweep"),
        ("csv_layout", opts.csv_layout, "", CSV_LAYOUTS[opts.csv_layout]),
        ("csv_number_format", number_format(opts.csv_number_format, opts.csv_decimals), "", "printf format"),
        ("csv_split_minutes", opts.csv_split_minutes, "min", "0 = one file"),
        ("csv_decimate", plan.csv_decimate, "sweep", "selected sweeps combined per CSV row (1 = every sweep)"),
        ("csv_decimate_detector", opts.csv_decimate_detector if plan.csv_decimate > 1 else "",
         "", CSV_DECIMATE_DETECTORS[opts.csv_decimate_detector] if plan.csv_decimate > 1 else "not used"),
    ]
    for number, (file_path, count) in enumerate(zip(info.paths, info.file_sweeps), start=1):
        if info.is_set:
            rows.append((f"source_file_{number:03d}", file_path, "", f"{count} sweeps (joined recording)"))
    for number, entry in enumerate(result.csv_files, start=1):
        span = (f"{utc_iso(np.array([entry['first_ms']]))[0]} to {utc_iso(np.array([entry['last_ms']]))[0]}, "
                f"{entry['sweeps']} sweeps")
        rows.append((f"csv_file_{number:03d}", Path(entry["final"]).name, "", span))
    rows += [
        ("converter", f"{PROGRAM_NAME} {__version__}", "", "this program"),
        ("shr_reader", SHR_READER_VERSION, "", "reader version (shr_reader.py)"),
        ("vszh5_writer", vszh5_writer.__version__, "", "Veusz writer version"),
        ("converted_utc", _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "", ""),
    ]
    rows += [("note", n, "", "") for n in info.notes]
    with open(target, "w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write(d.join(_quote(v, d) for v in row) + "\n")


def format_sweep_rows(chunk: dict[str, Any]) -> bytes:
    """Rows of the _sweeps.csv for one chunk (top-level: runs in workers).

    ``chunk`` holds the per-sweep arrays of the chunk plus "delimiter",
    "time_columns" and "t0_ms".
    """
    d = chunk["delimiter"]
    times = _time_strings(chunk["time_columns"], chunk["timestamp_ms"], chunk["t0_ms"])
    out = []
    for k in range(len(chunk["sweep_index"])):
        row = [str(int(chunk["sweep_index"][k]))] + [c[k] for c in times] + [
            repr(float(chunk["latitude"][k])), repr(float(chunk["longitude"][k])),
            repr(float(chunk["altitude"][k])), "1" if chunk["overflow"][k] else "0",
            "%.9g" % chunk["peak"][k], frequency_text(chunk["peak_frequency_hz"][k]),
            "%.9g" % chunk["power_mean"][k]]
        out.append(d.join(row) + "\n")
    return "".join(out).encode("ascii")


def _write_sweeps_table(target: Path, result: ConvertResult, opts: ConvertOptions,
                        pool: cf.Executor | None = None, cancel: Callable[[], bool] | None = None) -> None:
    """One row per selected sweep: time, GPS, overflow, peak, power mean.

    Formatted in chunks of SWEEPS_TABLE_CHUNK_ROWS; with a pool and more than
    SWEEPS_TABLE_PARALLEL_ROWS sweeps the chunks are formatted in parallel
    (a 3-hour capture can have millions of rows).
    """
    d = DELIMITERS[opts.csv_delimiter]
    unit = result.info.amplitude_unit
    mean_name = f"power_mean_{unit}" if result.info.is_db else f"rms_{unit}"
    names = ["sweep_index", *opts.csv_time_columns, "latitude_deg", "longitude_deg", "altitude_m",
             "adc_overflow", f"peak_{unit}", "peak_frequency_hz", mean_name]
    n = len(result.sweep_index)
    t0 = int(result.timestamp_ms[0]) if n else 0
    chunks = [{"sweep_index": np.asarray(result.sweep_index[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "timestamp_ms": np.asarray(result.timestamp_ms[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "latitude": np.asarray(result.latitude[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "longitude": np.asarray(result.longitude[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "altitude": np.asarray(result.altitude[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "overflow": np.asarray(result.overflow[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "peak": np.asarray(result.peak[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "peak_frequency_hz": np.asarray(result.peak_frequency_hz[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "power_mean": np.asarray(result.power_mean[s:s + SWEEPS_TABLE_CHUNK_ROWS]),
               "delimiter": d, "time_columns": tuple(opts.csv_time_columns), "t0_ms": t0}
              for s in range(0, n, SWEEPS_TABLE_CHUNK_ROWS)]
    use = pool if (pool is not None and n > SWEEPS_TABLE_PARALLEL_ROWS) else None
    with open(target, "wb") as handle:
        handle.write((d.join(names) + "\n").encode("ascii"))
        for text in _run_ordered(format_sweep_rows, chunks, use, 2 * max(1, opts.workers or default_workers()),
                                 cancel or (lambda: False)):
            handle.write(text)


def _write_statistics_table(target: Path, result: ConvertResult, opts: ConvertOptions,
                            pool: cf.Executor | None = None, cancel: Callable[[], bool] | None = None) -> None:
    """One row per selected bin: max, min, power mean, dB mean, std, count."""
    d = DELIMITERS[opts.csv_delimiter]
    unit = result.info.amplitude_unit
    if result.info.is_db:
        names = ["frequency_hz", f"max_hold_{unit}", f"min_hold_{unit}", f"power_mean_{unit}",
                 f"db_mean_{unit}", "std_dB", "count"]
    else:
        names = ["frequency_hz", f"max_hold_{unit}", f"min_hold_{unit}", f"rms_{unit}",
                 f"mean_{unit}", f"std_{unit}", "count"]
    columns = np.column_stack([result.stat_max, result.stat_min, result.stat_power_mean,
                               result.stat_db_mean, result.stat_std])
    row_format = d.join(["%.9g"] * 5)
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(d.join(names) + "\n")
        for j, frequency in enumerate(result.frequency_hz):
            handle.write(frequency_text(frequency) + d + (row_format % tuple(columns[j]))
                         + d + str(int(result.stat_count[j])) + "\n")


# %% ===========================================================================
#    VEUSZ DOCUMENT
# =============================================================================
#: Page titles (also the PDF bookmarks), by Veusz page name.
PAGE_TITLES = {
    "spectrogram": "Spectrogram",
    "statistics": "Spectrum statistics",
    "selected_sweeps": "Selected sweeps",
    "level_vs_time": "Level versus time",
    "gps_track": "GPS track",
    "file_header": "File header",
}


def resolve_time_axis(opts: ConvertOptions, result: ConvertResult) -> str:
    """The time axis actually used ('auto' resolved by the capture length)."""
    if opts.time_axis != "auto":
        return opts.time_axis
    if len(result.timestamp_ms) < 2:
        return "index"
    span_s = (float(np.max(result.timestamp_ms)) - float(np.min(result.timestamp_ms))) / 1000.0
    return "utc" if span_s >= 60.0 else "elapsed"


def _time_values(axis: str, epoch_ms: np.ndarray, sweep_index: np.ndarray, t0_ms: float) -> np.ndarray:
    """Time stamps on the chosen axis: Veusz date seconds, seconds or index."""
    seconds = np.asarray(epoch_ms, dtype=float) / 1000.0
    if axis == "utc":
        return epoch_to_veusz(seconds)
    if axis == "local":
        return epoch_to_veusz(seconds, local_utc_offsets(seconds))
    if axis == "elapsed":
        return (np.asarray(epoch_ms, dtype=float) - t0_ms) / 1000.0
    return np.asarray(sweep_index, dtype=float)


def _parse_selected(spec: str, result: ConvertResult) -> list[int]:
    """'first,last,peak,12,-3' -> positions in the selection (deduplicated, in order)."""
    n = result.sweep_index.size
    positions: list[int] = []
    for token in (t.strip().lower() for t in spec.split(",")):
        if not token or n == 0:
            continue
        if token == "first":
            pos = 0
        elif token == "last":
            pos = n - 1
        elif token == "peak":
            finite = np.isfinite(result.peak)
            if not finite.any():
                continue
            pos = int(np.argmax(np.where(finite, result.peak, -np.inf)))
        else:
            try:
                index = int(token)
            except ValueError:
                continue
            if index < 0:
                index += result.info.n_sweeps
            hits = np.flatnonzero(result.sweep_index == index)
            if not hits.size:
                continue
            pos = int(hits[0])
        if pos not in positions:
            positions.append(pos)
    return positions


def _reduce_trace(values: np.ndarray, factor: int, method: str, is_db: bool) -> np.ndarray:
    """Shorten a statistics trace for plotting (max, min or power mean)."""
    if factor <= 1:
        return values
    row = values[None, :]
    if method == "power_mean":
        linear = np.power(10.0, row / 10.0) if is_db else row * row
        mean = block_reduce(linear, 1, factor, "mean")[0]
        return 10.0 * np.log10(mean) if is_db else np.sqrt(mean)
    return block_reduce(row, 1, factor, method)[0]


def write_vszh5(target: str | os.PathLike, result: ConvertResult, opts: ConvertOptions) -> Path:
    """The Veusz document of one converted file (atomic write)."""
    info, plan = result.info, result.plan
    unit = info.amplitude_unit
    funit, fscale = frequency_unit(result.frequency_hz[-1] - result.frequency_hz[0], result.frequency_hz[-1])
    axis = resolve_time_axis(opts, result)
    t0 = float(result.t0_ms)                     # elapsed-time origin: the first selected sweep
    time_label = {"utc": "Time (UTC)", "local": "Local time", "elapsed": "Elapsed time (s)",
                  "index": "Sweep index"}[axis]
    xmode = "datetime" if axis in ("utc", "local") else "numeric"
    doc = VszDoc(generator=f"{PROGRAM_NAME} {__version__} (vszh5_writer {vszh5_writer.__version__}, "
                           f"shr_reader {SHR_READER_VERSION})")
    doc.comment(f"Source: {info.path}")
    name = short_name(info.name)          # page titles must fit the page width
    pages: list[tuple[str, str]] = []
    with VeuszWriter(target, compress=opts.vszh5_compress,
                     writer_tag=f"{PROGRAM_NAME} {__version__}") as writer:
        # -- statistics ----------------------------------------------------------------
        factor = max(1, math.ceil(result.frequency_hz.size / opts.stats_max_points))
        freq_plot = result.frequency_hz
        if factor > 1:   # centre of each block of bins
            freq_plot = block_reduce(result.frequency_hz[None, :], 1, factor, "mean")[0]
        writer.dataset_1d("frequency_" + funit, freq_plot / fscale, tags=("statistics",))
        writer.dataset_1d("max_hold", _reduce_trace(result.stat_max, factor, "max", info.is_db), tags=("statistics",))
        writer.dataset_1d("min_hold", _reduce_trace(result.stat_min, factor, "min", info.is_db), tags=("statistics",))
        writer.dataset_1d("power_mean", _reduce_trace(result.stat_power_mean, factor, "power_mean", info.is_db),
                          tags=("statistics",))
        writer.dataset_1d("db_mean" if info.is_db else "mean",
                          block_reduce(result.stat_db_mean[None, :], 1, factor, "mean")[0], tags=("statistics",))
        # -- per sweep -------------------------------------------------------------------
        # A 3-hour capture can hold millions of sweeps; Veusz draws a few
        # hundred thousand points comfortably, so the series are thinned to
        # time_series_max_points with reduce_series() (peak hold for the
        # peak, power mean for the band level, frequency of the strongest
        # sweep, any overflow, first GPS fix of each group).
        series_factor = max(1, math.ceil(len(result.sweep_index) / opts.time_series_max_points))
        series = reduce_series(result.series(), series_factor, info.is_db)
        series_peak_frequency = info.first_bin_hz + series["peak_bin"] * info.bin_hz
        times = _time_values(axis, series["timestamp_ms"], series["sweep_index"], t0)
        if xmode == "datetime":
            writer.dataset_date("sweep_time", times, tags=("sweeps",))
        else:
            writer.dataset_1d("sweep_time", times, tags=("sweeps",))
        writer.dataset_1d("sweep_index", series["sweep_index"].astype(float), tags=("sweeps",))
        writer.dataset_1d("sweep_peak", series["peak"], tags=("sweeps",))
        writer.dataset_1d("sweep_peak_frequency_" + funit, series_peak_frequency / fscale, tags=("sweeps",))
        writer.dataset_1d("sweep_power_mean", series["power_mean"], tags=("sweeps",))
        writer.dataset_1d("adc_overflow", series["overflow"].astype(float), tags=("sweeps",))
        writer.dataset_1d("latitude", series["latitude"], tags=("gps",))
        writer.dataset_1d("longitude", series["longitude"], tags=("gps",))
        writer.dataset_1d("altitude", series["altitude"], tags=("gps",))
        per_point = (f", {series_factor} sweeps per point (peak hold, power mean)"
                     if series_factor > 1 else "")
        # -- spectrogram -----------------------------------------------------------------------
        if opts.page_spectrogram:
            row_times = _time_values(axis, result.image_time_ms,
                                     result.sweep_index[::plan.row_factor][: result.image.shape[0]]
                                     + (plan.row_factor - 1) * plan.sweep_step / 2.0, t0)
            # Rows onto an even time grid: pauses in the recording become blank
            # (NaN) rows, and Veusz draws the image through its fast path.
            grid, (y_start, y_stop), how = vszh5_writer.regularize_rows(result.image, row_times)
            if how != "regular":
                doc.comment({"gaps": "spectrogram: pauses in the recording left blank (NaN rows)",
                             "even": "spectrogram rows spread evenly (time stamps repeat or crowd)"}[how])
            writer.dataset_2d("spectrogram", grid,
                              xrange=(result.image_edges_hz[0] / fscale, result.image_edges_hz[-1] / fscale),
                              yrange=(y_start, y_stop), tags=("spectrogram",))
            zmin, zmax = _z_limits(opts, result)
            per_pixel = (f"{plan.row_factor} sweep{'s' if plan.row_factor > 1 else ''} x "
                         f"{plan.col_factor} bin{'s' if plan.col_factor > 1 else ''} per pixel, "
                         f"{IMAGE_REDUCTIONS[opts.image_reduction].split(' (')[0]}"
                         + {"regular": "", "gaps": "; pauses blank", "even": "; rows evenly spaced"}[how])
            image_page(doc, "spectrogram", "spectrogram", title=f"{name} - spectrogram ({per_pixel})",
                       xlabel=f"Frequency ({funit})", ylabel=time_label, zlabel=f"Level ({unit})",
                       colormap=opts.colormap, zmin=zmin, zmax=zmax,
                       ymode="datetime" if xmode == "datetime" else "numeric",
                       left_margin="3.4cm" if xmode == "datetime" else "")
            pages.append(("spectrogram", PAGE_TITLES["spectrogram"]))
        # -- statistics page ---------------------------------------------------------------
        if opts.page_statistics:
            fx = "frequency_" + funit
            traces = [Trace(fx, "max_hold", "max hold", colour="#d62728"),
                      Trace(fx, "power_mean", "power mean" if info.is_db else "RMS", colour="#1f77b4"),
                      Trace(fx, "db_mean" if info.is_db else "mean",
                            "dB mean" if info.is_db else "mean", colour="#9467bd", style="dashed"),
                      Trace(fx, "min_hold", "min hold", colour="#2ca02c")]
            reduced = f", {factor} bins per point" if factor > 1 else ""
            detector = f", {info.detector} detector" if info.detector else ""
            xy_page(doc, "statistics", traces,
                    title=f"{name} - statistics over {plan.n_sweeps} sweeps{detector}{reduced}",
                    xlabel=f"Frequency ({funit})", ylabel=f"Level ({unit})", key=True, x_autorange="exact")
            pages.append(("statistics", PAGE_TITLES["statistics"]))
        # -- selected sweeps -------------------------------------------------------------------
        positions = _parse_selected(opts.selected_sweeps, result) if opts.page_selected_sweeps else []
        if positions:
            traces = []
            with open_source(info.paths, info.file_sweeps) as shr:
                for k, pos in enumerate(positions):
                    index = int(result.sweep_index[pos])
                    values = shr.read(index, index + 1, 1, plan.col_start, plan.col_stop).amplitudes[0].astype(float)
                    sweep_factor = max(1, math.ceil(values.size / opts.stats_max_points))
                    dataset = f"sweep_{index}"
                    writer.dataset_1d(dataset, _reduce_trace(values, sweep_factor, "max", info.is_db),
                                      tags=("selected",))
                    if sweep_factor != factor:      # own frequency axis for this length
                        writer.dataset_1d(f"{dataset}_frequency_{funit}",
                                          block_reduce(result.frequency_hz[None, :], 1, sweep_factor,
                                                       "mean")[0] / fscale, tags=("selected",))
                        x_name = f"{dataset}_frequency_{funit}"
                    else:
                        x_name = "frequency_" + funit
                    stamp = utc_iso(np.array([result.timestamp_ms[pos]]))[0]
                    traces.append(Trace(x_name, dataset, f"sweep {index} ({stamp})"))
            xy_page(doc, "selected_sweeps", traces, title=f"{name} - selected sweeps",
                    xlabel=f"Frequency ({funit})", ylabel=f"Level ({unit})", key=True, x_autorange="exact")
            pages.append(("selected_sweeps", PAGE_TITLES["selected_sweeps"]))
        # -- level versus time -------------------------------------------------------------------
        if opts.page_level_vs_time:
            mean_label = "power mean over the band" if info.is_db else "RMS over the band"
            level_span = 1.0 if info.is_db else 0.05 * max(1e-12, float(np.nanmax(np.abs(series["peak"]))))
            pk_min, pk_max = _y_limits(series["peak"], level_span)
            pm_min, pm_max = _y_limits(series["power_mean"], level_span)
            fq_min, fq_max = _y_limits(series_peak_frequency / fscale, 10.0 * info.bin_hz / fscale)
            panels = [Panel([Trace("sweep_time", "sweep_peak", "peak", marker="circle", marker_size="1.5pt")],
                            xlabel=time_label, ylabel=f"Peak ({unit})", title="Peak level per sweep",
                            xmode=xmode, x_autorange="exact", ymin=pk_min, ymax=pk_max),
                      Panel([Trace("sweep_time", "sweep_power_mean", mean_label, colour="#1f77b4")],
                            xlabel=time_label, ylabel=f"Level ({unit})", title=mean_label.capitalize(),
                            xmode=xmode, x_autorange="exact", ymin=pm_min, ymax=pm_max),
                      Panel([Trace("sweep_time", "sweep_peak_frequency_" + funit, "peak frequency",
                                   colour="#2ca02c", line=False, marker="circle", marker_size="1.5pt")],
                            xlabel=time_label, ylabel=f"Frequency ({funit})", title="Frequency of the peak",
                            xmode=xmode, x_autorange="exact", ymin=fq_min, ymax=fq_max)]
            if series["overflow"].any():
                panels.append(Panel([Trace("sweep_time", "adc_overflow", "ADC overflow", colour="#d62728")],
                                    xlabel=time_label, ylabel="overflow (0/1)", title="ADC overflow flag",
                                    xmode=xmode, x_autorange="exact", ymin=-0.1, ymax=1.1))
            grid_page(doc, "level_vs_time", panels, title=f"{name} - level versus time{per_point}", columns=1,
                      height=f"{max(18, 7 * len(panels))}cm")
            pages.append(("level_vs_time", PAGE_TITLES["level_vs_time"]))
        # -- GPS track -------------------------------------------------------------------------------
        has_gps = bool(np.any(series["latitude"] != 0) or np.any(series["longitude"] != 0))
        if opts.page_gps and has_gps:
            xy_page(doc, "gps_track", [Trace("longitude", "latitude", "position", line=False, marker="circle",
                                             marker_size="2pt")],
                    title=f"{name} - GPS track ({len(result.sweep_index)} sweeps{per_point})",
                    xlabel="Longitude (deg)",
                    ylabel="Latitude (deg)", key=False)
            pages.append(("gps_track", PAGE_TITLES["gps_track"]))
        # -- header -------------------------------------------------------------------------------------
        keys = [n for n, _u, _t in HEADER_FIELDS]
        values = [str(info.header[k]) for k in keys]
        writer.dataset_text("shr_header_key", keys + ["title", "source_file", "converter", "reader"])
        writer.dataset_text("shr_header_value", values + [info.title, " | ".join(info.paths) or info.path,
                                                          f"{PROGRAM_NAME} {__version__}",
                                                          f"shr_reader {SHR_READER_VERSION}"])
        if opts.page_header:
            lines = info.summary_lines() + [""] + result.plan.lines() + [""] + result.summary_lines()[:3]
            lines += ["", f"{PROGRAM_NAME} {__version__}, shr_reader {SHR_READER_VERSION}, "
                      f"vszh5_writer {vszh5_writer.__version__}"]
            lines = wrap_report_lines(lines, HEADER_PAGE_COLUMNS)    # long notes stay on the page
            for page in text_page(doc, "file_header", f"{name} - file header and conversion", lines,
                                  lines_per_page=36):
                pages.append((page, PAGE_TITLES["file_header"] if page == "file_header" else page))
        writer.dataset_text("page_title", [title for _page, title in pages])
        written = writer.finish(doc.text())
    return written


#: Characters per line of the header page (monospaced text at the page width).
HEADER_PAGE_COLUMNS = 110


def wrap_report_lines(lines: Sequence[str], width: int = HEADER_PAGE_COLUMNS) -> list[str]:
    """Wrap "Label           : value" lines longer than ``width``.

    Continuation lines are indented to the value column, so a long note
    stays readable on the header page instead of running off the edge.
    """
    import textwrap
    out: list[str] = []
    for line in lines:
        if len(line) <= width:
            out.append(line)
            continue
        colon = line.find(" : ")
        indent = " " * (colon + 3 if 0 < colon < 24 else 4)
        out.extend(textwrap.wrap(line, width=width, subsequent_indent=indent, break_on_hyphens=False)
                   or [line])
    return out


def _y_limits(values: np.ndarray, minimum_half_span: float) -> tuple[Any, Any]:
    """Axis limits centred on a (nearly) constant series, else Veusz Auto.

    Veusz pads a flat series to the next major ticks, which can leave the
    trace on the edge of a much wider range (e.g. 2999.9995 MHz drawn on a
    3000-3300 MHz axis).
    """
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return "Auto", "Auto"
    low, high = float(finite.min()), float(finite.max())
    if high - low >= 2.0 * minimum_half_span:
        return "Auto", "Auto"
    centre = 0.5 * (low + high)
    return centre - minimum_half_span, centre + minimum_half_span


def _z_limits(opts: ConvertOptions, result: ConvertResult) -> tuple[Any, Any]:
    """Colour-scale limits of the spectrogram for opts.z_mode."""
    if opts.z_mode == "manual":
        return float(opts.z_min), float(opts.z_max)
    if opts.z_mode == "reference":
        reference = float(result.info.header["ref_level"])
        return reference - 10.0 * float(result.info.header["div"] or 10.0), reference
    if opts.z_mode == "data":
        finite = result.image[np.isfinite(result.image)]
        if finite.size:
            low, high = float(np.percentile(finite, 1.0)), float(finite.max())
            if high > low:
                return low, high
    return "Auto", "Auto"


def render_vszh5(path: str | os.PathLike, result: ConvertResult, opts: ConvertOptions) -> list[Path]:
    """PDF (with a bookmark tree) and PNG through Veusz (vszh5_writer.render_pages)."""
    title = result.info.name

    def outline(page_names: list[str]) -> list[tuple]:
        children = [(PAGE_TITLES.get(p, p.replace("_", " ")), i) for i, p in enumerate(page_names)]
        return [(f"{title}", 0, children)]

    return render_pages(path, png_pages=opts.render_png, dpi=opts.render_dpi, veusz_exe=opts.veusz_exe,
                        bookmarks=outline, png_background="white",
                        pdf_info={"title": f"{title} - SHR Converter", "author": __author__,
                                  "subject": f"Signal Hound SHR file {title}",
                                  "keywords": "Signal Hound, Spike, SHR, spectrogram"})


def render_existing(path: str | os.PathLike, opts: ConvertOptions) -> list[Path]:
    """Render a .vszh5 this program wrote earlier (bookmarks from its page titles)."""
    source = Path(path)
    titles = vszh5_writer.read_text_dataset(source, "page_title") or []

    def outline(page_names: list[str]) -> list[tuple]:
        children = [(titles[i] if i < len(titles) else p.replace("_", " "), i)
                    for i, p in enumerate(page_names)]
        return [(source.stem, 0, children)]

    return render_pages(source, png_pages=opts.render_png, dpi=opts.render_dpi, veusz_exe=opts.veusz_exe,
                        bookmarks=outline, png_background="white",
                        pdf_info={"title": f"{source.stem} - SHR Converter", "author": __author__})


# %% ===========================================================================
#    SYNTHETIC SHR FILES (tests, demonstrations)
# =============================================================================
def write_synthetic_shr(path: str | os.PathLike, n_sweeps: int = 50, n_bins: int = 1001,
                        first_bin_hz: float = 1.0e9, bin_hz: float = 10_000.0, scale: str = "dBm",
                        start_ms: int = 1_761_600_000_000, step_ms: int = 100, title: str = "",
                        gps: bool = False, overflow_every: int = 0, seed: int = 1,
                        truncate_bytes: int = 0, header_count: int | None = None, detector: int = 1,
                        version: int = 2, quantise_db: float = 0.0) -> Path:
    """Write an SHR file with shr_reader's layout (the SDK struct [R1]).

    Noise around -90 dBm (or 0.02 mV) with a carrier at bin n_bins // 3
    drifting by one bin per 10 sweeps and a burst every 7th sweep at bin
    2 * n_bins // 3. ``truncate_bytes`` cuts the end off (a crashed
    recording); ``header_count`` overrides the stated sweep count;
    ``detector`` is the header code (2 = what Spike 4.0 writes for the Max
    detector); ``quantise_db`` > 0 puts dB values on that grid plus
    0.00824 dB, like the SM200C sample. Sweeps are generated in chunks, so a
    large file never needs its full size in RAM.
    """
    rng = np.random.default_rng(seed)
    is_db = scale == "dBm"
    header = ShrHeader(
        version=int(version), sweep_count=n_sweeps if header_count is None else int(header_count),
        sweep_length=n_bins, first_bin_freq_hz=first_bin_hz, bin_size_hz=bin_hz,
        title_raw=ShrHeader.encode_title(title), center_freq_hz=first_bin_hz + bin_hz * (n_bins - 1) / 2.0,
        span_hz=bin_hz * (n_bins - 1), rbw_hz=3 * bin_hz, vbw_hz=3 * bin_hz,
        ref_level=-20.0 if is_db else 100.0, ref_scale=0 if is_db else 1, div=10.0, window=0,
        attenuation=0, gain=0, detector=int(detector), processing_units=2, window_bandwidth=3.0,
        decimation_type=1, decimation_detector=0, decimation_count=1, decimation_time_ms=1000,
        channelize_enabled=0, channel_output_units=0)
    record = sweep_record_dtype(n_bins)
    chunk = max(1, 4_000_000 // max(n_bins, 1))          # sweeps generated at once
    with open(path, "wb") as handle:
        handle.write(header.to_bytes())
        for k0 in range(0, n_sweeps, chunk):
            k = np.arange(k0, min(k0 + chunk, n_sweeps), dtype=np.int64)
            records = np.zeros(k.size, dtype=record)
            if is_db:
                amps = rng.normal(-90.0, 2.0, (k.size, n_bins)).astype(np.float32)
                amps[np.arange(k.size), np.minimum(n_bins - 1, n_bins // 3 + k // 10)] = -40.0
                amps[k % 7 == 0, 2 * n_bins // 3] = -30.0
                if quantise_db > 0:
                    amps = (np.round(amps.astype(np.float64) / quantise_db) * quantise_db + 0.00824).astype(np.float32)
            else:
                amps = np.abs(rng.normal(0.02, 0.005, (k.size, n_bins))).astype(np.float32)
                amps[:, n_bins // 3] = 5.0
            records["amplitude"] = amps
            records["timestamp_ms"] = start_ms + k * step_ms
            if gps:
                records["latitude"] = 38.4331 + 1e-5 * k
                records["longitude"] = -79.8398 - 1e-5 * k
                records["altitude_m"] = 807.0
            if overflow_every:
                records["adc_overflow"] = (k % overflow_every == 0)
            records.tofile(handle)
        if truncate_bytes:
            handle.truncate(handle.tell() - truncate_bytes)
    return Path(path)


def split_recording(source: str | os.PathLike, targets: Sequence[str | os.PathLike],
                    sizes: Sequence[int]) -> list[Path]:
    """Split one .shr file into consecutive files of ``sizes`` sweeps (tests).

    Each part gets the source header with its own sweep count - what a
    multi-file Spike recording looks like when it is read back.
    """
    out = []
    with ShrFile(source) as whole:
        first = 0
        for target, size in zip(targets, sizes):
            block = whole.read(first, first + int(size))
            out.append(shr_reader.write_shr(target, block.amplitudes, block.timestamp_ms, header=whole.header,
                                            latitude=block.latitude, longitude=block.longitude,
                                            altitude_m=block.altitude_m, adc_overflow=block.adc_overflow))
            first += int(size)
    return out


# %% ===========================================================================
#    SELF-TEST
# =============================================================================
def self_test(report: Callable[[str], None] = print, workers: int = 2,
              real_file: str | os.PathLike | None = None) -> bool:
    """Check reading, every CSV layout, statistics, salvage, joins, decimation, parallel and GPU paths.

    Every amplitude written to CSV is compared with what shr_reader reads
    directly (lossless format: exactly). Returns True when all checks pass.
    """
    import csv
    import h5py
    global IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS, STATS_CHUNK_SAMPLES
    limits = (IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS)
    passed, failed = 0, 0

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed, failed
        if condition:
            passed += 1
            report(f"PASS {name}")
        else:
            failed += 1
            report(f"FAIL {name} {detail}")

    def direct(path: Path) -> np.ndarray:
        """Every amplitude of a file, read directly with shr_reader (the reference)."""
        with open_source(path) as shr:
            return shr.read_amplitudes()

    def read_csv(path: Path) -> list[list[str]]:
        return list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))

    with tempfile.TemporaryDirectory(prefix="shr_selftest_") as folder:
        root = Path(folder)
        source = write_synthetic_shr(root / "synthetic.shr", n_sweeps=60, n_bins=777, gps=True,
                                     overflow_every=13, title="GBO test – Ω")
        info = read_info(source)
        data = direct(source)
        check("title decoded (UTF-16LE)", info.title == "GBO test – Ω", repr(info.title))
        check("frequency axis = first + i*bin", np.allclose(info.frequencies()[[0, -1]],
                                                            [1.0e9, 1.0e9 + 776 * 1e4]))
        for layout in CSV_LAYOUTS:
            for n_workers in (1, workers):
                out = root / f"{layout}_{n_workers}"
                opts = ConvertOptions(output_dir=str(out), csv_layout=layout, workers=n_workers,
                                      write_vszh5=(layout == "sweeps_as_rows"), ram_budget_mb=16,
                                      csv_time_columns=("epoch_ms", "utc_iso", "elapsed_s"),
                                      image_max_rows=17, image_max_columns=100)
                # Force several blocks (7 sweeps, not a multiple of the 4
                # sweeps per spectrogram row) and, for n_workers > 1, real
                # worker processes even for this small file.
                IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = (0 if n_workers > 1 else limits[0]), 7
                try:
                    result = convert_file(source, opts)
                finally:
                    IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = limits
                rows = read_csv(out / "synthetic.csv")
                if layout == "sweeps_as_rows":
                    values = np.array([r[8:] for r in rows[1:]], dtype=np.float32)   # 1 + 3 time + 4
                    freqs = np.array(rows[0][8:], dtype=float)
                elif layout == "frequencies_as_rows":
                    values = np.array([r[1:] for r in rows[1:]], dtype=np.float32).T
                    freqs = np.array([r[0] for r in rows[1:]], dtype=float)
                else:
                    values = np.array([r[-1] for r in rows[1:]], dtype=np.float32).reshape(60, 777)
                    freqs = np.array([r[-2] for r in rows[1:777 + 1]], dtype=float)
                check(f"CSV {layout} workers={n_workers}: values exact", np.array_equal(values, data))
                check(f"CSV {layout} workers={n_workers}: frequencies exact",
                      np.array_equal(freqs, info.frequencies()))
        ref = ConvertOptions(output_dir=str(root / "stats"), write_vszh5=True, workers=1,
                             image_max_rows=17, image_max_columns=100)
        result = convert_file(source, ref)
        x = data.astype(float)
        check("max hold", np.allclose(result.stat_max, x.max(0)))
        check("min hold", np.allclose(result.stat_min, x.min(0)))
        check("power mean (linear power)", np.allclose(result.stat_power_mean,
                                                       10 * np.log10(np.mean(10 ** (x / 10), 0))))
        check("dB mean and std", np.allclose(result.stat_db_mean, x.mean(0))
              and np.allclose(result.stat_std, x.std(0, ddof=1)))
        check("per-sweep peak and frequency", np.allclose(result.peak, x.max(1)) and np.allclose(
            result.peak_frequency_hz, info.frequencies()[x.argmax(1)]))
        image_ref = block_reduce(x, math.ceil(60 / 17), math.ceil(777 / 100), "max")
        check("spectrogram peak hold = block_reduce", np.allclose(result.image, image_ref))
        check("overflow flags", int(result.overflow.sum()) == len(range(0, 60, 13)))
        with h5py.File(root / "stats" / "synthetic.vszh5", "r") as h5:
            names = set(h5["Veusz/Data"].keys())
            script = h5["Veusz/Document/document"][0].decode()
        check(".vszh5 datasets", {"spectrogram", "max_hold", "sweep_time", "latitude"} <= names, str(names))
        check(".vszh5 pages", all(f"Add('page', name='{p}'" in script for p in
                                  ("spectrogram", "statistics", "selected_sweeps", "level_vs_time", "gps_track")))
        # power-mean spectrogram accumulated across blocks of 7 sweeps (rows of
        # 4 sweeps straddle the blocks) equals the direct reduction
        MAX_BLOCK_SWEEPS = 7
        try:
            pm = convert_file(source, ConvertOptions(output_dir=str(root / "pm"), write_csv=False, workers=1,
                                                 image_reduction="power_mean", image_max_rows=17,
                                                 image_max_columns=100, ram_budget_mb=16,
                                                 write_vszh5=False))
        finally:
            MAX_BLOCK_SWEEPS = limits[1]
        check("spectrogram power mean = block_reduce", np.allclose(
            pm.image, block_reduce(x, math.ceil(60 / 17), math.ceil(777 / 100), "power_mean_db")))
        # sub-ranges
        sub = convert_file(source, ConvertOptions(output_dir=str(root / "sub"), write_vszh5=False, workers=1,
                                                  sweep_start=5, sweep_stop=50, sweep_step=3,
                                                  freq_min_hz=1.0e9 + 100e4, freq_max_hz=1.0e9 + 200e4))
        rows = read_csv(root / "sub" / "synthetic.csv")
        values = np.array([r[7:] for r in rows[1:]], dtype=np.float32)    # 1 + 2 time + 4
        check("sweep and frequency sub-range", np.array_equal(values, data[5:50:3, 100:201])
              and sub.plan.n_sweeps == len(range(5, 50, 3)), str(values.shape))
        # cut-short recordings
        cut = write_synthetic_shr(root / "cut.shr", n_sweeps=20, n_bins=101, truncate_bytes=150)
        cut_info = read_info(cut)
        check("truncated file: complete sweeps only", cut_info.n_sweeps == 19 and cut_info.n_sweeps_header == 20,
              f"{cut_info.n_sweeps}/{cut_info.n_sweeps_header}")
        zero = write_synthetic_shr(root / "zero.shr", n_sweeps=12, n_bins=101, header_count=0)
        check("header count 0: sweeps recovered", read_info(zero).n_sweeps == 12)
        convert_file(cut, ConvertOptions(output_dir=str(root / "cut"), workers=1))
        check("truncated file converts", (root / "cut" / "cut.csv").is_file())
        # mV scale
        mv = write_synthetic_shr(root / "mv.shr", n_sweeps=10, n_bins=64, scale="mV")
        mv_result = convert_file(mv, ConvertOptions(output_dir=str(root / "mv"), workers=1))
        xm = direct(mv).astype(float)
        check("mV: RMS power mean", mv_result.info.amplitude_unit == "mV"
              and np.allclose(mv_result.stat_power_mean, np.sqrt(np.mean(xm ** 2, 0))))
        # GPU code path through the NumPy stand-in
        os.environ["SHR_CONVERTER_FAKE_CUPY"] = "1"
        _BACKEND_CACHE.clear()
        try:
            gpu = convert_file(source, ConvertOptions(output_dir=str(root / "gpu"), compute="gpu", workers=1,
                                                      write_vszh5=False, image_max_rows=17, image_max_columns=100))
        finally:
            os.environ.pop("SHR_CONVERTER_FAKE_CUPY", None)
            _BACKEND_CACHE.clear()
        check("GPU code path (stand-in) = CPU", gpu.backend.startswith("fake CuPy")
              and np.allclose(gpu.stat_power_mean, result.stat_power_mean)
              and np.allclose(gpu.image, result.image), gpu.backend)
        # statistics merged across many sub-blocks equal the one-pass results
        saved_chunk = STATS_CHUNK_SAMPLES
        STATS_CHUNK_SAMPLES = 777 * 4                    # four sweeps per sub-block
        try:
            chunked = convert_file(source, ConvertOptions(output_dir=str(root / "chunked"), workers=1,
                                                          write_csv=False, write_vszh5=False,
                                                          image_max_rows=17, image_max_columns=100))
        finally:
            STATS_CHUNK_SAMPLES = saved_chunk
        check("statistics in sub-blocks = one pass", np.allclose(chunked.stat_power_mean, result.stat_power_mean)
              and np.array_equal(chunked.stat_max, result.stat_max) and np.allclose(chunked.stat_std, result.stat_std)
              and np.array_equal(chunked.peak, result.peak) and np.allclose(chunked.image, result.image))
        # long captures: CSV split by time, disk check, disk-mapped sweep table, thinning
        timed = write_synthetic_shr(root / "timed.shr", n_sweeps=60, n_bins=101, step_ms=1000)
        whole = convert_file(timed, ConvertOptions(output_dir=str(root / "whole"), workers=1, write_vszh5=False))
        split = convert_file(timed, ConvertOptions(output_dir=str(root / "split"), workers=1, write_vszh5=False,
                                                   csv_split_minutes=0.25))
        whole_rows = (root / "whole" / "timed.csv").read_text().splitlines()
        part_files = sorted((root / "split").glob("timed_part*.csv"))
        part_rows = [line for f in part_files for line in f.read_text().splitlines()[1:]]
        check("CSV split by time: 4 files of 15 s, same rows", len(part_files) == 4 and len(whole.csv_files) == 1
              and part_rows == whole_rows[1:] and len(split.csv_files) == 4
              and all(f.read_text().splitlines()[0] == whole_rows[0] for f in part_files),
              f"{len(part_files)} files")
        real_usage = shutil.disk_usage
        shutil.disk_usage = lambda _p: type("U", (), {"free": 1000, "total": 1, "used": 0})()
        try:
            convert_file(timed, ConvertOptions(output_dir=str(root / "nospace"), workers=1))
            refused = False
        except OSError as exc:
            refused = "free" in str(exc)
        finally:
            shutil.disk_usage = real_usage
        check("disk check refuses a CSV that cannot fit", refused
              and not list((root / "nospace").glob("*.csv")))
        on_disk = convert_file(source, ConvertOptions(output_dir=str(root / "mm"), workers=1, write_vszh5=False,
                                                      sweep_table_storage="disk", image_max_rows=17,
                                                      image_max_columns=100))
        check("per-sweep table memory-mapped on disk = in RAM",
              np.array_equal(on_disk.peak, result.peak) and np.array_equal(on_disk.timestamp_ms, result.timestamp_ms)
              and (root / "mm" / "synthetic_sweeps.csv").read_bytes()
              == (root / "stats" / "synthetic_sweeps.csv").read_bytes())
        thin = convert_file(source, ConvertOptions(output_dir=str(root / "thin"), workers=1, write_csv=False,
                                                   time_series_max_points=7))
        with h5py.File(root / "thin" / "synthetic.vszh5", "r") as h5:
            veusz_peak = h5["Veusz/Data/sweep_peak/data"][()]
        check("time series thinned with peak hold (Veusz and result)", len(veusz_peak) <= 7
              and np.isclose(veusz_peak.max(), x.max()) and len(thin.peak) <= 7
              and thin.sweeps_per_point == math.ceil(60 / 7) and np.isclose(thin.peak.max(), x.max()))
        os.environ["SHR_CONVERTER_FAKE_CUPY"] = "fail"
        _BACKEND_CACHE.clear()
        try:
            fallback = convert_file(source, ConvertOptions(output_dir=str(root / "gpufail"), compute="gpu",
                                                           workers=1, write_csv=False, write_vszh5=False,
                                                           image_max_rows=17, image_max_columns=100))
        finally:
            os.environ.pop("SHR_CONVERTER_FAKE_CUPY", None)
            _BACKEND_CACHE.clear()
        check("GPU failure falls back to the CPU per block", "GPU failed" in fallback.backend
              and np.allclose(fallback.stat_power_mean, result.stat_power_mean), fallback.backend)
        # a destination locked by another program (Excel on Windows) is kept under a new name
        real_replace = os.replace
        locked = root / "locked"
        locked.mkdir()

        def fake_replace(src: Any, dst: Any) -> None:
            if str(dst).endswith(os.sep + "synthetic.csv"):
                raise PermissionError(13, "locked by another process", str(dst))
            real_replace(src, dst)
        os.replace = fake_replace
        try:
            kept = convert_file(source, ConvertOptions(output_dir=str(locked), workers=1, write_vszh5=False))
        finally:
            os.replace = real_replace
        renamed = [p for p in kept.outputs if Path(p).name.startswith("synthetic_2") and p.endswith(".csv")]
        check("locked CSV kept under a time-stamped name", len(renamed) == 1 and Path(renamed[0]).is_file()
              and any("locked" in m for m in kept.log), str(kept.outputs))
        # cancel leaves nothing behind
        try:
            convert_file(source, ConvertOptions(output_dir=str(root / "cancel"), workers=1, ram_budget_mb=16),
                         cancel=lambda: True)
            cancelled = False
        except ConversionCancelled:
            cancelled = True
        leftovers = list((root / "cancel").glob("*")) if (root / "cancel").exists() else []
        check("cancel removes partial files", cancelled and not leftovers, str(leftovers))

        # -- 0.0.2: Spike 4.0 Max detector (code 2) on the SM 0.01 dB grid ---------------------
        sm = write_synthetic_shr(root / "sm200c_like.shr", n_sweeps=30, n_bins=257, detector=2, quantise_db=0.01)
        sm_info = read_info(sm)
        check("detector 2 opens, labelled Max (inferred)", sm_info.detector == "Max (code 2, inferred)",
              sm_info.detector)
        check("0.01 dB grid noted for detector 2", any("0.01 dB grid" in n for n in sm_info.notes), str(sm_info.notes))
        convert_file(sm, ConvertOptions(output_dir=str(root / "sm"), workers=1, write_vszh5=True))
        header_text = (root / "sm" / "sm200c_like_header.csv").read_text(encoding="utf-8")
        sm_rows = read_csv(root / "sm" / "sm200c_like.csv")
        check("detector 2 converts exactly, header table names it",
              "Max (code 2, inferred)" in header_text and "shr_reader" in header_text
              and np.array_equal(np.array([r[7:] for r in sm_rows[1:]], dtype=np.float32), direct(sm)))
        odd = write_synthetic_shr(root / "unknown_codes.shr", n_sweeps=8, n_bins=64, detector=9)
        odd_result = convert_file(odd, ConvertOptions(output_dir=str(root / "odd"), workers=1, write_vszh5=False))
        check("unknown detector code converts with a note", any("not a known value" in m for m in odd_result.log)
              and (root / "odd" / "unknown_codes.csv").is_file(), str(odd_result.log))
        # -- 0.0.2: a multi-file recording joined as one (worker processes) ----------------------
        joined_dir = root / "join"
        joined_dir.mkdir()
        part_a, part_b = split_recording(source, [joined_dir / "rec_b.shr", joined_dir / "rec_a.shr"], [25, 35])
        far = write_synthetic_shr(joined_dir / "unrelated.shr", n_sweeps=6, n_bins=777, start_ms=1_800_000_000_000)
        IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = 0, 7
        try:
            joined = convert_files([part_b, far, part_a], ConvertOptions(
                output_dir=str(joined_dir / "out"), workers=workers, join_files=True, write_vszh5=False,
                image_max_rows=17, image_max_columns=100, ram_budget_mb=16))
        finally:
            IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = limits
        joined_csv = joined_dir / "out" / "rec_b_joined.csv"
        rows = read_csv(joined_csv) if joined_csv.is_file() else [[]]
        check("join: two results (one joined recording, one single file)", len(joined) == 2
              and (joined_dir / "out" / "unrelated.csv").is_file(), str([r.info.name for r in joined]))
        check("join: CSV equals the unsplit file, sweep numbers continuous",
              len(rows) == 61 and np.array_equal(np.array([r[7:] for r in rows[1:]], dtype=np.float32), data)
              and [int(r[0]) for r in rows[1:]] == list(range(60)))
        joined_result = next((r for r in joined if r.info.is_set), None)
        check("join: statistics and spectrogram equal the unsplit file", joined_result is not None
              and np.allclose(joined_result.stat_power_mean, result.stat_power_mean)
              and np.allclose(joined_result.image, result.image)
              and "rec_a.shr" in (joined_dir / "out" / "rec_b_joined_header.csv").read_text())
        # -- 0.0.2: CSV time decimation in every layout (blocks of 7 -> aligned to 4) --------------
        groups4 = np.arange(0, 60, 4)
        expected = {"max": np.fmax.reduceat(data, groups4, axis=0), "min": np.fmin.reduceat(data, groups4, axis=0)}
        lin = np.power(10.0, data.astype(np.float64) / 10.0)
        expected["power_mean"] = (10 * np.log10(np.add.reduceat(lin, groups4, axis=0) / 4)).astype(np.float32)
        for layout in CSV_LAYOUTS:
            for n_workers in (1, workers):
                out = root / f"dec_{layout}_{n_workers}"
                IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = (0 if n_workers > 1 else limits[0]), 7
                try:
                    dec = convert_file(source, ConvertOptions(output_dir=str(out), csv_layout=layout, workers=n_workers,
                                                              write_vszh5=False, csv_decimate=4, ram_budget_mb=16,
                                                              image_max_rows=17, image_max_columns=100))
                finally:
                    IN_PROCESS_MAX_SAMPLES, MAX_BLOCK_SWEEPS = limits
                rows = read_csv(out / "synthetic.csv")
                if layout == "sweeps_as_rows":           # 1 + 2 time + combined + 4
                    values = np.array([r[8:] for r in rows[1:]], dtype=np.float32)
                    meta = [int(r[0]) for r in rows[1:]] == list(groups4) and {r[3] for r in rows[1:]} == {"4"}
                elif layout == "frequencies_as_rows":
                    values = np.array([r[1:] for r in rows[1:]], dtype=np.float32).T
                    meta = rows[0][1:] == [f"sweep_{g}" for g in groups4]
                else:                                     # sweep, 2 time, combined, frequency, amplitude
                    values = np.array([r[-1] for r in rows[1:]], dtype=np.float32).reshape(15, 777)
                    meta = {r[3] for r in rows[1:]} == {"4"}
                check(f"CSV decimate 4 (max) {layout} workers={n_workers}",
                      np.array_equal(values, expected["max"]) and meta and dec.plan.csv_rows == 15
                      and np.allclose(dec.stat_power_mean, result.stat_power_mean), str(values.shape))
        for detector in ("power_mean", "min"):
            out = root / f"dec_{detector}"
            convert_file(source, ConvertOptions(output_dir=str(out), workers=1, write_vszh5=False, csv_decimate=4,
                                                csv_decimate_detector=detector))
            values = np.array([r[8:] for r in read_csv(out / "synthetic.csv")[1:]], dtype=np.float32)
            check(f"CSV decimate 4 ({detector})", np.allclose(values, expected[detector], rtol=0, atol=1e-4))
        stepped = convert_file(source, ConvertOptions(output_dir=str(root / "dec_step"), workers=1, write_vszh5=False,
                                                      sweep_start=1, sweep_stop=58, sweep_step=2, csv_decimate=4))
        rows = read_csv(root / "dec_step" / "synthetic.csv")
        selection = data[1:58:2]
        starts = np.arange(0, selection.shape[0], 4)
        check("CSV decimate with a sweep step (partial last group)",
              np.array_equal(np.array([r[8:] for r in rows[1:]], dtype=np.float32),
                             np.fmax.reduceat(selection, starts, axis=0))
              and [r[3] for r in rows[1:]][-1] == str(selection.shape[0] - starts[-1])
              and stepped.plan.csv_rows == len(starts))
        # -- 0.0.2: time stamps going backwards are noted -------------------------------------------
        with ShrFile(timed) as shr:
            block = shr.read()
        backwards_ts = block.timestamp_ms.copy()
        backwards_ts[30:] -= 5000
        back = shr_reader.write_shr(root / "backwards.shr", block.amplitudes, backwards_ts, header=shr.header)
        back_result = convert_file(back, ConvertOptions(output_dir=str(root / "back"), workers=1, write_vszh5=False))
        check("time stamps going backwards noted", any("backwards" in m for m in back_result.log), str(back_result.log))
    if real_file and Path(real_file).is_file():
        info = read_info(real_file)
        with tempfile.TemporaryDirectory(prefix="shr_real_") as folder:
            res = convert_file(real_file, ConvertOptions(output_dir=folder, workers=workers))
            first = direct(Path(real_file))[0]
            check(f"real file {info.name}: converted", Path(folder, Path(real_file).stem + ".csv").is_file())
            check(f"real file {info.name}: peak frequency of sweep 0",
                  abs(res.peak_frequency_hz[0] - info.frequencies()[int(np.argmax(first))]) < 1e-3)
        try:                                   # optional independent cross-check [R10]
            from shr_parser import ShrFileParser
            other = ShrFileParser(str(real_file))
            other.open()
            try:
                same = np.array_equal(other.get_sweep_n(0).sweep, first)
            finally:
                other.close()
            check(f"real file {info.name}: sweep 0 equals py-shr-parser", same)
        except ImportError:
            report("INFO py-shr-parser not installed: cross-check skipped")
        except Exception as exc:  # noqa: BLE001 - e.g. ValueError on detector code 2
            report(f"INFO py-shr-parser cannot read {info.name} ({type(exc).__name__}: {exc}); "
                   f"cross-check skipped")
    report(f"{passed} passed, {failed} failed")
    return failed == 0


# %% ===========================================================================
#    COMMAND LINE
# =============================================================================
def build_arg_parser() -> argparse.ArgumentParser:
    """Command-line options (every ConvertOptions field)."""
    defaults = ConvertOptions()
    p = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "shr_converter_core.py",
        description=f"{PROGRAM_NAME} {__version__}: Signal Hound .shr -> CSV and Veusz .vszh5")
    p.add_argument("inputs", nargs="*", help=".shr files or folders (folders: every *.shr inside)")
    p.add_argument("-o", "--output-dir", default="", help="output folder (default: beside each input)")
    p.add_argument("--no-csv", action="store_true", help="do not write the CSV files")
    p.add_argument("--layout", choices=list(CSV_LAYOUTS), default=defaults.csv_layout,
                   help="CSV layout: sweeps_as_rows (default), frequencies_as_rows or long")
    p.add_argument("--fixed", type=int, metavar="DECIMALS", help="fixed decimals instead of lossless %%.9g")
    p.add_argument("--delimiter", choices=list(DELIMITERS), default=defaults.csv_delimiter,
                   help="CSV delimiter: comma (default), semicolon or tab")
    p.add_argument("--time-columns", default=",".join(defaults.csv_time_columns),
                   help=f"comma list of {', '.join(TIME_COLUMNS)}")
    p.add_argument("--no-companions", action="store_true", help="skip _header/_sweeps/_statistics.csv")
    p.add_argument("--split-minutes", type=float, default=0.0,
                   help="new CSV file every N minutes of recording (0 = one file)")
    p.add_argument("--csv-decimate", type=int, default=defaults.csv_decimate, metavar="N",
                   help="combine every N selected sweeps into one CSV row (1 = every sweep)")
    p.add_argument("--csv-decimate-detector", choices=list(CSV_DECIMATE_DETECTORS),
                   default=defaults.csv_decimate_detector,
                   help="how --csv-decimate combines sweeps: max (peak hold, default), power_mean or min")
    p.add_argument("--join", action="store_true",
                   help="convert the files of a multi-file Spike recording as one (grouped by content)")
    p.add_argument("--no-disk-check", action="store_true", help="do not refuse when the CSV may not fit")
    p.add_argument("--no-vszh5", action="store_true", help="do not write the Veusz document")
    p.add_argument("--image-size", default=f"{defaults.image_max_rows}x{defaults.image_max_columns}",
                   help="maximum spectrogram ROWSxCOLUMNS")
    p.add_argument("--reduction", choices=list(IMAGE_REDUCTIONS), default=defaults.image_reduction,
                   help="spectrogram pixels: max (peak hold, default), power_mean or min")
    p.add_argument("--colormap", default=defaults.colormap, help="Veusz colour map, e.g. viridis, magma, heat")
    p.add_argument("--z", default=defaults.z_mode, help="data | reference | veusz | MIN,MAX")
    p.add_argument("--time-axis", choices=list(TIME_AXES), default=defaults.time_axis,
                   help="auto (date/time from 60 s on), utc, local, elapsed or index")
    p.add_argument("--sweeps-to-plot", default=defaults.selected_sweeps,
                   help="selected-sweeps page: first,last,peak and/or sweep indices")
    p.add_argument("--render", action="store_true", help="render PDF (bookmarked) and PNG with Veusz")
    p.add_argument("--png", choices=("all", "first", "none"), default=defaults.render_png,
                   help="PNG pages when rendering: first (default), all or none")
    p.add_argument("--veusz", default="", help="Veusz program (else VEUSZ_EXE, PATH, usual folders)")
    p.add_argument("--sweeps", default="", help="sweep selection START:STOP:STEP (STOP exclusive)")
    p.add_argument("--freq", default="", help="frequency range FMIN:FMAX in MHz")
    p.add_argument("-j", "--workers", type=int, default=0, help="worker processes (0 = CPUs - 1)")
    p.add_argument("--ram-mb", type=int, default=defaults.ram_budget_mb, help="RAM budget for blocks")
    p.add_argument("--compute", choices=("auto", "cpu", "gpu"), default=defaults.compute,
                   help="statistics on auto (CuPy GPU when present), cpu or gpu (falls back to CPU)")
    p.add_argument("--series-points", type=int, default=defaults.time_series_max_points,
                   help="maximum points of the level-vs-time and GPS series in the .vszh5")
    p.add_argument("--sweep-table", choices=("auto", "memory", "disk"), default=defaults.sweep_table_storage,
                   help="per-sweep table in RAM or memory-mapped on disk (auto: by size)")
    p.add_argument("--info", action="store_true", help="print header, plan and notes only")
    p.add_argument("--selftest", action="store_true", help="run the self-test and exit")
    p.add_argument("--real-file", default="", help="also check this real .shr in the self-test")
    p.add_argument("--version", action="version",
                   version=f"{PROGRAM_NAME} {__version__} (vszh5_writer {vszh5_writer.__version__}, "
                           f"shr_reader {SHR_READER_VERSION})")
    return p


def options_from_args(args: argparse.Namespace) -> ConvertOptions:
    """ConvertOptions from parsed command-line arguments."""
    opts = ConvertOptions(output_dir=args.output_dir, write_csv=not args.no_csv, csv_layout=args.layout,
                          csv_delimiter=args.delimiter, write_vszh5=not args.no_vszh5,
                          image_reduction=args.reduction, colormap=args.colormap, time_axis=args.time_axis,
                          selected_sweeps=args.sweeps_to_plot, render=args.render, render_png=args.png,
                          veusz_exe=args.veusz, workers=args.workers, ram_budget_mb=args.ram_mb,
                          compute=args.compute, csv_split_minutes=args.split_minutes,
                          check_disk_space=not args.no_disk_check, time_series_max_points=args.series_points,
                          sweep_table_storage=args.sweep_table, csv_decimate=args.csv_decimate,
                          csv_decimate_detector=args.csv_decimate_detector, join_files=args.join)
    if args.fixed is not None:
        opts.csv_number_format, opts.csv_decimals = "fixed", args.fixed
    opts.csv_time_columns = tuple(c.strip() for c in args.time_columns.split(",") if c.strip())
    if args.no_companions:
        opts.csv_header_table = opts.csv_sweeps_table = opts.csv_statistics_table = False
    rows, _, cols = args.image_size.lower().partition("x")
    opts.image_max_rows, opts.image_max_columns = int(rows), int(cols or rows)
    if "," in args.z:
        opts.z_mode = "manual"
        opts.z_min, opts.z_max = (float(v) for v in args.z.split(",", 1))
    else:
        opts.z_mode = args.z
    if args.sweeps:
        parts = (args.sweeps.split(":") + ["", ""])[:3]
        opts.sweep_start = int(parts[0] or 0)
        opts.sweep_stop = int(parts[1] or 0)
        opts.sweep_step = int(parts[2] or 1)
    if args.freq:
        low, _, high = args.freq.partition(":")
        opts.freq_min_hz = float(low or 0) * 1e6
        opts.freq_max_hz = float(high or 0) * 1e6
    opts.validate()
    return opts


def expand_inputs(items: Iterable[str]) -> list[str]:
    """Files as given; folders expanded to their *.shr files (sorted, no duplicates)."""
    out: list[str] = []
    for item in items:
        path = Path(item)
        found = sorted(path.glob("*.shr")) + sorted(path.glob("*.SHR")) if path.is_dir() else [path]
        for candidate in found:
            text = str(candidate.resolve())
            if text not in out:
                out.append(text)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; returns the exit code."""
    args = build_arg_parser().parse_args(argv)
    if args.selftest:
        return 0 if self_test(workers=max(2, args.workers or 2), real_file=args.real_file or None) else 1
    inputs = expand_inputs(args.inputs)
    if not inputs:
        build_arg_parser().print_usage()
        print("no .shr input given", file=sys.stderr)
        return 2
    opts = options_from_args(args)
    if args.info:
        groups = group_recordings(inputs) if opts.join_files else [[p] for p in inputs]
        for group in groups:
            info = read_info(group if len(group) > 1 else group[0])
            print("\n".join(info.summary_lines() + make_plan(info, opts).lines()))
            print()
        return 0
    last = [0.0]

    def progress(fraction: float, text: str) -> None:
        if fraction - last[0] >= 0.05 or fraction >= 1.0:
            last[0] = fraction
            print(f"  {100 * fraction:5.1f} %  {text}", flush=True)

    errors: list[Any] = []
    results = convert_files(inputs, opts, progress=progress, log=print,
                            deliver=lambda r: errors.append(r) if isinstance(r, Exception) else None)
    # With --join several files can make one recording, so success means: no
    # error was delivered and at least one recording was converted.
    print(f"{len(results)} recording(s) converted from {len(inputs)} file(s)"
          + (f", {len(errors)} failed" if errors else ""))
    return 0 if not errors and results else 1


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# from shr_converter_core import ConvertOptions, convert_file, convert_files, read_info
# info = read_info(r"C:\data\capture.shr"); print("\n".join(info.summary_lines()))
# result = convert_file(r"C:\data\capture.shr", ConvertOptions(output_dir=r"C:\data\out"))
# print("\n".join(result.summary_lines()))
# # a multi-file recording, every 30 sweeps peak-held into one CSV row:
# convert_files([r"C:\data\rec_1.shr", r"C:\data\rec_2.shr"],
#               ConvertOptions(join_files=True, csv_decimate=30), log=print)

if __name__ == "__main__":
    sys.exit(main())
