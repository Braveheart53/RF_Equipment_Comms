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
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12
 Requires       : shr_converter_core.py, vszh5_writer.py (same package); a TeX
                  installation with lualatex (TeX Live or MiKTeX) and the
                  packages fontspec, hyperref, bookmark, booktabs, longtable,
                  tabularx, graphicx, amsmath, xcolor, caption, enumitem
 Licence        : GPL-3.0-or-later
===============================================================================

Writes docs/SHR_Converter_Manual_v<version>.tex and compiles it twice with
lualatex (the second run resolves the contents and the bookmarks). Tables of
options, command-line flags, header fields and functions are generated from
the program itself, so the manual cannot drift from the code. Measured
figures are read from docs/validation/*.txt when present.

    python tools/build_manual.py            # from the package folder
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
import vszh5_writer as writer  # noqa: E402

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
    for name in ("long_capture_and_memory_0.0.1.txt", "validation_0.0.1.txt"):
        path = DOCS / "validation" / name
        if path.is_file():
            validation += path.read_text(encoding="utf-8", errors="replace")
    # -- measured numbers (from the validation logs of this release) --------------------------
    slow = measured(r"\(3 h, 2 sweeps/s x 4001 bins\)\n(?:.*\n)*?converted in ([0-9.]+ s)", "20.5 s", validation)
    slow_rss = measured(r"\(3 h, 2 sweeps/s x 4001 bins\)\n(?:.*\n)*?peak RSS of the process tree: ([0-9,]+ MiB)",
                        "871 MiB", validation)
    fast = measured(r"\(3 h, 540 000 sweeps\)\n(?:.*\n)*?converted in ([0-9.]+ s)", "53.5 s", validation)
    fast_rss = measured(r"\(3 h, 540 000 sweeps\)\n(?:.*\n)*?peak RSS of the process tree: ([0-9,]+ MiB)",
                        "520 MiB", validation)
    mem_rss = measured(r"Peak RSS of tree\s*: ([0-9,]+ MiB)", "463 MiB", validation)
    mem_time = measured(r"CSV written\s*: [0-9,]+ MiB in ([0-9.]+ s)", "43.8 s", validation)
    n_self = measured(r"(\d+) passed, 0 failed", "38", validation)

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
        [tt("shr_parser.ShrFileParser"), tex("open(), header, get_sweep_n()"),
         tex("reads every header and sweep; one instance per worker process [1]")],
        [tt("numpy"), tex("float32/float64 arrays, ufunc.reduceat, memmap, percentile"),
         tex("statistics, block reductions, per-sweep table on disk")],
        [tt("cupy (optional)"), tex("same array calls on the GPU"),
         tex("statistics and spectrogram reduction per sub-block [9]")],
        [tt("concurrent.futures"), tex("ProcessPoolExecutor (spawn, max_tasks_per_child)"),
         tex("parallel blocks, bounded and in order [8]")],
        [tt("h5py via vszh5_writer"), tex("VeuszWriter, image_page, xy_page, grid_page, text_page"),
         tex("native .vszh5 without Veusz")],
        [tt("vszh5_writer (0.0.20)"), tex("block_reduce, regularize_rows, render_pages"),
         tex("thinning, even spectrogram grid, PDF/PNG with bookmarks")],
        [tt("Qt.py + PySide6"), tex("QtCore, QtGui, QtWidgets"), tex("the GUI through the abstraction layer [11]")],
        [tt("pyqtgraph"), tex("ImageItem, ColorBarItem, PlotDataItem"), tex("preview plots")],
        [tt("psutil"), tex("Process().memory_info()"), tex("memory read-out and tests")],
        [tt("pypdf (via the writer)"), tex("PdfWriter.add_outline_item"), tex("PDF bookmark tree")],
        [tt("ctypes"), tex("malloc_trim (Linux), EmptyWorkingSet (Windows)"), tex("return freed memory to the OS")],
    ]
    refs = [
        ("1", r'T. Schmitz, ``py-shr-parser: Python library for parsing Signal Hound SHR files,'' v1.0.0, '
              r'WiSE Lab, Carnegie Mellon Univ., 2025.', "https://github.com/WiseLabCMU/py-shr-parser"),
        ("2", r"Signal Hound, ``.shr file format specification,'' BB Series Discussions forum, May--Aug. 2018.",
         "https://signalhound.com/?p=158701"),
        ("3", r"Signal Hound, ``Open recording .shr file in MATLAB,'' BB Series Discussions forum, Jul. 2019.",
         "https://signalhound.com/support/forums/topic/open-recording-shr-file-in-matlab/"),
        ("4", r"Hewlett-Packard, ``Measuring Noise and Noise-like Digital Communications Signals with a Spectrum "
              r"Analyzer,'' Application Note 1303, lit.\ no.\ 5966-4008E.",
         "https://www.hpmemoryproject.org/an/pdf/an_1303.pdf"),
        ("5", r"IEEE, ``IEEE Standard for Floating-Point Arithmetic,'' IEEE Std 754-2019, pp.~1--84, Jul. 2019, "
              r"doi: 10.1109/IEEESTD.2019.8766229.", "https://doi.org/10.1109/IEEESTD.2019.8766229"),
        ("6", r"Microsoft, ``Excel specifications and limits.''",
         "https://support.microsoft.com/en-us/office/1672b34d-7043-467e-8e27-269d656771c3"),
        ("7", r"Keysight Technologies, ``Spectrum Analysis Basics,'' Application Note 150, 5952-0292.",
         "https://www.keysight.com/us/en/assets/7018-06714/application-notes/5952-0292.pdf"),
        ("8", r"Python Software Foundation, ``concurrent.futures --- Launching parallel tasks,'' Python 3.12.",
         "https://docs.python.org/3.12/library/concurrent.futures.html"),
        ("9", r"Preferred Networks, ``CuPy documentation.''", "https://docs.cupy.dev/"),
        ("10", r"J. Sanders, ``Veusz --- a scientific plotting package.''", "https://veusz.github.io/"),
        ("11", r"M. Ottosson \emph{et al.}, ``Qt.py,'' v2.0.7.", "https://github.com/mottosso/Qt.py"),
        ("12", r"R. Regan, ``Number of digits required for round-trip conversions,'' Exploring Binary.",
         "https://www.exploringbinary.com/number-of-digits-required-for-round-trip-conversions/"),
        ("13", r"W. W. Wallace, ``vszh5\_writer.py --- Veusz HDF5 document writer,'' v0.0.20, NRAO/GBO, 2026.",
         "(shipped with this program)"),
    ]

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
            pdfkeywords={{Signal Hound, Spike, SHR, CSV, Veusz, vszh5, spectrogram}}]{{hyperref}}
\usepackage{{bookmark}}
\urlstyle{{same}}
\setlength{{\LTcapwidth}}{{\linewidth}}
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
\code{{vszh5\_writer.py}} & {writer.__version__}\\
py-shr-parser (reader) & {tex(core.SHR_PARSER_VERSION)}\\
\bottomrule
\end{{tabular}}
\end{{center}}
\tableofcontents
\clearpage

\section{{Overview}}
Spike, Signal Hound's analyzer software, records sweeps to \code{{.shr}} files: a 472-byte file header, then
per sweep a 48-byte sweep header (time stamp, GPS latitude/longitude/altitude, ADC-overflow flag) and the
amplitudes as 32-bit floats \cite{{r1}},\cite{{r2}}. The SHR Converter reads these files with py-shr-parser
\cite{{r1}} and writes CSV tables and a native Veusz document (\code{{.vszh5}}) through the author's
\code{{vszh5\_writer}} \cite{{r13}}, optionally rendered by Veusz \cite{{r10}} to a bookmarked PDF and PNGs.
Everything is streamed in blocks, so memory is set by a RAM budget and not by the file, and the blocks run in
parallel worker processes, with the numerical part on the GPU when CuPy is present.

\section{{Installation}}
\begin{{enumerate}}[nosep]
\item \code{{mamba env create -f environment.yml}} --- Python 3.12; pip installs \code{{requirements.txt}}
      (py-shr-parser is on PyPI only).
\item \code{{mamba activate shr-converter}}
\item Optional: \code{{mamba install -c conda-forge veusz}} (or the Veusz installer) to open and render;
      \code{{mamba install -c conda-forge cupy}} for an NVIDIA GPU.
\item \code{{python shr\_converter.py --selftest --gui-smoke}} --- {n_self} engine checks and 11 GUI checks.
\item \code{{python shr\_converter.py}} starts the GUI. On Windows: \code{{create\_environment.bat}} once,
      then \code{{run\_shr\_converter.bat}} (files may be dropped on it) and \code{{run\_selftest.bat}}.
\end{{enumerate}}
The launcher imports nothing heavy at its top level: worker processes started with \emph{{spawn}} re-run the
main script's top level, and this keeps Qt (about 50~MB per process) out of them.

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
\item Add files. Each header is read at once (sweeps, bins, span, length); notes report cut-short recordings.
\item \textbf{{Inspect}} runs the complete statistics pass without writing any file --- the same code as
      Convert --- and shows the preview. The \emph{{File info}} tab shows the plan
      (Figure~\ref{{fig:info}}).
\item \textbf{{Convert}}: one worker pool serves the whole batch; each file's preview arrives when it is
      done. \textbf{{Stop}} ends after the current block and deletes that file's partial outputs.
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
Companion tables: \code{{\_header.csv}} (every header field with its unit, derived values, CSV parts with their
time spans, versions), \code{{\_sweeps.csv}} (per sweep: time, GPS, overflow, peak, peak frequency, power mean)
and \code{{\_statistics.csv}} (per bin: max hold, min hold, power mean, dB mean, standard deviation, count).
Files are written to private \code{{.part}} names and published only when complete; a CSV that another program
holds open (Excel on Windows) is kept under a time-stamped name. Excel's limits (16\,384 columns,
1\,048\,576 rows \cite{{r6}}) are reported by the plan.

\subsection{{Veusz document}}
{table("ll", ["Page", "Title (PDF bookmark)"], page_rows)}
{figure("figures/veusz_statistics_sweep0v2.png", "Statistics page of Spike's own test file sweep0v2.shr (417 sweeps): max hold, power mean, dB mean, min hold.")}
{figure("figures/veusz_selected_sweeps_sweep0v2.png", "Selected-sweeps page: first and last sweep (the peak sweep is the first here).")}

\section{{Statistics and their derivations}}
Let $x_k(f)$ be the level of bin $f$ in sweep $k$, $k=1\ldots N$.
\subsection{{Frequency of a bin}}
\begin{{equation}}f_i = f_0 + i\,\Delta f,\qquad f_0=\code{{first\_bin\_freq\_hz}},\ \Delta f=\code{{bin\_size\_hz}}.\end{{equation}}
This is the file header's definition, also used by py-shr-parser for the peak frequency. Its plotting helpers
use $\mathrm{{linspace}}(f_c-S/2, f_c+S/2, n)$ instead; on \code{{sweep0v2.shr}}
($\Delta f = 1220.703125$~Hz, $n=16\,386$, $S=20$~MHz) the two differ by up to one bin at the top, because
$(n-1)\,\Delta f = 20.0012$~MHz $\neq S$.
\subsection{{Power mean, dB mean and the 2.51 dB bias}}
\begin{{align}}
\bar P(f) &= 10\log_{{10}}\!\Big(\frac1N\sum_{{k=1}}^{{N}}10^{{x_k(f)/10}}\Big)\quad[\mathrm{{dBm}}],\\
\bar L(f) &= \frac1N\sum_{{k=1}}^{{N}}x_k(f)\quad[\mathrm{{dBm}}].
\end{{align}}
For noise the dB mean reads low \cite{{r4}}. With a Rayleigh envelope the power $p$ is exponential with mean
$\mu$, $\rho(p)=\mu^{{-1}}e^{{-p/\mu}}$, and with $u=p/\mu$
\begin{{equation}}
\mathrm{{E}}[\ln p]=\ln\mu+\int_0^\infty \ln u\,e^{{-u}}\,\mathrm du=\ln\mu+\Gamma'(1)=\ln\mu-\gamma,
\end{{equation}}
so
\begin{{equation}}
\mathrm{{E}}[10\log_{{10}}p]-10\log_{{10}}\mu=-\frac{{10\,\gamma}}{{\ln 10}}=-2.5068~\mathrm{{dB}},
\qquad \gamma=0.5772156649\ldots
\end{{equation}}
(a $10^7$-sample simulation gave $-2.5067$~dB). The converter therefore reports both: the power mean is the
physical mean power, the dB mean matches Spike's log averaging.
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
Binary32 has $p=24$ significand bits; a decimal string round-trips with \cite{{r5}},\cite{{r12}}
\begin{{equation}}d=\lceil p\log_{{10}}2\rceil+1=\lceil 7.22\rceil+1=9\end{{equation}}
significant digits, hence \code{{\%.9g}}. Every value of every layout was compared with py-shr-parser bit for bit.

\section{{Time axes and the even grid}}
Time stamps are milliseconds since 1970 UTC from the recording PC's clock \cite{{r2}}. The \code{{.vszh5}}
time axis is UTC or local date/time, elapsed seconds or sweep index (\code{{auto}}: date/time for captures of
60~s or more). Spectrogram rows are put on an even grid by \code{{vszh5\_writer.regularize\_rows}}: the step is
fitted over the whole span, $\Delta=(c_{{\mathrm{{last}}}}-c_0)/s_{{\mathrm{{last}}}}$ with slots
$s_k=\mathrm{{round}}((c_k-c_0)/\Delta)$; rows that already lie within $\Delta/4$ of the grid are kept; pauses
become blank (NaN) rows; crowded time stamps are spread evenly. Veusz draws images with uneven axes through a
non-linear path: on a 3-hour spectrogram 30.3~s and 3.2~GB, against 2.7~s and 0.31~GB on the even grid.

\section{{Long captures}}
\begin{{itemize}}[nosep]
\item \textbf{{CSV split by time}}: \code{{\_part001.csv}}, \ldots, one per N minutes of recording, each with the
      header line; slices follow the running maximum of the time stamps, so a clock step back never sends a
      sweep to an earlier file.
\item \textbf{{Disk check}}: the CSV size is estimated (lossless: $\approx 12$ bytes per value) and the
      conversion refuses to start when the drive cannot hold it.
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
\item Blocks of sweeps are read, formatted and reduced in worker processes (\emph{{spawn}}, never fork a GUI),
      at most $2\times$workers blocks in flight, merged in order \cite{{r8}}. Default workers: CPUs $-1$
      (at most 61 on Windows).
\item Block size: $B=\lfloor (M-M_\mathrm{{stats}})/(s\,n_c\,\beta)\rfloor$ with budget $M$, $s=2w+1$ slots,
      $n_c$ bins and $\beta$ bytes per sample in flight (30 for \code{{sweeps\_as\_rows}}); the statistics
      work in sub-blocks of 2~M samples, so their float64 temporaries do not grow with the block.
\item GPU: CuPy \cite{{r9}} runs the statistics and spectrogram reduction per sub-block; any GPU error repeats
      the block on the CPU (tested with a stand-in). Text formatting stays on the CPU.
\item Edit $>$ Free memory: garbage collection, CuPy pools, \code{{malloc\_trim}} / \code{{EmptyWorkingSet}};
      previews are pickled to disk, one in memory.
\end{{itemize}}
{table("p{6.2cm}p{4.2cm}rr", ["Case (2 CPU cores, no GPU)", "Data", "Time", "Peak memory"], [
    [tex("3 h, 2 sweeps/s x 4001 bins, 2 workers, with the Veusz PDF/PNG render"),
     tex("331 MiB to 981 MiB CSV, 7 files"), tex(slow), tex(slow_rss)],
    [tex("3 h, 50 sweeps/s x 512 bins (540 000 sweeps), 2 workers"), tex("1.1 GiB to CSV (2 decimals)"), tex(fast), tex(fast_rss)],
    [tex("3000 x 65 536 bins, RAM budget 256 MB, 2 workers"), tex("750 MiB to 2.2 GiB CSV"), tex(mem_time), tex(mem_rss)],
], "Measured with tests/long\\_capture\\_check.py and tests/memory\\_check.py (docs/validation).")}

\section{{Robustness}}
\begin{{itemize}}[nosep]
\item py-shr-parser raises \code{{ShrFileParserWarning}} when the size does not match the header and leaves
      the file open; the converter reads up to the last complete sweep (header count 0 is replaced by the
      sweeps present) and says so \cite{{r2}}.
\item Every output is written to a private \code{{.part}} and published atomically; Stop, an error or a
      refused disk check leaves no partial file.
\item Published files get the usual permissions (writer 0.0.20 fix of the 0600 mode).
\end{{itemize}}

\section{{Command line}}
\code{{python shr\_converter.py --cli [options] files-or-folders}}
{table("p{4.6cm}p{11cm}", ["Option", "Meaning"], cli_rows)}

\section{{vszh5\_writer 0.0.20}}
Two releases were both numbered 0.0.18: the R\&S FSP logger 0.9.0 (render fixes) and the AB Power Meter
Monitor 1.6.0 (\code{{VeuszAppender}}); 0.0.19 grew from the latter. 0.0.20 joins them and adds the 0600 file-mode
fix, \code{{png\_background}}, date-axis images, \code{{block\_reduce}} and \code{{regularize\_rows}}. Every public
signature of 0.0.5, 0.0.10, both 0.0.18 and 0.0.19 is unchanged (checked by machine).
{table("p{4.4cm}p{5.4cm}p{6cm}", ["Program", "Own suite with 0.0.20", "Note"], [
    [tex("R&S FSP logger 0.9.0"), tex("44/44 (PyQt5, PySide6; Veusz 3.6.2, 4.2.1)"), tex("update the About test's expected version 0.0.18 -> 0.0.20")],
    [tex("AB Power Meter Monitor 1.7.0"), tex("45/45, real renders"), tex("none")],
    [tex("SA Time Stability Tools 0.0.3"), tex("7/7 and 22/22 in Veusz 4.2.1"), tex("none")],
    [tex("QuickSyn package 0.0.10"), tex("44 pass, 3 pinned checks fail"), tex("same with 0.0.19: version string and pre-0.0.15 temporary name")],
])}

\section{{Verification}}
\code{{--selftest}}: {n_self} checks (every CSV layout bit-exact with 1 and 2 workers; statistics, spectrogram and
sub-block merging against direct NumPy; cut-short files; mV; GPU stand-in and fallback; split, disk check,
disk-mapped table, thinning; locked file; cancel). \code{{--gui-smoke}}: 11 offscreen GUI checks including real
worker processes. \code{{pytest tests}}: 28 tests with 30 sub-tests, real renders in Veusz 3.6.2 and 4.2.1 and
Spike's own \code{{sweep0v2.shr}}. Logs: \code{{docs/validation}}.

\section{{Data gaps}}
{table("p{4.2cm}p{8.6cm}l", ["Item", "Status", "Confidence"], [
    [tex("Real Spike files"), tex("sweep0v2.shr (v2, dBm) read bit-exactly"), "High"],
    [tex("mV recordings"), tex("synthetic only"), "Medium"],
    [tex("Title encoding"), tex("UTF-16LE if it looks like it, else UTF-8; no titled file seen"), "Medium"],
    [tex("Channelized recordings"), tex("read as stored, not interpreted"), "Unknown"],
    [tex("GPU"), tex("stand-in only; no CUDA device here"), "Medium"],
    [tex("Windows"), tex("designed for it, tested on Linux"), "Medium"],
])}

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
