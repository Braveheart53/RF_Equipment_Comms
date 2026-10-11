#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Round-trip a .vszh5 through Veusz's own HDF5 loader and renderer.

===============================================================================
 Title          : Veusz Round-Trip Validation of the .vszh5 Export
 Filename       : validate_vszh5_in_veusz.py
 Version        : 0.0.2  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.2
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-11
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13
 Requires       : numpy, h5py and the veusz Python package (3.6 or 4.x);
                  scipy only when no file is given (phase-noise page)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Development validation script (not part of the GUI)
===============================================================================

LICENCE
-------
This program is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option)
any later version. It is distributed WITHOUT ANY WARRANTY; see the GNU
General Public License (file LICENSE) for details.

DESCRIPTION
-----------
Run with a Python that can import veusz (for example the conda environment
that has the conda-forge 'veusz' package). The script

  1. writes a test document with veusz_export.export_vszh5() from a
     synthetic flicker-FM series, unless a .vszh5 is given on the command
     line;
  2. loads it with Veusz's own loader (Document.load(mode='hdf5'), the call
     File > Open makes for a .vszh5);
  3. checks every HDF5 dataset arrived in Veusz with the right type, the
     same tags and BIT-EXACT values, that every plotted xData/yData names an
     existing dataset, and that all pages exist;
  4. renders every page to PNG and all pages to one PDF in-process, and,
     when a Veusz program is found, once more through
     veusz_export.render_vszh5(method="program").

Exit status 0 = all checks passed, 1 = a check failed, 2 = Veusz missing.

USAGE
-----
    python validate_vszh5_in_veusz.py [FILE.vszh5] [--keep DIR]

REVISION HISTORY
----------------
0.0.2  2026-10-11  First version (package 0.0.2).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS AND PATHS
# =============================================================================
from __future__ import annotations

import argparse
import builtins
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

_THIS_FILE = Path(globals().get("__file__") or "validate_vszh5_in_veusz.py").resolve()
_HERE = _THIS_FILE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

__version__ = "0.0.2"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__license__ = "GPL-3.0-or-later"

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# %% ===========================================================================
#    CHECK BOOK-KEEPING
# =============================================================================
class Checks:
    """Collects PASS/FAIL lines and the overall result."""

    def __init__(self) -> None:
        self.n_pass = 0
        self.failures: List[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> bool:
        """Record one check and print it."""
        if ok:
            self.n_pass += 1
            print(f"  PASS  {label}" + (f"  ({detail})" if detail else ""))
        else:
            self.failures.append(label)
            print(f"  FAIL  {label}" + (f"  ({detail})" if detail else ""))
        return ok


def _same(a: np.ndarray, b: np.ndarray) -> bool:
    """Bit-exact equality with NaN == NaN."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all((a == b) | (np.isnan(a) & np.isnan(b))))


# %% ===========================================================================
#    TEST DOCUMENT
# =============================================================================
def make_test_document(folder: Path) -> Path:
    """Write a .vszh5 from a synthetic flicker-FM series with every result."""
    import stability_core as sc
    import veusz_export as ve

    tau0 = 1.0
    x = sc.generate_power_law_phase(4096, tau0, alpha=-1, seed=5)
    t = np.arange(x.size) * tau0
    drift = sc.fit_and_remove_drift(x, t, order=1)
    pts = sc.compute_all_deviations(drift.residual_x, tau0)
    theoh = sc.compute_theoh_family(drift.residual_x, tau0)
    classes = sc.classify_noise(pts)
    pn_res = f_classes = None
    try:
        import phase_noise as pn
        pn_res = pn.ssb_phase_noise_from_time_series(drift.residual_x, tau0, 1e7)
        f_classes = pn.classify_freq_domain_noise(pn_res)
    except ImportError:
        print("  note: scipy not importable here - phase-noise page not tested")
    return ve.export_vszh5(folder / "roundtrip test [v0.0.2].vszh5", t, x,
                           x_residual=drift.residual_x, tau0=tau0, f0_hz=1e7,
                           dev_points=pts, theoh_points=theoh, noise_classes=classes,
                           phase_noise=pn_res, freq_classes=f_classes, drift=drift,
                           title="round_trip_test {x_1}\\path", source="synthetic")


# %% ===========================================================================
#    ROUND TRIP THROUGH VEUSZ
# =============================================================================
def _walk(widget: Any):
    """Every widget below ``widget`` (depth first)."""
    for child in widget.children:
        yield child
        yield from _walk(child)


def run_checks(path: Path, outdir: Path) -> Checks:
    """Load ``path`` with Veusz and compare it with the HDF5 contents."""
    import h5py
    import veusz.qtall as vqt
    _app = vqt.QApplication.instance() or vqt.QApplication([])  # noqa: F841 - keep the app alive
    import veusz.document as vdoc
    import veusz.widgets  # noqa: F401  registers widget types
    import veusz.dataimport  # noqa: F401  Import* commands used by the loader
    import veusz.datasets as vds
    import veusz

    c = Checks()
    try:
        from veusz.utils import version as _veusz_version
        vz_ver = _veusz_version()
    except Exception:  # noqa: BLE001 - only used for the report line
        vz_ver = "?"
    print(f"Veusz {vz_ver} ({Path(veusz.__file__).parent}) - file {path.name}")

    # ---- what the file holds (read with h5py) ---------------------------------
    expected: Dict[str, Dict[str, Any]] = {}
    with h5py.File(path, "r") as f:
        c.check(int(f["Veusz"].attrs["vsz_format"]) == 1, "vsz_format attribute = 1")
        for key, grp in f["Veusz/Data"].items():
            name = grp["data"].attrs["vsz_name"]
            name = name.decode("utf-8") if isinstance(name, bytes) else str(name)
            kind = grp.attrs["vsz_datatype"]
            kind = kind.decode() if isinstance(kind, bytes) else str(kind)
            data = grp["data"][()]
            expected[name] = {"kind": kind, "data": data}
        tags: Dict[str, List[str]] = {}
        for tag, arr in f["Veusz/Document/Tags"].items():
            tags[tag] = [v.decode("utf-8") if isinstance(v, bytes) else str(v) for v in arr[()]]
        script = f["Veusz/Document/document"][0]
        script = script.decode("utf-8") if isinstance(script, bytes) else str(script)
    n_pages_script = script.count("Add('page'")

    # ---- Veusz's own loader ---------------------------------------------------
    doc = vdoc.Document()
    try:
        doc.load(str(path), mode="hdf5")
        loaded = True
    except Exception as exc:  # noqa: BLE001
        loaded = False
        c.check(False, "Document.load(mode='hdf5')", f"{type(exc).__name__}: {exc}")
    if not loaded:
        return c
    c.check(True, "Document.load(mode='hdf5')")
    pages = list(doc.basewidget.children)
    c.check(len(pages) == n_pages_script and len(pages) > 0, "page count",
            f"{len(pages)} loaded, {n_pages_script} in script: "
            + ", ".join(p.name for p in pages))

    # ---- datasets: type, tags and bit-exact values ------------------------------
    bad_type, bad_value, missing = [], [], []
    for name, info in expected.items():
        ds = doc.data.get(name)
        if ds is None:
            missing.append(name)
            continue
        if info["kind"] == "text":
            if not isinstance(ds, vds.DatasetText):
                bad_type.append(name)
            want = [v.decode("utf-8") if isinstance(v, bytes) else str(v) for v in info["data"]]
            if list(ds.data) != want:
                bad_value.append(name)
        else:
            if isinstance(ds, vds.DatasetText):
                bad_type.append(name)
            if not _same(ds.data, info["data"]):
                bad_value.append(name)
    c.check(not missing, f"all {len(expected)} datasets present in Veusz", ", ".join(missing))
    c.check(not bad_type, "dataset types (numeric / text)", ", ".join(bad_type))
    c.check(not bad_value, "values bit-exact after Veusz load (float64)", ", ".join(bad_value))
    tag_errors = [f"{n}:{t}" for t, names in tags.items() for n in names
                  if n in doc.data and t not in getattr(doc.data[n], "tags", set())]
    c.check(not tag_errors, f"tags restored ({', '.join(sorted(tags))})", ", ".join(tag_errors))

    # ---- every xy plot refers to a loaded dataset --------------------------------
    dangling, n_xy = [], 0
    for page in pages:
        for w in _walk(page):
            if w.typename == "xy":
                n_xy += 1
                for setn in ("xData", "yData"):
                    ref = w.settings.get(setn).val
                    if isinstance(ref, str) and ref not in doc.data:
                        dangling.append(f"{w.path}:{setn}={ref}")
    c.check(n_xy > 0 and not dangling, f"{n_xy} xy plots reference existing datasets",
            ", ".join(dangling))

    # ---- in-process render ---------------------------------------------------------
    ci = vdoc.CommandInterface(doc)
    outdir.mkdir(parents=True, exist_ok=True)
    pdf = outdir / (path.stem + "_inprocess.pdf")
    ci.Export(str(pdf), page=list(range(len(pages))))
    c.check(pdf.is_file() and pdf.stat().st_size > 2000, "in-process PDF of all pages",
            f"{pdf.stat().st_size if pdf.is_file() else 0} bytes")
    small = []
    for i, page in enumerate(pages):
        png = outdir / f"{path.stem}_inprocess_p{i:02d}_{page.name}.png"
        ci.Export(str(png), page=[i], dpi=110)
        if not png.is_file() or png.stat().st_size < 5000:
            small.append(page.name)
    c.check(not small, f"in-process PNG of every page ({len(pages)})", ", ".join(small))
    return c


def program_render(path: Path, outdir: Path, c: Checks) -> None:
    """Render through the Veusz program (--listen), when one is found."""
    import veusz_export as ve
    exe = ve.find_veusz()
    if not exe:
        print("  SKIP  program render (no Veusz program found; set TIME_STABILITY_VEUSZ)")
        return
    try:
        files = ve.render_vszh5(path, outdir=outdir, dpi=100, png_pages="all",
                                method="program", timeout=300)
        c.check(any(f.suffix == ".pdf" for f in files) and sum(f.suffix == ".png" for f in files) >= 1,
                f"program render via {Path(exe).name} --listen", f"{len(files)} files")
        again = ve.render_vszh5(path, outdir=outdir, dpi=100, png_pages="first",
                                method="program", timeout=300)
        c.check(len(again) >= 2, "re-render reports overwritten files", f"{len(again)} files")
    except Exception as exc:  # noqa: BLE001
        c.check(False, "program render", f"{type(exc).__name__}: {str(exc)[-300:]}")


# %% ===========================================================================
#    ENTRY POINT
# =============================================================================
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run all checks; return the exit status."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("file", nargs="?", help=".vszh5 to check (default: write a test file)")
    p.add_argument("--keep", default="", help="folder for the rendered files (kept)")
    args = p.parse_args(argv)
    try:
        # veusz.qtall, not just veusz: a distribution package can be on the
        # path of a Python it was not built for (its Qt binding then fails).
        import veusz.qtall  # noqa: F401 - availability check only
    except Exception as exc:  # noqa: BLE001 - ImportError or a broken Qt binding
        print(f"SKIP: Veusz is not usable in this interpreter "
              f"({type(exc).__name__}: {exc})")
        return 2
    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="vszh5_rt_"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        path = Path(args.file).resolve() if args.file else make_test_document(work)
        c = run_checks(path, work / "render")
        program_render(path, work / "render_program", c)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"\n{c.n_pass} passed, {len(c.failures)} failed")
    return 0 if not c.failures else 1


if __name__ == "__main__":
    _status = main()
    if not getattr(builtins, "__IPYTHON__", False):
        sys.exit(_status)
