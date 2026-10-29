#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Build the SHR Converter manual (LuaLaTeX, PDF with a bookmark hierarchy).

===============================================================================
 Title          : SHR Converter - manual builder
 Filename       : tools/build_manual.py
 Version        : 0.0.2 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12
 Requires       : shr_converter_core.py, shr_reader.py, vszh5_writer.py (same
                  package); a TeX installation with lualatex (TeX Live or
                  MiKTeX) and the packages fontspec, hyperref, bookmark,
                  booktabs, longtable, tabularx, graphicx, amsmath, xcolor,
                  caption, enumitem
 Licence        : GPL-3.0-or-later
===============================================================================

Writes docs/SHR_Converter_Manual_v<version>.tex and compiles it twice with
lualatex (the second run resolves the contents and the bookmarks). Tables of
options, command-line flags, header fields, the .shr byte layout, the
enumerations with their confidence and the modules used are generated from
the program itself, so the manual cannot drift from the code. Measured
figures are read from docs/validation/*_<version>.txt when present.

    python tools/build_manual.py            # from the package folder

REVISION HISTORY (newest first)
-------------------------------
 0.0.2  2026-10-28  shr_reader replaces py-shr-parser: new chapters "The .shr
                    format and shr_reader" (byte layout and enumeration tables
                    generated from shr_reader), "Multi-file recordings" and
                    "CSV time decimation" (with derivations); even-grid chapter
                    rewritten for vszh5_writer 0.0.21; measured numbers from
                    the 0.0.2 logs, including the SM200C-rate check; IEEE
                    references renumbered to match shr_converter_core.
 0.0.1  2026-10-28  First internal draft.
"""

# %% IMPORTS
from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shr_converter_core as core  # noqa: E402
import shr_reader as reader  # noqa: E402
import vszh5_writer as writer  # noqa: E402

# C type of each struct code in shr_reader.HEADER_LAYOUT (for the byte-layout table).
C_TYPES = {"H": "uint16", "I": "uint32", "Q": "uint64", "i": "int32", "d": "double", "f": "float",
           "B": "uint8", "256s": "uint16[128]", "64s": "uint8[64]", "15s": "uint8[15]"}

DOCS = ROOT / "docs"
NAME = f"SHR_Converter_Manual_v{core.__version__}"


# %% TEXT HELPERS
def tex(text: object) -> str:
    """Escape plain text for LaTeX."""
    s = str(text)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
                 ("_", r"\_"), ("{", r"\{"), ("}", r"\}"), ("~", r"\textasciitilde{}"),
                 ("^", r"\textasciicircum{}"), ("<", r"\textless{}"), (">", r"\textgreater{}")):
        s = s.replace(a, b)
    return s.replace("\\textbackslash\\{\\}", r"\textbackslash{}")


def tt(text: object) -> str:
    """Monospaced, escaped, breakable at underscores."""
    return r"\texttt{" + tex(text).replace(r"\_", r"\_\allowbreak{}") + "}"


def table(columns: str, header: list[str], rows: list[list[str]], caption: str = "") -> str:
    """A longtable with booktabs rules (cells are already LaTeX)."""
    out = [r"\begin{longtable}{" + columns + "}"]
    if caption:
        out.append(r"\caption{" + caption + r"}\\")
    out += [r"\toprule", " & ".join(r"\textbf{" + h + "}" for h in header) + r"\\", r"\midrule", r"\endhead"]
    out += [" & ".join(r) + r"\\" for r in rows]
    out += [r"\bottomrule", r"\end{longtable}"]
    return "\n".join(out)


def figure(path: str, caption: str, width: str = r"\linewidth") -> str:
    """An included figure if the file exists (paths relative to docs/)."""
    if not (DOCS / path).is_file():
        return ""
    return (r"\begin{figure}[htbp]\centering" "\n" rf"\includegraphics[width={width}]{{{path}}}" "\n"
            rf"\caption{{{caption}}}" "\n" r"\end{figure}")


def measured(pattern: str, default: str, text: str) -> str:
    """First regex group found in the validation text, else ``default``."""
    match = re.search(pattern, text)
    return match.group(1) if match else default


# %% CONTENT
def build() -> str:
    """The complete LaTeX source."""
    v = core.__version__
    validation = ""
    for name in (f"long_capture_and_memory_{v}.txt", f"validation_{v}.txt"):
        path = DOCS / "validation" / name
        if path.is_file():
            validation += path.read_text(encoding="utf-8", errors="replace")
    # -- measured numbers (from the validation logs of this release) --------------------------
    # Each pattern finds the section of one check, then the first matching line after it; the
    # defaults are the values measured on 2026-10-28 (used only when a log is missing).
    slow = measured(r"4001 bins, 1\.5 ms jitter.*\n(?:.*\n)*?converted in ([0-9.]+ s)", "27.9 s", validation)
    slow_rss = measured(r"4001 bins, 1\.5 ms jitter.*\n(?:.*\n)*?peak RSS of the process tree: ([0-9,]+ MiB)",
                        "865 MiB", validation)
    fast = measured(r"\(540 000 sweeps.*\n(?:.*\n)*?converted in ([0-9.]+ s)", "58.9 s", validation)
    fast_rss = measured(r"\(540 000 sweeps.*\n(?:.*\n)*?peak RSS of the process tree: ([0-9,]+ MiB)",
                        "560 MiB", validation)
    mem_rss = measured(r"Peak RSS of tree\s*: ([0-9,]+ MiB)", "417 MiB", validation)
    mem_time = measured(r"CSV written\s*: [0-9,]+ MiB in ([0-9.]+ s)", "21.4 s", validation)
    sm_time = measured(r"sm200c_rate_check.*\n(?:.*\n)*?converted in ([0-9.]+ s)", "11.4 s", validation)
    sm_rate = measured(r"sm200c_rate_check.*\n(?:.*\n)*?converted in [0-9.]+ s: [0-9.]+ M samples/s, "
                       r"([0-9.]+ MiB/s) of SHR", "100.5 MiB/s", validation)
    sm_rss = measured(r"sm200c_rate_check.*\n(?:.*\n)*?peak RSS of the process tree: ([0-9,]+ MiB)",
                      "477 MiB", validation)
    n_reader = measured(r"shr_reader [0-9.]+ self-test: (\d+)/\d+ passed", "39", validation)
    n_self = measured(r"(\d+) passed, 0 failed", "58", validation)
    n_pytest = measured(r"(\d+) passed, \d+ subtests passed", "34", validation)

    # -- the .shr format, generated from shr_reader ---------------------------------------------
    layout_rows = []
    for py_name, code, sdk_name in reader.HEADER_LAYOUT:
        layout_rows.append([str(reader.HEADER_OFFSETS[py_name]), tt(sdk_name), tt(py_name),
                            tex(C_TYPES.get(code, code))])
    sweep_layout_rows = [["0", tt("timestamp"), tt("timestamp_ms"), "uint64"],
                         ["8", tt("latitude"), tt("latitude"), "double"],
                         ["16", tt("longitude"), tt("longitude"), "double"],
                         ["24", tt("altitude"), tt("altitude_m"), "double"],
                         ["32", tt("adcOverflow"), tt("adc_overflow"), "uint8"],
                         ["33", tt("reserved[15]"), tt("reserved"), "uint8[15]"],
                         ["48", tex("sweep data"), tt("amplitude"), tex("float32 x sweepLength")]]
    enum_rows = []
    for field_name, codes in reader.ENUM_FIELDS.items():
        for code, (label, confidence) in sorted(codes.items()):
            enum_rows.append([tt(field_name), str(code), tex(label), tex(confidence)])
    join_required = ", ".join(tt(n) for n in reader.JOIN_REQUIRED)
    join_noted = ", ".join(tt(n) for n in reader.JOIN_NOTED)
    decimate_rows = [[tt(k), tex(text)] for k, text in core.CSV_DECIMATE_DETECTORS.items()]

    # -- generated tables ------------------------------------------------------------------------
    defaults = core.ConvertOptions()
    option_rows = []
    for f in dataclasses.fields(core.ConvertOptions):
        value = getattr(defaults, f.name)
        option_rows.append([tt(f.name), tt(repr(value) if not isinstance(value, str) else f'"{value}"')])
    parser = core.build_arg_parser()
    cli_rows = []
    for action in parser._actions:                  # argparse keeps them in this list
        flags = ", ".join(action.option_strings) or action.dest
        if flags in ("-h, --help",):
            continue
        cli_rows.append([tt(flags), tex((action.help or "").replace("%%", "%"))])   # argparse escapes %
    header_rows = [[tt(n), tex(u), tex(t)] for n, u, t in core.HEADER_FIELDS]
    page_rows = [[tt(k), tex(v)] for k, v in core.PAGE_TITLES.items()]
    module_rows = [
        [tt(f"shr_reader ({reader.__version__})"),
         tex("ShrHeader, ShrFile, ShrFileSet, group_recordings, detect_amplitude_grid"),
         tex("reads every header and sweep (memory-mapped, one vectorised read per block); "
             "picklable, so each worker opens its own map [1]")],
        [tt("struct"), tex("Struct('<HHIQIIdd256s...64s')"), tex("the 472-byte file header in one call [1]")],
        [tt("numpy"), tex("memmap with a structured dtype, float32/float64 arrays, ufunc.reduceat, "
                          "add.reduceat, percentile"),
         tex("sweep records, statistics, block and CSV decimation, per-sweep table on disk")],
        [tt("cupy (optional)"), tex("same array calls on the GPU"),
         tex("statistics and spectrogram reduction per sub-block [8]")],
        [tt("concurrent.futures"), tex("ProcessPoolExecutor (spawn, max_tasks_per_child)"),
         tex("parallel blocks, bounded and in order [7]")],
        [tt("h5py via vszh5_writer"), tex("VeuszWriter, image_page, xy_page, grid_page, text_page"),
         tex("native .vszh5 without Veusz")],
        [tt(f"vszh5_writer ({writer.__version__})"), tex("block_reduce, regularize_rows, render_pages"),
         tex("thinning, even spectrogram grid, PDF/PNG with bookmarks [3]")],
        [tt("Qt.py + PySide6"), tex("QtCore, QtGui, QtWidgets"), tex("the GUI through the abstraction layer [15]")],
        [tt("pyqtgraph"), tex("ImageItem, ColorBarItem, PlotDataItem"), tex("preview plots")],
        [tt("psutil"), tex("Process().memory_info()"), tex("memory read-out and tests")],
        [tt("pypdf (via the writer)"), tex("PdfWriter.add_outline_item"), tex("PDF bookmark tree")],
        [tt("ctypes"), tex("malloc_trim (Linux), EmptyWorkingSet (Windows)"), tex("return freed memory to the OS")],
    ]
    # IEEE-style references; [1]-[11] are numbered as in shr_converter_core's docstring (R1-R11).
    refs = [
        ("1", r"Signal Hound, ``SHR parsing example'' (\code{shr\_parse.h}, \code{shr\_parse.cpp}), in "
              r"\emph{Signal Hound Software Development Kit}, release of 2026-10-05.",
         "https://signalhound.com/software/signal-hound-software-development-kit-sdk/"),
        ("2", r"Signal Hound, ``.shr file format specification,'' BB Series Discussions forum, May--Aug. 2018.",
         "https://signalhound.com/?p=158701"),
        ("3", rf"W. W. Wallace, ``vszh5\_writer.py --- Veusz HDF5 document writer,'' v{writer.__version__}, "
              r"NRAO/GBO, 2026 (shipped with this program).", ""),
        ("4", r"Hewlett-Packard, ``Measuring Noise and Noise-like Digital Communications Signals with a Spectrum "
              r"Analyzer,'' Application Note 1303, lit.\ no.\ 5966-4008E.",
         "https://www.hpmemoryproject.org/an/pdf/an_1303.pdf"),
        ("5", r"IEEE, ``IEEE Standard for Floating-Point Arithmetic,'' IEEE Std 754-2019, pp.~1--84, Jul. 2019, "
              r"doi: 10.1109/IEEESTD.2019.8766229.", "https://doi.org/10.1109/IEEESTD.2019.8766229"),
        ("6", r"Microsoft, ``Excel specifications and limits.''",
         "https://support.microsoft.com/en-us/office/1672b34d-7043-467e-8e27-269d656771c3"),
        ("7", r"Python Software Foundation, ``concurrent.futures --- Launching parallel tasks,'' Python 3.12.",
         "https://docs.python.org/3.12/library/concurrent.futures.html"),
        ("8", r"Preferred Networks, ``CuPy documentation.''", "https://docs.cupy.dev/"),
        ("9", r"Signal Hound, ``Technical Software and Hardware Change Log'' (Spike), v4.0.17, Sep. 2026 "
              r"(max/min detectors 3.5.7; multi-file sweep recording 3.9.7; limit-line triggered recording 4.0.17).",
         "https://signalhound.com/sigdownloads/Spike/change_log.txt"),
        ("10", r"T. Schmitz, ``py-shr-parser: Python library for parsing Signal Hound SHR files,'' v1.0.0, "
               r"WiSE Lab, Carnegie Mellon Univ., 2025.", "https://github.com/WiseLabCMU/py-shr-parser"),
        ("11", r"Signal Hound, ``SM200A/B/C -- SM435B/C Product Manual,'' Jan. 2025 (min/max processing at "
               r"0.01~dB resolution).", "https://signalhound.com/sigdownloads/SM200A/SM-User-Manual.pdf"),
        ("12", r"Signal Hound, ``Spike Software Documentation'' (Sweep Record and Playback).",
         "https://signalhound.com/sigdownloads/Spike/docs/html/index.html"),
        ("13", r"Keysight Technologies, ``Spectrum Analysis Basics,'' Application Note 150, 5952-0292.",
         "https://www.keysight.com/us/en/assets/7018-06714/application-notes/5952-0292.pdf"),
        ("14", r"J. Sanders, ``Veusz --- a scientific plotting package.''", "https://veusz.github.io/"),
        ("15", r"M. Ottosson \emph{et al.}, ``Qt.py,'' v2.0.7.", "https://github.com/mottosso/Qt.py"),
        ("16", r"R. Regan, ``Number of digits required for round-trip conversions,'' Exploring Binary.",
         "https://www.exploringbinary.com/number-of-digits-required-for-round-trip-conversions/"),
    ]

    # -- CSV volume of a 3-hour recording at the SM200C sample's rate (decimation chapter) -------
    # The sample holds 460 sweeps over 15.341 s (459 intervals), i.e. 29.92 sweeps/s x 8384 bins.
    sm_rate_hz = 459.0 / 15.341
    sm_bins = 8384
    sm_sweeps = int(sm_rate_hz * 3 * 3600)
    sm_shr_bytes = reader.FILE_HEADER_SIZE + sm_sweeps * (reader.SWEEP_HEADER_SIZE + 4 * sm_bins)
    volume_rows = []
    for n_combine in (1, 10, 30, 300):
        csv_rows = -(-sm_sweeps // n_combine)                    # ceil: the last row may be shorter
        csv_bytes = core.estimate_csv_bytes(core.ConvertOptions(csv_decimate=n_combine), csv_rows, sm_bins)
        volume_rows.append([str(n_combine), tex(f"{csv_rows:,}"), tex(f"{n_combine / sm_rate_hz:.2f} s"),
                            tex(core.human_bytes(csv_bytes))])

    return rf"""% !TeX program = lualatex
% SHR Converter {v} - user and technical manual. Generated by tools/build_manual.py; edit that, not this.
\documentclass[11pt,a4paper]{{article}}
\usepackage{{fontspec}}
\usepackage[margin=2.2cm]{{geometry}}
\usepackage{{amsmath,amssymb}}
\usepackage{{booktabs,longtable,tabularx,array}}
\usepackage{{graphicx}}
\usepackage{{xcolor}}
\usepackage{{caption}}
\usepackage{{enumitem}}
\usepackage[hidelinks,bookmarksnumbered,bookmarksopen,bookmarksopenlevel=2,
            pdftitle={{SHR Converter {v} - Manual}},
            pdfauthor={{William W. Wallace}},
            pdfsubject={{Signal Hound Spike .shr to CSV and Veusz .vszh5}},
            pdfkeywords={{Signal Hound, Spike, SM200C, SHR, CSV, Veusz, vszh5, spectrogram}}]{{hyperref}}
\usepackage{{bookmark}}
\urlstyle{{same}}
\setlength{{\LTcapwidth}}{{\linewidth}}
\setlength{{\emergencystretch}}{{3em}}
\captionsetup[longtable]{{justification=centering}}
\newcommand{{\code}}[1]{{\texttt{{#1}}}}
\title{{SHR Converter {v}\\[4pt]\large Signal Hound Spike \code{{.shr}} recordings to CSV and native Veusz documents\\
User and technical manual}}
\author{{William W. Wallace\\NRAO/GBO\\\code{{wwallace@nrao.edu}}}}
\date{{2026-10-28}}
\begin{{document}}
\maketitle
\begin{{center}}
\begin{{tabular}}{{ll}}
\toprule
Program & Version\\
\midrule
\code{{shr\_converter.py}} (launcher) & {v}\\
\code{{shr\_converter\_gui.py}} & {v}\\
\code{{shr\_converter\_core.py}} & {v}\\
\code{{shr\_reader.py}} (reader) & {reader.__version__}\\
\code{{vszh5\_writer.py}} & {writer.__version__}\\
\bottomrule
\end{{tabular}}
\end{{center}}
\tableofcontents
\clearpage

\section{{Overview}}
Spike, Signal Hound's analyzer software, records sweeps to \code{{.shr}} files: a 472-byte file header, then
per sweep a 48-byte sweep header (time stamp, GPS latitude/longitude/altitude, ADC-overflow flag) and the
amplitudes as 32-bit floats \cite{{r1}},\cite{{r2}}. The SHR Converter reads these files with its own reader,
\code{{shr\_reader}}, written from the definition in Signal Hound's SDK (\code{{shr\_parse.h}}) \cite{{r1}} and
needing only NumPy. It writes CSV tables and a native Veusz document (\code{{.vszh5}}) through the author's
\code{{vszh5\_writer}} \cite{{r3}}, optionally rendered by Veusz \cite{{r14}} to a bookmarked PDF and PNGs.
Everything is streamed in blocks, so memory is set by a RAM budget and not by the file, and the blocks run in
parallel worker processes, with the numerical part on the GPU when CuPy is present.

\subsection{{What is new in {v}}}
\begin{{itemize}}[nosep]
\item \textbf{{Own reader.}} Version 0.0.1 used py-shr-parser 1.0.0 \cite{{r10}}, which stops with
      \code{{ValueError: 2 is not a valid ShrVideoDetector}} on SM200C recordings from current Spike releases:
      their \code{{detector}} field holds code 2, which the SDK's enumeration does not list. \code{{shr\_reader}}
      keeps every raw code, labels it with a stated confidence and never refuses a file for an unknown value
      (Section~\ref{{sec:format}}).
\item \textbf{{Multi-file recordings}} (Spike~3.9.7 \cite{{r9}}) are joined into one recording
      (Section~\ref{{sec:join}}).
\item \textbf{{CSV time decimation}}: N sweeps per CSV row, by peak hold, power mean or minimum hold
      (Section~\ref{{sec:decimate}}).
\item \textbf{{vszh5\_writer {writer.__version__}}}: no false blank spectrogram rows from millisecond time-stamp
      jitter (Section~\ref{{sec:grid}}).
\item GHz axes above 10~GHz, short page titles, wrapped header page; detector shown on the statistics page.
\end{{itemize}}

\section{{Installation}}
\begin{{enumerate}}[nosep]
\item \code{{mamba env create -f environment.yml}} --- Python 3.12; pip installs \code{{requirements.txt}}
      (NumPy, h5py, Qt.py, PySide6, pyqtgraph, psutil, pypdf).
\item \code{{mamba activate shr-converter}}
\item Optional: \code{{mamba install -c conda-forge veusz}} (or the Veusz installer) to open and render;
      \code{{mamba install -c conda-forge cupy}} for an NVIDIA GPU.
\item \code{{python shr\_converter.py --selftest --gui-smoke}} --- {n_reader} reader checks, {n_self} engine checks
      and 12 GUI checks.
\item \code{{python shr\_converter.py}} starts the GUI. On Windows: \code{{create\_environment.bat}} once,
      then \code{{run\_shr\_converter.bat}} (files may be dropped on it) and \code{{run\_selftest.bat}}.
\item \code{{python shr\_converter.py --reader file.shr}} prints a file's header, enumerations, notes and
      amplitude grid without converting anything (\code{{--json}}, \code{{--group}}, \code{{--grid}}).
\end{{enumerate}}
The launcher imports nothing heavy at its top level: worker processes started with \emph{{spawn}} re-run the
main script's top level, and this keeps Qt (about 50~MB per process) out of them.

\section{{\texorpdfstring{{The \code{{.shr}} format and \code{{shr\_reader}}}}{{The .shr format and shr\_reader}}}}\label{{sec:format}}
\subsection{{Byte layout}}
All fields are little-endian and packed (no padding) \cite{{r1}}. A file of $S$ bytes with $n$ bins per sweep
holds
\begin{{equation}}
N_\mathrm{{complete}}=\left\lfloor\frac{{S-\code{{dataOffset}}}}{{48+4n}}\right\rfloor
\end{{equation}}
complete sweep records of $48+4n$ bytes each; the SM200C sample ($n=8384$) has records of 33\,584 bytes. The
reader parses the header with one \code{{struct}} call and maps the records as a NumPy structured array, so a
block of sweeps is one slice of a memory map and no Python loop runs per sweep.
{table("rp{3.4cm}p{4.2cm}l", ["Offset", "SDK name", "shr\\_reader name", "C type"], layout_rows,
       "File header (472 bytes), generated from shr\\_reader.HEADER\\_LAYOUT.")}
{table("rp{3.4cm}p{4.2cm}l", ["Offset", "SDK name", "shr\\_reader name", "C type"], sweep_layout_rows,
       "One sweep record: 48-byte sweep header, then the amplitudes.")}

\subsection{{Enumerations and their confidence}}
Every enumerated field is stored as its raw integer. Labels carry a confidence: \emph{{documented}} (in
\code{{shr\_parse.h}}), \emph{{inferred}} (from data, see below) or \emph{{unverified}} (by analogy, no file seen).
Any other code is shown as ``unknown (code $c$)'' and becomes a note; it never stops a conversion.
{table("p{4.2cm}rp{4.4cm}l", ["Field", "Code", "Label", "Confidence"], enum_rows,
       "Enumerations, generated from shr\\_reader.ENUM\\_FIELDS.")}

\subsection{{Why detector code 2 is read as Max}}
Spike~3.5.7 added max and min detectors \cite{{r9}}; the SDK lists only 0~=~MinMax and 1~=~Average
\cite{{r1}}. Two independent tests on the SM200C sample (460 sweeps $\times$ 8384 bins, detector~2) point to
Max:
\begin{{enumerate}}[nosep]
\item \textbf{{Amplitude grid.}} For min/max processing the SM series converts each FFT to 0.01~dB resolution
      \cite{{r11}}. All 4\,999 distinct values of the sample satisfy
      \begin{{equation}}x=0.01\,k+0.00824~\mathrm{{dB}},\qquad k\in\mathbb Z,\end{{equation}}
      with a largest residual of $7.3\times10^{{-6}}$~dB (float32 precision). An average detector gives
      continuous values, so the file came through the min/max path.
\item \textbf{{Noise shape.}} In a noise-only bin the power of one FFT is exponential (unit mean). The maximum
      $M$ of $K$ FFTs has
      \begin{{equation}}
      P(M\le x)=\left(1-e^{{-x}}\right)^K,\qquad \mathrm E[M]=H_K=\sum_{{k=1}}^{{K}}\frac1k\approx\ln K+\gamma ,
      \end{{equation}}
      and $M-\ln K$ tends to the Gumbel distribution (standard deviation $\pi/\sqrt6\approx1.283$, skewness
      $+1.14$). With $Y=10\log_{{10}}M$ and $\mathrm dY=\frac{{10}}{{\ln10}}\frac{{\mathrm dM}}{{M}}$,
      \begin{{equation}}
      \sigma_Y\approx\frac{{10}}{{\ln 10}}\,\frac{{\pi/\sqrt6}}{{\ln K+\gamma}}
      =\frac{{4.343\times1.283}}{{6.238+0.577}}=0.82~\mathrm{{dB}}\quad(K=512),
      \end{{equation}}
      skewed to the right. The sample's noise bins give $\sigma=0.745$~dB and skewness $+0.51$, against
      0.77~dB and $+0.50$ simulated for the max of 512 FFTs. A minimum gives $\sigma_Y=5.57$~dB for every $K$,
      and a power average gives $\sigma_Y\approx4.343/\sqrt K$ with negative skew; neither fits.
\end{{enumerate}}
The full analysis is in \code{{docs/design/SM200C\_SHR\_PARSER\_BRIEF\_0.0.1.md}}. Code~3~=~Min is assumed by
analogy, and what a MinMax (code~0) file stores is not known; both are among the questions to Signal Hound
(\code{{docs/SignalHound\_support\_letter\_2026-10-28.md}}).
{figure("design/figures/sm200c_sample_analysis.png", "SM200C sample: (a) max, power mean and min over 460 sweeps; (b) spectrogram; (c) noise distribution against detector models (max of K = 512 FFTs fits).")}

\subsection{{Amplitude-grid detection}}
\code{{detect\_amplitude\_grid}} scales the distinct values by the step $q=0.01$~dB and takes their common
fractional part as a circular mean,
\begin{{equation}}
\phi=\frac{{1}}{{2\pi}}\arg\Big(\frac1m\sum_{{j=1}}^{{m}}e^{{2\pi i\,(x_j/q\bmod 1)}}\Big)\bmod 1,
\qquad r_j=\Big|\Big(\frac{{x_j}}{{q}}-\phi+\tfrac12\Big)\bmod 1-\tfrac12\Big|\,q ,
\end{{equation}}
so an offset near 0 (values just below and just above whole steps) is not averaged to $q/2$. The values are on
the grid when $\max_j r_j<5\times10^{{-4}}$~dB and there are at least 16 distinct values. The converter then
notes that fixed-decimal CSV output moves values by up to half a step; lossless output is unaffected.

\subsection{{Validation and salvage}}
\begin{{itemize}}[nosep]
\item Signature other than \code{{0xAA10}}, impossible sizes or a header shorter than 472 bytes: \code{{ShrFormatError}}.
\item Version above {reader.SHR_MAX_KNOWN_VERSION}: read with the version-{reader.SHR_MAX_KNOWN_VERSION} layout, with a note.
      \code{{dataOffset}} larger than 472 is honoured.
\item \code{{sweepCount}} = 0 (recording not closed): the complete sweeps present are read.
\item \code{{sweepCount}} larger than $N_\mathrm{{complete}}$ (cut short): $N_\mathrm{{complete}}$ sweeps are read.
\item Complete sweeps beyond \code{{sweepCount}}, and trailing bytes after the last complete sweep: ignored,
      with a note.
\item Every note reaches the GUI, the log, \code{{\_header.csv}} and the header page.
\end{{itemize}}

\subsection{{Using the reader from Python}}
\begin{{itemize}}[nosep]
\item \code{{open\_recording(path or list)}} returns a \code{{ShrFile}} or, for several files, a
      \code{{ShrFileSet}}; both have \code{{n\_sweeps}}, \code{{n\_bins}}, \code{{header}},
      \code{{frequencies\_hz()}}, \code{{read(start, stop, step, col0, col1)}} (a \code{{SweepBlock}} of
      amplitudes, time stamps, GPS and overflow), \code{{get\_sweep(k)}}, \code{{iter\_blocks()}} and
      \code{{close()}}.
\item Objects pickle as path and sweep count, so a worker process opens its own memory map; \code{{close()}}
      releases the map, which Windows needs before a file can be moved or deleted.
\item \code{{write\_shr()}} writes a valid file (tests and synthetic recordings).
\end{{itemize}}

\section{{The window}}
{figure("figures/gui_dark.png", "Dark theme, a synthetic 3-hour capture inspected: input list and settings (left), preview (centre), log (bottom).")}
{figure("figures/gui_light.png", "Light theme (View > Theme, or Ctrl+T to toggle).")}
\subsection{{Menus and keys}}
\begin{{description}}[nosep,leftmargin=2.2cm,style=nextline]
\item[File] Add files (Ctrl+O), Add folder (Ctrl+Shift+O), Recent inputs, Remove (Del), Clear, Output folder,
      Open output folder (Ctrl+Shift+D), Save/Load settings (JSON), Save log, Quit.
\item[Edit] Copy file info, copy/clear log, \textbf{{Free memory}} (Ctrl+Shift+M).
\item[View] \textbf{{Theme: System / Light / Dark}}, toggle light/dark (Ctrl+T), auto-range (Ctrl+0), panels,
      toolbar, full screen (F11).
\item[Convert] Inspect (Ctrl+I), Convert all (F5), Convert selected (Shift+F5), Stop (Esc), Show plan (Ctrl+P),
      Self-test.
\item[Veusz] Open the \code{{.vszh5}} in Veusz (Ctrl+Shift+Z), Render to PDF/PNG (Ctrl+R), Open PDF.
\item[Help] Manual (F1), keyboard shortcuts, About (author, licence, every loaded version), About Qt.
\end{{description}}
\subsection{{Workflow}}
\begin{{enumerate}}[nosep]
\item Add files. Each header is read at once (sweeps, bins, span, length, detector); notes report cut-short
      recordings, unknown codes and the 0.01~dB grid.
\item Settings: \emph{{CSV > Combine N sweeps per row}} with its detector (Section~\ref{{sec:decimate}});
      \emph{{Selection > Join the files of one recording}} (Section~\ref{{sec:join}}).
\item \textbf{{Inspect}} runs the complete statistics pass without writing any file --- the same code as
      Convert --- and shows the preview. The \emph{{File info}} tab shows the plan (Figure~\ref{{fig:info}}).
\item \textbf{{Convert}}: one worker pool serves the whole batch; each file's preview arrives when it is
      done. \textbf{{Stop}} ends after the current block and deletes that file's partial outputs. Every file
      of a joined recording shows its status.
\end{{enumerate}}
\begin{{figure}}[htbp]\centering\includegraphics[width=\linewidth]{{figures/gui_fileinfo.png}}
\caption{{File info: header, plan, CSV estimate, seconds per spectrogram row and free disk space.}}\label{{fig:info}}
\end{{figure}}

\section{{Outputs}}
\subsection{{CSV}}
\begin{{description}}[nosep,leftmargin=3.6cm,style=nextline]
\item[\code{{sweeps\_as\_rows}}] one row per sweep: index, time columns, GPS, overflow, then one column per
      frequency (header: the bin frequencies in Hz). The default.
\item[\code{{frequencies\_as\_rows}}] one row per bin: frequency, then one column per sweep. Needs every
      selected sweep of a column block at once, so the file is read once per block (the plan says how often).
\item[\code{{long}}] one row per sample: index, time columns, frequency, amplitude.
\end{{description}}
With \code{{csv\_decimate}} $>1$ a \code{{sweeps\_combined}} column follows the time columns. Companion
tables: \code{{\_header.csv}} (every header field with its unit and enumeration label, derived values, CSV parts
with their time spans, the files of a joined recording, versions), \code{{\_sweeps.csv}} (per sweep: time,
GPS, overflow, peak, peak frequency, power mean) and \code{{\_statistics.csv}} (per bin: max hold, min hold,
power mean, dB mean, standard deviation, count). Files are written to private \code{{.part}} names and
published only when complete; a CSV that another program holds open (Excel on Windows) is kept under a
time-stamped name. Excel's limits (16\,384 columns, 1\,048\,576 rows \cite{{r6}}) are reported by the plan.

\subsection{{Veusz document}}
{table("ll", ["Page", "Title (PDF bookmark)"], page_rows)}
{figure("figures/veusz_statistics_sm200c.png", "Statistics page of the SM200C sample (460 sweeps, detector code 2 shown as Max, inferred); frequency axis in GHz.")}
{figure("figures/veusz_spectrogram_sm200c.png", "Spectrogram page of the SM200C sample: every row present (no false blank rows with writer 0.0.21).")}
{figure("figures/veusz_statistics_sweep0v2.png", "Statistics page of Spike's own test file sweep0v2.shr (417 sweeps): max hold, power mean, dB mean, min hold.")}

\section{{Multi-file recordings}}\label{{sec:join}}
Since Spike~3.9.7 a long recording continues in a new, sequentially numbered file when the maximum file size is
reached \cite{{r9}},\cite{{r12}}. The naming scheme is not documented, so \code{{group\_recordings}} groups files by
content:
\begin{{enumerate}}[nosep]
\item Files are sorted by their first time stamp.
\item A file joins the previous group when these fields are equal: {join_required}.
\item and it starts no later than
      \begin{{equation}}t_\mathrm{{first}}^{{(j)}}-t_\mathrm{{last}}^{{(j-1)}}\le\max\big(10~\mathrm s,\ 50\,\tilde\Delta\big),\end{{equation}}
      $\tilde\Delta$ being the median sweep interval of the previous file.
\item Differences in {join_noted} are reported, not refused.
\end{{enumerate}}
A \code{{ShrFileSet}} numbers the sweeps of $J$ files continuously: with $N_i$ sweeps in file $i$, sweep $k_j$ of
file $j$ has the recording-wide index
\begin{{equation}}k=O_j+k_j,\qquad O_j=\sum_{{i<j}}N_i ,\end{{equation}}
and a read that crosses a file boundary is split and joined transparently. Outputs are named
\code{{<first file>\_joined.*}}; \code{{\_header.csv}} lists every source file, and gaps between files are noted.
Files that do not group are converted on their own (\code{{--join}} with \code{{--info}} shows the grouping).

\section{{CSV time decimation}}\label{{sec:decimate}}
At the SM200C sample's rate a 3-hour recording is about {tex(core.human_bytes(sm_shr_bytes))} of \code{{.shr}};
lossless CSV needs about 12 bytes per value, so roughly three times as much. \code{{csv\_decimate}} $=N$
combines every $N$ selected sweeps into one CSV row (one column in the \code{{frequencies\_as\_rows}} layout).
With $G_r$ the sweeps of row $r$ (blocks aligned to multiples of $N$; the last group may be shorter):
\begin{{align}}
y^{{\max}}_r(f)&=\max_{{k\in G_r}}x_k(f), \qquad y^{{\min}}_r(f)=\min_{{k\in G_r}}x_k(f),\\
y^{{P}}_r(f)&=10\log_{{10}}\Big(\frac{{1}}{{|G_r|}}\sum_{{k\in G_r}}10^{{x_k(f)/10}}\Big)\quad[\mathrm{{dBm}}],
\qquad y^{{V}}_r(f)=\sqrt{{\frac{{1}}{{|G_r|}}\sum_{{k\in G_r}}x_k(f)^2}}\quad[\mathrm{{mV}}].
\end{{align}}
{table("lp{10cm}", ["Detector", "Use"], decimate_rows)}
Each row carries the index, time stamp and GPS fix of the \emph{{first}} sweep of its group, ADC overflow if any
sweep of the group overflowed, and $|G_r|$ in \code{{sweeps\_combined}}. Only the main CSV is decimated: the
statistics, the spectrogram, \code{{\_sweeps.csv}} and the \code{{.vszh5}} always use every selected sweep.
{table("rrrr", ["N", "CSV rows", "Time per row", "Lossless CSV (estimate)"], volume_rows,
       "A 3-hour recording at 29.92 sweeps/s x 8384 bins (the SM200C sample's settings), sweeps\\_as\\_rows.")}

\section{{Statistics and their derivations}}
Let $x_k(f)$ be the level of bin $f$ in sweep $k$, $k=1\ldots N$.
\subsection{{Frequency of a bin}}
\begin{{equation}}f_i = f_0 + i\,\Delta f,\qquad f_0=\code{{firstBinFreqHz}},\ \Delta f=\code{{binSizeHz}},\end{{equation}}
as the SDK defines the bin axis \cite{{r1}}.
py-shr-parser's plotting helpers \cite{{r10}} use $\mathrm{{linspace}}(f_c-S/2, f_c+S/2, n)$ instead; on
\code{{sweep0v2.shr}} ($\Delta f = 1220.703125$~Hz, $n=16\,386$, $S=20$~MHz) the two differ by up to one bin at
the top, because $(n-1)\,\Delta f = 20.0012$~MHz $\neq S$. Frequency axes switch to GHz from 10~GHz up, before
Veusz would print scientific tick labels.
\subsection{{Power mean, dB mean and the 2.51 dB bias}}
\begin{{align}}
\bar P(f) &= 10\log_{{10}}\!\Big(\frac1N\sum_{{k=1}}^{{N}}10^{{x_k(f)/10}}\Big)\quad[\mathrm{{dBm}}],\\
\bar L(f) &= \frac1N\sum_{{k=1}}^{{N}}x_k(f)\quad[\mathrm{{dBm}}].
\end{{align}}
For noise the dB mean reads low \cite{{r4}},\cite{{r13}}. With a Rayleigh envelope the power $p$ is exponential
with mean $\mu$, $\rho(p)=\mu^{{-1}}e^{{-p/\mu}}$, and with $u=p/\mu$
\begin{{equation}}
\mathrm{{E}}[\ln p]=\ln\mu+\int_0^\infty \ln u\,e^{{-u}}\,\mathrm du=\ln\mu+\Gamma'(1)=\ln\mu-\gamma,
\end{{equation}}
so
\begin{{equation}}
\mathrm{{E}}[10\log_{{10}}p]-10\log_{{10}}\mu=-\frac{{10\,\gamma}}{{\ln 10}}=-2.5068~\mathrm{{dB}},
\qquad \gamma=0.5772156649\ldots
\end{{equation}}
(a $10^7$-sample simulation gave $-2.5067$~dB). The converter therefore reports both: the power mean is the
physical mean power, the dB mean matches Spike's log averaging. With a Max detector each $x_k$ is already a
maximum over many FFTs (Section~\ref{{sec:format}}), so these statistics describe the recorded max-hold traces.
\subsection{{mV recordings}}
\begin{{equation}}V_\mathrm{{rms}}(f)=\sqrt{{\frac1N\sum_k x_k(f)^2}}\quad[\mathrm{{mV}}].\end{{equation}}
\subsection{{Standard deviation from running sums}}
\begin{{equation}}s^2=\frac{{S_2-S_1^2/N}}{{N-1}},\qquad S_1=\sum_k x_k,\ S_2=\sum_k x_k^2 .\end{{equation}}
In float64 the cancellation error is about $\varepsilon\,\bar x^2/s^2\approx 10^{{-16}}\times 80^2/2^2\approx
2\times10^{{-13}}$ (relative), negligible for dBm levels.
\subsection{{Exact merging of blocks}}
Each block returns $\max$, $\min$, $S_1$, $S_2$, $\sum 10^{{x/10}}$ and $N$ per bin; the file's values follow
exactly: maxima of maxima, minima of minima, sums of sums, e.g.
$\bar P_{{A\cup B}}=10\log_{{10}}\big((\Sigma_A+\Sigma_B)/(N_A+N_B)\big)$. Parallel and serial conversions give
identical results (self-test).
\subsection{{Spectrogram pixels}}
A pixel covers $n_r$ sweeps $\times$ $n_c$ bins. Peak hold is the block maximum; the power mean is
\begin{{equation}}
\bar P_{{ij}}=10\log_{{10}}\Big(\frac{{1}}{{n_r n_c}}\sum_{{k\in r_i}}\sum_{{f\in c_j}}10^{{x_k(f)/10}}\Big)
=10\log_{{10}}\Big(\frac{{1}}{{n_r}}\sum_{{k\in r_i}}\Big[\frac1{{n_c}}\sum_{{f\in c_j}}10^{{x_k(f)/10}}\Big]\Big),
\end{{equation}}
computed as the column mean per sweep, then summed over the sweeps of the row (exact, since every sweep of a
row has the same $n_c$). A row may span two worker blocks; its partial sums are added by the main process.
\subsection{{Lossless numbers}}
Binary32 has $p=24$ significand bits; a decimal string round-trips with \cite{{r5}},\cite{{r16}}
\begin{{equation}}d=\lceil p\log_{{10}}2\rceil+1=\lceil 7.22\rceil+1=9\end{{equation}}
significant digits, hence \code{{\%.9g}}. Every value of every layout was compared with the file's float32
values bit for bit (and with py-shr-parser \cite{{r10}} on \code{{sweep0v2.shr}}, which it can read).

\section{{Time axes and the even grid}}\label{{sec:grid}}
Time stamps are whole milliseconds since 1970 UTC from the recording PC's clock \cite{{r2}}. The \code{{.vszh5}}
time axis is UTC or local date/time, elapsed seconds or sweep index (\code{{auto}}: date/time for captures of
60~s or more). Veusz draws images with uneven axes through a slow non-linear path (on a 3-hour spectrogram
30.3~s and 3.2~GB, against 2.7~s and 0.31~GB on an even grid), so the rows are put on an even grid by
\code{{vszh5\_writer.regularize\_rows}} ({writer.__version__}). With row centres $c_k$, intervals
$d_k=c_{{k+1}}-c_k$, median $\tilde d$ and tolerance $\tau=0.25$:
\begin{{align}}
\text{{ordinary}}_k &: d_k\le(1+2\tau)\,\tilde d,\qquad
\Delta=\operatorname{{mean}}\{{d_k:\text{{ordinary}}_k\}},\\
s_0&=0,\qquad s_{{k+1}}=s_k+\begin{{cases}}1 & \text{{ordinary}}_k\\ \max\!\big(1,\operatorname{{rint}}(d_k/\Delta)\big) & \text{{otherwise}}\end{{cases}}
\end{{align}}
Row $k$ goes to slot $s_k$; empty slots are blank (NaN) rows and show a pause. Why the mean: a step $\Delta'$
that differs from the true mean interval $\mu$ advances each row by $\mu/\Delta'$ slots, so the rounding skips a
slot about every $\Delta'/|\mu-\Delta'|$ rows. Spike's whole-millisecond stamps make the SM200C intervals
32--35~ms (mean 33.35~ms, median 33~ms); version 0.0.20, which took its step from the median, left a false blank
row about every 47 sweeps. With the mean of the ordinary intervals no slot is skipped, and a real 2-s pause
still gives 60 blank rows. Rows that are not strictly increasing are spread evenly instead (times approximate).

\section{{Long captures}}
\begin{{itemize}}[nosep]
\item \textbf{{CSV split by time}}: \code{{\_part001.csv}}, \ldots, one per N minutes of recording, each with the
      header line; slices follow the running maximum of the time stamps, so a clock step back never sends a
      sweep to an earlier file (and the step is noted).
\item \textbf{{CSV decimation}} (Section~\ref{{sec:decimate}}) and \textbf{{joined files}} (Section~\ref{{sec:join}}).
\item \textbf{{Disk check}}: the CSV size is estimated and the conversion refuses to start when the drive cannot
      hold it.
\item \textbf{{Per-sweep table}}: 57 bytes per sweep, memory-mapped from a private temporary folder when larger
      than a quarter of the RAM budget.
\item \textbf{{Thinned series}}: level versus time and GPS in the \code{{.vszh5}} are reduced to
      \code{{time\_series\_max\_points}} (100\,000) --- peak hold for the peak, power mean for the band level,
      the frequency of the strongest sweep, any overflow --- so a single burst is never averaged away.
\item \textbf{{Time per row}}: 2000 rows over 3~h is 5.4~s per row; the plan states it.
\end{{itemize}}
{figure("figures/veusz_spectrogram_3h.png", "Synthetic 3-hour capture: drifting carrier, a 2 ms burst every 10 min at 2415 MHz, a 2-minute pause (blank band).")}
{figure("figures/veusz_level_vs_time_3h.png", "Level versus time of the same capture: every burst present, the pause visible.")}

\section{{Performance, parallelism, GPU and memory}}
\begin{{itemize}}[nosep]
\item Blocks of sweeps are read (one memory-mapped slice each), formatted and reduced in worker processes
      (\emph{{spawn}}, never fork a GUI), at most $2\times$workers blocks in flight, merged in order \cite{{r7}}.
      Default workers: CPUs $-1$ (at most 61 on Windows).
\item Block size: $B=\lfloor (M-M_\mathrm{{stats}})/(s\,n_c\,\beta)\rfloor$ with budget $M$, $s=2w+1$ slots,
      $n_c$ bins and $\beta$ bytes per sample in flight (30 for \code{{sweeps\_as\_rows}}); the statistics
      work in sub-blocks of 2~M samples, so their float64 temporaries do not grow with the block. With
      \code{{csv\_decimate}} $=N$, $B$ is rounded down to a multiple of $N$.
\item GPU: CuPy \cite{{r8}} runs the statistics and spectrogram reduction per sub-block; any GPU error repeats
      the block on the CPU (tested with a stand-in). Text formatting stays on the CPU.
\item Edit $>$ Free memory: garbage collection, CuPy pools, \code{{malloc\_trim}} / \code{{EmptyWorkingSet}};
      previews are pickled to disk, one in memory.
\end{{itemize}}
{table("p{6.2cm}p{4.2cm}rr", ["Case (2 CPU cores, no GPU)", "Data", "Time", "Peak memory"], [
    [tex("3 h, 2 sweeps/s x 4001 bins, 1.5 ms jitter, 2 workers, with the Veusz PDF/PNG render"),
     tex("331 MiB to 981 MiB CSV, 7 files"), tex(slow), tex(slow_rss)],
    [tex("3 h, 50 sweeps/s x 512 bins (540 000 sweeps), 2 workers"), tex("1.1 GiB to 3.1 GiB CSV"), tex(fast),
     tex(fast_rss)],
    [tex("3000 x 65 536 bins, RAM budget 256 MB, 2 workers"), tex("375 MiB to 1.1 GiB CSV"), tex(mem_time),
     tex(mem_rss)],
    [tex("SM200C rate: 2 joined files x 10 min (35 902 sweeps x 8384 bins), csv_decimate 30, 2 workers"),
     tex(f"1.1 GiB to 114 MiB CSV ({sm_rate} of SHR)"), tex(sm_time), tex(sm_rss)],
], "Measured with tests/long\\_capture\\_check.py, tests/memory\\_check.py and tests/sm200c\\_rate\\_check.py (docs/validation).")}

\section{{Robustness}}
\begin{{itemize}}[nosep]
\item The reader's validation and salvage rules (Section~\ref{{sec:format}}) turn cut-short, unclosed or
      unusual files into notes instead of errors; unknown enumeration codes never stop a conversion.
\item Memory maps are closed explicitly after every block and file, so Windows can move or delete the input.
\item Every output is written to a private \code{{.part}} and published atomically; Stop, an error or a
      refused disk check leaves no partial file.
\item Published files get the usual permissions (writer fix of the 0600 mode, since 0.0.20).
\end{{itemize}}

\section{{Command line}}
\code{{python shr\_converter.py --cli [options] files-or-folders}}
{table("p{4.6cm}p{11cm}", ["Option", "Meaning"], cli_rows)}
Examples:
\begin{{itemize}}[nosep]
\item \code{{python shr\_converter.py --cli --join --csv-decimate 30 D:\textbackslash{{}}captures}} --- every
      recording in the folder, files of one recording joined, 30 sweeps per CSV row (peak hold).
\item \code{{python shr\_converter.py --cli --info --join *.shr}} --- headers, notes and the grouping only.
\item \code{{python shr\_converter.py --reader --group *.shr}} --- the reader's own view of the files.
\end{{itemize}}

\section{{vszh5\_writer {writer.__version__}}}
{writer.__version__} is 0.0.20 with one fix in \code{{regularize\_rows()}} (Section~\ref{{sec:grid}}); no public
name, parameter, position or default of 0.0.5, 0.0.10, both 0.0.18 releases, 0.0.19 or 0.0.20 changed. 0.0.20
had joined the two releases both numbered 0.0.18 (R\&S FSP logger 0.9.0: render fixes; AB Power Meter Monitor
1.6.0: \code{{VeuszAppender}}) with 0.0.19, and added the 0600 file-mode fix, \code{{png\_background}}, date-axis
images, \code{{block\_reduce}} and \code{{regularize\_rows}}. No other program calls \code{{regularize\_rows()}}.
{table("p{4.0cm}p{5.0cm}p{6.0cm}", ["Program", "Own suite with " + writer.__version__, "Note"], [
    [tex("R&S FSP logger 0.9.0"), tex("44/44 (PySide6; Veusz 4.2.1)"),
     tex("set the About test's expected writer version to 0.0.21")],
    [tex("AB Power Meter Monitor 1.7.0"), tex("45 PASS, 0 FAIL"), tex("none")],
    [tex("SA Time Stability Tools 0.0.3"), tex("7/7 and 22/22 in Veusz 4.2.1"), tex("none")],
    [tex("QuickSyn package 0.0.10"), tex("44 pass, 3 pinned checks fail"),
     tex("same with 0.0.19 and 0.0.20: version literal and pre-0.0.15 temporary name")],
    [tex("EMF Envelope FFT 0.0.4, RFI evaluator 0.0.5"), tex("API check only"),
     tex("they use the 0.0.13/0.0.14 API, unchanged")],
], "Details: docs/WRITER\\_0.0.21\\_NOTES.md and docs/validation/writer\\_compatibility\\_0.0.21.")}

\section{{Verification}}
\code{{shr\_reader.py --selftest}}: {n_reader} checks (header size and field offsets, write/read round trip
bit-exact, UTF-16 title, detector 2 and unknown codes kept with notes, versions 1 and 3, \code{{dataOffset}}
1024, salvage of unclosed and cut-short files, bad signature refused, file sets across boundaries, grouping,
pickling, 0.01~dB grid detection, time stamps going backwards). \code{{--selftest}}:
{n_self} engine checks with a real file (every CSV layout bit-exact with 1 and 2 workers; statistics, spectrogram
and sub-block merging against direct NumPy; joins; decimation by all three detectors; cut-short files; mV; GPU
stand-in and fallback; split, disk check, disk-mapped table, thinning; locked file; cancel).
\code{{--gui-smoke}}: 12 offscreen GUI checks including real worker processes and a joined, decimated conversion.
\code{{pytest tests}}: {n_pytest} tests with 30 sub-tests, real renders in Veusz 4.2.1, Spike's own
\code{{sweep0v2.shr}} and the SM200C sample (shipped in \code{{tests/data}}). Logs: \code{{docs/validation}}.

\section{{Data gaps}}
{table("p{4.2cm}p{8.6cm}l", ["Item", "Status", "Confidence"], [
    [tex("Real Spike files"), tex("sweep0v2.shr (v2, dBm) and the SM200C sample (v2, detector 2) read bit-exactly"),
     "High"],
    [tex("Detector code 2 = Max"), tex("inferred from the 0.01 dB grid and the noise shape; not in the SDK"),
     "Medium"],
    [tex("Detector code 3 = Min"), tex("by analogy; no file seen"), "Low"],
    [tex("MinMax (code 0) contents"), tex("which array a MinMax file stores is not known"), "Unknown"],
    [tex("Multi-file recordings"), tex("grouped by content; Spike's naming not seen"), "Medium"],
    [tex("Limit-line-triggered recordings"), tex("not seen; skipped sweeps would appear as pauses"), "Unknown"],
    [tex("Channelized recordings"), tex("read as stored, not interpreted"), "Unknown"],
    [tex("Spike time decimation"), tex("which instant a decimated sweep's time stamp marks is not known"),
     "Unknown"],
    [tex("mV recordings"), tex("synthetic only"), "Medium"],
    [tex("Title encoding"), tex("UTF-16LE per the SDK; no titled file seen"), "Medium"],
    [tex("GPU"), tex("stand-in only; no CUDA device here"), "Medium"],
    [tex("Windows"), tex("designed for it (spawn, explicit map close, locked CSV), tested on Linux"), "Medium"],
])}
The open format questions are in \code{{docs/SignalHound\_support\_letter\_2026-10-28.md}}.

\appendix
\section{{Options (ConvertOptions) and their defaults}}
{table("p{5.6cm}p{9.6cm}", ["Field", "Default"], option_rows)}
\section{{File-header fields}}
{table("p{4.4cm}p{2.2cm}p{8.6cm}", ["Field", "Unit", "Meaning"], header_rows)}
\section{{Modules and functions used, and why}}
{table("p{3.8cm}p{5.2cm}p{6.4cm}", ["Module", "Used", "Why"], module_rows)}

\section*{{References}}
\addcontentsline{{toc}}{{section}}{{References}}
\begin{{thebibliography}}{{99}}
""" + "\n".join(rf"\bibitem{{r{n}}} {text} \url{{{url}}}" if url.startswith("http") else rf"\bibitem{{r{n}}} {text}"
                 for n, text, url in refs) + r"""
\end{thebibliography}
\end{document}
"""


# %% BUILD
def main() -> int:
    """Write the .tex and compile it twice with lualatex."""
    DOCS.mkdir(exist_ok=True)
    source = DOCS / f"{NAME}.tex"
    source.write_text(build(), encoding="utf-8")
    print(f"wrote {source}")
    exe = shutil.which("lualatex")
    if not exe:
        print("lualatex not found: the .tex is written; compile it with LuaLaTeX twice")
        return 1
    for run in (1, 2):
        done = subprocess.run([exe, "-interaction=nonstopmode", "-halt-on-error", source.name], cwd=DOCS,
                              capture_output=True, text=True, errors="replace")
        if done.returncode != 0:
            print(done.stdout[-3000:])
            return done.returncode
        print(f"lualatex pass {run}: ok")
    for suffix in (".aux", ".log", ".out", ".toc"):
        (DOCS / f"{NAME}{suffix}").unlink(missing_ok=True)
    print(f"wrote {DOCS / (NAME + '.pdf')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
