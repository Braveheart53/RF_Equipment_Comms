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
 Version        : 0.0.4  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-11
 Modified       : 2026-10-11
 Language       : Python 3.12
 Requires       : numpy, h5py   (Veusz only to open or render the result)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Derived from   : isp_speed_monitor.py 1.3.0 (VeuszWriter, VszDoc, vz_text,
                  epoch_to_veusz, find_veusz_exe, _atomic_path/_commit_atomic,
                  tests/render_in_veusz.sh), Copyright (C) 2026 William W.
                  Wallace, Adaptive Electrodynamics LLC dba AdaptEd.
 Status         : Internal draft - checked against real Veusz 3.6.2 and 4.2.1
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

FILE LAYOUT  (Veusz document format 1, as written by Document.saveToHDF5File
and read by loader.loadHDF5Doc in Veusz 3.6 and 4.2 [R1])
-----------
    /Veusz                     attrs vsz_version, vsz_saved_at, vsz_format = 1
    /Veusz/Data/<name>         group, attr vsz_datatype in {'1d', 'date', 'text'}
         .../data              values; attr vsz_name = <name> (UTF-8)
         .../serr|perr|nerr    optional error arrays for '1d'
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
  PDF, Windows-safe paths (repr), and an in-process fallback.

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
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover - reported when a writer is created
    h5py = None

__version__ = "0.0.4"                 # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"      # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"

__all__ = [
    "VSZH5_FORMAT", "VSZH5_LAYOUT_VERSION", "VEUSZ_EPOCH", "UNIX_TO_VEUSZ_S",
    "epoch_to_veusz", "local_utc_offsets", "vz_text", "escape_hdf_name",
    "VszDoc", "VeuszWriter", "find_veusz_exe", "render_pages",
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
        Final file name. Data go to "<path>.part" until finish().
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
        self.path = Path(str(self.final_path) + ".part") if atomic else self.final_path
        if self.path.exists():
            self.path.unlink()
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
        "print('VSZH5_PAGES', len(names), '|'.join(names))",
    ]
    if pdf is not None:
        lines.append(f"Export({str(pdf)!r}, page=list(range(len(names))))")
    if png_stem is not None:
        upto = "len(names)" if png_pages == "all" else "min(1, len(names))"
        lines.append(
            f"exec(\"for i in range({upto}): Export({str(png_stem)!r} + '_p%02d_%s.png' "
            f"% (i, names[i]), page=[i], dpi={int(dpi)})\")")
    lines += ["print('VSZH5_DONE')", "Quit()", ""]
    return "\n".join(lines)


def render_pages(vszh5: str | os.PathLike, outdir: str | os.PathLike | None = None,
                 dpi: int = 150, pdf: bool = True, png_pages: str = "all",
                 veusz_exe: str = "", timeout: float = 600.0,
                 method: str = "auto") -> list[Path]:
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
        "auto" (program if found, else the Python package), "program"
        (the Veusz executable only) or "inprocess" (the Python package only).

    Returns
    -------
    list of Path
        Files written.

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
    before = set(out.iterdir())

    if method not in ("auto", "program", "inprocess"):
        raise ValueError(f"method must be auto, program or inprocess, not {method!r}")
    exe = "" if method == "inprocess" else (veusz_exe or find_veusz_exe())
    if method == "program" and not exe:
        raise RuntimeError("Veusz program not found (set QUICKSYN_VEUSZ to veusz.exe)")
    if exe:
        env = dict(os.environ)
        if sys.platform.startswith("linux") and not env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY"):
            env.setdefault("QT_QPA_PLATFORM", "offscreen")
        script = _render_script(src, pdf_path, png_stem, png_pages, dpi)
        ok, log = _run_listen(exe, script, env, timeout)
        if not ok:
            raise RuntimeError(f"Veusz ({exe}) did not finish the render: {log[-800:]}")
    else:
        _render_in_process(src, pdf_path, png_stem, png_pages, dpi)
    return sorted(p for p in out.iterdir() if p not in before and p.suffix in (".pdf", ".png"))


def _run_listen(exe: str, script: str, env: dict[str, str], timeout: float) -> tuple[bool, str]:
    """Pipe a script into `veusz --listen --quiet` and wait for the marker.

    Veusz 3.6.2 exits on Quit(); Veusz 4.2.1 only closes its hidden window
    and keeps running. Every Export() has completed by the time the script
    prints VSZH5_DONE, so after the marker the program gets two seconds to
    exit on its own and is then terminated.
    """
    import threading

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen([exe, "--listen", "--quiet"], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=err, text=True,
                                encoding="utf-8", errors="replace", env=env,
                                **_popen_kwargs())
        killer = threading.Timer(timeout, proc.kill)
        killer.start()
        lines: list[str] = []
        done = False
        try:
            proc.stdin.write(script)
            proc.stdin.close()
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
        err.seek(0)
        return done, "".join(lines) + err.read()


def _render_in_process(src: Path, pdf_path: Path | None, png_stem: Path | None,
                       png_pages: str, dpi: int) -> None:
    """Fallback: render with the veusz Python package in this process."""
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
                           "Veusz installer) or set QUICKSYN_VEUSZ to veusz.exe "
                           f"[{type(exc).__name__}: {exc}]") from exc
    doc = vdoc.Document()
    doc.load(str(src), mode="hdf5")
    pages = doc.basewidget.children
    if not pages:
        raise RuntimeError(f"{src.name} loaded as an empty Veusz document")
    ci = vdoc.CommandInterface(doc)
    if pdf_path is not None:
        ci.Export(str(pdf_path), page=list(range(len(pages))))
    if png_stem is not None:
        upto = len(pages) if png_pages == "all" else 1
        for i in range(upto):
            ci.Export(f"{png_stem}_p{i:02d}_{pages[i].name}.png", page=[i], dpi=dpi)


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
