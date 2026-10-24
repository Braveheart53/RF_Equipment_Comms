#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""FSP CSV-to-Veusz reporting, version 0.1.1, 2026-10-23.

Python 3.8 through 3.12; NumPy, h5py, adjacent vszh5_writer.py required.
The GUI launches this module in an isolated process only after acquisition
and CSV drain finish. No VISA or GUI dependency is imported here.

Revision 0.1.1: strict two-pass parser, disk-backed raw matrices, chunked
parallel reductions, native plots and Markdown/JSON/CSV reports, optional
Veusz PDF/PNG rendering. Synthetic fixtures in tests are not measurements.
"""
from __future__ import annotations

# %% IMPORTS AND RESOURCE LIMITS
import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import vszh5_writer as native_writer

__version__ = "0.1.1"
TRACE_PATTERN = re.compile(r"trace([1-3])_dBm$")
DEFAULT_MAX_MATRIX_MIB = 512
CHUNK_CAPTURE_COUNT = 128

# %% STRICT CSV VALIDATION
class ReportValidationError(ValueError):
    """Reject ambiguous, inconsistent or incomplete input without data loss."""


def file_signature(path):
    source_stat = path.stat()
    return (source_stat.st_dev, source_stat.st_ino, source_stat.st_size, source_stat.st_mtime_ns)


def iter_capture_blocks(source_path):
    """Yield timestamp, frequency vector and trace arrays for each capture.

    Legacy CSV has no explicit capture identifier. Contiguous timestamp groups
    define captures; frequency axes must repeat exactly and timestamps must
    strictly increase. A single malformed group is rejected, not truncated.
    Naive timestamps retain local wall-time semantics (including DST ambiguity).
    """
    with Path(source_path).open("r", encoding="utf-8-sig", newline="") as source_stream:
        reader = csv.DictReader(source_stream)
        columns = reader.fieldnames or []
        required = {"date", "time", "timestamp_iso", "freq_hz"}
        trace_columns = [(int(TRACE_PATTERN.fullmatch(name).group(1)), name)
                         for name in columns if TRACE_PATTERN.fullmatch(name)]
        if (len(columns) != len(set(columns)) or not required.issubset(columns) or
                not trace_columns or set(columns) != required | {name for _, name in trace_columns}):
            raise ReportValidationError("Expected unique logger columns date,time,timestamp_iso,freq_hz,trace<n>_dBm.")
        current_timestamp = None
        current_frequencies = []
        current_values = {number: [] for number, _ in trace_columns}
        reference_axis = None
        previous_datetime = None
        aware_timestamps = None

        def validate_block(timestamp_text):
            nonlocal reference_axis, previous_datetime, aware_timestamps
            axis = np.asarray(current_frequencies, dtype=float)
            if not axis.size or not np.all(np.diff(axis) > 0):
                raise ReportValidationError("Non-increasing frequency axis or duplicate timestamp/capture.")
            if reference_axis is None:
                reference_axis = axis.copy()
            elif axis.shape != reference_axis.shape or not np.array_equal(axis, reference_axis):
                raise ReportValidationError("Incomplete capture or changed frequency grid at " + timestamp_text)
            try:
                capture_datetime = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
            except ValueError as error:
                raise ReportValidationError("Invalid ISO timestamp: " + timestamp_text) from error
            current_aware = capture_datetime.utcoffset() is not None
            if aware_timestamps is None:
                aware_timestamps = current_aware
            if aware_timestamps != current_aware:
                raise ReportValidationError("Mixed naive and timezone-aware timestamps.")
            if previous_datetime is not None and capture_datetime <= previous_datetime:
                raise ReportValidationError("Capture timestamps must strictly increase.")
            previous_datetime = capture_datetime
            return timestamp_text, axis, {number: np.asarray(values, dtype=float)
                                           for number, values in current_values.items()}

        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ReportValidationError("Malformed CSV row %d." % row_number)
            timestamp_text = row["timestamp_iso"]
            if current_timestamp is not None and timestamp_text != current_timestamp:
                yield validate_block(current_timestamp)
                current_frequencies = []
                current_values = {number: [] for number, _ in trace_columns}
            current_timestamp = timestamp_text
            try:
                frequency_hz = float(row["freq_hz"])
                trace_values = {number: float(row[name]) for number, name in trace_columns}
            except ValueError as error:
                raise ReportValidationError("Non-numeric value at CSV row %d." % row_number) from error
            if frequency_hz < 0 or not all(math.isfinite(value) for value in [frequency_hz] + list(trace_values.values())):
                raise ReportValidationError("Invalid frequency/non-finite level at row %d." % row_number)
            if row["date"] != timestamp_text[:10] or not timestamp_text[11:].startswith(row["time"]):
                raise ReportValidationError("Inconsistent date/time columns at row %d." % row_number)
            current_frequencies.append(frequency_hz)
            for number, value in trace_values.items():
                current_values[number].append(value)
        if current_timestamp is None:
            raise ReportValidationError("CSV has no capture data.")
        yield validate_block(current_timestamp)


# %% PARALLEL CHUNKED REDUCTIONS

def trace_statistics(trace_number, power_matrix, frequency_hz):
    """Compute statistics without equating summed bins to integrated RF power.

    Mean levels are averaged in linear power, NOT arithmetically in dBm.
    Scaling to the largest level per bin avoids overflow during conversion.
    NumPy numerical work may execute concurrently across the per-trace pool.
    """
    capture_count, frequency_count = power_matrix.shape
    minimum_dbm = np.full(frequency_count, np.inf)
    maximum_dbm = np.full(frequency_count, -np.inf)
    peak_dbm = np.empty(capture_count)
    peak_frequency_hz = np.empty(capture_count)
    for first in range(0, capture_count, CHUNK_CAPTURE_COUNT):
        values = np.asarray(power_matrix[first:first + CHUNK_CAPTURE_COUNT])
        minimum_dbm = np.minimum(minimum_dbm, np.min(values, axis=0))
        maximum_dbm = np.maximum(maximum_dbm, np.max(values, axis=0))
        peak_indices = np.argmax(values, axis=1)
        last = first + len(values)
        peak_dbm[first:last] = values[np.arange(len(values)), peak_indices]
        peak_frequency_hz[first:last] = frequency_hz[peak_indices]
    scaled_sum = np.zeros(frequency_count)
    for first in range(0, capture_count, CHUNK_CAPTURE_COUNT):
        values = np.asarray(power_matrix[first:first + CHUNK_CAPTURE_COUNT])
        with np.errstate(under="ignore"):
            scaled_sum += np.sum(np.power(10.0, (values - maximum_dbm) / 10.0), axis=0)
    mean_dbm = maximum_dbm + 10.0 * np.log10(scaled_sum / capture_count)
    peak_index = int(np.argmax(peak_dbm))
    return dict(trace_number=trace_number, minimum_dbm=minimum_dbm,
                maximum_dbm=maximum_dbm, linear_mean_dbm=mean_dbm,
                peak_dbm=peak_dbm, peak_frequency_hz=peak_frequency_hz,
                peak_capture_index=peak_index, global_peak_dbm=float(peak_dbm[peak_index]),
                global_peak_frequency_hz=float(peak_frequency_hz[peak_index]))


# %% NATIVE DOCUMENT AND REPORT TABLES

def write_native_document(destination, metadata, frequency_hz, elapsed_s, matrices, statistics):
    document = native_writer.VszDoc("R&S FSP logger 0.8.1 / fsp_reports " + __version__)
    summary_lines = ["Source: " + Path(metadata["source_csv"]).name,
                     "Captures: %d; bins: %d; traces: %s" % (metadata["captures"], len(frequency_hz), metadata["traces"]),
                     "First: " + metadata["first_timestamp"], "Last: " + metadata["last_timestamp"],
                     "Spectral means use linear power, not arithmetic dBm.",
                     "Raw values embedded without decimation.",
                     "Waterfall row = capture index, not uniformly sampled time.",
                     "RBW/detector/calibration unknown; no compliance assertion."]
    pages = native_writer.text_page(document, "measurement_report", "R&S FSP measurement report", summary_lines)
    with native_writer.VeuszWriter(destination, compress=True, writer_tag="fsp_reports " + __version__) as writer:
        writer.dataset_1d("frequency_hz", frequency_hz, tags=("axis", "raw"))
        writer.dataset_1d("elapsed_s", elapsed_s, tags=("axis", "raw"))
        writer.dataset_text("timestamp_iso", metadata["timestamps"], tags=("raw", "metadata"))
        # Provenance is immutable; final renderer status lives in report.json.
        writer.dataset_text("acquisition_metadata_json", [json.dumps(metadata, sort_keys=True)], tags=("metadata",))
        last_capture_traces = []
        for result in statistics:
            number = result["trace_number"]
            prefix = "trace%d_" % number
            power_matrix = matrices[number]
            writer.dataset_2d(prefix + "raw_dbm", power_matrix, xcent=frequency_hz,
                              ycent=np.arange(len(elapsed_s), dtype=float), tags=("raw", "trace%d" % number))
            datasets = {name: result[name] for name in ("minimum_dbm", "maximum_dbm", "linear_mean_dbm", "peak_dbm", "peak_frequency_hz")}
            datasets.update(first_dbm=power_matrix[0], last_dbm=power_matrix[-1])
            for name, values in datasets.items():
                writer.dataset_1d(prefix + name, values, tags=("trace%d" % number,))
            last_capture_traces.append(native_writer.Trace("frequency_hz", prefix + "last_dbm", "Trace %d" % number))
            spectrum_page = "trace%d_spectral_envelope" % number
            native_writer.xy_page(document, spectrum_page, [
                native_writer.Trace("frequency_hz", prefix + "minimum_dbm", "Minimum"),
                native_writer.Trace("frequency_hz", prefix + "linear_mean_dbm", "Linear-power mean"),
                native_writer.Trace("frequency_hz", prefix + "maximum_dbm", "Maximum")],
                title="Trace %d: spectral envelope" % number, xlabel="Frequency (Hz)", ylabel="Level (dBm)")
            waterfall_page = "trace%d_waterfall" % number
            native_writer.image_page(document, waterfall_page, prefix + "raw_dbm", title="Trace %d: all captures" % number,
                                     xlabel="Frequency (Hz)", ylabel="Capture index (zero-based)", zlabel="Level (dBm)")
            trend_page = "trace%d_peak_history" % number
            native_writer.grid_page(document, trend_page, [
                native_writer.Panel([native_writer.Trace("elapsed_s", prefix + "peak_dbm")], title="Peak level",
                                    xlabel="Elapsed time (s)", ylabel="Level (dBm)"),
                native_writer.Panel([native_writer.Trace("elapsed_s", prefix + "peak_frequency_hz")], title="Peak frequency",
                                    xlabel="Elapsed time (s)", ylabel="Frequency (Hz)")],
                                    columns=1, title="Trace %d: peak history" % number)
            pages.extend([spectrum_page, waterfall_page, trend_page])
        native_writer.xy_page(document, "last_capture", last_capture_traces, title="Last complete capture",
                              xlabel="Frequency (Hz)", ylabel="Level (dBm)")
        pages.append("last_capture")
        writer.finish(document.text())
    return pages


def write_statistics_tables(directory, frequency_hz, elapsed_s, timestamps, statistics):
    with (directory / "spectral_statistics.csv").open("w", newline="", encoding="utf-8") as stream:
        output = csv.writer(stream)
        output.writerow(["freq_hz"] + ["trace%d_%s" % (result["trace_number"], name)
                        for result in statistics for name in ("minimum_dbm", "linear_mean_dbm", "maximum_dbm")])
        for index, frequency in enumerate(frequency_hz):
            output.writerow([frequency] + [result[name][index] for result in statistics
                            for name in ("minimum_dbm", "linear_mean_dbm", "maximum_dbm")])
    with (directory / "capture_statistics.csv").open("w", newline="", encoding="utf-8") as stream:
        output = csv.writer(stream)
        output.writerow(["timestamp_iso", "elapsed_s"] + ["trace%d_%s" % (result["trace_number"], name)
                        for result in statistics for name in ("peak_dbm", "peak_frequency_hz")])
        for index, timestamp in enumerate(timestamps):
            output.writerow([timestamp, elapsed_s[index]] + [result[name][index] for result in statistics
                            for name in ("peak_dbm", "peak_frequency_hz")])


# %% VALIDATED TWO-PASS IMPORT AND ATOMIC BUNDLE PUBLICATION

def create_reports(csv_path, output_directory, render=False, max_matrix_mib=DEFAULT_MAX_MATRIX_MIB):
    """Write a new bundle; never overwrite an existing destination or source.

    First pass validates and sizes the data. Second pass fills disk-backed
    matrices. Signatures are checked after both passes and the SHA-256 read.
    A private staging directory is renamed only when required reports exist.
    Optional renderer failure preserves all native/numerical deliverables.
    The raw-matrix budget is NOT a guarantee on total process resident memory.
    """
    source = Path(csv_path).expanduser().resolve()
    destination = Path(output_directory).expanduser().resolve()
    if destination.exists():
        raise FileExistsError("Choose a new output directory; existing reports are never overwritten.")
    if max_matrix_mib <= 0:
        raise ValueError("max_matrix_mib must be positive.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_signature = file_signature(source)
    timestamps = []
    matrix_bytes = 0
    for timestamp, frequency_axis, trace_values in iter_capture_blocks(source):
        timestamps.append(timestamp)
        if len(timestamps) == 1:
            frequency_hz = frequency_axis.copy()
            trace_numbers = sorted(trace_values)
        matrix_bytes = len(timestamps) * len(frequency_hz) * len(trace_numbers) * 8
        if matrix_bytes > max_matrix_mib * 1024 ** 2:
            raise ReportValidationError("Raw matrices exceed --max-matrix-mib (%d MiB). Split the CSV or raise this limit." % max_matrix_mib)
    if file_signature(source) != original_signature:
        raise ReportValidationError("CSV changed during validation; stop recording first.")
    if shutil.disk_usage(destination.parent).free < 3 * matrix_bytes + 16 * 1024 ** 2:
        raise OSError("Insufficient free disk space for scratch matrices and reports.")
    staging = Path(tempfile.mkdtemp(prefix="." + destination.name + ".", dir=str(destination.parent)))
    scratch = staging / "scratch"
    scratch.mkdir()
    matrices = {}
    try:
        for number in trace_numbers:
            matrices[number] = np.memmap(str(scratch / ("trace%d.bin" % number)), mode="w+", dtype="float64",
                                        shape=(len(timestamps), len(frequency_hz)))
        imported_count = 0
        for index, (timestamp, axis, traces) in enumerate(iter_capture_blocks(source)):
            if index >= len(timestamps) or timestamp != timestamps[index] or not np.array_equal(axis, frequency_hz):
                raise ReportValidationError("CSV changed between parsing passes.")
            for number in trace_numbers:
                matrices[number][index] = traces[number]
            imported_count += 1
        if imported_count != len(timestamps) or file_signature(source) != original_signature:
            raise ReportValidationError("CSV changed during import.")
        initial_time = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
        elapsed_s = np.asarray([(datetime.fromisoformat(text.replace("Z", "+00:00")) - initial_time).total_seconds()
                                for text in timestamps])
        with ThreadPoolExecutor(max_workers=min(3, len(trace_numbers))) as executor:
            futures = [executor.submit(trace_statistics, number, matrices[number], frequency_hz) for number in trace_numbers]
            statistics = [future.result() for future in futures]
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if file_signature(source) != original_signature:
            raise ReportValidationError("CSV changed during provenance hashing.")
        metadata = dict(report_engine_version=__version__, writer_version=native_writer.__version__,
                        generated_utc=datetime.now(timezone.utc).isoformat(), source_csv=str(source),
                        source_sha256=digest.hexdigest(), captures=len(timestamps), frequency_points=len(frequency_hz),
                        traces=trace_numbers, timestamps=timestamps, first_timestamp=timestamps[0], last_timestamp=timestamps[-1],
                        duration_s=float(elapsed_s[-1]), spectral_mean="10*log10(mean(10**(dBm/10))) per frequency bin",
                        time_axis="Elapsed seconds; naive timestamps preserve local wall time.",
                        limitations=["RBW, VBW, detector, impedance and calibration metadata are absent from legacy CSV.",
                                     "Not an EMC compliance report or integrated channel-power measurement.",
                                     "Single-bin or single-capture image extents use +/-0.5 display units only.",
                                     "Legacy CSV cannot prove whether the first or sole capture was truncated."], trace_statistics=[])
        for result in statistics:
            metadata["trace_statistics"].append({name: result[name] for name in
                ("trace_number", "global_peak_dbm", "global_peak_frequency_hz", "peak_capture_index")})
        metadata["pages"] = write_native_document(staging / "fsp_report.vszh5", metadata, frequency_hz, elapsed_s, matrices, statistics)
        write_statistics_tables(staging, frequency_hz, elapsed_s, timestamps, statistics)
        metadata["rendering"] = dict(requested=bool(render), status="not_requested")
        if render:
            try:
                rendered = native_writer.render_pages(staging / "fsp_report.vszh5", outdir=staging / "rendered",
                                                      png_pages="all", pdf=True, timeout=180.0,
                                                      pdf_info={"title": "R&S FSP measurement report"})
                metadata["rendering"] = dict(requested=True, status="completed", files=[str(path.relative_to(staging)) for path in rendered])
            except Exception as render_error:
                metadata["rendering"] = dict(requested=True, status="unavailable_or_failed", error=str(render_error))
        (staging / "report.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        lines = ["# R&S FSP measurement report", "", "## Acquisition", "", "| Item | Value |", "|---|---|"]
        for key in ("source_csv", "source_sha256", "captures", "frequency_points", "traces", "first_timestamp", "last_timestamp", "duration_s"):
            lines.append("| %s | %s |" % (key, str(metadata[key]).replace("|", "\\|")))
        lines += ["", "## Trace extrema", "", "| Trace | Peak (dBm) | Frequency (Hz) | Capture index |", "|---|---:|---:|---:|"]
        for result in metadata["trace_statistics"]:
            lines.append("| {trace_number} | {global_peak_dbm:.4f} | {global_peak_frequency_hz:.6f} | {peak_capture_index} |".format(**result))
        lines += ["", "## Interpretation", "", "Means are computed in linear power per frequency bin, not arithmetic dBm.",
                  "Waterfalls use capture index, retaining irregular capture timing in elapsed_s/timestamp_iso datasets.",
                  "Tied maxima select the first bin/capture. No EMC pass/fail or standards-conformance claim is made.", ""]
        lines += metadata["limitations"] + ["", "## Rendering", "", "```json", json.dumps(metadata["rendering"], indent=2), "```", ""]
        (staging / "report.md").write_text("\n".join(lines), encoding="utf-8")
        for matrix in matrices.values():
            matrix.flush()
            matrix._mmap.close()
        matrices.clear()
        shutil.rmtree(scratch)
        if destination.exists():
            raise FileExistsError("Report destination appeared while processing.")
        staging.rename(destination)
        return metadata
    except BaseException:
        for matrix in matrices.values():
            try:
                matrix._mmap.close()
            except Exception:
                pass
        shutil.rmtree(staging, ignore_errors=True)
        raise


# %% QPROCESS / COMMAND LINE ENTRY POINT

def main(arguments=None):
    parser = argparse.ArgumentParser(description="Create Veusz plots/reports from a closed FSP logger CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--render", action="store_true", help="Also create PDF/PNG when an installed Veusz renderer is available.")
    parser.add_argument("--max-matrix-mib", type=int, default=DEFAULT_MAX_MATRIX_MIB)
    options = parser.parse_args(arguments)
    try:
        if hasattr(os, "nice"):
            try:
                os.nice(5)
            except OSError:
                pass
        metadata = create_reports(options.csv, options.output_dir, options.render, options.max_matrix_mib)
        print(json.dumps(dict(status="completed", output_directory=str(Path(options.output_dir).resolve()),
                              pages=len(metadata["pages"]), rendering=metadata["rendering"])), flush=True)
        return 0
    except Exception as report_error:
        print("Report generation failed: " + str(report_error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
