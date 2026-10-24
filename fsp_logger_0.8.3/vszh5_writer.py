#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# SPDX-FileCopyrightText: 2026 William W. Wallace, Adaptive Electrodynamics LLC dba AdaptEd
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Native Veusz HDF5 document (.vszh5) writer - no Veusz needed to write.

===============================================================================
 Title          : Veusz HDF5 Document Writer
 Filename       : vszh5_writer.py
 Version        : 0.0.17 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-11
 Modified       : 2026-10-23
 Language       : Python 3.8 through 3.12
 Requires       : numpy, h5py   (Veusz only to open or render the result;
                  pypdf only for PDF bookmarks)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Derived from   : isp_speed_monitor.py 1.3.0 (VeuszWriter, VszDoc, vz_text,
                  epoch_to_veusz, find_veusz_exe, _atomic_path/_commit_atomic,
                  tests/render_in_veusz.sh), Copyright (C) 2026 William W.
                  Wallace, Adaptive Electrodynamics LLC dba AdaptEd.
 Status         : Internal draft - checked against real Veusz 3.6.2 and 4.2.1
                  (2-D datasets and the page helpers of 0.0.11/0.0.12: 4.2.1;
                  the 0.0.14 fills, bar pages and step masks: 3.6.2)
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
Writes Veusz's native HDF5 save format directly with h5py: the data as typed
Veusz datasets and the plots as the Veusz command script, in one file that
opens in Veusz with File > Open. Nothing from Veusz is imported to write it.

    from vszh5_writer import VeuszWriter, VszDoc, vz_text

    doc = VszDoc(generator="my_program 1.0")
    doc.add("page", "page1"); doc.to("page1")
    doc.add("graph", "g"); doc.to("g")
    doc.add("axis", "x"); doc.add("axis", "y")
    doc.set("y/direction", "vertical")
    doc.add("xy", "trace"); doc.set("trace/xData", "t"); doc.set("trace/yData", "v")
    doc.up(); doc.up()

    with VeuszWriter("out.vszh5", compress=True) as w:
        w.dataset_1d("t", t)
        w.dataset_1d("v", v, serr=sigma, tags=("raw",))
        w.finish(doc.text())

The plot-page helpers (0.0.11) build whole pages in one call, the same way
on every page of every program:

    from vszh5_writer import Trace, image_page, xy_page

    xy_page(doc, "spectrum", [Trace("f", "amp", "FFT"), Trace("f", "fit", "fit")],
            title="Envelope spectrum", xlabel="Frequency (Hz)", ylabel="W/m^2",
            ylog=True)
    image_page(doc, "map", "level_db", title="Spectrogram", xlabel="Time (s)",
               ylabel="Frequency (Hz)", zlabel="dB", zmin=-60, zmax=0)
    ...
    w.dataset_2d("level_db", image, xcent=time_s, ycent=freq_hz)

FILE LAYOUT  (Veusz document format 1, as written by Document.saveToHDF5File
and read by loader.loadHDF5Doc in Veusz 3.6 and 4.2 [R1])
-----------
    /Veusz                     attrs vsz_version, vsz_saved_at, vsz_format = 1
    /Veusz/Data/<name>         group, attr vsz_datatype in {'1d', '2d', 'date', 'text'}
         .../data              values; attr vsz_name = <name> (UTF-8)
         .../serr|perr|nerr    optional error arrays for '1d'
         .../xrange|xedge|xcent  '2d' only: x axis of the image (one of the
         .../yrange|yedge|ycent  three per axis); 'data' carries an HDF5
                               object reference to it in attr vsz_<key>
                               (Dataset2D.saveDataDumpToHDF5 [R1])
    /Veusz/Document/document   1-element byte-string array: the command script
    /Veusz/Document/Tags/<tag> byte-string array of the dataset names tagged
Names containing '/' or '`' are escaped as '`SL' and '`BT'. Date datasets
hold seconds since 2009-01-01 00:00:00 (naive), Veusz's date origin.

WRITING SAFELY
--------------
Every file is written to "<name>.part" and moved onto "<name>" with one
os.replace() when finish() succeeds, so Veusz or a script that opens the
file mid-update sees the old complete file or the new one, never half of
one. An exception inside the "with" block deletes the .part file.

RENDERING  (needs Veusz)
---------
render_pages() renders PDF and PNG from a .vszh5. `veusz --export` cannot
open a .vszh5 (Veusz 3.6.2 and 4.2.1 read it as text, get an empty document
and fail), and `--export-dpi` and `%PAGE%` are not command-line features. So
the program is driven in `--listen --quiet` mode with a script that calls
loader.loadHDF5Doc, as tests/render_in_veusz.sh in isp_speed_monitor does.
That works with a standalone Veusz install (Windows installer) as well as
with the conda-forge package. If no Veusz program is found but the veusz
Python package imports, the same load-and-export runs in-process.

PDF BOOKMARKS  (needs pypdf)
-------------
Veusz writes a multipage PDF without an outline. render_pages() adds one
afterwards with add_pdf_bookmarks(): by default one bookmark per page, named
after the Veusz page; a caller can pass its own hierarchy (a callable that
receives the page names). The outline opens in the reader's bookmark pane.
Without pypdf the PDF is still written, only without bookmarks.

DIFFERENCES FROM isp_speed_monitor.py 1.3.0
-------------------------------------------
* vz_text() follows Veusz's own latexEscape exactly: '\\' becomes
  {\\backslash} (in Veusz text '\\\\' is a LINE BREAK, so the 1.3.0 escape
  split a label at any backslash) and '[' ']' are escaped as well.
* VeuszWriter: optional gzip+shuffle compression; perr/nerr error arrays;
  context manager; atomic .part write built in; abort().
* local_utc_offsets(): per-sample UTC offset, so a local-time axis stays
  correct across a daylight-saving change.
* render_pages(): the --listen method, every page to PNG plus one multipage
  PDF, Windows-safe paths (bound outside exec), waits for a done marker, and
  falls back to the veusz package when the program fails.
* add_pdf_bookmarks(): a bookmark hierarchy and document information in the
  rendered PDF.
* (0.0.11) dataset_2d() for images, and plot-page helpers: Trace, add_title,
  xy_page (line plots, linear/log/date axes, legend) and image_page (2-D
  image with a colour bar placed where Veusz 4.2.1 draws it).
* (0.0.12) grid_page (several graphs on one page, e.g. an overview) and
  text_page (a page of text lines, e.g. a results summary in the PDF).
* (0.0.14) Trace.fill (shaded region below/above a trace, e.g. where a
  level exceeds a protection mask), bar_page (category bar charts with a
  labels-mode axis), step_mask (stepped mask lines with gaps) and
  reference_line (horizontal or vertical threshold/marker lines).
* (0.0.13) dataset_names, read_text_dataset and page_names: read a written
  document back with h5py (no Veusz): datasets, text metadata, page order.

REFERENCES
----------
[R1] Veusz Developers, Veusz 4.2.1 source: veusz/document/doc.py
     (saveToHDF5File), veusz/document/loader.py (loadHDF5Doc),
     veusz/utils/textrender.py (latexEscape, symbols), veusz/veusz_main.py.
     https://pypi.org/project/veusz/4.2.1/
[R2] h5py developers, "h5py 3.16.0." https://pypi.org/project/h5py/
[R3] W. W. Wallace, isp_speed_monitor.py 1.3.0, Adaptive Electrodynamics
     LLC dba AdaptEd, 2026 (source of the writer design).

REVISION HISTORY
----------------
0.0.17 2026-10-23  Consolidate numerically stable, chunked linear-power dBm
                   averaging for the merged logger/report release 0.8.3.

0.0.17 2026-10-23  Add precise frequency_ghz_text() and frequency_time_pages():
                   Freq_N_GHz and Combined_Freq_vs_Time with datetime axes.
                   Independent analyzer traces are never averaged together.
0.0.15 2026-10-23  Python 3.8-safe typing alias; private atomic temp files;
                   flushed renderer markers to prevent export-complete hangs.

0.0.14 2026-10-19  Released with the GBT RFI Interference Evaluator 0.0.1.
                   Additions only; every 0.0.13 call is unchanged:
                   * Trace.fill ("below" | "above" | ""), fill_colour and
                     fill_transparency: shades the region between a trace
                     and the bottom/top of the graph (Veusz xy FillBelow /
                     FillAbove), e.g. the part of a spectrum above a mask.
                   * bar_page(): category bar chart (Veusz 'bar' widget,
                     x axis in 'labels' mode from a text dataset), linear
                     or log value axis, legend for grouped bars.
                   * step_mask(): (x, y) arrays of a stepped mask from band
                     edges and levels, NaN between bands so Veusz and
                     pyqtgraph draw separate steps.
                   * reference_line(): two-point (x, y) arrays for a
                     horizontal or vertical threshold/marker line.
                   * Revision history re-ordered newest first (numeric
                     version order), the author's house style.
                   Checked by rendering in Veusz 3.6.2 (PDF and PNG).
0.0.13 2026-10-15  Released with EMF Envelope FFT Analyzer 0.0.4. Additions
                   only:
                   * dataset_names(), read_text_dataset() and page_names():
                     read back what a document holds without Veusz (e.g. the
                     unit sections an analyzer stored as a text dataset, to
                     rebuild the PDF bookmarks when a document is rendered
                     later, or to list its pages).
0.0.12 2026-10-15  Released with EMF Envelope FFT Analyzer 0.0.3. Additions
                   only; every earlier call is unchanged:
                   * Panel and grid_page(): several graphs on one page in a
                     Veusz grid widget (rows x columns), each with its own
                     traces, axes, log/date modes and a small panel title.
                   * text_page(): lines of text (monospaced by default) on a
                     page, continued on further pages when long; Veusz
                     markup is escaped and lines joined with Veusz's line
                     break, so a summary prints as written.
                   * "Veusz not found" messages name both variables that
                     find_veusz_exe() reads (VEUSZ_EXE, QUICKSYN_VEUSZ).
                   * xy_page() and grid_page() share _add_traces/_add_key.
                   Checked by rendering in Veusz 4.2.1 (PDF and PNG).
0.0.11 2026-10-15  Released with EMF Envelope FFT Analyzer 0.0.2. Additions
                   only; every 0.0.10 call is unchanged:
                   * VeuszWriter.dataset_2d(): 2-D (image) datasets in the
                     layout of Veusz's Dataset2D.saveDataDumpToHDF5 - 'data'
                     (ny, nx) plus xrange/xedge/xcent and yrange/yedge/ycent,
                     linked by vsz_<key> object references. Regular edges or
                     centres are stored as a range, as Veusz does on load.
                   * Plot-page helpers: TRACE_COLOURS, Trace, add_title(),
                     xy_page() and image_page(). image_page() places the
                     colour bar manually (horzPosn/vertPosn 'manual', right
                     of the graph, labels reflected): with the default
                     placement Veusz 4.2.1 does not draw it.
                   * xy_page(xmode="datetime") for date datasets on x;
                     x_autorange/y_autorange ("exact" for time axes).
                     Image axes and the colour bar use "exact" ranges, so
                     the bar is not padded with white past zmin/zmax.
                   Checked by rendering in Veusz 4.2.1 (PDF and PNG).
0.0.10 2026-10-14  Released with QuickSyn package 0.0.10. The GUI now also
                   uses VszDoc/VeuszWriter in-process to export a power
                   calibration table (Calibration tab). No change to this
                   module's code.
0.0.9  2026-10-12  Released with QuickSyn package 0.0.9 (10 MHz output command
                   path in the GUI). No change to this module's code.
0.0.8  2026-10-12  Released with QuickSyn package 0.0.8 (hardware-session
                   fixes in the GUI). No change to this module's code.
0.0.7  2026-10-12  Released with QuickSyn package 0.0.7 (output-power fix in
                   the GUI). No change to this module's code.
0.0.6  2026-10-11  add_pdf_bookmarks(): writes a bookmark (outline) hierarchy
                   and the document title, author and subject into a PDF with
                   pypdf, atomically, and opens the outline pane by default.
                   render_pages() calls it for the multipage PDF (new
                   parameters bookmarks= and pdf_info=; one bookmark per page
                   unless the caller supplies a hierarchy); skipped with a
                   warning, never an error, when pypdf is not installed.
                   FIX (Veusz 4.x): PDF pages were drawn at 48 % scale in the
                   top-left corner. Veusz 4.2.1 (and master) lays a PDF out
                   at 72 dpi, the only resolution Qt's PDF engine reports,
                   but sets the printer to Export()'s pdfdpi, default 150;
                   PDFs are now exported with pdfdpi=72 (PDF_DPI). Veusz
                   3.6.2 was unaffected. The PNGs were always correct, which
                   is why the 0.0.4 checks, which inspected PNGs, missed it.
                   FIX: render_pages() returns the files it wrote even when
                   they already existed. 0.0.5 compared against the folder
                   listing taken at the start, so a second render into the
                   same folder returned an empty list (the files were
                   rewritten, but the export reported no plots).
                   Released with QuickSyn package 0.0.6 (0.0.5 was never
                   packaged; its changes ship here).
0.0.5  2026-10-11  render_pages(): Windows paths fixed (the PNG path sat
                   inside an exec() string, so C:\\Users... was unescaped twice;
                   it is now bound on its own line); method "auto" falls back
                   to the veusz package when the Veusz program found fails to
                   render (e.g. a distribution package built for another
                   Python) and reports both errors otherwise. A program that
                   exits before reading its script (broken pipe) or cannot
                   be started is now reported as a failed render rather than
                   raising BrokenPipeError/OSError, so the fallback runs. The
                   stdout pipe is closed (ResourceWarning) and Veusz is never
                   left running after an error.
0.0.4  2026-10-11  First version, released with QuickSyn package 0.0.4
                   (version follows the package). Extracted from
                   isp_speed_monitor.py 1.3.0 and extended as listed above.
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import datetime as _dt
import glob
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, Union, List, Mapping

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - reported when a writer is created
    h5py = None

__version__ = "0.0.17"                 # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"      # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"

__all__ = [
    "VSZH5_FORMAT", "VSZH5_LAYOUT_VERSION", "VEUSZ_EPOCH", "UNIX_TO_VEUSZ_S",
    "epoch_to_veusz", "local_utc_offsets", "vz_text", "escape_hdf_name",
    "VszDoc", "VeuszWriter", "find_veusz_exe", "render_pages",
    "add_pdf_bookmarks", "OutlineEntry",
    # 0.0.11: plot-page helpers
    "TRACE_COLOURS", "Trace", "add_title", "xy_page", "image_page",
    # 0.0.12: multi-panel and text pages
    "Panel", "grid_page", "text_page",
    "frequency_ghz_text", "frequency_time_pages", "linear_power_mean_dbm",
    # 0.0.13: reading a written document back
    "dataset_names", "read_text_dataset", "page_names",
    # 0.0.14: fills, bar charts, step masks, reference lines
    "bar_page", "step_mask", "reference_line",
]

# %% ===========================================================================
#    CONSTANTS AND TIME HELPERS
# =============================================================================
#: Highest document format the Veusz 3.6 and 4.2 loaders accept.
VSZH5_FORMAT = 1
#: Veusz release whose HDF5 layout this writer follows (written as vsz_version).
VSZH5_LAYOUT_VERSION = "4.2.1"
#: Arrays at least this long are gzip+shuffle compressed when compress=True.
COMPRESS_MIN_ELEMENTS = 4096
#: Resolution passed to Veusz's Export() for PDF. Veusz 4.x lays a PDF page
#: out at the nearest resolution the Qt PDF engine supports (72) but sets the
#: printer to the requested pdfdpi (Export() defaults to 150), so the drawing
#: lands in the top-left 48 % of each page. 72 keeps both the same; Veusz
#: 3.6 is unaffected, and PDF output is vector, so nothing is lost.
PDF_DPI = 72

#: Veusz date origin, and the offset that maps Unix seconds onto it.
VEUSZ_EPOCH = _dt.datetime(2009, 1, 1)
UNIX_TO_VEUSZ_S = (_dt.datetime(1970, 1, 1) - VEUSZ_EPOCH).total_seconds()  # -1230768000


def epoch_to_veusz(epoch_s: Any, offset_s: Any = 0.0) -> np.ndarray:
    """Unix epoch seconds -> Veusz date value (seconds since 2009-01-01).

    Pass the UTC offset in seconds (scalar or per sample) to get a local
    wall-clock axis; leave it 0 for UTC.
    """
    return (np.asarray(epoch_s, dtype=float) + np.asarray(offset_s, dtype=float)
            + UNIX_TO_VEUSZ_S)


def local_utc_offsets(epoch_s: Any) -> np.ndarray:
    """Local UTC offset in seconds for every timestamp, DST-aware.

    Offsets only change on whole hours, so the lookup is done once per
    distinct UTC hour and broadcast, which keeps it fast for long logs.
    """
    t = np.asarray(epoch_s, dtype=float)
    out = np.zeros_like(t)
    good = np.isfinite(t)
    if not good.any():
        return out
    hours = np.floor(t[good] / 3600.0)
    uniq, inverse = np.unique(hours, return_inverse=True)
    table = np.array([
        _dt.datetime.fromtimestamp(h * 3600.0 + 1800.0, _dt.timezone.utc)
        .astimezone().utcoffset().total_seconds()
        for h in uniq
    ])
    out[good] = table[inverse]
    return out


# %% ===========================================================================
#    TEXT AND NAME ESCAPING
# =============================================================================
def vz_text(text: Any) -> str:
    """Escape Veusz text-markup characters so a string prints literally.

    Identical to veusz.utils.textrender.latexEscape [R1]: '_' and '^' would
    start sub/superscripts, braces and brackets group, and a backslash
    becomes {\\backslash} because '\\\\' is a line break in Veusz text.
    """
    s = str(text).replace("\\", "\ue000")
    s = re.sub(r"([_\^\[\]\{\}])", r"\\\1", s)
    return s.replace("\ue000", "{\\backslash}")


def escape_hdf_name(name: str) -> str:
    """Escape a dataset name for use as an HDF5 member name, as Veusz does."""
    return name.replace("`", "`BT").replace("/", "`SL")


# %% ===========================================================================
#    DOCUMENT SCRIPT BUILDER
# =============================================================================
class VszDoc:
    """Builder for the Veusz command script stored in the document.

    Same calls as isp_speed_monitor's VszDoc: add() creates a widget under the
    current one without moving, to() moves into a widget, up() moves back,
    and set() takes a path relative to the current widget ("x/label").
    Values are written with repr(), which is valid Python and therefore what
    Veusz executes.
    """

    def __init__(self, generator: str = "", veusz_version: str = VSZH5_LAYOUT_VERSION) -> None:
        stamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
        self.lines: list[str] = [f"# Veusz saved document (version {veusz_version})"]
        if generator:
            self.lines.append(f"# Generated by {generator}")
        self.lines += [f"# Saved at {stamp}", ""]
        self.depth = 0

    def add(self, wtype: str, name: str, **kw: Any) -> None:
        """Add a widget of type ``wtype`` called ``name`` (no auto children)."""
        extra = "".join(f", {k}={v!r}" for k, v in kw.items())
        self.lines.append(f"Add({wtype!r}, name={name!r}, autoadd=False{extra})")

    def to(self, name: str) -> None:
        """Make ``name`` the current widget ('/' = root, '..' = parent)."""
        self.lines.append(f"To({name!r})")
        if name == "/":
            self.depth = 0
        elif name == "..":
            self.depth -= 1
        else:
            self.depth += 1

    def up(self) -> None:
        """Move to the parent widget."""
        self.to("..")

    def set(self, path: str, value: Any) -> None:
        """Set a setting, path relative to the current widget."""
        self.lines.append(f"Set({path!r}, {value!r})")

    def comment(self, text: str) -> None:
        """Add a comment line to the script (ignored by Veusz)."""
        for line in str(text).splitlines() or [""]:
            self.lines.append(f"# {line}")

    def text(self) -> str:
        """The complete script."""
        if self.depth < 0:
            raise ValueError("document script moves above the root widget")
        return "\n".join(self.lines) + "\n"


# %% ===========================================================================
#    HDF5 WRITER
# =============================================================================
class VeuszWriter:
    """Write Veusz datasets and a document script to a .vszh5 file.

    Parameters
    ----------
    path:
        Final file name. Data go to a private sibling .part until finish().
    compress:
        gzip (level 4) + shuffle for arrays of COMPRESS_MIN_ELEMENTS or more.
        Veusz reads compressed datasets transparently.
    atomic:
        Write via .part and os.replace (default). False writes in place.
    """

    def __init__(self, path: str | os.PathLike, compress: bool = False,
                 atomic: bool = True, veusz_version: str = VSZH5_LAYOUT_VERSION,
                 writer_tag: str = "") -> None:
        if h5py is None:
            raise RuntimeError("h5py is required to write .vszh5 files "
                               "(mamba install -c conda-forge h5py)")
        self.final_path = Path(path)
        if atomic:
            # Private same-directory temporary file: concurrent writers must
            # not unlink one another's unfinished documents.
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=self.final_path.name + ".", suffix=".part", dir=str(self.final_path.parent))
            os.close(descriptor)
            self.path = Path(temporary_name)
        else:
            self.path = self.final_path
        self.compress = compress
        self.f = h5py.File(self.path, "w")
        self.root = self.f.create_group("Veusz")
        self.root.attrs["vsz_version"] = veusz_version
        self.root.attrs["vsz_saved_at"] = (
            _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat())
        self.root.attrs["vsz_format"] = VSZH5_FORMAT
        if writer_tag:
            self.root.attrs["writer"] = writer_tag      # ignored by Veusz
        self.data = self.root.create_group("Data")
        self.docgrp = self.root.create_group("Document")
        self.tags: dict[str, list[str]] = {}
        self.names: list[str] = []
        self._finished = False

    # --- context manager ------------------------------------------------------
    def __enter__(self) -> "VeuszWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None or not self._finished:
            self.abort()

    # --- internals --------------------------------------------------------------
    def _group(self, name: str, datatype: str) -> Any:
        if name in self.names:
            raise ValueError(f"dataset {name!r} written twice")
        self.names.append(name)
        g = self.data.create_group(escape_hdf_name(name))
        g.attrs["vsz_datatype"] = datatype
        return g

    def _array(self, group: Any, key: str, values: np.ndarray, vsz_name: str) -> Any:
        if self.compress and values.size >= COMPRESS_MIN_ELEMENTS:
            ds = group.create_dataset(key, data=values, compression="gzip",
                                      compression_opts=4, shuffle=True)
        else:
            group[key] = values
            ds = group[key]
        ds.attrs["vsz_name"] = vsz_name.encode("utf-8")
        return ds

    def _tag(self, name: str, tags: Iterable[str]) -> None:
        for t in tags:
            self.tags.setdefault(t, []).append(name)

    # --- datasets -----------------------------------------------------------------
    def dataset_1d(self, name: str, data: Any, serr: Any = None, tags: Sequence[str] = (),
                   perr: Any = None, nerr: Any = None) -> None:
        """Numeric dataset (float64), with optional symmetric or +/- errors."""
        values = np.ascontiguousarray(data, dtype=float)
        if values.ndim != 1:
            raise ValueError(f"dataset {name!r} must be 1-D, got shape {values.shape}")
        g = self._group(name, "1d")
        self._array(g, "data", values, name)
        for key, arr, suffix in (("serr", serr, " (+-)"), ("perr", perr, " (+)"),
                                 ("nerr", nerr, " (-)")):
            if arr is not None:
                err = np.ascontiguousarray(arr, dtype=float)
                if err.shape != values.shape:
                    raise ValueError(f"{name!r} {key} shape {err.shape} != {values.shape}")
                self._array(g, key, err, name + suffix)
        self._tag(name, tags)

    def dataset_date(self, name: str, veusz_seconds: Any, tags: Sequence[str] = ()) -> None:
        """Date/time dataset in Veusz date seconds (see epoch_to_veusz)."""
        g = self._group(name, "date")
        ds = self._array(g, "data", np.ascontiguousarray(veusz_seconds, dtype=float), name)
        ds.attrs["vsz_convert_datetime"] = 1
        self._tag(name, tags)

    def dataset_text(self, name: str, strings: Iterable[Any], tags: Sequence[str] = ()) -> None:
        """Text dataset, one string per element."""
        g = self._group(name, "text")
        g["data"] = [str(s).encode("utf-8") for s in strings]
        g["data"].attrs["vsz_name"] = name.encode("utf-8")
        self._tag(name, tags)

    def dataset_2d(self, name: str, data: Any, xrange: Any = None, yrange: Any = None,
                   xedge: Any = None, yedge: Any = None, xcent: Any = None,
                   ycent: Any = None, tags: Sequence[str] = ()) -> None:
        """2-D numeric dataset (an image) of shape (ny, nx): rows are y, columns x.

        Each axis is given by at most one of
            ``xrange``  (start, stop) of the outer pixel edges,
            ``xedge``   nx + 1 pixel edges (irregular grids),
            ``xcent``   nx pixel centres (irregular grids);
        and likewise for y. With none given the axis is the pixel index
        0..n, Veusz's default. Regular edges or centres are stored as a
        range, which is what Veusz's own Dataset2D does when it loads them
        [R1]. Every axis array is linked from 'data' by an HDF5 object
        reference attribute vsz_<key>, as Dataset2D.saveDataDumpToHDF5 writes.
        NaN pixels are drawn transparent by Veusz.
        """
        values = np.ascontiguousarray(data, dtype=float)
        if values.ndim != 2:
            raise ValueError(f"dataset {name!r} must be 2-D, got shape {values.shape}")
        n_rows, n_columns = values.shape
        # Check the axes before creating anything, so a bad call leaves no group.
        x_key, x_values = _image_axis(name, "x", n_columns, xrange, xedge, xcent)
        y_key, y_values = _image_axis(name, "y", n_rows, yrange, yedge, ycent)
        group = self._group(name, "2d")
        image = self._array(group, "data", values, name)
        for key, axis_values in ((x_key, x_values), (y_key, y_values)):
            group[key] = axis_values
            image.attrs["vsz_" + key] = group[key].ref
        self._tag(name, tags)

    # --- completion -------------------------------------------------------------------
    def finish(self, document_text: str) -> Path:
        """Write the tags and the script, close, and publish the file."""
        tagsgrp = self.docgrp.create_group("Tags")
        for tag, names in sorted(self.tags.items()):
            tagsgrp[tag] = [n.encode("utf-8") for n in sorted(names)]
        self.docgrp["document"] = [document_text.encode("utf-8")]
        self.f.close()
        if self.path != self.final_path:
            os.replace(self.path, self.final_path)
        self._finished = True
        return self.final_path

    def abort(self) -> None:
        """Close and delete the unfinished file (the old final file is kept)."""
        try:
            self.f.close()
        except Exception:  # noqa: BLE001 - already closed or never opened
            pass
        if not self._finished and self.path != self.final_path and self.path.exists():
            self.path.unlink()


def _is_regular(values: np.ndarray) -> bool:
    """True when the spacing of ``values`` is constant (relative 1e-6)."""
    if values.size < 3:
        return values.size == 2
    steps = np.diff(values)
    return bool(np.allclose(steps, steps[0], rtol=1e-6, atol=abs(steps[0]) * 1e-9))


def _image_axis(name: str, axis: str, n_pixels: int, value_range: Any, edges: Any,
                centres: Any) -> tuple[str, np.ndarray]:
    """Choose and check the stored form of one image axis (see dataset_2d).

    Returns (key, values) with key '<axis>range', '<axis>edge' or '<axis>cent'.
    """
    given = [k for k, v in (("range", value_range), ("edge", edges), ("cent", centres))
             if v is not None]
    if len(given) > 1:
        raise ValueError(f"{name!r}: give only one of {axis}range/{axis}edge/{axis}cent")
    if value_range is not None:
        bounds = np.asarray(value_range, dtype=float).ravel()
        if bounds.size != 2:
            raise ValueError(f"{name!r}: {axis}range needs (start, stop)")
        return f"{axis}range", bounds
    if edges is not None:
        edge_values = np.asarray(edges, dtype=float).ravel()
        if edge_values.size != n_pixels + 1:
            raise ValueError(f"{name!r}: {axis}edge needs {n_pixels + 1} values, "
                             f"got {edge_values.size}")
        if _is_regular(edge_values):
            return f"{axis}range", edge_values[[0, -1]]
        return f"{axis}edge", edge_values
    if centres is not None:
        centre_values = np.asarray(centres, dtype=float).ravel()
        if centre_values.size != n_pixels:
            raise ValueError(f"{name!r}: {axis}cent needs {n_pixels} values, "
                             f"got {centre_values.size}")
        if n_pixels == 1:                   # one pixel: unit width around the centre
            return f"{axis}range", centre_values[0] + np.array([-0.5, 0.5])
        if _is_regular(centre_values):      # outer edges half a step outside
            half_step = 0.5 * (centre_values[1] - centre_values[0])
            return f"{axis}range", np.array([centre_values[0] - half_step,
                                             centre_values[-1] + half_step])
        return f"{axis}cent", centre_values
    return f"{axis}range", np.array([0.0, float(n_pixels)])


# %% ===========================================================================
#    PLOT-PAGE HELPERS (0.0.11)
# =============================================================================
# One call builds one complete page: a title label, a graph with two axes and
# its plot widgets. Every helper starts and ends at the widget that was
# current when it was called (normally the root "/"), so pages can be added
# one after another. Text is escaped with vz_text() unless escape=False, in
# which case Veusz markup (e.g. "W/m^{2}") is passed through.

#: Default line colours, in order (Tableau 10, as matplotlib; distinguishable
#: for the common colour-vision deficiencies when combined with line styles).
TRACE_COLOURS = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e",
                 "#17becf", "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22")


@dataclass(frozen=True)
class Trace:
    """One line or marker series (Veusz 'xy' widget) for xy_page().

    Attributes
    ----------
    x, y:
        Dataset names (a 'date' dataset on x needs xmode="datetime").
    label:
        Legend text; empty = not in the legend.
    colour:
        Line colour; empty = next entry of TRACE_COLOURS.
    width:
        Line width with unit, e.g. "1pt".
    style:
        Veusz line style: solid, dashed, dotted, dash-dot, ...
    marker:
        Veusz marker name ("none", "circle", "square", ...).
    marker_size:
        Marker size with unit.
    line:
        False draws markers only.
    fill:
        (0.0.14) "below" shades from the trace down to the bottom of the
        graph, "above" up to the top, "" (default) no shading.
    fill_colour:
        (0.0.14) Shading colour; empty = the line colour.
    fill_transparency:
        (0.0.14) Shading transparency in percent (0 opaque, 100 invisible).
    """
    x: str
    y: str
    label: str = ""
    colour: str = ""
    width: str = "1pt"
    style: str = "solid"
    marker: str = "none"
    marker_size: str = "3pt"
    line: bool = True
    fill: str = ""
    fill_colour: str = ""
    fill_transparency: int = 70


def add_title(doc: VszDoc, text: str, name: str = "title", y_position: float = 0.965,
              size: str = "14pt", escape: bool = True) -> None:
    """Centred title label near the top of the current page."""
    doc.add("label", name)
    doc.set(f"{name}/label", vz_text(text) if escape else text)
    doc.set(f"{name}/xPos", [0.5])
    doc.set(f"{name}/yPos", [y_position])
    doc.set(f"{name}/alignHorz", "centre")
    doc.set(f"{name}/alignVert", "top")
    doc.set(f"{name}/Text/size", size)


#: Centimetres per unit for the physical Veusz distance units.
_CM_PER_UNIT = {"cm": 1.0, "mm": 0.1, "in": 2.54, "inch": 2.54, '"': 2.54, "pt": 2.54 / 72.0}


def _distance_cm(distance: str) -> float | None:
    """A physical Veusz distance ("15cm", "6in", "20pt") in cm; None otherwise."""
    match = re.fullmatch(r"\s*([0-9.]+)\s*(cm|mm|inch|in|\"|pt)\s*", str(distance))
    return float(match.group(1)) * _CM_PER_UNIT[match.group(2)] if match else None


def _open_page_and_graph(doc: VszDoc, page: str, title: str, width: str, height: str,
                         margins: dict[str, str], escape: bool) -> None:
    """Add a page (sized), its title and a graph; leave the graph current."""
    doc.add("page", page)
    doc.to(page)
    doc.set("width", width)
    doc.set("height", height)
    if title:
        add_title(doc, title, escape=escape)
    doc.add("graph", "graph")
    doc.to("graph")
    for side, value in margins.items():         # leftMargin, rightMargin, ...
        doc.set(side, value)


def _add_axes(doc: VszDoc, xlabel: str, ylabel: str, xlog: bool, ylog: bool,
              xmin: Any, xmax: Any, ymin: Any, ymax: Any, xmode: str, escape: bool,
              x_autorange: str = "next-tick", y_autorange: str = "next-tick") -> None:
    """The x and y axes of the current graph, with labels, scales and limits.

    ``x_autorange``/``y_autorange`` are Veusz autoRange values used when the
    limit is "Auto": "next-tick" (Veusz default), "exact", "+5%", ...
    """
    doc.add("axis", "x")
    doc.add("axis", "y")
    doc.set("y/direction", "vertical")
    doc.set("x/label", vz_text(xlabel) if escape else xlabel)
    doc.set("y/label", vz_text(ylabel) if escape else ylabel)
    doc.set("x/mode", xmode)                     # numeric | datetime | labels
    doc.set("x/log", bool(xlog))
    doc.set("y/log", bool(ylog))
    doc.set("x/autoRange", x_autorange)
    doc.set("y/autoRange", y_autorange)
    for setting_path, value in (("x/min", xmin), ("x/max", xmax),
                                ("y/min", ymin), ("y/max", ymax)):
        doc.set(setting_path, value if value == "Auto" else float(value))


def xy_page(doc: VszDoc, page: str, traces: Sequence[Trace], title: str = "",
            xlabel: str = "", ylabel: str = "", *, xlog: bool = False, ylog: bool = False,
            xmin: Any = "Auto", xmax: Any = "Auto", ymin: Any = "Auto", ymax: Any = "Auto",
            xmode: str = "numeric", x_autorange: str = "next-tick",
            y_autorange: str = "next-tick", key: bool | str = "auto",
            key_position: tuple[str, str] = ("right", "top"),
            width: str = "25cm", height: str = "15cm", left_margin: str = "2.2cm",
            top_margin: str = "1.4cm", escape: bool = True) -> None:
    """A page with one graph of line/marker traces.

    Parameters
    ----------
    doc:
        The script builder; the current widget should be the root ("/").
    page:
        Veusz page name (also the PDF bookmark name with render_pages()).
    traces:
        The series to draw, in drawing order.
    title, xlabel, ylabel:
        Page title and axis labels.
    xlog, ylog:
        Logarithmic axes. Non-positive values are not drawn on a log axis.
    xmin, xmax, ymin, ymax:
        Axis limits, or "Auto".
    xmode:
        "numeric", or "datetime" for a 'date' dataset on x.
    x_autorange, y_autorange:
        How an "Auto" limit is found: "next-tick" (Veusz default, extends
        to the next labelled tick), "exact" (data range, e.g. for time
        axes), or a margin such as "+5%".
    key:
        Legend: True, False, or "auto" (when more than one trace has a label).
    key_position:
        (horizontal, vertical) position of the legend inside the graph.
    width, height, left_margin, top_margin:
        Page size and graph margins (Veusz distances with unit).
    escape:
        Escape the texts with vz_text (False passes Veusz markup through).
    """
    _open_page_and_graph(doc, page, title, width, height,
                         {"leftMargin": left_margin, "topMargin": top_margin}, escape)
    _add_axes(doc, xlabel, ylabel, xlog, ylog, xmin, xmax, ymin, ymax, xmode, escape,
              x_autorange, y_autorange)
    _add_traces(doc, traces, escape)
    _add_key(doc, traces, key, key_position)
    doc.up()                                     # graph -> page
    doc.up()                                     # page -> where we started


def _add_traces(doc: VszDoc, traces: Sequence[Trace], escape: bool = True) -> None:
    """Add the xy widgets of ``traces`` to the current graph."""
    for index, trace in enumerate(traces):
        widget = f"trace{index}"
        doc.add("xy", widget)
        doc.set(f"{widget}/xData", trace.x)
        doc.set(f"{widget}/yData", trace.y)
        doc.set(f"{widget}/marker", trace.marker)
        doc.set(f"{widget}/markerSize", trace.marker_size)
        colour = trace.colour or TRACE_COLOURS[index % len(TRACE_COLOURS)]
        doc.set(f"{widget}/PlotLine/color", colour)
        doc.set(f"{widget}/PlotLine/width", trace.width)
        doc.set(f"{widget}/PlotLine/style", trace.style)
        doc.set(f"{widget}/PlotLine/hide", not trace.line)
        doc.set(f"{widget}/MarkerFill/color", colour)
        doc.set(f"{widget}/MarkerLine/color", colour)
        if trace.fill in ("below", "above"):
            # Veusz xy plotters carry two edge fills, FillBelow (default edge
            # "bottom") and FillAbove (default "top"); both are hidden unless
            # switched on [R1: veusz/widgets/point.py, setting/collections.py].
            group = "FillBelow" if trace.fill == "below" else "FillAbove"
            doc.set(f"{widget}/{group}/hide", False)
            doc.set(f"{widget}/{group}/fillto", "bottom" if trace.fill == "below" else "top")
            doc.set(f"{widget}/{group}/color", trace.fill_colour or colour)
            doc.set(f"{widget}/{group}/transparency", int(trace.fill_transparency))
        elif trace.fill:
            raise ValueError(f"Trace.fill must be 'below', 'above' or '', not {trace.fill!r}")
        if trace.label:
            doc.set(f"{widget}/key", vz_text(trace.label) if escape else trace.label)


def _add_key(doc: VszDoc, traces: Sequence[Trace], key: bool | str = "auto",
             key_position: tuple[str, str] = ("right", "top")) -> None:
    """Legend in the current graph: True, False or "auto" (more than one label)."""
    n_labelled = sum(bool(trace.label) for trace in traces)
    if key is True or (key == "auto" and n_labelled > 1):
        doc.add("key", "key")
        doc.set("key/horzPosn", key_position[0])
        doc.set("key/vertPosn", key_position[1])


def image_page(doc: VszDoc, page: str, dataset: str, title: str = "", xlabel: str = "",
               ylabel: str = "", zlabel: str = "", *, colormap: str = "viridis",
               zmin: Any = "Auto", zmax: Any = "Auto", zscaling: str = "linear",
               xlog: bool = False, ylog: bool = False, colorbar: bool = True,
               width: str = "25cm", height: str = "15cm", right_margin: str = "3.2cm",
               top_margin: str = "1.4cm", bottom_margin: str = "1.7cm",
               escape: bool = True) -> None:
    """A page with a 2-D dataset drawn as an image, and a colour bar.

    Parameters
    ----------
    dataset:
        Name of a dataset written with VeuszWriter.dataset_2d().
    colormap:
        Veusz colour map name (viridis, magma, heat, grey, ...).
    zmin, zmax:
        Colour-scale limits, or "Auto".
    zscaling:
        "linear", "sqrt", "log" or "squared" (Veusz colorScaling).
    colorbar:
        Draw the colour bar right of the graph. It is placed manually
        (left edge at 1.03 of the graph width, top at the graph top, labels
        on the outside): with the default automatic placement Veusz 4.2.1
        does not draw a colour bar that belongs to a graph. Its height is the
        graph height, height - top_margin - bottom_margin, when those are
        physical distances, else Veusz's automatic height.
    bottom_margin:
        Graph bottom margin (Veusz default 1.7cm), used for the bar height.
    Other parameters as xy_page().
    """
    _open_page_and_graph(doc, page, title, width, height,
                         {"rightMargin": right_margin, "topMargin": top_margin,
                          "bottomMargin": bottom_margin}, escape)
    # Image axes span the pixel edges exactly (no padding to the next tick).
    _add_axes(doc, xlabel, ylabel, xlog, ylog, "Auto", "Auto", "Auto", "Auto", "numeric", escape,
              "exact", "exact")
    doc.add("image", "image")
    doc.set("image/data", dataset)
    doc.set("image/colorMap", colormap)
    doc.set("image/colorScaling", zscaling)
    doc.set("image/min", zmin if zmin == "Auto" else float(zmin))
    doc.set("image/max", zmax if zmax == "Auto" else float(zmax))
    if colorbar:
        doc.add("colorbar", "colorbar")
        doc.set("colorbar/widgetName", "image")
        doc.set("colorbar/label", vz_text(zlabel) if escape else zlabel)
        doc.set("colorbar/direction", "vertical")
        # The bar is an axis: "exact" keeps it on the image's colour range
        # (the default "next-tick" pads it with white beyond zmin/zmax).
        doc.set("colorbar/autoRange", "exact")
        doc.set("colorbar/horzPosn", "manual")
        doc.set("colorbar/vertPosn", "manual")
        doc.set("colorbar/horzManual", 1.03)
        doc.set("colorbar/vertManual", 0.0)
        doc.set("colorbar/width", "0.45cm")
        sizes_cm = [_distance_cm(d) for d in (height, top_margin, bottom_margin)]
        if None not in sizes_cm and sizes_cm[0] - sizes_cm[1] - sizes_cm[2] > 1.0:
            graph_height_cm = sizes_cm[0] - sizes_cm[1] - sizes_cm[2]
            doc.set("colorbar/height", f"{graph_height_cm:.3f}cm")
        doc.set("colorbar/reflect", True)
    doc.up()                                     # graph -> page
    doc.up()                                     # page -> where we started


@dataclass(frozen=True)
class Panel:
    """One graph of grid_page(): traces, axes and a small title (0.0.12).

    The fields mean the same as the parameters of xy_page().
    """
    traces: Sequence[Trace]
    xlabel: str = ""
    ylabel: str = ""
    title: str = ""
    xlog: bool = False
    ylog: bool = False
    xmin: Any = "Auto"
    xmax: Any = "Auto"
    ymin: Any = "Auto"
    ymax: Any = "Auto"
    xmode: str = "numeric"
    x_autorange: str = "next-tick"
    key: Any = "auto"


def grid_page(doc: VszDoc, page: str, panels: Sequence[Panel], title: str = "", columns: int = 2,
              width: str = "25cm", height: str = "15cm", escape: bool = True) -> None:
    """A page with several graphs in a Veusz grid (rows filled left to right).

    Each panel gets its own axes, traces, legend and a title above the plot
    area. Use it for overview pages (e.g. time series, spectrum, PSD and zoom
    of one measurement together).
    """
    rows = max(1, math.ceil(len(panels) / max(columns, 1)))
    doc.add("page", page)
    doc.to(page)
    doc.set("width", width)
    doc.set("height", height)
    if title:
        add_title(doc, title, escape=escape)
    doc.add("grid", "grid")
    doc.to("grid")
    doc.set("rows", rows)
    doc.set("columns", columns)
    for side, value in (("topMargin", "1.2cm" if title else "0.3cm"), ("bottomMargin", "0.2cm"),
                        ("leftMargin", "0.2cm"), ("rightMargin", "0.3cm"), ("internalMargin", "0cm")):
        doc.set(side, value)
    for index, panel in enumerate(panels):
        graph = f"graph{index}"
        doc.add("graph", graph)
        doc.to(graph)
        for side, value in (("leftMargin", "1.8cm"), ("rightMargin", "0.3cm"),
                            ("topMargin", "0.7cm"), ("bottomMargin", "1.3cm")):
            doc.set(side, value)
        _add_axes(doc, panel.xlabel, panel.ylabel, panel.xlog, panel.ylog, panel.xmin, panel.xmax,
                  panel.ymin, panel.ymax, panel.xmode, escape, panel.x_autorange)
        _add_traces(doc, panel.traces, escape)
        _add_key(doc, panel.traces, panel.key)
        if panel.title:                          # small title just above the plot area
            doc.add("label", "panel_title")
            doc.set("panel_title/label", vz_text(panel.title) if escape else panel.title)
            doc.set("panel_title/xPos", [0.5])
            doc.set("panel_title/yPos", [1.02])
            doc.set("panel_title/alignHorz", "centre")
            doc.set("panel_title/alignVert", "bottom")
            doc.set("panel_title/Text/size", "10pt")
        doc.up()                                 # graph -> grid
    doc.up()                                     # grid -> page
    doc.up()                                     # page -> where we started


# %% FREQUENCY-VERSUS-TIME PAGES — 0.0.17

# %% LINEAR-POWER AVERAGING — SHARED BY REPORTS AND FUTURE CALLERS

def linear_power_mean_dbm(levels_dbm: Any, axis: int = 0,
                          chunk_size: int = 128) -> np.ndarray:
    """Equal-weight power mean of finite dBm samples, returned in dBm.

    Averages relative milliwatts, not logarithms. Maximum-referenced scaling
    avoids overflow even outside ordinary RF ranges. Only one chunk of
    relative linear powers is allocated at a time. This supports disk-backed
    input without loading a second complete matrix into memory. Independent
    analyzer channels must be passed separately, never stacked as samples.

    No NaN skipping, weighting, smoothing, interpolation or decimation is
    implicit. Empty/nonfinite inputs fail rather than produce biased reports.
    The reduction axis is removed, matching NumPy reduction conventions.
    """
    input_levels = np.asarray(levels_dbm, dtype=float)
    if input_levels.ndim == 0:
        raise ValueError("Supply at least one sample dimension.")
    if not isinstance(axis, (int, np.integer)) or not -input_levels.ndim <= axis < input_levels.ndim:
        raise ValueError("Invalid reduction axis.")
    if not isinstance(chunk_size, (int, np.integer)) or chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer.")
    sample_levels = np.moveaxis(input_levels, axis, 0)
    if not sample_levels.size:
        raise ValueError("Cannot average empty power samples.")
    sample_count = sample_levels.shape[0]
    maximum_levels = np.full(sample_levels.shape[1:], -np.inf)
    for first_sample in range(0, sample_count, chunk_size):
        sample_block = sample_levels[first_sample:first_sample + chunk_size]
        if not np.all(np.isfinite(sample_block)):
            raise ValueError("Power samples must all be finite dBm values.")
        maximum_levels = np.maximum(maximum_levels, np.max(sample_block, axis=0))
    relative_power_sum = np.zeros_like(maximum_levels)
    for first_sample in range(0, sample_count, chunk_size):
        sample_block = sample_levels[first_sample:first_sample + chunk_size]
        with np.errstate(under="ignore", over="ignore"):
            relative_power_sum += np.sum(
                np.power(10.0, (sample_block - maximum_levels) / 10.0), axis=0)
    return maximum_levels + 10.0 * np.log10(relative_power_sum / sample_count)


def frequency_ghz_text(frequency_hz: Any) -> str:
    """Scale decimal Hz to GHz without coarse rounding/name collisions.

    Decimal(str(value)) respects the supplied float's decimal representation;
    fixed-point GHz avoids scientific notation in page names and trace keys.
    """
    value = Decimal(str(frequency_hz))
    if not value.is_finite() or value < 0:
        raise ValueError("Frequency must be finite and nonnegative.")
    result = format(value / Decimal("1000000000"), "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result in ("", "-0") else result


def frequency_time_pages(doc: VszDoc, frequency_hz: Sequence[float], time_dataset: str,
                         channel_frequency_datasets: Mapping[str, Sequence[str]], *,
                         xlabel: str = "Time", xmode: str = "datetime",
                         datetime_format: str = "%VDY-%VDm-%VDd %VDH:%VDM:%VDS") -> list[str]:
    """Append one page per frequency and a combined page; preserve all raw data.

    Mapping keys identify independent analyzer channels. Mapping values list
    one raw 1-D dataset per frequency, in input order. Each Freq_N_GHz page
    overlays the analyzer channels at that frequency. Combined_Freq_vs_Time
    uses one panel per analyzer channel, so every panel's legend is exactly
    'N GHz', without merging incompatible hold/detector channels or creating
    ambiguous duplicate labels. One analyzer channel produces one graph.

    No averaging/interpolation/decimation occurs here. All bins are included;
    large sweeps necessarily create many pages and crowded combined legends.
    The caller must avoid naming conflicts with existing document pages.
    """
    frequency_names = [frequency_ghz_text(value) for value in frequency_hz]
    channels = list(channel_frequency_datasets.items())
    if not frequency_names or len(frequency_names) != len(set(frequency_names)):
        raise ValueError("At least one frequency with unique GHz text is required.")
    if not channels or any(len(names) != len(frequency_names) for _, names in channels):
        raise ValueError("Each analyzer channel requires one dataset per frequency.")
    if xmode not in ("numeric", "datetime"):
        raise ValueError("xmode must be numeric or datetime.")
    pages = []
    for frequency_index, ghz_text in enumerate(frequency_names):
        page_name = "Freq_" + ghz_text + "_GHz"
        traces = [Trace(time_dataset, names[frequency_index], channel_name,
                        colour=TRACE_COLOURS[channel_index % len(TRACE_COLOURS)],
                        marker="circle", marker_size="2pt")
                  for channel_index, (channel_name, names) in enumerate(channels)]
        xy_page(doc, page_name, traces, title=ghz_text + " GHz versus time",
                xlabel=xlabel, ylabel="Level (dBm)", xmode=xmode, key=True)
        if xmode == "datetime" and datetime_format:
            doc.to(page_name)
            doc.set("graph/x/TickLabels/format", datetime_format)
            doc.up()
        pages.append(page_name)
    panels = []
    styles = ("solid", "dashed", "dotted", "dash-dot")
    for channel_name, datasets in channels:
        traces = [Trace(time_dataset, dataset_name, frequency_names[index] + " GHz",
                        colour=TRACE_COLOURS[index % len(TRACE_COLOURS)],
                        style=styles[(index // len(TRACE_COLOURS)) % len(styles)],
                        marker="circle", marker_size="2pt")
                  for index, dataset_name in enumerate(datasets)]
        panels.append(Panel(traces, title=channel_name, xlabel=xlabel,
                            ylabel="Level (dBm)", xmode=xmode, key=True))
    page_name = "Combined_Freq_vs_Time"
    if len(panels) == 1:
        xy_page(doc, page_name, panels[0].traces, title="All frequencies versus time — " + channels[0][0],
                xlabel=xlabel, ylabel="Level (dBm)", xmode=xmode, key=True, width="30cm", height="18cm")
    else:
        grid_page(doc, page_name, panels, columns=1, title="All frequencies versus time",
                  width="30cm", height=str(max(18, 10 * len(panels))) + "cm")
    if xmode == "datetime" and datetime_format:
        doc.to(page_name)
        paths = ["graph/x/TickLabels/format"] if len(panels) == 1 else [
            "grid/graph%d/x/TickLabels/format" % index for index in range(len(panels))]
        for path in paths:
            doc.set(path, datetime_format)
        doc.up()
    pages.append(page_name)
    return pages


#: Veusz text markup for a line break (two backslashes in the label text).
VEUSZ_LINE_BREAK = "\\\\"


def text_page(doc: VszDoc, page: str, title: str, lines: Sequence[str], font: str = "Courier New",
              size: str = "9pt", lines_per_page: int = 40, width: str = "25cm",
              height: str = "15cm") -> list[str]:
    """Pages of plain text lines (escaped; monospaced by default) (0.0.12).

    Long texts continue on pages "<page>_2", "<page>_3", ...; returns the
    page names. Lines are escaped with vz_text and joined with Veusz's line
    break, so they print exactly as given. "Courier New" maps to a
    monospaced font on every platform (fontconfig substitutes on Linux).
    """
    pages: list[str] = []
    chunks = [list(lines[i:i + lines_per_page]) for i in range(0, max(len(lines), 1), lines_per_page)] or [[]]
    for number, chunk in enumerate(chunks, start=1):
        name = page if number == 1 else f"{page}_{number}"
        doc.add("page", name)
        doc.to(name)
        doc.set("width", width)
        doc.set("height", height)
        add_title(doc, title if number == 1 else f"{title} (continued, {number})")
        doc.add("label", "body")
        doc.set("body/label", VEUSZ_LINE_BREAK.join(vz_text(line) if line else " " for line in chunk))
        doc.set("body/xPos", [0.04])
        doc.set("body/yPos", [0.90])
        doc.set("body/alignHorz", "left")
        doc.set("body/alignVert", "top")
        doc.set("body/Text/font", font)
        doc.set("body/Text/size", size)
        doc.up()
        pages.append(name)
    return pages


# %% ===========================================================================
#    BAR PAGES, STEP MASKS AND REFERENCE LINES (0.0.14)
# =============================================================================
def step_mask(lower_edges: Any, upper_edges: Any, levels: Any) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) arrays of a stepped mask: one flat segment per band.

    Each band i is drawn from ``lower_edges[i]`` to ``upper_edges[i]`` at
    ``levels[i]``; a NaN point follows every band so plotting programs
    (Veusz, pyqtgraph with connect="finite") leave a gap between bands
    instead of joining them with a sloping line. Overlapping bands are
    drawn as given (the caller decides which level applies).

    Returns
    -------
    (x, y): float arrays of length 3 * number of bands.
    """
    lower = np.asarray(lower_edges, dtype=float).ravel()
    upper = np.asarray(upper_edges, dtype=float).ravel()
    level = np.asarray(levels, dtype=float).ravel()
    if not lower.size == upper.size == level.size:
        raise ValueError("step_mask: lower_edges, upper_edges and levels differ in length")
    x_values = np.column_stack([lower, upper, np.full(lower.size, np.nan)]).ravel()
    y_values = np.column_stack([level, level, np.full(lower.size, np.nan)]).ravel()
    return x_values, y_values


def reference_line(value: float, span: Sequence[float], orientation: str = "horizontal"
                   ) -> tuple[np.ndarray, np.ndarray]:
    """(x, y) arrays of a straight threshold or marker line.

    ``orientation="horizontal"``: y = value for x from span[0] to span[1]
    (e.g. a 0 dB margin line). ``"vertical"``: x = value for y over span
    (e.g. the 1 GHz upper limit of a standard).
    """
    start, stop = float(span[0]), float(span[1])
    if orientation == "horizontal":
        return np.array([start, stop]), np.array([float(value)] * 2)
    if orientation == "vertical":
        return np.array([float(value)] * 2), np.array([start, stop])
    raise ValueError(f"orientation must be 'horizontal' or 'vertical', not {orientation!r}")


def bar_page(doc: VszDoc, page: str, labels: str, lengths: Sequence[str], title: str = "",
             xlabel: str = "", ylabel: str = "", *, keys: Sequence[str] = (),
             colours: Sequence[str] = (), ylog: bool = False, ymin: Any = "Auto",
             ymax: Any = "Auto", width: str = "25cm", height: str = "15cm",
             left_margin: str = "2.4cm", bottom_margin: str = "2.2cm",
             top_margin: str = "1.4cm", escape: bool = True) -> None:
    """A page with a vertical category bar chart (0.0.14).

    Parameters
    ----------
    labels:
        Name of a *text* dataset with one category label per bar position;
        the x axis is put in Veusz 'labels' mode to print them.
    lengths:
        Names of numeric datasets, one per bar group member (grouped mode).
    keys:
        Legend text per dataset in ``lengths`` (a legend is added when more
        than one is given).
    colours:
        Fill colour per dataset; default TRACE_COLOURS in order.
    ylog, ymin, ymax:
        Value axis scale and limits ("Auto" or a number). Bars on a log axis
        start at the axis minimum.
    Other parameters as xy_page().
    """
    _open_page_and_graph(doc, page, title, width, height,
                         {"leftMargin": left_margin, "bottomMargin": bottom_margin,
                          "topMargin": top_margin}, escape)
    _add_axes(doc, xlabel, ylabel, False, ylog, "Auto", "Auto", ymin, ymax, "labels", escape)
    doc.add("bar", "bars")
    doc.set("bars/lengths", tuple(lengths))
    doc.set("bars/labels", labels)
    doc.set("bars/direction", "vertical")
    doc.set("bars/mode", "grouped")
    fills = []
    for index, _name in enumerate(lengths):
        colour = colours[index] if index < len(colours) else TRACE_COLOURS[index % len(TRACE_COLOURS)]
        fills.append(("solid", colour, False))
    doc.set("bars/BarFill/fills", fills)
    if keys:
        doc.set("bars/keys", tuple(vz_text(k) if escape else k for k in keys))
        if len(keys) > 1:
            doc.add("key", "key")
            doc.set("key/horzPosn", "right")
            doc.set("key/vertPosn", "top")
    doc.up()                                     # graph -> page
    doc.up()                                     # page -> where we started


# %% ===========================================================================
#    READING A WRITTEN DOCUMENT BACK (0.0.13)
# =============================================================================
def dataset_names(path: str | os.PathLike) -> list[str]:
    """Names of the datasets stored in a .vszh5 document (unescaped, sorted).

    Reads /Veusz/Data with h5py only; Veusz is not needed.
    """
    if h5py is None:
        raise RuntimeError("h5py is required to read .vszh5 documents")
    names = []
    with h5py.File(str(path), "r") as hdf:
        data_group = hdf.get("Veusz/Data")
        for member in (data_group or {}):
            stored = data_group[member].get("data")
            raw = stored.attrs.get("vsz_name") if stored is not None else None
            names.append(raw.decode("utf-8") if isinstance(raw, bytes) else
                         member.replace("`SL", "/").replace("`BT", "`"))
    return sorted(names)


def read_text_dataset(path: str | os.PathLike, name: str) -> list[str] | None:
    """The strings of a text dataset written by dataset_text(), or None if absent."""
    if h5py is None:
        raise RuntimeError("h5py is required to read .vszh5 documents")
    with h5py.File(str(path), "r") as hdf:
        group = hdf.get(f"Veusz/Data/{escape_hdf_name(name)}")
        if group is None or "data" not in group:
            return None
        return [value.decode("utf-8") if isinstance(value, bytes) else str(value)
                for value in group["data"][()]]


def page_names(path: str | os.PathLike) -> list[str]:
    """Names of the pages of a written document, in page order (0.0.13).

    Read from the Veusz command script stored in /Veusz/Document/document
    (the top-level Add('page', name=...) lines written by VszDoc), so the
    page list is known without Veusz, e.g. to build PDF bookmarks.
    """
    if h5py is None:
        raise RuntimeError("h5py is required to read .vszh5 documents")
    with h5py.File(str(path), "r") as hdf:
        stored = hdf["Veusz/Document/document"][()]
    script = b"".join(stored).decode("utf-8") if not isinstance(stored, (bytes, str)) else (
        stored.decode("utf-8") if isinstance(stored, bytes) else stored)
    return [match.group(2) for match in
            re.finditer(r"^Add\('page', name=(['\"])(.*?)\1", script, flags=re.MULTILINE)]


# %% ===========================================================================
#    FINDING AND DRIVING VEUSZ (only to open or render)
# =============================================================================
def find_veusz_exe(explicit: str = "", env_vars: Sequence[str] = ("QUICKSYN_VEUSZ", "VEUSZ_EXE")) -> str:
    """Locate the Veusz program: explicit path, env var, PATH, usual folders."""
    if explicit:
        return explicit if os.path.isfile(explicit) else ""
    for var in env_vars:
        p = os.environ.get(var, "").strip().strip('"')
        if p and os.path.isfile(p):
            return p
    names = ["veusz.exe", "veusz"] if os.name == "nt" else ["veusz"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    extra: list[str] = []
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LOCALAPPDATA", "")):
            if base:
                extra += [os.path.join(base, "Veusz", "veusz.exe"),
                          os.path.join(base, "Programs", "Veusz", "veusz.exe")]
    elif sys.platform == "darwin":
        extra.append("/Applications/Veusz.app/Contents/MacOS/veusz")
    else:
        extra += ["/opt/veusz/veusz", os.path.expanduser("~/.local/opt/veusz/veusz")]
    return next((e for e in extra if os.path.isfile(e)), "")


def _popen_kwargs() -> dict[str, Any]:
    """Hide the console window of child processes on Windows."""
    return {"creationflags": 0x08000000} if os.name == "nt" else {}


def _render_script(src: Path, pdf: Path | None, png_stem: Path | None,
                   png_pages: str, dpi: int) -> str:
    """The script piped into `veusz --listen`. Paths go through repr() so
    Windows back-slashes are safe."""
    lines = [
        "import veusz.document.loader as L",
        "doc = Root._ci.document",
        f"L.loadHDF5Doc(doc, {str(src)!r})",
        "names = [p.name for p in doc.basewidget.children]",
        "print('VSZH5_PAGES', len(names), '|'.join(names), flush=True)",
    ]
    if pdf is not None:
        lines.append(f"Export({str(pdf)!r}, page=list(range(len(names))), pdfdpi={PDF_DPI})")
    if png_stem is not None:
        upto = "len(names)" if png_pages == "all" else "min(1, len(names))"
        # The path is bound on its own line, where repr() gives a valid
        # literal; the exec() string carries no path, so a Windows back-slash
        # is never unescaped a second time (C:\\Users would become \\U...).
        lines.append(f"vszh5_png_stem = {str(png_stem)!r}")
        lines.append(
            f"exec(\"for i in range({upto}): Export(vszh5_png_stem + '_p%02d_%s.png' "
            f"% (i, names[i]), page=[i], dpi={int(dpi)})\")")
    lines += ["print('VSZH5_DONE', flush=True)", "Quit()", ""]
    return "\n".join(lines)


#: One bookmark: (title, page index) or (title, page index, children). A page
#: index of None points at the first page of the entry's first child.
OutlineEntry = tuple

#: What render_pages() accepts as bookmarks: True (one per page), False (none),
#: an outline list, or a callable mapping the Veusz page names to an outline.
Bookmarks = Union[bool, Sequence[OutlineEntry], Callable[[List[str]], Sequence[OutlineEntry]]]


def _outline_parts(entry: OutlineEntry) -> tuple[str, int | None, Sequence[OutlineEntry]]:
    """Split an outline entry into (title, page, children)."""
    if len(entry) == 2:
        return str(entry[0]), entry[1], ()
    title, page, children = entry
    return str(title), page, children or ()


def add_pdf_bookmarks(pdf_path: str | os.PathLike, outline: Sequence[OutlineEntry],
                      title: str = "", author: str = "", subject: str = "",
                      keywords: str = "", open_outline: bool = True) -> int:
    """Write a bookmark (outline) hierarchy into an existing PDF, in place.

    Parameters
    ----------
    pdf_path:
        The PDF to annotate. It is rewritten through "<name>.part" and
        os.replace(), so a reader never sees a half-written file.
    outline:
        Nested entries, see OutlineEntry. Page indices count from 0.
    title, author, subject, keywords:
        Document information; empty strings leave the existing value.
    open_outline:
        Expand every level and open the reader's bookmark pane on load.

    Returns
    -------
    int
        Number of bookmarks written.

    Raises
    ------
    ImportError
        pypdf is not installed.
    ValueError
        An entry points outside the document.
    """
    try:
        from pypdf import PdfWriter
    except ImportError as exc:
        raise ImportError("pypdf is needed for PDF bookmarks "
                          "(mamba install -c conda-forge pypdf)") from exc
    path = Path(pdf_path)
    writer = PdfWriter(clone_from=str(path))
    n_pages = len(writer.pages)

    def first_page(entry: OutlineEntry) -> int | None:
        _, page, children = _outline_parts(entry)
        if page is not None:
            return int(page)
        return next((p for p in map(first_page, children) if p is not None), None)

    count = 0

    def add(entries: Sequence[OutlineEntry], parent: Any) -> None:
        nonlocal count
        for entry in entries:
            name, _, children = _outline_parts(entry)
            target = first_page(entry)
            if target is None or not 0 <= target < n_pages:
                raise ValueError(f"bookmark {name!r} points at page {target}; "
                                 f"the PDF has {n_pages} pages")
            item = writer.add_outline_item(name, target, parent=parent, is_open=open_outline)
            count += 1
            add(children, item)

    add(outline, None)
    info = {key: value for key, value in (("/Title", title), ("/Author", author),
                                          ("/Subject", subject), ("/Keywords", keywords))
            if value}
    if info:
        writer.add_metadata(info)
    if open_outline:
        writer.page_mode = "/UseOutlines"
    part = path.with_name(path.name + ".part")
    try:
        with open(part, "wb") as handle:
            writer.write(handle)
        os.replace(part, path)
    finally:
        if part.exists():
            part.unlink()
    return count


def render_pages(vszh5: str | os.PathLike, outdir: str | os.PathLike | None = None,
                 dpi: int = 150, pdf: bool = True, png_pages: str = "all",
                 veusz_exe: str = "", timeout: float = 600.0,
                 method: str = "auto", bookmarks: Bookmarks = True,
                 pdf_info: dict[str, str] | None = None) -> list[Path]:
    """Render a .vszh5 to one multipage PDF and per-page PNG files.

    Parameters
    ----------
    vszh5:
        The document.
    outdir:
        Output folder; default is the document's folder.
    dpi:
        PNG resolution.
    pdf:
        Write "<stem>.pdf" holding every page.
    png_pages:
        "all" (every page), "first", or "none".
    veusz_exe:
        Veusz program to drive; found with find_veusz_exe() when empty.
    method:
        "auto" (the program if found, falling back to the Python package if
        the program fails or is absent), "program" (the Veusz executable
        only) or "inprocess" (the Python package only).
    bookmarks:
        Outline for the PDF: True (default) = one bookmark per page named
        after the Veusz page; a list of OutlineEntry; a callable that gets
        the page names and returns such a list; False = none. Needs pypdf;
        without it a RuntimeWarning is issued and the PDF has no outline.
    pdf_info:
        Optional document information for the PDF: title, author, subject,
        keywords (see add_pdf_bookmarks).

    Returns
    -------
    list of Path
        Files written by this call (re-rendered files included).

    Raises
    ------
    RuntimeError
        Veusz is neither installed as a program nor importable, or the
        render did not complete.
    """
    src = Path(vszh5).resolve()
    out = Path(outdir).resolve() if outdir else src.parent
    out.mkdir(parents=True, exist_ok=True)
    stem = out / src.stem
    pdf_path = stem.with_suffix(".pdf") if pdf else None
    png_stem = stem if png_pages in ("all", "first") else None
    started = time.time()

    if method not in ("auto", "program", "inprocess"):
        raise ValueError(f"method must be auto, program or inprocess, not {method!r}")
    exe = "" if method == "inprocess" else (veusz_exe or find_veusz_exe())
    if method == "program" and not exe:
        raise RuntimeError("Veusz program not found (set VEUSZ_EXE or QUICKSYN_VEUSZ to veusz.exe)")
    if exe:
        env = dict(os.environ)
        if sys.platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
        script = _render_script(src, pdf_path, png_stem, png_pages, dpi)
        ok, log = _run_listen(exe, script, env, timeout)
        names = _page_names_from_log(log)
        if not ok:
            program_error = (f"Veusz program {exe} did not finish the render "
                             f"(check that `{os.path.basename(exe)} --version` runs; set "
                             f"VEUSZ_EXE or QUICKSYN_VEUSZ to a working Veusz): {log.strip()[-600:]}")
            if method == "program":
                raise RuntimeError(program_error)
            # auto: a Veusz found on the PATH can be broken (e.g. a Linux
            # distribution package built for another Python), so try the
            # veusz Python package before giving up.
            try:
                names = _render_in_process(src, pdf_path, png_stem, png_pages, dpi)
            except RuntimeError as exc:
                raise RuntimeError(f"{program_error}\nIn-process fallback: {exc}") from exc
    else:
        names = _render_in_process(src, pdf_path, png_stem, png_pages, dpi)

    if pdf_path is not None and pdf_path.is_file() and bookmarks is not False:
        if bookmarks is True:
            outline = [(name, i) for i, name in enumerate(names)]
        elif callable(bookmarks):
            outline = list(bookmarks(list(names)))
        else:
            outline = list(bookmarks)
        try:
            if outline:
                add_pdf_bookmarks(pdf_path, outline, **(pdf_info or {}))
        except ImportError as exc:
            warnings.warn(f"{pdf_path.name} written without bookmarks: {exc}",
                          RuntimeWarning, stacklevel=2)

    # Report what this call wrote, including files that existed before and
    # were overwritten (0.0.5 compared against the folder listing taken at
    # the start, so a re-render returned nothing).
    written = [pdf_path] if pdf_path is not None else []
    if png_stem is not None:
        # Frequency-per-page exports can exceed 99 pages; :02d is a
        # minimum width, not a two-digit limit. Include p100, p1000, ... .
        written += sorted(path for path in out.glob(f"{glob.escape(png_stem.name)}_p*_*.png")
                          if re.match(re.escape(png_stem.name) + r"_p[0-9]+_", path.name))
    return sorted(p for p in written
                  if p.is_file() and p.stat().st_mtime >= started - 2.0)


def _page_names_from_log(log: str) -> list[str]:
    """Veusz page names from the VSZH5_PAGES line the render script prints."""
    for line in log.splitlines():
        if line.startswith("VSZH5_PAGES"):
            parts = line.split(maxsplit=2)
            return parts[2].split("|") if len(parts) == 3 and parts[2] else []
    return []


def _run_listen(exe: str, script: str, env: dict[str, str], timeout: float) -> tuple[bool, str]:
    """Pipe a script into `veusz --listen --quiet` and wait for the marker.

    Veusz 3.6.2 exits on Quit(); Veusz 4.2.1 only closes its hidden window
    and keeps running. Every Export() has completed by the time the script
    prints VSZH5_DONE, so after the marker the program gets two seconds to
    exit on its own and is then terminated.
    """
    import threading

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        try:
            proc = subprocess.Popen([exe, "--listen", "--quiet"], stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=err, text=True,
                                    encoding="utf-8", errors="replace", env=env,
                                    **_popen_kwargs())
        except OSError as exc:      # missing, not executable, wrong architecture
            return False, f"cannot start {exe}: {type(exc).__name__}: {exc}"
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        lines: list[str] = []
        done = False
        try:
            try:
                proc.stdin.write(script)
                proc.stdin.close()
            except OSError:
                # BrokenPipeError: the program exited before reading its
                # script (typically it cannot start at all). Not fatal here:
                # its stderr says why, and the missing VSZH5_DONE marker
                # reports the failure to the caller, which may fall back.
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            for line in proc.stdout:
                lines.append(line)
                if line.startswith("VSZH5_DONE"):
                    done = True
                    break
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
        finally:
            killer.cancel()
            if proc.poll() is None:     # an exception above: never leave Veusz behind
                proc.kill()
                proc.wait()
            proc.stdout.close()         # the pipe is ours to close (ResourceWarning)
        err.seek(0)
        return done, "".join(lines) + err.read()


def _render_in_process(src: Path, pdf_path: Path | None, png_stem: Path | None,
                       png_pages: str, dpi: int) -> list[str]:
    """Fallback: render with the veusz Python package in this process.

    Returns the page names, for the PDF bookmarks.
    """
    try:
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import veusz.qtall as vqt
        _app = vqt.QApplication.instance() or vqt.QApplication([])
        import veusz.document as vdoc
        import veusz.widgets  # noqa: F401  registers widget types
        import veusz.dataimport  # noqa: F401  registers Import* commands used by the loader
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Veusz not found: install it (conda-forge 'veusz' or the "
                           "Veusz installer) or set VEUSZ_EXE (or QUICKSYN_VEUSZ) to veusz.exe "
                           f"[{type(exc).__name__}: {exc}]") from exc
    doc = vdoc.Document()
    doc.load(str(src), mode="hdf5")
    pages = doc.basewidget.children
    if not pages:
        raise RuntimeError(f"{src.name} loaded as an empty Veusz document")
    ci = vdoc.CommandInterface(doc)
    if pdf_path is not None:
        ci.Export(str(pdf_path), page=list(range(len(pages))), pdfdpi=PDF_DPI)
    if png_stem is not None:
        upto = len(pages) if png_pages == "all" else 1
        for i in range(upto):
            ci.Export(f"{png_stem}_p{i:02d}_{pages[i].name}.png", page=[i], dpi=dpi)
    return [page.name for page in pages]


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# import numpy as np
# from vszh5_writer import VeuszWriter, VszDoc, render_pages
# t = np.linspace(0, 10, 501); v = np.sin(t)
# doc = VszDoc("scratch"); doc.add("page", "p"); doc.to("p")
# doc.add("graph", "g"); doc.to("g"); doc.add("axis", "x"); doc.add("axis", "y")
# doc.set("y/direction", "vertical"); doc.add("xy", "c")
# doc.set("c/xData", "t"); doc.set("c/yData", "v"); doc.set("c/marker", "none")
# doc.up(); doc.up()
# with VeuszWriter("scratch.vszh5") as w:
#     w.dataset_1d("t", t); w.dataset_1d("v", v); w.finish(doc.text())
# print(render_pages("scratch.vszh5", png_pages="first"))
