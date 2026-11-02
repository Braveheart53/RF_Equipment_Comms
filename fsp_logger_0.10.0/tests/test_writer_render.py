#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Regression tests for vszh5_writer 0.0.18 render_pages() fixes
=============================================================
 Filename       : tests/test_writer_render.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-26
 Language       : Python 3.8 through 3.12
 Requires       : numpy; h5py for the real-Veusz test

A stand-in "Veusz program" (a small Python script speaking the same
--listen protocol: read the script on stdin, print VSZH5_PAGES / VSZH5_DONE)
tests the three 0.0.18 fixes without Veusz. A real render runs only when the
environment variable VEUSZ_EXE names a working Veusz with h5py.
"""

# %% IMPORTS
from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vszh5_writer as writer  # noqa: E402

FAKE_VEUSZ = textwrap.dedent('''
    import re, sys
    mode = sys.argv[1]
    script = sys.stdin.read()
    names = ["first_page", "second_page"]
    if mode == "noload":                 # load error printed, marker still sent
        print("VSZH5_PAGES 0 ", flush=True)
        print("LoadError: No HDF5 support as h5py module is missing", flush=True)
        print("VSZH5_DONE", flush=True)
        sys.exit(0)
    print("VSZH5_PAGES 2 " + "|".join(names), flush=True)
    if mode == "write":
        pdf = re.search(r"Export\\((['\\"])(.+?\\.pdf)\\1", script)
        if pdf:
            open(pdf.group(2), "wb").write(b"%PDF-1.4\\n%%EOF\\n")
        stem = re.search(r"vszh5_png_stem = (['\\"])(.+?)\\1", script)
        if stem:
            count = 1 if "(1 if names else 0)" in script else 2
            for i in range(count):
                open("%s_p%02d_%s.png" % (stem.group(2), i, names[i]), "wb").write(b"png")
    print("VSZH5_DONE", flush=True)
''')


def make_fake_exe(folder: Path, mode: str) -> str:
    """Executable wrapper running FAKE_VEUSZ with this interpreter."""
    script = folder / "fake_veusz.py"
    script.write_text(FAKE_VEUSZ, encoding="utf-8")
    exe = folder / f"veusz_{mode}"
    exe.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" {mode}\n', encoding="utf-8")
    exe.chmod(0o755)
    return str(exe)


# %% TESTS
class RenderScriptTests(unittest.TestCase):

    def test_first_page_bound_is_not_min(self):
        # 0.0.17: min(1, len(names)) -> numpy.min inside Veusz 4.2.1 listen mode.
        text = writer._render_script(Path("a.vszh5"), None, Path("a"), "first", 72)
        self.assertIn("range((1 if names else 0))", text)
        self.assertNotIn("min(", text)


@unittest.skipIf(os.name == "nt", "shell-script stand-in for Veusz")
class RenderPagesTests(unittest.TestCase):

    def setUp(self):
        self.folder_object = tempfile.TemporaryDirectory()
        self.folder = Path(self.folder_object.name)
        self.source = self.folder / "run v0.0.2.vszh5"
        self.source.write_bytes(b"not read by the stand-in")

    def tearDown(self):
        self.folder_object.cleanup()

    def test_dotted_stem_keeps_full_name(self):
        # 0.0.17: "run v0.0.2.vszh5" -> "run v0.0.pdf".
        exe = make_fake_exe(self.folder, "write")
        written = writer.render_pages(self.source, self.folder / "out", png_pages="first",
                                      veusz_exe=exe, method="program", bookmarks=False)
        self.assertEqual([p.name for p in written],
                         ["run v0.0.2.pdf", "run v0.0.2_p00_first_page.png"])

    def test_no_pages_loaded_is_a_failure(self):
        # 0.0.17: returned [] as a success.
        exe = make_fake_exe(self.folder, "noload")
        with self.assertRaisesRegex(RuntimeError, "loaded no pages"):
            writer.render_pages(self.source, self.folder / "out", veusz_exe=exe,
                                method="program", bookmarks=False)

    def test_missing_outputs_are_a_failure(self):
        exe = make_fake_exe(self.folder, "silent")
        with self.assertRaisesRegex(RuntimeError, "did not write"):
            writer.render_pages(self.source, self.folder / "out", veusz_exe=exe,
                                method="program", bookmarks=False)


@unittest.skipUnless(os.environ.get("VEUSZ_EXE") and writer.h5py is not None,
                     "set VEUSZ_EXE to a Veusz with h5py for a real render")
class RealVeuszTests(unittest.TestCase):

    def test_real_render_pdf_and_first_png(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "real v1.2.vszh5"
            doc = writer.VszDoc("test_writer_render")
            writer.xy_page(doc, "spectrum", [writer.Trace("f", "p", "trace")],
                           title="Synthetic", xlabel="Frequency (Hz)", ylabel="dBm")
            writer.xy_page(doc, "second", [writer.Trace("f", "p", "trace")],
                           title="Synthetic 2", xlabel="Frequency (Hz)", ylabel="dBm")
            with writer.VeuszWriter(path) as output:
                output.dataset_1d("f", np.linspace(1e9, 2e9, 11))
                output.dataset_1d("p", np.linspace(-90, -30, 11))
                output.finish(doc.text())
            written = writer.render_pages(path, Path(folder) / "out", png_pages="first",
                                          veusz_exe=os.environ["VEUSZ_EXE"], method="program")
            self.assertEqual([p.name for p in written],
                             ["real v1.2.pdf", "real v1.2_p00_spectrum.png"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
