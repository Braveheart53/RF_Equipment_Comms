# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Reproduce the three Veusz limits and check the upstream patch against them.

Part of the QuickSyn SCPI controller package, version 0.0.6.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Usage::

    python upstream/check_veusz_patch.py VEUSZ_PROGRAM [VEUSZ_PROGRAM ...]

Give one or more Veusz programs (for example an unpatched and a patched
4.2.1, and 3.6.2). Each is run on a two-page .vszh5 written with
vszh5_writer.py, and a table of results is printed:

1. ``veusz --export=out.pdf doc.vszh5`` and ``--export=out.png``: the command
   line reads every document as text, so a .vszh5 gives an empty document.
2. ``Load('doc.vszh5')`` in ``--listen`` mode: the embedded Load() has the
   same limit; then ``Export()`` of both pages.
3. ``Quit()`` in ``--listen --quiet`` mode: Veusz 4.2.1 keeps running.
4. PDF scale: Veusz 4.x draws a PDF page at 72/150 of its size when
   Export() is called with its default pdfdpi=150. The check measures how far
   across the page the text reaches (pypdf), 0.9+ for a full page.
5. A text .vsz saved by the same Veusz still exports (patch 1 must not
   change it).

Needs numpy, h5py and pypdf. The patch is
``veusz-4.2.1-vszh5-load-quit-pdfdpi.patch`` beside this file.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # vszh5_writer

import numpy as np                                             # noqa: E402
import vszh5_writer as vw                                      # noqa: E402

ENV = dict(os.environ)
if sys.platform.startswith("linux") and not ENV.get("DISPLAY"):
    ENV["QT_QPA_PLATFORM"] = "offscreen"


def make_document(folder: Path) -> Path:
    """A two-page .vszh5 with a labelled curve on each page."""
    doc = vw.VszDoc(generator="check_veusz_patch.py")
    for page in ("page_one", "page_two"):
        doc.add("page", page)
        doc.to(page)
        doc.set("width", "20cm")
        doc.set("height", "12cm")
        doc.add("graph", "g")
        doc.to("g")
        doc.add("axis", "x")
        doc.add("axis", "y")
        doc.set("x/label", "Right-hand edge label")
        doc.set("y/direction", "vertical")
        doc.add("xy", "c")
        doc.set("c/xData", "t")
        doc.set("c/yData", "v")
        doc.up()
        doc.up()
    path = folder / "doc.vszh5"
    with vw.VeuszWriter(path) as writer:
        t = np.linspace(0.0, 10.0, 101)
        writer.dataset_1d("t", t)
        writer.dataset_1d("v", np.sin(t))
        writer.finish(doc.text())
    return path


def text_reach(pdf: Path, index: int = 0) -> float:
    """Rightmost text position on a PDF page, as a fraction of its width."""
    from pypdf import PdfReader

    page = PdfReader(str(pdf)).pages[index]
    width = float(page.mediabox.width)
    xs: list[float] = []

    def visit(text, cm, tm, _font, _size):
        if text.strip():
            xs.append(tm[4] * cm[0] + tm[5] * cm[2] + cm[4])

    page.extract_text(visitor_text=visit)
    return max(xs) / width if xs else 0.0


def pdf_pages(pdf: Path) -> int:
    """Number of pages in a PDF (0 if it is missing or unreadable)."""
    from pypdf import PdfReader

    try:
        return len(PdfReader(str(pdf)).pages)
    except Exception:  # noqa: BLE001
        return 0


def run_cli(exe: str, args: list[str], timeout: float = 120.0) -> tuple[int, str]:
    """Run the Veusz program with arguments; return (exit code, output tail)."""
    try:
        proc = subprocess.run([exe, *args], capture_output=True, text=True, env=ENV,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return -9, "timeout"
    return proc.returncode, (proc.stdout + proc.stderr).strip()[-300:]


def run_listen(exe: str, script: str, wait_after: float = 30.0) -> tuple[str, float | None]:
    """Pipe a script into --listen --quiet; return (stdout, exit delay after DONE).

    The delay is None when the program was still running ``wait_after``
    seconds after printing DONE (it is then killed).
    """
    proc = subprocess.Popen([exe, "--listen", "--quiet"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, env=ENV)
    proc.stdin.write(script)
    proc.stdin.close()
    lines = []
    done_at = None
    for line in proc.stdout:
        lines.append(line)
        if line.startswith("DONE"):
            done_at = time.monotonic()
            break
    delay = None
    try:
        proc.wait(timeout=wait_after)
        delay = time.monotonic() - done_at if done_at else None
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    proc.stdout.close()
    return "".join(lines), delay


def check(exe: str, work: Path) -> dict[str, str]:
    """All checks for one Veusz program."""
    out = work / Path(exe).name
    out.mkdir(parents=True, exist_ok=True)
    doc = make_document(out)
    res: dict[str, str] = {}
    code, tail = run_cli(exe, ["--version"])
    res["version"] = next((w for w in tail.split() if w[:1].isdigit()), "?")

    pdf = out / "cli.pdf"
    code, tail = run_cli(exe, [f"--export={pdf}", str(doc)])
    res["--export .vszh5 to PDF"] = (f"OK, text reaches {text_reach(pdf):.2f} of page"
                                     if code == 0 and pdf.is_file() else
                                     f"fails (exit {code}, {'no file' if not pdf.is_file() else 'file'})")
    png = out / "cli.png"
    code, tail = run_cli(exe, [f"--export={png}", str(doc)])
    res["--export .vszh5 to PNG"] = ("OK" if code == 0 and png.is_file() else
                                     f"fails (exit {code}, {'no file' if not png.is_file() else 'file'})")

    lpdf = out / "listen.pdf"
    script = (f"Load({str(doc)!r})\n"
              f"Export({str(lpdf)!r}, page=[0, 1])\n"
              "print('DONE')\nQuit()\n")
    text, delay = run_listen(exe, script)
    if lpdf.is_file() and pdf_pages(lpdf) == 2:
        res["Load() .vszh5 + Export()"] = (f"OK, 2 pages, text reaches "
                                           f"{text_reach(lpdf):.2f} of page")
    else:
        res["Load() .vszh5 + Export()"] = ("fails (no PDF)" if not lpdf.is_file() else
                                           f"fails ({pdf_pages(lpdf)} pages exported)")
    res["Quit() in --listen --quiet"] = (f"exits {delay:.2f} s after DONE" if delay is not None
                                         else "still running 30 s after DONE (killed)")

    vsz = out / "saved.vsz"
    script = ("import veusz.document.loader as L\n"
              f"L.loadHDF5Doc(Root._ci.document, {str(doc)!r})\n"
              f"Save({str(vsz)!r})\nprint('DONE')\nQuit()\n")
    run_listen(exe, script, wait_after=5.0)
    tpdf = out / "text_vsz.pdf"
    code, tail = run_cli(exe, [f"--export={tpdf}", str(vsz)])
    res["text .vsz --export to PDF"] = (f"OK, text reaches {text_reach(tpdf):.2f} of page"
                                        if code == 0 and tpdf.is_file() else f"fails (exit {code})")
    return res


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    with tempfile.TemporaryDirectory(prefix="veusz_patch_") as tmp:
        results = {exe: check(exe, Path(tmp)) for exe in argv}
    keys = list(next(iter(results.values())).keys())
    print("| Check | " + " | ".join(f"`{Path(e).name}`" for e in argv) + " |")
    print("| --- |" + " --- |" * len(argv))
    for key in keys:
        print(f"| {key} | " + " | ".join(results[e][key] for e in argv) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
