# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Typeset README_quicksyn_controller.md as a LuaLaTeX PDF with bookmarks.

Part of the QuickSyn SCPI controller package, version 0.0.10.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Usage::

    python tools/build_readme_pdf.py [--keep-aux]

Writes README_quicksyn_controller.tex (the LaTeX source, editable) and
README_quicksyn_controller.pdf beside the README. Needs pandoc (3.x) and a
TeX distribution with lualatex (TeX Live or MiKTeX) and the DejaVu fonts,
which TeX Live includes. The section headings become the PDF bookmark
hierarchy (two levels), and the bookmark pane opens when the PDF is opened.

Symbols that DejaVu Serif lacks (arrows, box drawing, check marks) are taken
from DejaVu Sans and DejaVu Sans Mono through a luaotfload fallback chain,
which must be defined before fontspec loads the fonts; pandoc's template puts
header-includes after the font set-up, so the line is inserted after
\\documentclass instead.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
README = PKG / "README_quicksyn_controller.md"
VERSION = "0.0.10"

FALLBACK = ('\\directlua{luaotfload.add_fallback("qsfallback", {"DejaVu Sans:mode=harf;", '
            '"DejaVu Sans Mono:mode=harf;", "DejaVu Math TeX Gyre:mode=harf;"})}\n')

HEADER = r"""% Extra preamble for the README PDF (LuaLaTeX via pandoc)
\usepackage{fvextra}
\DefineVerbatimEnvironment{Highlighting}{Verbatim}{breaklines,breakanywhere,commandchars=\\\{\}}
\renewenvironment{verbatim}{\VerbatimEnvironment\begin{Verbatim}[breaklines,breakanywhere,fontsize=\small]}{\end{Verbatim}}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\lhead{\small QuickSyn SCPI Controller and Telemetry Logger}
\rhead{\small\thepage}
\lfoot{\scriptsize README\_quicksyn\_controller, version VERSION, GPL-3.0-or-later}
\setlength{\headheight}{14pt}
\sloppy
% Figures stay where the README puts them (0.0.10: Calibration screenshots)
\usepackage{float}
\floatplacement{figure}{H}
""".replace("VERSION", VERSION)


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run a program, capturing its output."""
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    pandoc = shutil.which("pandoc")
    lualatex = os.environ.get("QUICKSYN_LUALATEX") or shutil.which("lualatex")
    if not pandoc or not lualatex:
        print("needs pandoc and lualatex on the PATH (or QUICKSYN_LUALATEX)")
        return 2
    header = PKG / "readme_header.tmp.tex"
    header.write_text(HEADER, encoding="utf-8")
    tex = README.with_suffix(".tex")
    fonts = "RawFeature={fallback=qsfallback}"
    cmd = [pandoc, README.name, "-s", "-o", tex.name, "--shift-heading-level-by=-1",
           "--toc", "--toc-depth=2", "-H", header.name,
           "-V", "documentclass=article", "-V", "papersize=letter",
           "-V", "geometry:margin=1.8cm", "-V", "fontsize=10pt",
           "-V", "mainfont=DejaVu Serif", "-V", f"mainfontoptions={fonts}",
           "-V", "sansfont=DejaVu Sans", "-V", f"sansfontoptions={fonts}",
           "-V", "monofont=DejaVu Sans Mono", "-V", f"monofontoptions={fonts},Scale=0.85",
           "-V", "mathfont=DejaVu Math TeX Gyre",
           "-V", "colorlinks=true", "-V", "linkcolor=blue", "-V", "urlcolor=blue",
           "-V", "hyperrefoptions=bookmarksopen=true",
           "-V", "hyperrefoptions=bookmarksopenlevel=1",
           "-V", "hyperrefoptions=pdfpagemode=UseOutlines",
           "-M", "title=QuickSyn SCPI Controller and Telemetry Logger",
           "-M", "author=William W. Wallace, NRAO/GBO",
           "-M", f"date=Version {VERSION}",
           "-M", "subject=README for the QuickSyn SCPI controller package",
           "-M", "lang=en-US"]
    try:
        proc = run(cmd, PKG)
    finally:
        header.unlink(missing_ok=True)
    if proc.returncode != 0:
        print(proc.stderr)
        return 1
    text = tex.read_text(encoding="utf-8")
    cut = text.index("\n", text.index("\\documentclass")) + 1
    text = ("% !TeX program = lualatex\n"
            f"% README for the QuickSyn SCPI controller package {VERSION}, typeset with LuaLaTeX.\n"
            "% Generated from README_quicksyn_controller.md by tools/build_readme_pdf.py\n"
            "% (pandoc); compile twice:  lualatex README_quicksyn_controller.tex\n"
            + text[:cut]
            + "% Fallback fonts for symbols (arrows, box drawing) missing from DejaVu Serif\n"
            + FALLBACK + text[cut:])
    tex.write_text(text, encoding="utf-8")
    for _ in range(2):          # second run: contents and bookmarks
        proc = run([lualatex, "-interaction=nonstopmode", "-halt-on-error", tex.name], PKG)
        if proc.returncode != 0:
            print(proc.stdout[-2000:])
            return 1
    if "--keep-aux" not in argv:
        for suffix in (".aux", ".log", ".out", ".toc"):
            tex.with_suffix(suffix).unlink(missing_ok=True)
    print(f"wrote {tex.name} and {tex.with_suffix('.pdf').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
