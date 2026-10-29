#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Peak memory of a large conversion: is it set by the RAM budget, not the file?

===============================================================================
 Title          : SHR Converter - memory check
 Filename       : tests/memory_check.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Language       : Python 3.12
 Requires       : shr_converter_core.py and its requirements, psutil
 Licence        : GPL-3.0-or-later
===============================================================================

Writes a synthetic SHR file of --sweeps x --bins float32 (default 1500 x
65536 = 393 MB), converts it (CSV sweeps_as_rows + .vszh5) with --workers
and --ram-mb, samples the resident memory of this process and all its
worker processes every 50 ms, and reports the peak against the file size.
Pass: peak of the whole process tree < --limit-mb (default: RAM budget +
300 MB per process for interpreters and libraries).

    python tests/memory_check.py --sweeps 1500 --bins 65536 --workers 2 --ram-mb 256
"""

# %% IMPORTS
from __future__ import annotations

import argparse
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil  # noqa: E402

import shr_converter_core as core  # noqa: E402


# %% MEMORY SAMPLER
class TreeSampler(threading.Thread):
    """Peak RSS (MiB) of this process plus its children, sampled every 50 ms."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak_mb = 0.0
        self.peak_children = 0
        self._halt = threading.Event()

    def run(self) -> None:
        me = psutil.Process()
        while not self._halt.is_set():
            total, children = 0, 0
            try:
                total = me.memory_info().rss
                for child in me.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                        children += 1
                    except psutil.Error:
                        pass
            except psutil.Error:
                pass
            if total / 2 ** 20 > self.peak_mb:
                self.peak_mb, self.peak_children = total / 2 ** 20, children
            time.sleep(0.05)

    def stop(self) -> None:
        self._halt.set()
        self.join()


# %% MAIN
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sweeps", type=int, default=1500)
    parser.add_argument("--bins", type=int, default=65536)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--ram-mb", type=int, default=256)
    parser.add_argument("--limit-mb", type=float, default=0.0)
    parser.add_argument("--keep", default="", help="folder to keep the files in")
    args = parser.parse_args()
    folder = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="shr_memory_"))
    folder.mkdir(parents=True, exist_ok=True)
    source = core.write_synthetic_shr(folder / "large.shr", n_sweeps=args.sweeps, n_bins=args.bins)
    size_mb = source.stat().st_size / 2 ** 20
    core.flush_memory()
    baseline = psutil.Process().memory_info().rss / 2 ** 20
    sampler = TreeSampler()
    sampler.start()
    started = time.perf_counter()
    opts = core.ConvertOptions(output_dir=str(folder / "out"), workers=args.workers, ram_budget_mb=args.ram_mb)
    plan = core.make_plan(core.read_info(source), opts)
    core.IN_PROCESS_MAX_SAMPLES = 0 if args.workers > 1 else core.IN_PROCESS_MAX_SAMPLES
    result = core.convert_file(source, opts)
    seconds = time.perf_counter() - started
    sampler.stop()
    csv_mb = (folder / "out" / "large.csv").stat().st_size / 2 ** 20
    limit = args.limit_mb or args.ram_mb + 300.0 * (1 + args.workers)
    print("\n".join(plan.lines()))
    print(f"SHR file          : {size_mb:,.0f} MiB ({args.sweeps} x {args.bins})")
    print(f"CSV written       : {csv_mb:,.0f} MiB in {seconds:.1f} s ({result.backend})")
    print(f"Baseline RSS      : {baseline:,.0f} MiB (this process before converting)")
    print(f"Peak RSS of tree  : {sampler.peak_mb:,.0f} MiB with {sampler.peak_children} child process(es)")
    print(f"Limit             : {limit:,.0f} MiB")
    ok = sampler.peak_mb < limit
    print("PASS memory bounded by the budget" if ok else "FAIL peak above the limit")
    if not args.keep:
        import shutil
        shutil.rmtree(folder, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
