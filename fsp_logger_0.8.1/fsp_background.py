#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""FSP logger bounded background primitives, version 0.1.1, 2026-10-23.

Python 3.8 through 3.12. Standard-library-only except NumPy. The acquisition
thread submits immutable capture copies; one consumer exclusively owns CSV.
A full queue preserves one terminal capture and stops acquisition explicitly.
No scheduler can guarantee hard-real-time sampling on a general-purpose OS.
"""
from __future__ import annotations

# %% IMPORTS
import csv
import os
import queue
import threading
import numpy as np

__version__ = "0.1.1"

# %% BOUNDED ASYNCHRONOUS OUTPUT
class CsvBacklogError(RuntimeError):
    """The storage consumer cannot keep up; acquisition must stop explicitly."""


class AsyncCaptureCsvWriter:
    """Single ordered file owner with bounded queue and explicit failure.

    submit() never waits for disk output. If the normal queue is saturated,
    the just-acquired capture goes in a reserved terminal slot. Acquisition
    must then end; close() drains the queue and terminal slot in order.
    Disk errors are reported, not hidden. flush() is not a power-loss fsync.
    """

    def __init__(self, filename, frequency_axis, active_trace_numbers,
                 queue_capacity=32, maximum_queue_bytes=64 * 1024 * 1024):
        self.filename = os.path.abspath(filename)
        self.frequency_axis = np.array(frequency_axis, dtype=float, copy=True)
        self.active_trace_numbers = tuple(active_trace_numbers)
        capture_bytes = self.frequency_axis.nbytes * len(self.active_trace_numbers)
        if capture_bytes <= 0 or capture_bytes > maximum_queue_bytes:
            raise ValueError("Empty capture or capture exceeds CSV queue memory budget.")
        capacity = max(1, min(queue_capacity, maximum_queue_bytes // capture_bytes))
        self.capture_queue = queue.Queue(maxsize=capacity)
        self.closing_event = threading.Event()
        self.ready_event = threading.Event()
        self.failure = None
        self.terminal_capture = None
        self.written_capture_count = 0
        self.consumer_thread = threading.Thread(target=self._consume, name="fsp-csv-output", daemon=False)
        self.consumer_thread.start()
        # Output-open errors are caught before the first instrument trigger.
        self.ready_event.wait()
        self.raise_if_failed()

    def raise_if_failed(self):
        if self.failure is not None:
            raise RuntimeError("CSV output failed: %s" % self.failure) from self.failure

    def submit(self, capture_datetime, trace_arrays):
        self.raise_if_failed()
        if self.closing_event.is_set() or self.terminal_capture is not None:
            raise CsvBacklogError("CSV writer is closing or already saturated.")
        payload = (capture_datetime, {number: np.array(trace_arrays[number], dtype=float, copy=True)
                                      for number in self.active_trace_numbers})
        for trace_number, values in payload[1].items():
            if values.shape != self.frequency_axis.shape:
                raise ValueError("Trace %d length differs from frequency axis." % trace_number)
        try:
            self.capture_queue.put_nowait(payload)
        except queue.Full:
            self.terminal_capture = payload
            raise CsvBacklogError("CSV queue saturated; stopping sampling. Queued captures and this final capture will be drained.")

    def close(self):
        self.closing_event.set()
        self.consumer_thread.join()
        self.raise_if_failed()

    def _write_payload(self, csv_writer, output_stream, payload):
        capture_datetime, trace_arrays = payload
        date_text = capture_datetime.strftime("%Y-%m-%d")
        time_text = capture_datetime.strftime("%H:%M:%S.%f")[:-3]
        timestamp_text = capture_datetime.isoformat(timespec="milliseconds")
        # Generate one row at a time instead of allocating a whole list of
        # formatted strings. The analyzer owns no file handle or formatter.
        rows = ([date_text, time_text, timestamp_text, "%.6f" % frequency_hz] +
                ["%.4f" % trace_arrays[number][frequency_index] for number in self.active_trace_numbers]
                for frequency_index, frequency_hz in enumerate(self.frequency_axis))
        csv_writer.writerows(rows)
        output_stream.flush()
        self.written_capture_count += 1

    def _consume(self):
        try:
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)
            with open(self.filename, "w", newline="", encoding="utf-8") as output_stream:
                csv_writer = csv.writer(output_stream)
                csv_writer.writerow(["date", "time", "timestamp_iso", "freq_hz"] +
                                    ["trace%d_dBm" % number for number in self.active_trace_numbers])
                output_stream.flush()
                self.ready_event.set()
                while not self.closing_event.is_set() or not self.capture_queue.empty():
                    try:
                        payload = self.capture_queue.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    try:
                        self._write_payload(csv_writer, output_stream, payload)
                    finally:
                        self.capture_queue.task_done()
                if self.terminal_capture is not None:
                    self._write_payload(csv_writer, output_stream, self.terminal_capture)
        except BaseException as output_error:
            self.failure = output_error
        finally:
            self.ready_event.set()


# %% COALESCED GUI DISPLAY
class LatestCaptureMailbox:
    """Only display frames coalesce; every measurement still goes to CSV.

    A slow plot must not enqueue unlimited large NumPy arrays in Qt's event
    queue. The GUI polls the newest frame at a bounded update frequency.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.latest_capture = None

    def publish(self, capture_index, frequency_axis, trace_arrays):
        with self.lock:
            self.latest_capture = (capture_index, frequency_axis, trace_arrays)

    def take(self):
        with self.lock:
            latest_capture = self.latest_capture
            self.latest_capture = None
        return latest_capture
