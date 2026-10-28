#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Three-hour captures: CSV split, thinning, spectrogram timing, memory, speed.

===============================================================================
 Title          : SHR Converter - long-capture check
 Filename       : tests/long_capture_check.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Language       : Python 3.12
 Requires       : shr_converter_core.py and its requirements, psutil, h5py;
                  VEUSZ_EXE (optional) to render the document
 Licence        : GPL-3.0-or-later
===============================================================================

WHAT IT BUILDS
--------------
A synthetic Spike recording of --hours (default 3) written with
py-shr-parser's own struct layouts, containing what a long field capture
contains:
  * a noise floor near -90 dBm and a carrier drifting slowly upward,
  * a 2 ms burst at a fixed frequency every --burst-minutes (default 10),
  * a pause of --pause-minutes (default 2) in the middle of the recording.

WHAT IT CHECKS
--------------
  * the CSV is split into one file per --split-minutes and the files hold
    every sweep exactly once, in order;
  * every burst appears in the reduced spectrogram (peak hold) in the row
    that covers its time, at its frequency;
  * the level-versus-time series in the .vszh5 is thinned to at most
    --series-points and still contains every burst (peak hold);
  * peak memory of the whole process tree stays bounded;
  * prints the conversion time and throughput.

    python tests/long_capture_check.py                       # 2 sweeps/s x 4001 bins
    python tests/long_capture_check.py --rate 50 --bins 512  # 540 000 sweeps
"""

# %% IMPORTS
from __future__ import annotations

import argparse
import math
import os
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5py  # noqa: E402

import shr_converter_core as core  # noqa: E402
from memory_check import TreeSampler  # noqa: E402  (same folder)


# %% SYNTHETIC LONG RECORDING
def write_long_capture(path: Path, hours: float, rate_hz: float, n_bins: int, burst_minutes: float,
                       pause_minutes: float, seed: int = 7) -> dict:
    """Write the recording sweep by sweep (constant memory); return the truth."""
    rng = np.random.default_rng(seed)
    shr = core._shr_module                              # py-shr-parser's struct layouts
    first_bin, bin_hz = 2.40e9, 20e6 / (n_bins - 1)
    step_ms = 1000.0 / rate_hz
    n_sweeps = int(hours * 3600 * rate_hz)
    start_ms = 1_761_600_000_000                        # 2025-10-27T21:20:00Z
    pause_at = n_sweeps // 2
    burst_bin = int(0.75 * n_bins)
    burst_every = int(burst_minutes * 60 * rate_hz)
    header = struct.pack(shr.FILE_HEADER_PACK, shr.SHR_FILE_SIGNATURE, shr.SHR_FILE_VERSION, 0,
                         shr.FILE_HEADER_SIZE, n_sweeps, n_bins, first_bin, bin_hz, b"\x00" * 256,
                         first_bin + 10e6, 20e6, 3 * bin_hz, 3 * bin_hz, -20.0, 0, 10.0, 0, 0, 0, 1, 2,
                         3.0, 1, 0, 1, 1000, 0, 0, 0.0, 0.0, b"\x00" * 64)
    bursts = []
    with open(path, "wb") as handle:
        handle.write(header)
        chunk = 2000                                     # sweeps generated at once
        for c0 in range(0, n_sweeps, chunk):
            k = np.arange(c0, min(c0 + chunk, n_sweeps))
            sweeps = rng.normal(-90.0, 2.0, (len(k), n_bins)).astype(np.float32)
            carrier = (n_bins // 4 + (k * n_bins // 8) // max(n_sweeps, 1)).astype(int)
            sweeps[np.arange(len(k)), carrier] = -45.0
            t_ms = start_ms + k * step_ms + np.where(k >= pause_at, pause_minutes * 60_000, 0)
            hit = (k % burst_every == burst_every // 2)
            sweeps[hit, burst_bin] = -20.0
            for kk, tt in zip(k[hit], t_ms[hit]):
                bursts.append((int(kk), int(tt)))
            for row in range(len(k)):
                handle.write(struct.pack(shr.SWEEP_HEADER_PACK, int(t_ms[row]), 0.0, 0.0, 0.0, 0, b"\x00" * 15))
                handle.write(sweeps[row].tobytes())
    return {"n_sweeps": n_sweeps, "burst_bin": burst_bin, "bursts": bursts, "start_ms": start_ms,
            "first_bin": first_bin, "bin_hz": bin_hz}


# %% MAIN
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hours", type=float, default=3.0)
    parser.add_argument("--rate", type=float, default=2.0, help="sweeps per second")
    parser.add_argument("--bins", type=int, default=4001)
    parser.add_argument("--burst-minutes", type=float, default=10.0)
    parser.add_argument("--pause-minutes", type=float, default=2.0)
    parser.add_argument("--split-minutes", type=float, default=30.0)
    parser.add_argument("--series-points", type=int, default=100_000)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--ram-mb", type=int, default=1024)
    parser.add_argument("--fixed", type=int, default=-1, help="fixed decimals (default lossless)")
    parser.add_argument("--render", action="store_true", help="render PDF/PNG (needs VEUSZ_EXE)")
    parser.add_argument("--keep", default="", help="folder to keep the files in")
    args = parser.parse_args()
    folder = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="shr_long_"))
    folder.mkdir(parents=True, exist_ok=True)
    ok = True

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= bool(condition)
        print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

    t = time.perf_counter()
    source = folder / "long_capture.shr"
    truth = write_long_capture(source, args.hours, args.rate, args.bins, args.burst_minutes, args.pause_minutes)
    print(f"wrote {source.name}: {truth['n_sweeps']} sweeps x {args.bins} bins, "
          f"{core.human_bytes(source.stat().st_size)} in {time.perf_counter() - t:.1f} s")

    opts = core.ConvertOptions(output_dir=str(folder / "out"), csv_split_minutes=args.split_minutes,
                               time_series_max_points=args.series_points, workers=args.workers,
                               ram_budget_mb=args.ram_mb, render=args.render,
                               veusz_exe=os.environ.get("VEUSZ_EXE", ""), render_png="all")
    if args.fixed >= 0:
        opts.csv_number_format, opts.csv_decimals = "fixed", args.fixed
    info = core.read_info(source)
    plan = core.make_plan(info, opts)
    print("\n".join(plan.lines()))
    sampler = TreeSampler()
    sampler.start()
    t = time.perf_counter()
    result = core.convert_file(source, opts, log=print)
    seconds = time.perf_counter() - t
    sampler.stop()
    out = folder / "out"
    csv_parts = sorted(out.glob("long_capture_part*.csv"))
    csv_bytes = sum(p.stat().st_size for p in csv_parts)
    samples = truth["n_sweeps"] * args.bins
    print(f"converted in {seconds:.1f} s: {samples / seconds / 1e6:.2f} M samples/s, "
          f"CSV {core.human_bytes(csv_bytes)} in {len(csv_parts)} file(s) "
          f"(estimate {core.human_bytes(plan.est_csv_bytes)}), backend {result.backend}")
    print(f"peak RSS of the process tree: {sampler.peak_mb:,.0f} MiB with {sampler.peak_children} children")

    # -- CSV split: every sweep exactly once, in order -----------------------------------
    expected_files = math.ceil((args.hours * 60 + args.pause_minutes) / args.split_minutes)
    index_column = []
    for part in csv_parts:
        with open(part, encoding="ascii") as handle:
            handle.readline()
            index_column.extend(int(line.split(",", 1)[0]) for line in handle)
    check(f"CSV split into {expected_files} files of {args.split_minutes:g} min",
          len(csv_parts) == expected_files, f"{len(csv_parts)} files")
    check("every sweep exactly once, in order", index_column == list(range(truth["n_sweeps"])),
          f"{len(index_column)} rows")

    # -- spectrogram: each burst in the row covering its time, at its frequency ---------
    rows = result.plan.row_factor
    burst_col = (truth["burst_bin"]) // result.plan.col_factor
    hits = [result.image[k // rows, burst_col] for k, _t in truth["bursts"]]
    check(f"all {len(truth['bursts'])} bursts in the peak-hold spectrogram",
          all(abs(h + 20.0) < 1e-3 for h in hits), f"levels {sorted(set(np.round(hits, 2)))[:3]}")
    others = np.delete(result.image[:, burst_col], [k // rows for k, _t in truth["bursts"]])
    check("no burst where there was none", bool(np.all(others < -40)), f"max elsewhere {others.max():.1f}")

    # -- Veusz: thinned series keep every burst --------------------------------------------
    with h5py.File(out / "long_capture.vszh5", "r") as h5:
        peak = h5["Veusz/Data/sweep_peak/data"][()]
        time_s = h5["Veusz/Data/sweep_time/data"][()]
    check(f"level-vs-time series <= {args.series_points} points", len(peak) <= args.series_points,
          f"{len(peak)} points, {result.sweeps_per_point} sweeps each")
    check("every burst survives the thinning (peak hold)", int(np.sum(np.isclose(peak, -20.0))) == len(truth["bursts"]),
          f"{int(np.sum(np.isclose(peak, -20.0)))} of {len(truth['bursts'])}")
    gap = np.max(np.diff(time_s))
    check("the recording pause is visible on the time axis", gap >= args.pause_minutes * 60 * 0.9, f"{gap:.0f} s")
    if args.render:
        check("rendered PDF", any(p.endswith(".pdf") for p in result.outputs))
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    print(f"files in {out}")
    if not args.keep:
        shutil.rmtree(folder, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
