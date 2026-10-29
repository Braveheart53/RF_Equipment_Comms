#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Regression tests for vszh5_writer 0.0.21 (0.0.20 merge + regularize_rows fix).

===============================================================================
 Title          : vszh5_writer 0.0.21 regression tests
 Filename       : tests/test_vszh5_writer.py
 Version        : 0.0.2 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Language       : Python 3.8 through 3.12
 Requires       : numpy, h5py, pytest (or plain unittest); Veusz with h5py for
                  the real renders (VEUSZ_EXE)
 Licence        : GPL-3.0-or-later
 Derived from   : the R&S FSP logger 0.9.0 tests/test_writer_render.py (stand-in
                  Veusz speaking the --listen protocol), same author.
===============================================================================

What is checked
---------------
* every 0.0.18 FSP-branch render fix is present (first-page PNG bound, dotted
  PDF names, missing outputs, no pages loaded - with and without a
  Traceback, i.e. the 0.0.19 case and the wider 0.0.20 rule);
* the 0.0.18 AB-branch appender is present and works (create, append, read);
* 0.0.20: block_reduce against a brute-force loop, date-axis images,
  xy_page(datetime_format=), render_pages(png_background=), published file
  mode (not 0600), Spyder cell markers in place;
* 0.0.21: regularize_rows with jittered millisecond time stamps (the
  32..35 ms sweep intervals of a real SM200C recording) gives no false
  blank rows, and a real pause still gives the right number of them;
* a real Veusz render (VEUSZ_EXE) of a date-axis spectrogram with irregular
  rows, PDF + PNG on a white background.

Revision history: 0.0.2 (2026-10-28) writer 0.0.21 and the jitter test;
0.0.1 (2026-10-28) first version, with writer 0.0.20.
"""

# %% IMPORTS
from __future__ import annotations

import os
import stat
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
    if mode in ("noload", "traceback"):   # load error printed, marker still sent
        print("VSZH5_PAGES 0 ", flush=True)
        if mode == "traceback":
            print("Traceback (most recent call last):", flush=True)
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


# %% VERSION AND SOURCE LAYOUT
class VersionTests(unittest.TestCase):

    def test_version_and_exports(self):
        self.assertEqual(writer.__version__, "0.0.21")
        for name in ("VeuszAppender", "AppendLockedError", "APPEND_CHUNK_ELEMENTS", "block_reduce",
                     "REDUCE_METHODS", "frequency_time_pages", "linear_power_mean_dbm", "bar_page",
                     "read_text_dataset", "render_pages", "add_pdf_bookmarks"):
            self.assertIn(name, writer.__all__)
            self.assertTrue(hasattr(writer, name), name)

    def test_cell_markers_above_their_code(self):
        source = Path(writer.__file__).read_text(encoding="utf-8")
        self.assertIn("# %% LINEAR-POWER AVERAGING (0.0.17) — SHARED BY REPORTS AND FUTURE CALLERS\n"
                      "def linear_power_mean_dbm(", source)
        self.assertIn("# %% FREQUENCY-VERSUS-TIME PAGES (0.0.16)\ndef frequency_ghz_text(", source)

    def test_history_unique_and_descending(self):
        source = Path(writer.__file__).read_text(encoding="utf-8")
        history = source.split("REVISION HISTORY", 1)[1]
        import re
        versions = [tuple(map(int, v.split("."))) for v in re.findall(r"^(\d+\.\d+\.\d+) ", history, re.M)]
        self.assertEqual(len(versions), len(set(versions)), "duplicate version blocks")
        self.assertEqual(versions, sorted(versions, reverse=True), "not newest first")
        self.assertEqual(versions[0], (0, 0, 21))


# %% RENDER SCRIPT AND render_pages (stand-in Veusz)
class RenderScriptTests(unittest.TestCase):

    def test_first_page_bound_is_not_min(self):
        text = writer._render_script(Path("a.vszh5"), None, Path("a"), "first", 72)
        self.assertIn("range((1 if names else 0))", text)
        self.assertNotIn("min(", text)

    def test_png_background(self):
        plain = writer._render_script(Path("a.vszh5"), None, Path("a"), "all", 72)
        white = writer._render_script(Path("a.vszh5"), None, Path("a"), "all", 72, "white")
        self.assertNotIn("backcolor", plain)
        self.assertIn("backcolor='white'", white)


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
        exe = make_fake_exe(self.folder, "write")
        written = writer.render_pages(self.source, self.folder / "out", png_pages="first",
                                      veusz_exe=exe, method="program", bookmarks=False)
        self.assertEqual([p.name for p in written], ["run v0.0.2.pdf", "run v0.0.2_p00_first_page.png"])

    def test_no_pages_loaded_without_traceback(self):        # FSP 0.0.18 rule, kept in 0.0.20
        exe = make_fake_exe(self.folder, "noload")
        with self.assertRaisesRegex(RuntimeError, "loaded no pages"):
            writer.render_pages(self.source, self.folder / "out", veusz_exe=exe, method="program",
                                bookmarks=False)

    def test_no_pages_loaded_with_traceback(self):           # AB 0.0.19 case
        exe = make_fake_exe(self.folder, "traceback")
        with self.assertRaisesRegex(RuntimeError, "No HDF5 support"):
            writer.render_pages(self.source, self.folder / "out", veusz_exe=exe, method="program",
                                bookmarks=False)

    def test_missing_outputs_are_a_failure(self):
        exe = make_fake_exe(self.folder, "silent")
        with self.assertRaisesRegex(RuntimeError, "did not write"):
            writer.render_pages(self.source, self.folder / "out", veusz_exe=exe, method="program",
                                bookmarks=False)


# %% 0.0.20 ADDITIONS
class BlockReduceTests(unittest.TestCase):

    @staticmethod
    def brute(a, rf, cf, method):
        rows, cols = -(-a.shape[0] // rf), -(-a.shape[1] // cf)
        out = np.empty((rows, cols))
        for i in range(rows):
            for j in range(cols):
                b = a[i * rf:(i + 1) * rf, j * cf:(j + 1) * cf]
                out[i, j] = {"max": b.max(), "min": b.min(), "mean": b.mean(),
                             "power_mean_db": 10 * np.log10(np.mean(10 ** (b / 10))),
                             "power_mean_linear": np.sqrt(np.mean(b ** 2))}[method]
        return out

    def test_against_brute_force(self):
        a = np.random.default_rng(3).normal(-80, 6, (29, 41))
        for method in writer.REDUCE_METHODS:
            for rf, cf in ((2, 3), (4, 5), (29, 41), (7, 1), (1, 9), (50, 50)):
                with self.subTest(method=method, rf=rf, cf=cf):
                    np.testing.assert_allclose(writer.block_reduce(a, rf, cf, method),
                                               self.brute(a, rf, cf, method), rtol=1e-12, atol=1e-9)

    def test_factor_one_is_identity_and_bad_input(self):
        a = np.arange(12.0).reshape(3, 4) - 5
        np.testing.assert_array_equal(writer.block_reduce(a, 1, 1, "power_mean_linear"), a)
        with self.assertRaises(ValueError):
            writer.block_reduce(a, 1, 1, "median")
        with self.assertRaises(ValueError):
            writer.block_reduce(a[0], 1, 1)

    def test_power_mean_db_large_values_do_not_overflow(self):
        a = np.full((4, 4), 3000.0)          # 10^(300) would overflow without the max reference
        np.testing.assert_allclose(writer.block_reduce(a, 2, 2, "power_mean_db"), 3000.0)


class RegularizeRowsTests(unittest.TestCase):

    def test_regular_jitter_and_gaps(self):
        image = np.arange(12.0).reshape(6, 2)
        even = 100.0 + 5.0 * np.arange(6)
        out, (y0, y1), how = writer.regularize_rows(image, even + np.array([0, .4, -.3, .2, 0, -.1]))
        self.assertEqual(how, "regular")
        np.testing.assert_array_equal(out, image)
        self.assertAlmostEqual(y0, 97.5, delta=0.1)        # jitter moves the fitted grid slightly
        gapped = np.r_[even[:3], even[3:] + 20.0]          # a 20 s pause after row 2
        out, (y0, y1), how = writer.regularize_rows(image, gapped)
        self.assertEqual(how, "gaps")
        self.assertEqual(out.shape, (10, 2))
        self.assertTrue(np.isnan(out[3:7]).all())
        np.testing.assert_array_equal(out[7:], image[3:])
        self.assertAlmostEqual(y1 - y0, 10 * 5.0)

    def test_jittered_millisecond_stamps_have_no_false_gaps(self):
        # 0.0.21: the SM200C sample's pattern - 33.35 ms mean period, stamps
        # rounded to whole ms (32..35 ms intervals). 0.0.20 took the median
        # (33 ms) as the step and left a blank row about every 47 rows.
        rng = np.random.default_rng(5)
        stamps = np.sort(np.rint(1000.0 * 1.793e9 + 33.35 * np.arange(460) + rng.uniform(-1.5, 1.5, 460)))
        centres = stamps / 1000.0
        image = np.ones((460, 4))
        out, (y0, y1), how = writer.regularize_rows(image, centres)
        self.assertEqual(how, "regular")
        self.assertEqual(out.shape, (460, 4))
        self.assertAlmostEqual((y1 - y0) / 460, 0.03335, delta=0.0002)
        paused = np.r_[centres[:200], centres[200:] + 2.0]           # a real 2 s pause
        out, (y0, y1), how = writer.regularize_rows(image, paused)
        self.assertEqual(how, "gaps")
        blank = np.flatnonzero(np.isnan(out[:, 0]))
        self.assertEqual(blank.size, 60)                             # 2 s / 33.35 ms
        self.assertTrue(np.all(np.diff(blank) == 1))                 # one band, after row 199

    def test_crowded_rows_spread_evenly(self):
        image = np.zeros((4, 3))
        out, (y0, y1), how = writer.regularize_rows(image, [0.0, 0.0, 1.0, 1.0])
        self.assertEqual(how, "even")
        self.assertEqual(out.shape, (4, 3))
        self.assertLess(y0, 0.0)
        self.assertGreater(y1, 1.0)


class DocumentTests(unittest.TestCase):

    def test_image_page_datetime_axes(self):
        doc = writer.VszDoc("test")
        writer.image_page(doc, "spec", "img", ymode="datetime", datetime_format="%VDH:%VDM",
                          left_margin="3.4cm")
        text = doc.text()
        self.assertIn("Set('y/mode', 'datetime')", text)
        self.assertIn("Set('y/TickLabels/format', '%VDH:%VDM')", text)
        self.assertIn("Set('leftMargin', '3.4cm')", text)
        default = writer.VszDoc("test")
        writer.image_page(default, "spec", "img")
        self.assertNotIn("y/mode", default.text())        # 0.0.19 output unchanged by default
        with self.assertRaises(ValueError):
            writer.image_page(writer.VszDoc(), "p", "img", xmode="log")

    def test_xy_page_datetime_format(self):
        doc = writer.VszDoc("test")
        writer.xy_page(doc, "p", [writer.Trace("t", "v")], xmode="datetime", datetime_format="%VDS")
        self.assertIn("Set('x/TickLabels/format', '%VDS')", doc.text())

    @unittest.skipIf(os.name == "nt", "POSIX file modes")
    def test_published_file_mode_is_not_private(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mode.vszh5"
            with writer.VeuszWriter(path) as w:
                w.dataset_1d("x", [1.0, 2.0])
                w.finish("")
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode, writer._default_file_mode())
            self.assertNotEqual(mode, 0o600)
            path.chmod(0o640)                   # a replaced file keeps its mode
            with writer.VeuszWriter(path) as w:
                w.dataset_1d("x", [3.0])
                w.finish("")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_appender_still_works(self):           # 0.0.18 AB branch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "log.vszh5"
            with writer.VeuszAppender(path) as app:
                app.create_1d("v", [1.0, 2.0])
                app.append("v", [3.0])
            with writer.VeuszAppender(path) as app:
                self.assertEqual(app.length("v"), 3)
            self.assertIn("v", writer.dataset_names(path))


# %% REAL VEUSZ
@unittest.skipUnless(os.environ.get("VEUSZ_EXE") and writer.h5py is not None,
                     "set VEUSZ_EXE to a Veusz with h5py for a real render")
class RealVeuszTests(unittest.TestCase):

    def test_date_axis_spectrogram_white_png(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "spec v0.0.20.vszh5"
            t = writer.epoch_to_veusz(1.7616e9 + np.cumsum(np.r_[0, np.full(39, 30.0)]) + np.r_[0, np.arange(39) * 0.1])
            image = np.random.default_rng(1).normal(-90, 3, (40, 200))
            image[:, 60] = -40
            doc = writer.VszDoc("test_vszh5_writer")
            writer.image_page(doc, "spectrogram", "img", title="Date axis", xlabel="Frequency (MHz)",
                              ylabel="Time (UTC)", zlabel="dBm", ymode="datetime", left_margin="3.4cm")
            writer.xy_page(doc, "levels", [writer.Trace("t", "peak", "peak")], xmode="datetime",
                           datetime_format="%VDH:%VDM")
            with writer.VeuszWriter(path, compress=True) as w:
                w.dataset_2d("img", image, xedge=np.linspace(2995, 3015, 201), ycent=t)
                w.dataset_date("t", t)
                w.dataset_1d("peak", image.max(axis=1))
                w.finish(doc.text())
            written = writer.render_pages(path, Path(folder) / "out", png_pages="all",
                                          veusz_exe=os.environ["VEUSZ_EXE"], method="program",
                                          png_background="white")
            names = [p.name for p in written]
            self.assertEqual(names, ["spec v0.0.20.pdf", "spec v0.0.20_p00_spectrogram.png",
                                     "spec v0.0.20_p01_levels.png"])
            try:
                from PIL import Image
            except ImportError:
                return
            with Image.open(written[1]) as png:
                self.assertEqual(png.convert("RGBA").getpixel((2, 2)), (255, 255, 255, 255))


if __name__ == "__main__":
    unittest.main(verbosity=2)
