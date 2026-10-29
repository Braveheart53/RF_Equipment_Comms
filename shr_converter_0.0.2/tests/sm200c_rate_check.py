#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""An SM200C-rate multi-file recording: join, CSV decimation, speed and memory.

===============================================================================
 Title          : SHR Converter - SM200C-rate check
 Filename       : tests/sm200c_rate_check.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12
 Requires       : shr_converter_core.py 0.0.2 and its requirements, psutil
 Licence        : GPL-3.0-or-later
===============================================================================

WHAT IT BUILDS
--------------
--files synthetic .shr files that continue one another, like a multi-file
Spike recording, with the settings of the SM200C sample (2026-10-28):
8384 bins of 15258.789 Hz from 13836.029 MHz, ~29.9 sweeps/s (33.35 ms,
stamps rounded to whole ms with +-1.5 ms jitter), detector code 2 (Max) and
amplitudes on the 0.01 dB grid + 0.00824 dB, a carrier and one burst per
minute. Each file holds --minutes of recording (default 10 min = 17 991
sweeps = 0.60 GB).

WHAT IT CHECKS
--------------
  * the files group into one recording (join_files) and convert as one;
  * csv_decimate (default 30, peak hold) gives one CSV row per 30 sweeps,
    in order, with every burst kept;
  * the .vszh5 spectrogram has no blank rows (no false gaps from jitter);
  * the detector label and the 0.01 dB note reach the header table;
  * prints time, throughput and peak memory of the process tree.

    python tests/sm200c_rate_check.py                  # 2 files x 10 min
    python tests/sm200c_rate_check.py --files 3 --minutes 20 --workers 7

REVISION HISTORY (newest first)
-------------------------------
 0.0.1  2026-10-28  First internal draft.
"""

# %% IMPORTS
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5py  # noqa: E402

import shr_converter_core as core  # noqa: E402
import shr_reader  # noqa: E402
from memory_check import TreeSampler  # noqa: E402

# Settings of the SM200C sample (75fb3092-...-01h01m58s.shr).
FIRST_BIN_HZ = 13_836_029_052.734375
BIN_HZ = 15_258.7890625
N_BINS = 8384
PERIOD_MS = 15_341.0 / 459.0          # 33.42 ms: the sample's mean sweep interval


# %% SYNTHETIC SM200C RECORDING
def write_sm200c_like(folder: Path, files: int, minutes: float, seed: int = 11) -> dict:
    """Write ``files`` consecutive .shr files; return the truth (bursts, counts)."""
    rng = np.random.default_rng(seed)
    per_file = int(minutes * 60_000.0 / PERIOD_MS)
    header = shr_reader.ShrHeader(
        sweep_length=N_BINS, first_bin_freq_hz=FIRST_BIN_HZ, bin_size_hz=BIN_HZ, center_freq_hz=13.9e9,
        span_hz=128e6, rbw_hz=30_000.0, vbw_hz=30_000.0, ref_level=-20.0, detector=2, processing_units=2,
        window_bandwidth=1.96608, decimation_type=1, decimation_count=1, decimation_time_ms=40)
    record = shr_reader.sweep_record_dtype(N_BINS)
    start_ms = 1_793_163_718_211
    burst_bin, carrier_bin = 6000, 5174
    bursts, paths = [], []
    every = int(60_000.0 / PERIOD_MS)                    # one burst a minute
    for f in range(files):
        path = folder / f"sm200c_like_{f + 1:03d}.shr"
        header.sweep_count = per_file
        with open(path, "wb") as handle:
            handle.write(header.to_bytes())
            for k0 in range(0, per_file, 1000):
                k = np.arange(k0, min(k0 + 1000, per_file)) + f * per_file   # recording-wide index
                amps = rng.normal(-104.6, 0.8, (k.size, N_BINS))
                amps[:, carrier_bin - 2:carrier_bin + 3] = -51.0
                hit = k % every == every // 2
                amps[hit, burst_bin] = -30.0
                bursts.extend(int(x) for x in k[hit])
                records = np.zeros(k.size, dtype=record)
                records["amplitude"] = (np.round(amps / 0.01) * 0.01 + 0.00824).astype(np.float32)
                records["timestamp_ms"] = np.rint(start_ms + k * PERIOD_MS + rng.uniform(-1.5, 1.5, k.size))
                records.tofile(handle)
        paths.append(path)
    return {"paths": paths, "n_sweeps": per_file * files, "bursts": bursts, "burst_bin": burst_bin}


# %% MAIN
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--files", type=int, default=2)
    parser.add_argument("--minutes", type=float, default=10.0, help="recording per file")
    parser.add_argument("--decimate", type=int, default=30, help="sweeps per CSV row")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ram-mb", type=int, default=1024)
    parser.add_argument("--keep", default="", help="folder to keep the files in")
    args = parser.parse_args()
    folder = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="shr_sm200c_rate_"))
    folder.mkdir(parents=True, exist_ok=True)
    ok = True

    def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= bool(condition)
        print(("PASS " if condition else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

    t = time.perf_counter()
    truth = write_sm200c_like(folder, args.files, args.minutes)
    size = sum(p.stat().st_size for p in truth["paths"])
    print(f"wrote {args.files} file(s): {truth['n_sweeps']} sweeps x {N_BINS} bins, "
          f"{core.human_bytes(size)} in {time.perf_counter() - t:.1f} s")
    opts = core.ConvertOptions(output_dir=str(folder / "out"), join_files=True, csv_decimate=args.decimate,
                               workers=args.workers, ram_budget_mb=args.ram_mb)
    groups = core.group_recordings(truth["paths"])
    info = core.read_info(groups[0])
    plan = core.make_plan(info, opts)
    print("\n".join(plan.lines()))
    sampler = TreeSampler()
    sampler.start()
    t = time.perf_counter()
    results = core.convert_files(truth["paths"], opts, log=lambda _s: None)
    seconds = time.perf_counter() - t
    sampler.stop()
    out = folder / "out"
    csv_path = out / "sm200c_like_001_joined.csv"
    samples = truth["n_sweeps"] * N_BINS
    print(f"converted in {seconds:.1f} s: {samples / seconds / 1e6:.2f} M samples/s, "
          f"{core.human_bytes(size / seconds)}/s of SHR; CSV {core.human_bytes(csv_path.stat().st_size)} "
          f"(estimate {core.human_bytes(plan.est_csv_bytes)})")
    print(f"peak RSS of the process tree: {sampler.peak_mb:,.0f} MiB with {sampler.peak_children} children")

    check("the files group into one recording", len(groups) == 1 and len(results) == 1 and results[0].info.is_set,
          f"{len(groups)} group(s)")
    with open(csv_path, encoding="ascii") as handle:
        header_line = handle.readline().split(",")
        burst_col = header_line.index(core.frequency_text(FIRST_BIN_HZ + truth["burst_bin"] * BIN_HZ))
        first_index, burst_rows = [], []
        for line in handle:
            fields = line.split(",")
            first_index.append(int(fields[0]))
            if float(fields[burst_col]) > -40.0:
                burst_rows.append(int(fields[0]) // args.decimate)
    expected_rows = int(np.ceil(truth["n_sweeps"] / args.decimate))
    check(f"one CSV row per {args.decimate} sweeps, in order",
          first_index == list(range(0, truth["n_sweeps"], args.decimate)), f"{len(first_index)} of {expected_rows}")
    check("every burst kept by the peak-hold decimation",
          burst_rows == sorted({b // args.decimate for b in truth["bursts"]}),
          f"{len(burst_rows)} of {len(truth['bursts'])}")
    with h5py.File(out / "sm200c_like_001_joined.vszh5", "r") as h5:
        spectrogram = h5["Veusz/Data/spectrogram/data"][()]
    blank = int(np.all(np.isnan(spectrogram), axis=1).sum())
    check("no blank spectrogram rows (no false gaps from the jitter)", blank == 0, f"{blank} blank rows")
    header_table = (out / "sm200c_like_001_joined_header.csv").read_text(encoding="utf-8")
    check("detector label and 0.01 dB note in the header table",
          "Max (code 2, inferred)" in header_table and "0.01 dB grid" in header_table)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    if not args.keep:
        shutil.rmtree(folder, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
