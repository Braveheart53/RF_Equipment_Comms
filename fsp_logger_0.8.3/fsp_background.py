#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""FSP background output, version 0.1.2, modified 2026-10-23.
Author: William W. Wallace (application owner; generated integration update).
Python: 3.8–3.12. One ordered CSV consumer overlaps serialized instrument I/O.
Queue saturation retains the terminal capture, then sampling explicitly stops.
Only display frames coalesce; recorded captures do not.
"""
from __future__ import annotations
# %% IMPORTS
import csv
import os
import queue
import threading
import numpy as np
__version__ = "0.1.2"

# %% ORDERED BOUNDED OUTPUT
class CsvBacklogError(RuntimeError):
    """Sampling must stop and drain because storage is not keeping up."""


class AsyncCaptureCsvWriter:
    """One file owner; bounded queue plus one reserved terminal-capture slot.

    Nominal array budget excludes Python/container/file buffering overhead.
    Flush per capture is not a power-loss fsync guarantee. Call close() from
    the acquisition worker, not the GUI thread; it drains before returning.
    """
    def __init__(self, filename, frequency_axis, active_trace_numbers,
                 queue_capacity=32, maximum_queue_bytes=64 * 1024 * 1024):
        self.filename = os.path.abspath(filename)
        self.frequency_axis = np.array(frequency_axis, dtype=float, copy=True)
        self.active_trace_numbers = tuple(active_trace_numbers)
        if (self.frequency_axis.ndim != 1 or not self.frequency_axis.size or
                not np.all(np.isfinite(self.frequency_axis)) or
                not self.active_trace_numbers or
                len(set(self.active_trace_numbers)) != len(self.active_trace_numbers)):
            raise ValueError("Require finite 1-D frequencies and unique active channels.")
        capture_bytes = self.frequency_axis.nbytes * len(self.active_trace_numbers)
        if capture_bytes <= 0 or capture_bytes > maximum_queue_bytes or queue_capacity <= 0:
            raise ValueError("Empty capture or insufficient queue budget/capacity.")
        capacity = max(1, min(queue_capacity, maximum_queue_bytes // capture_bytes))
        self.capture_queue = queue.Queue(maxsize=capacity)
        self.closing_event = threading.Event()
        self.ready_event = threading.Event()
        self.failure = None
        self.terminal_capture = None
        self.written_capture_count = 0
        self.consumer_thread = threading.Thread(target=self._consume, name="fsp-csv-output", daemon=False)
        self.consumer_thread.start()
        self.ready_event.wait()
        self.raise_if_failed()

    def raise_if_failed(self):
        if self.failure is not None:
            raise RuntimeError("CSV output failed: %s" % self.failure) from self.failure

    def submit(self, capture_datetime, trace_arrays):
        self.raise_if_failed()
        if self.closing_event.is_set() or self.terminal_capture is not None:
            raise CsvBacklogError("CSV writer is closing or saturated.")
        payload = (capture_datetime, {number: np.array(trace_arrays[number], dtype=float, copy=True)
                                      for number in self.active_trace_numbers})
        if any(values.shape != self.frequency_axis.shape or not np.all(np.isfinite(values)) for values in payload[1].values()):
            raise ValueError("Trace length differs from frequency grid.")
        try:
            self.capture_queue.put_nowait(payload)
        except queue.Full:
            self.terminal_capture = payload
            raise CsvBacklogError("CSV queue saturated: sampling stopped; queued and final capture will drain.")

    def close(self):
        self.closing_event.set()
        self.consumer_thread.join()
        self.raise_if_failed()

    def _write_payload(self, csv_writer, stream, payload):
        instant, traces = payload
        date_text = instant.strftime("%Y-%m-%d")
        time_text = instant.strftime("%H:%M:%S.%f")[:-3]
        timestamp_text = instant.isoformat(timespec="milliseconds")
        csv_writer.writerows([date_text, time_text, timestamp_text, "%.6f" % frequency] +
                            ["%.4f" % traces[number][index] for number in self.active_trace_numbers]
                            for index, frequency in enumerate(self.frequency_axis))
        stream.flush()
        self.written_capture_count += 1

    def _consume(self):
        try:
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)
            with open(self.filename, "w", newline="", encoding="utf-8") as stream:
                writer = csv.writer(stream)
                writer.writerow(["date", "time", "timestamp_iso", "freq_hz"] +
                                ["trace%d_dBm" % number for number in self.active_trace_numbers])
                stream.flush()
                self.ready_event.set()
                while not self.closing_event.is_set() or not self.capture_queue.empty():
                    try:
                        payload = self.capture_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    try:
                        self._write_payload(writer, stream, payload)
                    finally:
                        self.capture_queue.task_done()
                if self.terminal_capture is not None:
                    self._write_payload(writer, stream, self.terminal_capture)
        except BaseException as error:
            self.failure = error
        finally:
            self.ready_event.set()


# %% DISPLAY MAILBOX
class LatestCaptureMailbox:
    """Bound GUI memory by retaining the most recent display frame only."""
    def __init__(self):
        self.lock = threading.Lock()
        self.latest_capture = None

    def publish(self, capture_index, frequency_axis, trace_arrays):
        with self.lock:
            self.latest_capture = (capture_index, frequency_axis, trace_arrays)

    def take(self):
        with self.lock:
            result = self.latest_capture
            self.latest_capture = None
        return result
