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
 Version        : 0.0.2 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Language       : Python 3.12
 Requires       : the converter's requirements, pytest; SHR_REAL_FILE (a real
                  Spike .shr, e.g. sweep0v2.shr from the prep folder) and
                  SHR_SM200C_FILE (the SM200C recording with detector code 2)
                  for the real-file tests; VEUSZ_EXE for the render test;
                  py-shr-parser only for its optional cross-check
 Licence        : GPL-3.0-or-later
===============================================================================

Revision history: 0.0.2 (2026-10-28) shr_reader is the reference (py-shr-parser
only as an optional cross-check), reader self-test, SM200C file, CSV
decimation and --join on the command line, display helpers;
0.0.1 (2026-10-28) first version.
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
import shr_reader  # noqa: E402

REAL = os.environ.get("SHR_REAL_FILE", "")
# The SM200C / Spike 4.0 recording (detector code 2) ships in tests/data.
_SM200C_DEFAULT = next(iter(sorted((ROOT / "tests" / "data").glob("*01h01m58s.shr"))), "")
SM200C = os.environ.get("SHR_SM200C_FILE", str(_SM200C_DEFAULT))


# %% ENGINE
def test_self_test_passes():
    lines: list[str] = []
    assert core.self_test(report=lines.append, workers=2), "\n".join(l for l in lines if l.startswith("FAIL"))


def test_reader_self_test_passes():
    assert shr_reader.self_test(verbose=False)


def test_display_helpers():
    assert core.frequency_unit(128e6, 13.964e9) == ("GHz", 1e9)       # not 1.39x10^4 MHz
    assert core.frequency_unit(20e6, 2.42e9) == ("MHz", 1e6)
    assert len(core.short_name("75fb3092-2026-10-28T00_59_00-4_00-W50_2026-10-28_01h01m58s.shr")) <= 32
    wrapped = core.wrap_report_lines(["Note            : " + "word " * 40], 60)
    assert len(wrapped) > 1 and all(len(line) <= 60 for line in wrapped)
    assert all(line.startswith(" " * 18) for line in wrapped[1:])


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


def test_command_line_join_and_decimate(tmp_path):
    source = core.write_synthetic_shr(tmp_path / "whole.shr", n_sweeps=12, n_bins=40)
    parts = core.split_recording(source, [tmp_path / "p1.shr", tmp_path / "p2.shr"], [5, 7])
    run = subprocess.run([sys.executable, str(ROOT / "shr_converter.py"), "--cli", *map(str, parts), "-o",
                          str(tmp_path / "out"), "--join", "--csv-decimate", "3", "--csv-decimate-detector", "min",
                          "--no-vszh5", "-j", "1"], capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stdout + run.stderr
    rows = (tmp_path / "out" / "p1_joined.csv").read_text().splitlines()
    assert len(rows) == 1 + 4 and rows[0].split(",")[3] == "sweeps_combined"
    whole = shr_reader.ShrFile(source).read_amplitudes()
    values = np.array([r.split(",")[8:] for r in rows[1:]], dtype=np.float32)
    assert np.array_equal(values, np.fmin.reduceat(whole, [0, 3, 6, 9], axis=0))
    reader = subprocess.run([sys.executable, str(ROOT / "shr_converter.py"), "--reader", str(parts[0]), "--json"],
                            capture_output=True, text=True, timeout=120)
    assert reader.returncode == 0 and '"sweep_length": 40' in reader.stdout


# %% REAL SPIKE FILE
@pytest.mark.skipif(not (REAL and Path(REAL).is_file()), reason="set SHR_REAL_FILE to a Spike .shr")
def test_real_file_round_trip(tmp_path):
    result = core.convert_file(REAL, core.ConvertOptions(output_dir=str(tmp_path), workers=2))
    with shr_reader.ShrFile(REAL) as shr:
        direct = shr.read_amplitudes()
        header = shr.header
    rows = list(csv.reader(io.StringIO((tmp_path / (Path(REAL).stem + ".csv")).read_text())))
    values = np.array([r[7:] for r in rows[1:]], dtype=np.float32)
    assert np.array_equal(values, direct)
    freqs = np.array(rows[0][7:], dtype=float)
    assert np.array_equal(freqs, header.first_bin_freq_hz + np.arange(header.sweep_length) * header.bin_size_hz)
    assert np.allclose(result.stat_max, direct.max(0))


@pytest.mark.skipif(not (REAL and Path(REAL).is_file()), reason="set SHR_REAL_FILE to a Spike .shr")
def test_real_file_equals_py_shr_parser():
    """Independent cross-check: every sweep bit-exact against py-shr-parser (when it can read the file)."""
    parser_module = pytest.importorskip("shr_parser")
    other = parser_module.ShrFileParser(REAL)
    try:
        other.open()
    except ValueError as exc:                       # e.g. "2 is not a valid ShrVideoDetector"
        pytest.skip(f"py-shr-parser cannot read this file: {exc}")
    try:
        reference = np.stack([s.sweep for s in other])
    finally:
        other.close()
    with shr_reader.ShrFile(REAL) as shr:
        assert np.array_equal(shr.read_amplitudes(), reference)


@pytest.mark.skipif(not (SM200C and Path(SM200C).is_file()), reason="set SHR_SM200C_FILE to the SM200C .shr")
def test_sm200c_detector_2_file(tmp_path):
    """The SM200C / Spike 4.0 recording that py-shr-parser rejects converts exactly."""
    info = core.read_info(SM200C)
    assert info.detector == "Max (code 2, inferred)"
    assert any("0.01 dB grid" in note for note in info.notes)
    core.convert_file(SM200C, core.ConvertOptions(output_dir=str(tmp_path), workers=2, write_vszh5=False))
    rows = list(csv.reader(io.StringIO((tmp_path / (Path(SM200C).stem + ".csv")).read_text())))
    with shr_reader.ShrFile(SM200C) as shr:
        direct = shr.read_amplitudes()
    assert np.array_equal(np.array([r[7:] for r in rows[1:]], dtype=np.float32), direct)
    assert '"Max (code 2, inferred)"' in (tmp_path / (Path(SM200C).stem + "_header.csv")).read_text()


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
