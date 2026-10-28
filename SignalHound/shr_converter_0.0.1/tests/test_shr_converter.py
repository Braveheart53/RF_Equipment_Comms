#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""pytest suite of the SHR Converter (engine, command line, GUI).

===============================================================================
 Title          : SHR Converter tests
 Filename       : tests/test_shr_converter.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Language       : Python 3.12
 Requires       : the converter's requirements, pytest; SHR_REAL_FILE (a real
                  Spike .shr, e.g. py-shr-parser's tests/test_files/sweep0v2.shr)
                  for the real-file tests; VEUSZ_EXE for the render test
 Licence        : GPL-3.0-or-later
===============================================================================
"""

# %% IMPORTS
from __future__ import annotations

import csv
import io
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shr_converter_core as core  # noqa: E402

REAL = os.environ.get("SHR_REAL_FILE", "")


# %% ENGINE
def test_self_test_passes():
    lines: list[str] = []
    assert core.self_test(report=lines.append, workers=2), "\n".join(l for l in lines if l.startswith("FAIL"))


def test_title_decoding():
    assert core.decode_title(b"\x00" * 256) == ""
    assert core.decode_title("Band 3 – Ω".encode("utf-16-le").ljust(256, b"\x00")) == "Band 3 – Ω"
    assert core.decode_title(b"plain ascii\x00" + b"\x00" * 244) == "plain ascii"


def test_options_round_trip_and_validation():
    opts = core.ConvertOptions(csv_layout="long", csv_time_columns=("utc_iso",), sweep_step=3)
    again = core.ConvertOptions.from_mapping(__import__("json").loads(opts.to_json()))
    assert again == opts
    with pytest.raises(ValueError):
        core.ConvertOptions(csv_layout="wide").validate()
    with pytest.raises(ValueError):
        core.ConvertOptions(z_mode="manual", z_min=0, z_max=-1).validate()


def test_empty_selection_and_frequency_range_errors(tmp_path):
    source = core.write_synthetic_shr(tmp_path / "s.shr", n_sweeps=5, n_bins=50)
    info = core.read_info(source)
    with pytest.raises(ValueError, match="empty"):
        core.make_plan(info, core.ConvertOptions(sweep_start=10))
    with pytest.raises(ValueError, match="no bin"):
        core.make_plan(info, core.ConvertOptions(freq_min_hz=5e9, freq_max_hz=6e9))


def test_semicolon_fixed_decimals(tmp_path):
    source = core.write_synthetic_shr(tmp_path / "s.shr", n_sweeps=4, n_bins=20)
    core.convert_file(source, core.ConvertOptions(output_dir=str(tmp_path / "o"), csv_delimiter="semicolon",
                                                  csv_number_format="fixed", csv_decimals=2,
                                                  write_vszh5=False, workers=1))
    rows = list(csv.reader(io.StringIO((tmp_path / "o" / "s.csv").read_text()), delimiter=";"))
    assert all(len(v.split(".")[1]) == 2 for v in rows[1][7:])


def test_command_line(tmp_path):
    source = core.write_synthetic_shr(tmp_path / "cli.shr", n_sweeps=6, n_bins=30)
    run = subprocess.run([sys.executable, str(ROOT / "shr_converter.py"), "--cli", str(source), "-o",
                          str(tmp_path / "out"), "--layout", "long", "--sweeps", "1:5:2", "-j", "1"],
                         capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "out" / "cli.csv").read_text().count("\n") == 1 + 2 * 30
    info = subprocess.run([sys.executable, str(ROOT / "shr_converter.py"), "--cli", "--info", str(source)],
                          capture_output=True, text=True, timeout=120)
    assert "Bins per sweep  : 30" in info.stdout


# %% REAL SPIKE FILE
@pytest.mark.skipif(not (REAL and Path(REAL).is_file()), reason="set SHR_REAL_FILE to a Spike .shr")
def test_real_file_round_trip(tmp_path):
    from shr_parser import ShrFileParser
    result = core.convert_file(REAL, core.ConvertOptions(output_dir=str(tmp_path), workers=2))
    with ShrFileParser(REAL) as parser:
        direct = np.stack([s.sweep for s in parser])
        header = parser.header
    rows = list(csv.reader(io.StringIO((tmp_path / (Path(REAL).stem + ".csv")).read_text())))
    values = np.array([r[7:] for r in rows[1:]], dtype=np.float32)
    assert np.array_equal(values, direct)
    freqs = np.array(rows[0][7:], dtype=float)
    assert np.array_equal(freqs, header.first_bin_freq_hz + np.arange(header.sweep_length) * header.bin_size_hz)
    assert np.allclose(result.stat_max, direct.max(0))


@pytest.mark.skipif(not (REAL and Path(REAL).is_file() and os.environ.get("VEUSZ_EXE")),
                    reason="set SHR_REAL_FILE and VEUSZ_EXE")
def test_real_file_renders(tmp_path):
    result = core.convert_file(REAL, core.ConvertOptions(output_dir=str(tmp_path), write_csv=False, render=True,
                                                         render_png="all", veusz_exe=os.environ["VEUSZ_EXE"],
                                                         workers=1))
    pdfs = [p for p in result.outputs if p.endswith(".pdf")]
    assert pdfs and Path(pdfs[0]).stat().st_size > 1000
    from pypdf import PdfReader
    outline = PdfReader(pdfs[0]).outline
    assert outline and len(outline) == 2 and len(outline[1]) >= 4     # file entry + its page entries


# %% GUI
def test_gui_smoke():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import shr_converter_gui
    lines: list[str] = []
    assert shr_converter_gui.gui_smoke_test(report=lines.append, workers=2), "\n".join(lines)
