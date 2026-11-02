#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Batch conversion core: logger CSV files -> Veusz plots / reports (no Qt)
=======================================================================
===============================================================================
 Title          : FSP Logger batch conversion core
 Filename       : fsp_batch_core.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-29
 Modified       : 2026-10-29
 Language       : Python 3.8 through 3.12
 Requires       : Python standard library only (fsp_reports.py does the work)
 Licence        : Same terms as rs_fsp_logger.py (not declared by the owner;
                  no grant inferred).
 Attribution    : AI-assisted (Claude) addition to the owner's logger bundle.
 Status         : Internal draft.
===============================================================================

DESCRIPTION
-----------
Everything the batch converter needs that is not GUI: finding logger CSV
files in folders, recognising a logger CSV by its header, planning one new
report folder per CSV, building the fsp_reports.py command, reading its
result and tidying up after a cancelled job. fsp_batch_convert.py (dialog,
standalone window and command line) and rs_fsp_logger.py use it.

Each CSV is converted by its own `python fsp_reports.py --csv ... --output-dir
...` process, exactly as the logger's single-file button does, so a batch
gives the same pages, statistics and optional PDF/PNG as single conversions.
Separate processes run in parallel, cannot share a crash, and release all
memory when they end.

A logger CSV is recognised by the header fsp_reports.py requires:
    date,time,timestamp_iso,freq_hz,trace<n>_dBm[,trace<m>_dBm ...]
Other CSV files met while scanning a folder (report tables, <run>_events.csv,
unrelated files) are skipped and listed.

REVISION HISTORY (newest first)
-------------------------------
0.0.1  2026-10-29  First version, logger bundle 0.10.0 (finished 2026-11-02:
                   Ctrl+C in --cli stops running report processes at once).
===============================================================================
"""

from __future__ import annotations

# %% IMPORTS
import csv
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__version__ = "0.0.1"
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"

__all__ = [
    "LOGGER_REQUIRED_COLUMNS", "TRACE_COLUMN", "REPORT_SCRIPT", "CsvCheck", "BatchOptions",
    "BatchJob", "JobResult", "check_logger_csv", "expand_inputs", "plan_jobs",
    "report_command", "report_environment", "parse_report_output", "cleanup_partial_output",
    "existing_report_folders", "default_jobs", "batch_stamp", "run_one", "run_batch",
    "build_parser", "main",
]

# %% CONSTANTS
#: Columns every logger CSV starts with (see fsp_background.AsyncCaptureCsvWriter).
LOGGER_REQUIRED_COLUMNS = ("date", "time", "timestamp_iso", "freq_hz")
#: One column per recorded analyzer trace.
TRACE_COLUMN = re.compile(r"trace([1-3])_dBm$")
#: The report program, next to this module.
REPORT_SCRIPT = Path(__file__).resolve().with_name("fsp_reports.py")
#: Folder name pattern of a report: <csv stem>_reports_<stamp>.
REPORT_FOLDER_INFIX = "_reports_"
#: BLAS/OpenMP thread caps for every report process (several run at once).
THREAD_CAP_VARIABLES = ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
                        "NUMEXPR_NUM_THREADS")


# %% DATA CLASSES
@dataclass
class CsvCheck:
    """Result of check_logger_csv()."""
    path: Path
    is_logger_csv: bool
    traces: Tuple[int, ...] = ()
    size_bytes: int = 0
    reason: str = ""


@dataclass
class BatchOptions:
    """What a batch does; the dialog and the command line fill this in.

    output_mode "beside": each report folder is created next to its CSV.
    output_mode "folder": all report folders go under output_root; with
    mirror_subfolders, a CSV found in <scanned folder>/a/b is reported in
    <output_root>/a/b, so equal file names in different folders never meet.
    """
    output_mode: str = "beside"
    output_root: str = ""
    mirror_subfolders: bool = True
    recursive: bool = True
    render: bool = False
    jobs: int = 2
    skip_existing: bool = False
    veusz_exe: str = ""
    max_matrix_mib: int = 512
    python: str = sys.executable

    def validate(self) -> None:
        if self.output_mode not in ("beside", "folder"):
            raise ValueError("output_mode must be 'beside' or 'folder'")
        if self.output_mode == "folder" and not str(self.output_root).strip():
            raise ValueError("choose an output folder")
        if int(self.jobs) < 1:
            raise ValueError("jobs must be at least 1")
        if int(self.max_matrix_mib) < 1:
            raise ValueError("max_matrix_mib must be positive")


@dataclass
class BatchJob:
    """One CSV and the NEW report folder it will be converted into."""
    csv_path: Path
    output_dir: Path
    base_folder: Optional[Path] = None      # the scanned folder it came from, if any
    check: Optional[CsvCheck] = None
    skip_reason: str = ""


@dataclass
class JobResult:
    """Outcome of one report process."""
    ok: bool
    pages: int = 0
    rendering: str = ""
    message: str = ""
    output_dir: str = ""
    raw: Dict[str, object] = field(default_factory=dict)


# %% DISCOVERY AND CHECKS
def check_logger_csv(path) -> CsvCheck:
    """Recognise a logger CSV from its first line (cheap, any file size).

    Accepts exactly the columns fsp_reports.py accepts: date, time,
    timestamp_iso, freq_hz and one or more unique trace<n>_dBm columns.
    """
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as error:
        return CsvCheck(path, False, reason=f"unreadable: {error}")
    if size == 0:
        return CsvCheck(path, False, size_bytes=0, reason="empty file")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            header = next(csv.reader([stream.readline()]), [])
    except (OSError, UnicodeDecodeError) as error:
        return CsvCheck(path, False, size_bytes=size, reason=f"unreadable: {error}")
    columns = [name.strip() for name in header]
    traces = []
    for name in columns:
        match = TRACE_COLUMN.fullmatch(name)
        if match:
            traces.append(int(match.group(1)))
    expected = set(LOGGER_REQUIRED_COLUMNS) | {f"trace{n}_dBm" for n in traces}
    if (not traces or len(columns) != len(set(columns)) or set(columns) != expected
            or tuple(columns[:4]) != LOGGER_REQUIRED_COLUMNS):
        return CsvCheck(path, False, size_bytes=size,
                        reason="not a logger CSV (needs date,time,timestamp_iso,freq_hz,trace<n>_dBm)")
    return CsvCheck(path, True, tuple(sorted(traces)), size)


def _is_hidden_staging(path: Path) -> bool:
    """fsp_reports stages in '.<report name>.<random>' folders; never scan them."""
    return any(part.startswith(".") and REPORT_FOLDER_INFIX in part for part in path.parts)


def expand_inputs(items: Iterable, recursive: bool = True, pattern: str = "*.csv"
                  ) -> Tuple[List[Tuple[Path, Optional[Path]]], List[CsvCheck]]:
    """Files and folders -> ([(csv, scanned folder or None)], [skipped checks]).

    A folder contributes its *.csv files (with sub-folders when recursive).
    Files given one by one are checked too. Duplicates (same resolved path)
    are dropped; order is preserved (folders sorted by path).
    """
    found: List[Tuple[Path, Optional[Path]]] = []
    skipped: List[CsvCheck] = []
    seen = set()

    def take(candidate: Path, base: Optional[Path]) -> None:
        key = os.path.normcase(str(candidate.resolve()))
        if key in seen:
            return
        seen.add(key)
        result = check_logger_csv(candidate)
        if result.is_logger_csv:
            found.append((candidate.resolve(), base))
        else:
            skipped.append(result)

    for item in items:
        path = Path(str(item)).expanduser()
        if path.is_dir():
            base = path.resolve()
            walker = base.rglob(pattern) if recursive else base.glob(pattern)
            for candidate in sorted(walker, key=lambda p: str(p).lower()):
                if candidate.is_file() and not _is_hidden_staging(candidate.relative_to(base)):
                    take(candidate, base)
        elif path.is_file():
            take(path, None)
        else:
            skipped.append(CsvCheck(path, False, reason="not found"))
    return found, skipped


def batch_stamp(when: Optional[datetime] = None) -> str:
    """Time stamp shared by every report folder of one batch."""
    return (when or datetime.now()).strftime("%Y%m%d_%H%M%S")


def existing_report_folders(csv_path, parent) -> List[Path]:
    """Completed report folders of this CSV in ``parent`` (<stem>_reports_* with report.json)."""
    parent = Path(parent)
    if not parent.is_dir():
        return []
    prefix = Path(csv_path).stem + REPORT_FOLDER_INFIX
    return sorted(p for p in parent.iterdir()
                  if p.is_dir() and p.name.startswith(prefix) and (p / "report.json").is_file())


def plan_jobs(found: Sequence[Tuple[Path, Optional[Path]]], options: BatchOptions,
              stamp: Optional[str] = None) -> List[BatchJob]:
    """One BatchJob per CSV with a report folder that does not exist yet.

    Equal names are made unique with _2, _3 ... A job whose CSV already has a
    completed report folder at the destination gets skip_reason when
    options.skip_existing is set.
    """
    options.validate()
    stamp = stamp or batch_stamp()
    taken = set()
    jobs: List[BatchJob] = []
    for csv_path, base in found:
        csv_path = Path(csv_path)
        if options.output_mode == "beside":
            parent = csv_path.parent
        else:
            parent = Path(options.output_root).expanduser().resolve()
            if options.mirror_subfolders and base is not None:
                try:
                    parent = parent / csv_path.parent.relative_to(base)
                except ValueError:
                    pass
        name = csv_path.stem + REPORT_FOLDER_INFIX + stamp
        candidate = parent / name
        counter = 2
        while os.path.normcase(str(candidate)) in taken or candidate.exists():
            candidate = parent / f"{name}_{counter}"
            counter += 1
        taken.add(os.path.normcase(str(candidate)))
        job = BatchJob(csv_path, candidate, base)
        if options.skip_existing:
            previous = existing_report_folders(csv_path, parent)
            if previous:
                job.skip_reason = f"already reported ({previous[-1].name})"
        jobs.append(job)
    return jobs


# %% RUNNING ONE REPORT
def default_jobs() -> int:
    """Parallel report processes: half the logical CPUs, 1 to 4."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))


def report_command(job: BatchJob, options: BatchOptions) -> List[str]:
    """argv of the fsp_reports.py process for one job."""
    command = [options.python or sys.executable, str(REPORT_SCRIPT),
               "--csv", str(job.csv_path), "--output-dir", str(job.output_dir),
               "--max-matrix-mib", str(int(options.max_matrix_mib))]
    if options.render:
        command.append("--render")
    return command


def report_environment(options: BatchOptions, base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Environment of a report process: BLAS threads capped at 1 (several
    processes run at once), unbuffered output, VEUSZ_EXE when given."""
    environment = dict(os.environ if base is None else base)
    for name in THREAD_CAP_VARIABLES:
        environment[name] = "1"
    environment["PYTHONUNBUFFERED"] = "1"
    if options.veusz_exe:
        environment["VEUSZ_EXE"] = options.veusz_exe
    return environment


def parse_report_output(exit_code: int, stdout: str, stderr: str, output_dir: str = "") -> JobResult:
    """Read the JSON line fsp_reports.py prints last; stderr on failure."""
    if exit_code == 0:
        for line in reversed([l for l in stdout.strip().splitlines() if l.strip()]):
            try:
                data = json.loads(line)
            except ValueError:
                continue
            rendering = data.get("rendering", {}) or {}
            status = str(rendering.get("status", ""))
            message = {"completed": "PDF + PNG rendered",
                       "not_requested": "",
                       "unavailable_or_failed": "PDF/PNG not rendered: "
                                                + str(rendering.get("error", ""))[:300]}.get(status, status)
            return JobResult(True, int(data.get("pages", 0)), status, message,
                             str(data.get("output_directory", output_dir)), data)
        return JobResult(True, 0, "", "finished without a result line", output_dir)
    text = (stderr or stdout or "").strip()
    last = text.splitlines()[-1] if text else f"exit code {exit_code}"
    return JobResult(False, message=last[:500], output_dir=output_dir)


def cleanup_partial_output(job: BatchJob) -> List[Path]:
    """Remove the hidden staging folder(s) a killed report process left.

    fsp_reports.py builds every report in '.<report name>.<random>' next to
    the destination and renames it at the end, so a cancelled job leaves only
    that hidden folder. Only folders with exactly that prefix are removed, and
    only when the finished report folder does not exist.
    """
    removed: List[Path] = []
    destination = Path(job.output_dir)
    parent = destination.parent
    if destination.exists() or not parent.is_dir():
        return removed
    prefix = "." + destination.name + "."
    for candidate in parent.iterdir():
        if candidate.is_dir() and candidate.name.startswith(prefix):
            shutil.rmtree(candidate, ignore_errors=True)
            removed.append(candidate)
    return removed


# %% HEADLESS BATCH (command line)
def run_one(job: BatchJob, options: BatchOptions, stop_event=None) -> JobResult:
    """Run one report process to completion (or until stop_event is set)."""
    import subprocess
    try:
        process = subprocess.Popen(report_command(job, options), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", env=report_environment(options),
                                   **({"creationflags": 0x08000000} if os.name == "nt" else {}))
    except OSError as error:
        return JobResult(False, message=f"cannot start Python: {error}", output_dir=str(job.output_dir))
    while True:
        try:
            stdout, stderr = process.communicate(timeout=0.25)
            break
        except subprocess.TimeoutExpired:
            if stop_event is not None and stop_event.is_set():
                process.kill()
                process.communicate()
                cleanup_partial_output(job)
                return JobResult(False, message="cancelled", output_dir=str(job.output_dir))
    result = parse_report_output(process.returncode, stdout, stderr, str(job.output_dir))
    if not result.ok:
        cleanup_partial_output(job)
    return result


def run_batch(jobs: Sequence[BatchJob], options: BatchOptions, on_event=None, stop_event=None
              ) -> Dict[str, object]:
    """Convert every job with up to options.jobs report processes at once.

    on_event(kind, job, result) is called with kind 'start', 'done' or
    'skip' from worker threads (keep it thread-safe, e.g. print).
    Returns a summary dict (counts and one entry per job).

    Ctrl+C (KeyboardInterrupt) sets stop_event at once, so running report
    processes are killed and their staging folders removed before the
    exception propagates (it does not wait for them to finish).
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed
    on_event = on_event or (lambda *args: None)
    if stop_event is None:
        stop_event = threading.Event()
    summary: Dict[str, object] = {"converted": 0, "failed": 0, "skipped": 0, "cancelled": 0, "jobs": []}
    runnable = []
    for job in jobs:
        if job.skip_reason:
            summary["skipped"] = int(summary["skipped"]) + 1
            summary["jobs"].append(dict(csv=str(job.csv_path), status="skipped", message=job.skip_reason))
            on_event("skip", job, None)
        else:
            runnable.append(job)

    def work(job):
        if stop_event is not None and stop_event.is_set():
            return job, JobResult(False, message="cancelled", output_dir=str(job.output_dir))
        on_event("start", job, None)
        return job, run_one(job, options, stop_event)

    pool = ThreadPoolExecutor(max_workers=max(1, int(options.jobs)), thread_name_prefix="fsp-batch")
    try:
        for future in as_completed([pool.submit(work, job) for job in runnable]):
            job, result = future.result()
            if result.ok:
                key, status = "converted", "done"
            elif result.message == "cancelled":
                key, status = "cancelled", "cancelled"
            else:
                key, status = "failed", "failed"
            summary[key] = int(summary[key]) + 1
            summary["jobs"].append(dict(csv=str(job.csv_path), status=status, output_dir=str(job.output_dir),
                                        pages=result.pages, rendering=result.rendering, message=result.message))
            on_event("done", job, result)
    except BaseException:
        stop_event.set()                       # workers kill their processes and clean up
        raise
    finally:
        pool.shutdown(wait=True)
    return summary


def build_parser():
    """Command line of the headless batch (fsp_batch_convert.py --cli ...)."""
    import argparse
    parser = argparse.ArgumentParser(
        prog="fsp_batch_convert.py --cli",
        description="Convert R&S FSP logger CSV files (single files, several files or whole folders) "
                    "to native Veusz plots/reports, one new report folder per CSV.")
    parser.add_argument("inputs", nargs="+", help="CSV files and/or folders")
    parser.add_argument("--no-recursive", dest="recursive", action="store_false",
                        help="scan only the top level of each folder")
    parser.add_argument("--output-dir", default="", help="put every report folder under this folder "
                        "(default: next to each CSV)")
    parser.add_argument("--flat", dest="mirror", action="store_false",
                        help="with --output-dir: do not recreate the scanned sub-folders")
    parser.add_argument("--render", action="store_true", help="also render PDF + PNG (needs Veusz)")
    parser.add_argument("--veusz-exe", default=os.environ.get("VEUSZ_EXE", ""), help="Veusz program")
    parser.add_argument("--jobs", type=int, default=default_jobs(), help="parallel report processes")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip CSVs that already have a <stem>_reports_* folder with report.json")
    parser.add_argument("--max-matrix-mib", type=int, default=512, help="per-file raw matrix limit")
    parser.add_argument("--dry-run", action="store_true", help="list the plan, convert nothing")
    return parser


def main(argv=None) -> int:
    """Headless batch. Exit 0 all converted/skipped, 1 any failure, 2 nothing to do."""
    import threading
    args = build_parser().parse_args(argv)
    options = BatchOptions(output_mode="folder" if args.output_dir else "beside",
                           output_root=args.output_dir, mirror_subfolders=args.mirror,
                           recursive=args.recursive, render=args.render, jobs=args.jobs,
                           skip_existing=args.skip_existing, veusz_exe=args.veusz_exe,
                           max_matrix_mib=args.max_matrix_mib)
    found, skipped = expand_inputs(args.inputs, recursive=args.recursive)
    for check in skipped:
        print(f"skip  {check.path}  ({check.reason})", flush=True)
    if not found:
        print("No logger CSV files found.", flush=True)
        return 2
    jobs = plan_jobs(found, options)
    for job in jobs:
        print(f"plan  {job.csv_path}  ->  {job.output_dir}" + (f"  [{job.skip_reason}]" if job.skip_reason else ""),
              flush=True)
    if args.dry_run:
        return 0
    lock = threading.Lock()

    def event(kind, job, result):
        with lock:
            if kind == "start":
                print(f"start {job.csv_path.name}", flush=True)
            elif kind == "done":
                state = "done " if result.ok else "FAIL "
                detail = (f"{result.pages} pages" + (f"; {result.message}" if result.message else "")
                          if result.ok else result.message)
                print(f"{state} {job.csv_path.name}: {detail}", flush=True)

    stop = threading.Event()
    try:
        summary = run_batch(jobs, options, event, stop)
    except KeyboardInterrupt:
        stop.set()
        for job in jobs:
            cleanup_partial_output(job)
        print("Interrupted; partial report folders removed.", flush=True)
        return 1
    print(json.dumps({k: summary[k] for k in ("converted", "failed", "skipped", "cancelled")}), flush=True)
    return 1 if summary["failed"] else 0


# %% INTERACTIVE SCRATCH CELL (Spyder)
# from fsp_batch_core import expand_inputs, plan_jobs, BatchOptions
# found, skipped = expand_inputs([r"C:\Users\wwallace\Claude\Projects\FSP Logger\data"])
# for job in plan_jobs(found, BatchOptions()): print(job.csv_path, "->", job.output_dir)
