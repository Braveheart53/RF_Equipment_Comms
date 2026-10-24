#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""FSP CSV reporting, version 0.1.3, modified 2026-10-23.
Author: William W. Wallace (application owner; generated integration update).
Python: 3.8–3.12. Native writer: 0.0.17; logger bundle: 0.8.3.

0.1.3: Freq_N_GHz and Combined_Freq_vs_Time pages; all raw frequency bins,
actual datetime axes and independent analyzer channels. All previous pages
remain. Means always use linear power before conversion to displayed dBm.
0.1.1: Strict validation, disk-backed matrices, parallel per-trace statistics,
staged output, provenance reports, optional PDF/PNG generation.
"""
from __future__ import annotations
# %% IMPORTS AND LIMITS
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
__version__ = "0.1.3"
TRACE_PATTERN = re.compile(r"trace([1-3])_dBm$")
DEFAULT_MAX_MATRIX_MIB = 512
CHUNK_CAPTURE_COUNT = 128

# %% STRICT CSV GROUPING
class ReportValidationError(ValueError):
    """Do not silently truncate malformed, changed or partial captures."""


def file_signature(path):
    details = path.stat()
    return (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)


def parse_timestamp(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iter_capture_blocks(source_path):
    """Contiguous timestamp groups define legacy captures without capture IDs."""
    with Path(source_path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames or []
        required = {"date", "time", "timestamp_iso", "freq_hz"}
        trace_columns = [(int(TRACE_PATTERN.fullmatch(name).group(1)), name)
                         for name in columns if TRACE_PATTERN.fullmatch(name)]
        if (len(columns) != len(set(columns)) or not trace_columns or
                set(columns) != required | {name for _, name in trace_columns}):
            raise ReportValidationError("Expected unique logger columns date,time,timestamp_iso,freq_hz,trace<n>_dBm.")
        timestamp = None
        frequencies = []
        values = {number: [] for number, _ in trace_columns}
        reference_axis = None
        previous_instant = None
        timestamps_are_aware = None
        validated_time_fields = None

        def validate_block(timestamp_text):
            nonlocal reference_axis, previous_instant, timestamps_are_aware
            axis = np.asarray(frequencies, dtype=float)
            if not axis.size or not np.all(np.diff(axis) > 0):
                raise ReportValidationError("Non-increasing grid or duplicate capture timestamp.")
            if reference_axis is None:
                reference_axis = axis.copy()
            elif axis.shape != reference_axis.shape or not np.array_equal(axis, reference_axis):
                raise ReportValidationError("Incomplete capture or changed frequency grid: " + timestamp_text)
            try:
                instant = parse_timestamp(timestamp_text)
            except ValueError as error:
                raise ReportValidationError("Invalid ISO timestamp: " + timestamp_text) from error
            aware = instant.utcoffset() is not None
            if timestamps_are_aware is None:
                timestamps_are_aware = aware
            if aware != timestamps_are_aware:
                raise ReportValidationError("Mixed aware/naive timestamps.")
            if previous_instant is not None and instant <= previous_instant:
                raise ReportValidationError("Capture timestamps must strictly increase.")
            previous_instant = instant
            return timestamp_text, axis, {number: np.asarray(data, dtype=float) for number, data in values.items()}

        for row_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ReportValidationError("Malformed CSV row %d." % row_number)
            next_timestamp = row["timestamp_iso"]
            if timestamp is not None and next_timestamp != timestamp:
                yield validate_block(timestamp)
                frequencies = []
                values = {number: [] for number, _ in trace_columns}
            timestamp = next_timestamp
            try:
                frequency_hz = float(row["freq_hz"])
                levels = {number: float(row[name]) for number, name in trace_columns}
            except ValueError as error:
                raise ReportValidationError("Non-numeric row %d." % row_number) from error
            if frequency_hz < 0 or not all(math.isfinite(value) for value in [frequency_hz] + list(levels.values())):
                raise ReportValidationError("Invalid/nonfinite value at row %d." % row_number)
            time_fields = (row["date"], row["time"], timestamp)
            if time_fields != validated_time_fields:
                try:
                    # CSV and ISO fields may use differing zero-fraction
                    # precision (.000 versus omitted). Compare values.
                    recorded_local = parse_timestamp(timestamp).replace(tzinfo=None)
                    separate_local = datetime.fromisoformat(row["date"] + "T" + row["time"])
                    consistent = separate_local == recorded_local
                except ValueError:
                    consistent = False
                if not consistent:
                    raise ReportValidationError("Inconsistent date/time at row %d." % row_number)
                validated_time_fields = time_fields
            frequencies.append(frequency_hz)
            for number, level in levels.items():
                values[number].append(level)
        if timestamp is None:
            raise ReportValidationError("CSV contains no capture data.")
        yield validate_block(timestamp)


# %% CHUNKED PARALLEL NUMERICAL REDUCTIONS

def trace_statistics(trace_number, power_matrix, frequency_hz):
    """Stable linear-power time mean per bin, NOT arithmetic mean of dBm.

    Scaling to each bin's maximum avoids overflow. Channels are never mixed:
    clear/write, max-hold and instrument average may be different quantities.
    Min/max are selections, not averages. Peak ties select the first sample.
    """
    capture_count, frequency_count = power_matrix.shape
    minimum_dbm = np.full(frequency_count, np.inf)
    maximum_dbm = np.full(frequency_count, -np.inf)
    peak_dbm = np.empty(capture_count)
    peak_frequency_hz = np.empty(capture_count)
    for first in range(0, capture_count, CHUNK_CAPTURE_COUNT):
        block = np.asarray(power_matrix[first:first + CHUNK_CAPTURE_COUNT])
        minimum_dbm = np.minimum(minimum_dbm, np.min(block, axis=0))
        maximum_dbm = np.maximum(maximum_dbm, np.max(block, axis=0))
        indices = np.argmax(block, axis=1)
        peak_dbm[first:first + len(block)] = block[np.arange(len(block)), indices]
        peak_frequency_hz[first:first + len(block)] = frequency_hz[indices]
    # One shared implementation owns every software-computed power mean.
    # Its chunks convert dBm to relative linear power, average there, then
    # convert to dBm. Analyzer channels remain independent.
    mean_dbm = native_writer.linear_power_mean_dbm(
        power_matrix, axis=0, chunk_size=CHUNK_CAPTURE_COUNT)
    peak_capture = int(np.argmax(peak_dbm))
    return dict(trace_number=trace_number, minimum_dbm=minimum_dbm, maximum_dbm=maximum_dbm,
                linear_mean_dbm=mean_dbm, peak_dbm=peak_dbm, peak_frequency_hz=peak_frequency_hz,
                peak_capture_index=peak_capture, global_peak_dbm=float(peak_dbm[peak_capture]),
                global_peak_frequency_hz=float(peak_frequency_hz[peak_capture]))


# %% HOST-TIMEZONE-INDEPENDENT DATETIME VALUES

def veusz_capture_datetimes(timestamps):
    """Naive CSV stays wall-clock; explicitly aware CSV is normalized to UTC.

    Veusz uses seconds since 2009-01-01. Never call timestamp() on naive
    values: that would incorrectly introduce the reporting host's timezone.
    """
    instants = [parse_timestamp(text) for text in timestamps]
    aware = instants[0].utcoffset() is not None
    if aware:
        normalized = [instant.astimezone(timezone.utc).replace(tzinfo=None) for instant in instants]
        label, semantics = "Time (UTC)", "Timezone-aware CSV normalized to UTC."
    else:
        normalized = instants
        label, semantics = "Time (recorded local wall clock)", "Naive CSV wall time preserved; reporting-host timezone not applied."
    epoch = datetime(2009, 1, 1)
    return np.asarray([(instant - epoch).total_seconds() for instant in normalized]), label, semantics


# %% NATIVE DOCUMENT: RETAIN OLD PAGES, APPEND FREQUENCY-TIME PAGES

def write_native_document(destination, metadata, frequency_hz, elapsed_s, matrices, statistics):
    document = native_writer.VszDoc("R&S FSP logger 0.8.3 / fsp_reports " + __version__)
    summary_lines = ["Source: " + Path(metadata["source_csv"]).name,
                     "Captures: %d; bins: %d; traces: %s" % (metadata["captures"], len(frequency_hz), metadata["traces"]),
                     "First: " + metadata["first_timestamp"], "Last: " + metadata["last_timestamp"],
                     "Means use linear power before dBm display.", "All raw captures/frequencies retained; no decimation.",
                     "Waterfall y = capture index, not uniform time.", "Frequency-time plots keep analyzer channels separate.",
                     "RBW/detector/calibration unknown; no compliance claim."]
    pages = native_writer.text_page(document, "measurement_report", "R&S FSP measurement report", summary_lines)
    date_seconds, time_label, _ = veusz_capture_datetimes(metadata["timestamps"])
    channel_frequency_datasets = {}
    with native_writer.VeuszWriter(destination, compress=True, writer_tag="fsp_reports " + __version__) as writer:
        writer.dataset_1d("frequency_hz", frequency_hz, tags=("axis", "raw"))
        writer.dataset_1d("elapsed_s", elapsed_s, tags=("axis", "raw"))
        writer.dataset_date("capture_datetime", date_seconds, tags=("axis", "raw", "datetime"))
        writer.dataset_text("timestamp_iso", metadata["timestamps"], tags=("raw", "metadata"))
        writer.dataset_text("acquisition_metadata_json", [json.dumps(metadata, sort_keys=True)], tags=("metadata",))
        last_capture_traces = []
        for result in statistics:
            number = result["trace_number"]
            prefix = "trace%d_" % number
            matrix = matrices[number]
            writer.dataset_2d(prefix + "raw_dbm", matrix, xcent=frequency_hz,
                              ycent=np.arange(len(elapsed_s), dtype=float), tags=("raw", "trace%d" % number))
            values_to_write = {name: result[name] for name in
                               ("minimum_dbm", "maximum_dbm", "linear_mean_dbm", "peak_dbm", "peak_frequency_hz")}
            values_to_write.update(first_dbm=matrix[0], last_dbm=matrix[-1])
            for name, values in values_to_write.items():
                writer.dataset_1d(prefix + name, values,
                                  tags=("trace%d" % number, "linear_power_mean" if name == "linear_mean_dbm" else "statistic"))
            last_capture_traces.append(native_writer.Trace("frequency_hz", prefix + "last_dbm", "Trace %d" % number))
            spectrum_name = "trace%d_spectral_envelope" % number
            native_writer.xy_page(document, spectrum_name, [
                native_writer.Trace("frequency_hz", prefix + "minimum_dbm", "Minimum"),
                native_writer.Trace("frequency_hz", prefix + "linear_mean_dbm", "Linear-power mean"),
                native_writer.Trace("frequency_hz", prefix + "maximum_dbm", "Maximum")],
                title="Trace %d: spectral envelope" % number, xlabel="Frequency (Hz)", ylabel="Level (dBm)")
            waterfall_name = "trace%d_waterfall" % number
            native_writer.image_page(document, waterfall_name, prefix + "raw_dbm", title="Trace %d: all captures" % number,
                                     xlabel="Frequency (Hz)", ylabel="Capture index (zero-based)", zlabel="Level (dBm)")
            trend_name = "trace%d_peak_history" % number
            native_writer.grid_page(document, trend_name, [
                native_writer.Panel([native_writer.Trace("elapsed_s", prefix + "peak_dbm")], title="Peak level",
                                    xlabel="Elapsed time (s)", ylabel="Level (dBm)"),
                native_writer.Panel([native_writer.Trace("elapsed_s", prefix + "peak_frequency_hz")], title="Peak frequency",
                                    xlabel="Elapsed time (s)", ylabel="Frequency (Hz)")], columns=1,
                title="Trace %d: peak history" % number)
            pages.extend([spectrum_name, waterfall_name, trend_name])
            frequency_dataset_names = []
            # Write each column once; both new plot types reference this
            # same series. Values are raw capture levels, not an average.
            for frequency_index, frequency in enumerate(frequency_hz):
                ghz_text = native_writer.frequency_ghz_text(frequency)
                name = prefix + "Freq_" + ghz_text + "_GHz_dbm"
                writer.dataset_1d(name, matrix[:, frequency_index],
                                  tags=("raw", "frequency_time", "trace%d" % number, ghz_text + " GHz"))
                frequency_dataset_names.append(name)
            channel_frequency_datasets["Trace %d" % number] = frequency_dataset_names
        native_writer.xy_page(document, "last_capture", last_capture_traces, title="Last complete capture",
                              xlabel="Frequency (Hz)", ylabel="Level (dBm)")
        pages.append("last_capture")
        pages.extend(native_writer.frequency_time_pages(document, frequency_hz, "capture_datetime",
                     channel_frequency_datasets, xlabel=time_label, xmode="datetime"))
        writer.finish(document.text())
    return pages


# %% STATISTICAL TABLES

def write_statistics_tables(directory, frequency_hz, elapsed_s, timestamps, statistics):
    with (directory / "spectral_statistics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        fields = ("minimum_dbm", "linear_mean_dbm", "maximum_dbm")
        writer.writerow(["freq_hz"] + ["trace%d_%s" % (result["trace_number"], name) for result in statistics for name in fields])
        for index, frequency in enumerate(frequency_hz):
            writer.writerow([frequency] + [result[name][index] for result in statistics for name in fields])
    with (directory / "capture_statistics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        fields = ("peak_dbm", "peak_frequency_hz")
        writer.writerow(["timestamp_iso", "elapsed_s"] + ["trace%d_%s" % (result["trace_number"], name) for result in statistics for name in fields])
        for index, timestamp in enumerate(timestamps):
            writer.writerow([timestamp, elapsed_s[index]] + [result[name][index] for result in statistics for name in fields])


# %% TWO-PASS IMPORT, RESOURCE BUDGET AND STAGED PUBLICATION

def create_reports(csv_path, output_directory, render=False, max_matrix_mib=DEFAULT_MAX_MATRIX_MIB):
    """Create a NEW directory; source stays untouched. CLI requires closed CSV.

    Signature checks detect ordinary input changes, not hostile edits or a
    cross-process file lock. Matrix budget is not a total-memory limit.
    Numerical per-channel tasks parallelize; HDF5 writing stays single-owner.
    """
    source = Path(csv_path).expanduser().resolve()
    destination = Path(output_directory).expanduser().resolve()
    if destination.exists():
        raise FileExistsError("Report directory exists: choose a new name.")
    if max_matrix_mib <= 0:
        raise ValueError("max_matrix_mib must be positive.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    signature = file_signature(source)
    timestamps = []
    for timestamp, axis, values in iter_capture_blocks(source):
        timestamps.append(timestamp)
        if len(timestamps) == 1:
            frequency_hz, trace_numbers = axis.copy(), sorted(values)
        matrix_bytes = len(timestamps) * len(frequency_hz) * len(trace_numbers) * 8
        if matrix_bytes > max_matrix_mib * 1024 ** 2:
            raise ReportValidationError("Raw matrices exceed --max-matrix-mib.")
    if file_signature(source) != signature:
        raise ReportValidationError("CSV changed during validation.")
    # Scratch plus raw 2-D and frequency-column representations need disk;
    # rendered page sizes cannot be predicted by this conservative preflight.
    if shutil.disk_usage(destination.parent).free < 5 * matrix_bytes + 32 * 1024 ** 2:
        raise OSError("Insufficient disk space for scratch/native output.")
    staging = Path(tempfile.mkdtemp(prefix="." + destination.name + ".", dir=str(destination.parent)))
    scratch = staging / "scratch"
    scratch.mkdir()
    matrices = {}
    try:
        for number in trace_numbers:
            matrices[number] = np.memmap(str(scratch / ("trace%d.bin" % number)), mode="w+", dtype="float64",
                                        shape=(len(timestamps), len(frequency_hz)))
        imported_count = 0
        for index, (timestamp, axis, values) in enumerate(iter_capture_blocks(source)):
            if index >= len(timestamps) or timestamp != timestamps[index] or not np.array_equal(axis, frequency_hz):
                raise ReportValidationError("CSV changed between import passes.")
            for number in trace_numbers:
                matrices[number][index] = values[number]
            imported_count += 1
        if imported_count != len(timestamps) or file_signature(source) != signature:
            raise ReportValidationError("CSV changed during import.")
        first_instant = parse_timestamp(timestamps[0])
        elapsed_s = np.asarray([(parse_timestamp(text) - first_instant).total_seconds() for text in timestamps])
        with ThreadPoolExecutor(max_workers=min(3, len(trace_numbers))) as executor:
            futures = [executor.submit(trace_statistics, number, matrices[number], frequency_hz) for number in trace_numbers]
            statistics = [future.result() for future in futures]
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if file_signature(source) != signature:
            raise ReportValidationError("CSV changed during provenance hashing.")
        _, time_label, time_semantics = veusz_capture_datetimes(timestamps)
        metadata = dict(logger_version="0.8.3", report_engine_version=__version__, writer_version=native_writer.__version__,
                        generated_utc=datetime.now(timezone.utc).isoformat(), source_csv=str(source), source_sha256=digest.hexdigest(),
                        captures=len(timestamps), frequency_points=len(frequency_hz), traces=trace_numbers, timestamps=timestamps,
                        first_timestamp=timestamps[0], last_timestamp=timestamps[-1], duration_s=float(elapsed_s[-1]),
                        spectral_mean="10*log10(mean(10**(dBm/10))) per frequency bin",
                        frequency_time_axis=time_semantics, frequency_time_xlabel=time_label,
                        frequency_time_pages=["Freq_" + native_writer.frequency_ghz_text(value) + "_GHz" for value in frequency_hz],
                        combined_frequency_time_page="Combined_Freq_vs_Time",
                        combined_frequency_time_layout="One panel per independent analyzer trace; one raw curve per frequency, key N GHz.",
                        limitations=["Legacy CSV lacks RBW/VBW/detector/impedance/calibration metadata.",
                                     "No EMC compliance claim or integrated channel-power assertion.",
                                     "Single-bin/capture image extents use +/-0.5 display units.",
                                     "Legacy CSV cannot independently prove first/sole capture completeness.",
                                     "All bins included: large sweeps generate many pages and crowded combined legends."],
                        trace_statistics=[{name: result[name] for name in ("trace_number", "global_peak_dbm", "global_peak_frequency_hz", "peak_capture_index")}
                                          for result in statistics])
        metadata["pages"] = write_native_document(staging / "fsp_report.vszh5", metadata, frequency_hz, elapsed_s, matrices, statistics)
        write_statistics_tables(staging, frequency_hz, elapsed_s, timestamps, statistics)
        metadata["rendering"] = dict(requested=bool(render), status="not_requested")
        if render:
            try:
                paths = native_writer.render_pages(staging / "fsp_report.vszh5", outdir=staging / "rendered", png_pages="all", pdf=True,
                    timeout=max(180.0, min(1800.0, 5.0 * len(metadata["pages"]))))
                metadata["rendering"] = dict(requested=True, status="completed", files=[str(path.relative_to(staging)) for path in paths])
            except Exception as error:
                metadata["rendering"] = dict(requested=True, status="unavailable_or_failed", error=str(error))
        (staging / "report.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        lines = ["# R&S FSP measurement report", "", "## Acquisition", "", "| Item | Value |", "|---|---|"]
        for key in ("source_csv", "source_sha256", "captures", "frequency_points", "traces", "first_timestamp", "last_timestamp", "duration_s"):
            lines.append("| %s | %s |" % (key, str(metadata[key]).replace("|", "\\|")))
        lines += ["", "## Trace extrema", "", "| Trace | Peak (dBm) | Frequency (Hz) | Capture |", "|---|---:|---:|---:|"]
        for result in metadata["trace_statistics"]:
            lines.append("| {trace_number} | {global_peak_dbm:.4f} | {global_peak_frequency_hz:.6f} | {peak_capture_index} |".format(**result))
        lines += ["", "## Frequency-time plots", "", "One Freq_N_GHz page per frequency, showing independent analyzer traces.",
                  "Combined_Freq_vs_Time has one panel per analyzer trace and N GHz keys.", time_semantics,
                  "Raw values: no averaging, interpolation or decimation in frequency-time plots.",
                  "All prior report/envelope/waterfall/peak-history/last-capture pages retained.",
                  "", "## Interpretation", "", "All means are linear-power averages converted back to dBm; no cross-channel mean.",
                  "Waterfall row = capture index; capture_datetime and elapsed_s retain irregular timing.", ""]
        lines += metadata["limitations"] + ["", "## Rendering", "", "```json", json.dumps(metadata["rendering"], indent=2), "```", ""]
        (staging / "report.md").write_text("\n".join(lines), encoding="utf-8")
        for matrix in matrices.values():
            matrix.flush()
            matrix._mmap.close()
        matrices.clear()
        shutil.rmtree(scratch)
        if destination.exists():
            raise FileExistsError("Destination appeared during processing.")
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


# %% COMMAND-LINE / QPROCESS ENTRY POINT

def main(arguments=None):
    parser = argparse.ArgumentParser(description="All native Veusz plots/reports from a completed FSP CSV.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--max-matrix-mib", type=int, default=DEFAULT_MAX_MATRIX_MIB)
    options = parser.parse_args(arguments)
    try:
        if hasattr(os, "nice"):
            try:
                os.nice(5)
            except OSError:
                pass
        result = create_reports(options.csv, options.output_dir, options.render, options.max_matrix_mib)
        print(json.dumps(dict(status="completed", output_directory=str(Path(options.output_dir).resolve()),
                              pages=len(result["pages"]), rendering=result["rendering"])), flush=True)
        return 0
    except Exception as error:
        print("Report generation failed: " + str(error), file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
