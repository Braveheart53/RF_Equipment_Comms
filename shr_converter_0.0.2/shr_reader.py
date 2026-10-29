#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Signal Hound Spike .shr sweep recordings: a dependency-free NumPy reader.

===============================================================================
 Title          : SHR Reader - Spike sweep-recording (.shr) file reader
 Filename       : shr_reader.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-28
 Modified       : 2026-10-28
 Language       : Python 3.12 (3.10 or later)
 Requires       : numpy (nothing else; no third-party SHR package)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Companion      : shr_converter_core.py 0.0.2 (SHR Converter)
 Status         : Internal draft. Checked bit-exact against py-shr-parser
                  1.0.0 on Spike's sweep0v2.shr, and on an SM200C recording
                  from Spike 4.0.x that py-shr-parser cannot open (detector
                  code 2). Not yet run on Windows.
===============================================================================

WHY THIS MODULE EXISTS
----------------------
py-shr-parser 1.0.0 [R3] converts every enumerated header field into a strict
Python IntEnum. Spike 3.5.7 (2020-07-22) added Max and Min sweep detectors
[R2], and recordings made with them carry detector codes the enumeration
does not know (code 2 in an SM200C recording, 2026-10-28), so the parser
raises ValueError before reading a single sweep. Signal Hound's own SDK
example [R1] reads the same field as a plain int32. This reader follows the
SDK: every field is kept as its raw integer, names are looked up from tables
that say how certain each name is, and an unknown value becomes a note,
never an exception.

FILE LAYOUT (version 2, little endian, packed) [R1]
--------------------------------------------------
    offset 0                 SHRFileHeader, 472 bytes (layout in HEADER_LAYOUT)
    offset dataOffset        sweep 0: SHRSweepHeader (48 bytes) + sweepLength float32
    dataOffset + n*(48+4N)   sweep n
The 48-byte sweep header is: uint64 time stamp (ms since the Unix epoch),
float64 latitude, float64 longitude, float64 altitude (m), uint8 ADC overflow
(file version >= 2; a reserved byte in version 1) and 15 reserved bytes.
Bin k of every sweep is at  f_k = firstBinFreqHz + k * binSizeHz  (not at
centre +- span/2: on the SM200C sample the first bin lies 1.9 bins above
centre - span/2).

WHAT THE READER DOES
--------------------
  * ShrHeader       - every header field (snake_case names, raw values),
                      UTF-16LE title, enumeration labels with confidence,
                      frequency axis, amplitude unit, validation.
  * ShrFile         - one .shr file: validation and salvage (header count 0,
                      cut-short recordings, trailing bytes, dataOffset > 472),
                      memory-mapped block reads with sweep step and column
                      range (no Python loop per sweep), sweep headers only,
                      amplitude-grid check, picklable for spawn workers,
                      explicit close() that releases the file on Windows.
  * ShrFileSet      - several files of one recording (Spike splits a long
                      recording at the maximum file size, since 3.9.7 [R2])
                      read as one: continuous sweep numbering, gaps between
                      files reported, incompatible files refused.
  * group_recordings- groups a list of files into recordings by their
                      contents (compatible headers, adjacent times), because
                      Spike's multi-file naming is not documented.
  * write_shr       - writes a .shr file (synthetic tests, examples).
  * self_test()     - 39 checks on synthetic files; run with --selftest.

ENUMERATION CONFIDENCE
----------------------
"documented"  - in the SDK's shr_parse.h [R1].
"inferred"    - detector 2 = Max: not documented; inferred from an SM200C
                recording whose values lie on the 0.01 dB grid of the SM
                min/max processing path [R4] and whose noise statistics match
                a max hold of about 512 FFTs (design brief 0.0.1, section 4).
"unverified"  - detector 3 = Min: assumed by elimination, never seen.
"unknown"     - any other value: kept, labelled "unknown (code n)".

PERFORMANCE AND MEMORY
----------------------
Sweeps are read through numpy.memmap with a structured dtype, so a block of
sweeps (with a step and a column range) is one vectorised copy and only the
pages it touches are read. Nothing is cached: memory use is the block the
caller asks for. Spawn worker processes receive a ShrFile or ShrFileSet by
pickling, which carries only the path(s) and sweep counts; each worker maps
the file itself. Every array handed out is a copy, so close() can release the
mapping at once (needed on Windows, where a mapped file cannot be renamed or
deleted).

USAGE
-----
    from shr_reader import ShrFile
    with ShrFile("capture.shr") as shr:
        print(shr.header.label("detector"), shr.n_sweeps, shr.n_bins)
        block = shr.read(0, 100, col0=1000, col1=2000)   # SweepBlock
        print(block.amplitudes.shape, block.timestamp_ms[:3])

    python shr_reader.py capture.shr [more.shr ...] [--join] [--json]
    python shr_reader.py --selftest

REFERENCES
----------
 [R1] Signal Hound, SHR parsing example shr_parse.h / shr_parse.cpp, in the
      Signal Hound SDK (release of 2026-10-05).
      https://signalhound.com/software/signal-hound-software-development-kit-sdk/
 [R2] Signal Hound, Spike change log, version 4.0.17 (2026-09-21).
      https://signalhound.com/sigdownloads/Spike/change_log.txt
 [R3] T. Schmitz, py-shr-parser 1.0.0, WiSE Lab, Carnegie Mellon Univ., 2025.
      https://github.com/WiseLabCMU/py-shr-parser
 [R4] Signal Hound, SM200A/B/C - SM435B/C Product Manual, 2025-01-27.
      https://signalhound.com/sigdownloads/SM200A/SM-User-Manual.pdf
 [R5] Signal Hound, Spike software documentation (Sweep Record and Playback).
      https://signalhound.com/sigdownloads/Spike/docs/html/index.html

REVISION HISTORY (newest first)
-------------------------------
 0.0.1  2026-10-28  First internal draft: header, tolerant enumerations,
                    validation and salvage, memmap block reads, file sets,
                    recording grouping, writer, amplitude-grid check, CLI,
                    self-test.
"""

# %% IMPORTS
from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

__version__ = "0.0.1"
__author__ = "William W. Wallace"

__all__ = [
    "SHR_SIGNATURE", "SHR_MAX_KNOWN_VERSION", "FILE_HEADER_SIZE", "SWEEP_HEADER_SIZE",
    "HEADER_LAYOUT", "ENUM_FIELDS", "ShrFormatError", "ShrHeader", "SweepBlock", "ShrFile",
    "ShrFileSet", "open_recording", "group_recordings", "sweep_record_dtype", "enum_label",
    "write_shr", "detect_amplitude_grid", "self_test",
]


# %% ===========================================================================
#    FILE FORMAT CONSTANTS
# =============================================================================
SHR_SIGNATURE = 0xAA10              # first two bytes of every .shr file [R1]
SHR_MAX_KNOWN_VERSION = 2           # 1 = initial, 2 = ADC overflow byte added [R1]
FILE_HEADER_SIZE = 472              # sizeof(SHRFileHeader), packed
SWEEP_HEADER_SIZE = 48              # sizeof(SHRSweepHeader), packed
AMPLITUDE_BYTES = 4                 # float32 per bin
TITLE_CHARACTERS = 128              # uint16 title[128]: 127 characters + NUL

# (python attribute, struct code, SDK field name), in file order [R1].
# "4s"-style codes are byte strings; 'I' / 'i' are 4-byte unsigned / signed.
HEADER_LAYOUT: tuple[tuple[str, str, str], ...] = (
    ("signature", "H", "signature"),
    ("version", "H", "version"),
    ("reserved1", "I", "reserved1"),
    ("data_offset", "Q", "dataOffset"),
    ("sweep_count", "I", "sweepCount"),
    ("sweep_length", "I", "sweepLength"),
    ("first_bin_freq_hz", "d", "firstBinFreqHz"),
    ("bin_size_hz", "d", "binSizeHz"),
    ("title_raw", "256s", "title"),
    ("center_freq_hz", "d", "centerFreqHz"),
    ("span_hz", "d", "spanHz"),
    ("rbw_hz", "d", "rbwHz"),
    ("vbw_hz", "d", "vbwHz"),
    ("ref_level", "f", "refLevel"),
    ("ref_scale", "I", "refScale"),
    ("div", "f", "div"),
    ("window", "I", "window"),
    ("attenuation", "i", "attenuation"),
    ("gain", "i", "gain"),
    ("detector", "i", "detector"),
    ("processing_units", "i", "processingUnits"),
    ("window_bandwidth", "d", "windowBandwidth"),
    ("decimation_type", "i", "decimationType"),
    ("decimation_detector", "i", "decimationDetector"),
    ("decimation_count", "i", "decimationCount"),
    ("decimation_time_ms", "i", "decimationTimeMs"),
    ("channelize_enabled", "i", "channelizeEnabled"),
    ("channel_output_units", "i", "channelOutputUnits"),
    ("channel_center_hz", "d", "channelCenterHz"),
    ("channel_width_hz", "d", "channelWidthHz"),
    ("reserved2", "64s", "reserved2"),
)
HEADER_STRUCT = struct.Struct("<" + "".join(code for _, code, _ in HEADER_LAYOUT))
assert HEADER_STRUCT.size == FILE_HEADER_SIZE, "header layout must be 472 bytes"

# Byte offset of every header field (documentation, tests, hex inspection).
HEADER_OFFSETS: dict[str, int] = {}
_offset = 0
for _name, _code, _sdk in HEADER_LAYOUT:
    HEADER_OFFSETS[_name] = _offset
    _offset += struct.calcsize("<" + _code)
del _offset, _name, _code, _sdk


def sweep_record_dtype(n_bins: int) -> np.dtype:
    """NumPy dtype of one stored sweep: 48-byte SHRSweepHeader + n_bins float32.

    Field names are the ones every array in this module uses; the layout
    (offsets 0, 8, 16, 24, 32, 33, 48) is the packed SDK struct [R1].
    """
    return np.dtype([
        ("timestamp_ms", "<u8"),          # ms since 1970-01-01T00:00:00Z
        ("latitude", "<f8"),              # degrees, 0 without GPS
        ("longitude", "<f8"),
        ("altitude_m", "<f8"),            # metres
        ("adc_overflow", "u1"),           # file version >= 2: IF overload flag
        ("reserved", "u1", (15,)),
        ("amplitude", "<f4", (int(n_bins),)),
    ])


# Header-only part of a record (used when only time stamps / GPS are read).
SWEEP_HEADER_FIELDS = ("timestamp_ms", "latitude", "longitude", "altitude_m", "adc_overflow")


# %% ===========================================================================
#    ENUMERATIONS (raw codes kept; names with a confidence level)
# =============================================================================
# field -> {code: (name, confidence)}; confidence as explained in the header.
ENUM_FIELDS: dict[str, dict[int, tuple[str, str]]] = {
    "ref_scale": {0: ("dBm", "documented"), 1: ("mV", "documented")},
    "window": {0: ("Nuttall", "documented"), 1: ("Flattop", "documented"), 2: ("Gaussian", "documented")},
    "detector": {0: ("MinMax", "documented"), 1: ("Average", "documented"),
                 2: ("Max", "inferred"), 3: ("Min", "unverified")},
    "processing_units": {0: ("Log", "documented"), 1: ("Voltage", "documented"),
                         2: ("Power", "documented"), 3: ("Sample", "documented")},
    "decimation_type": {0: ("Time", "documented"), 1: ("Count", "documented")},
    "decimation_detector": {0: ("Average", "documented"), 1: ("Max", "documented")},
    "channel_output_units": {0: ("dBm", "documented"), 1: ("dBm/Hz", "documented")},
}


def enum_label(field_name: str, code: int) -> str:
    """Readable label of an enumerated header value, with its confidence.

    "Average" (documented), "Max (code 2, inferred)", "unknown (code 7)".
    """
    entry = ENUM_FIELDS.get(field_name, {}).get(int(code))
    if entry is None:
        return f"unknown (code {int(code)})"
    name, confidence = entry
    return name if confidence == "documented" else f"{name} (code {int(code)}, {confidence})"


def enum_confidence(field_name: str, code: int) -> str:
    """'documented', 'inferred', 'unverified' or 'unknown' for one value."""
    entry = ENUM_FIELDS.get(field_name, {}).get(int(code))
    return "unknown" if entry is None else entry[1]


class ShrFormatError(ValueError):
    """The file is not a readable .shr recording (bad signature, impossible sizes)."""


# %% ===========================================================================
#    FILE HEADER
# =============================================================================
@dataclass
class ShrHeader:
    """The 472-byte SHRFileHeader, field by field (raw values, SDK order).

    Names are snake_case versions of the SDK names (dataOffset -> data_offset)
    and match py-shr-parser where both exist, so code written against either
    reads the same. title_raw keeps the 256 bytes; .title decodes them.
    """

    signature: int = SHR_SIGNATURE
    version: int = SHR_MAX_KNOWN_VERSION
    reserved1: int = 0
    data_offset: int = FILE_HEADER_SIZE
    sweep_count: int = 0
    sweep_length: int = 0
    first_bin_freq_hz: float = 0.0
    bin_size_hz: float = 0.0
    title_raw: bytes = b"\x00" * (2 * TITLE_CHARACTERS)
    center_freq_hz: float = 0.0
    span_hz: float = 0.0
    rbw_hz: float = 0.0
    vbw_hz: float = 0.0
    ref_level: float = 0.0
    ref_scale: int = 0
    div: float = 10.0
    window: int = 0
    attenuation: int = 0
    gain: int = 0
    detector: int = 1
    processing_units: int = 0
    window_bandwidth: float = 0.0
    decimation_type: int = 1
    decimation_detector: int = 0
    decimation_count: int = 1
    decimation_time_ms: int = 0
    channelize_enabled: int = 0
    channel_output_units: int = 0
    channel_center_hz: float = 0.0
    channel_width_hz: float = 0.0
    reserved2: bytes = b"\x00" * 64

    # -- conversion -------------------------------------------------------------------
    @classmethod
    def from_bytes(cls, raw: bytes) -> "ShrHeader":
        """Decode the first 472 bytes of a file (raises ShrFormatError if short)."""
        if len(raw) < FILE_HEADER_SIZE:
            raise ShrFormatError(f"file header is {len(raw)} bytes; {FILE_HEADER_SIZE} expected")
        values = HEADER_STRUCT.unpack(raw[:FILE_HEADER_SIZE])
        return cls(**{name: value for (name, _, _), value in zip(HEADER_LAYOUT, values)})

    def to_bytes(self) -> bytes:
        """Encode back to the 472-byte on-disk form (used by write_shr)."""
        values = []
        for name, code, _ in HEADER_LAYOUT:
            value = getattr(self, name)
            if code.endswith("s"):
                size = int(code[:-1])
                value = bytes(value)[:size].ljust(size, b"\x00")
            values.append(value)
        return HEADER_STRUCT.pack(*values)

    @staticmethod
    def encode_title(text: str) -> bytes:
        """UTF-16LE title field: at most 127 characters + NUL (256 bytes)."""
        data = text.encode("utf-16-le")[: 2 * (TITLE_CHARACTERS - 1)]
        return data.ljust(2 * TITLE_CHARACTERS, b"\x00")

    # -- derived values ---------------------------------------------------------------
    @property
    def title(self) -> str:
        """Title as text (UTF-16LE up to the first NUL character) [R1]."""
        codes = np.frombuffer(bytes(self.title_raw), dtype="<u2")
        end = np.flatnonzero(codes == 0)
        codes = codes[: end[0]] if end.size else codes
        return codes.tobytes().decode("utf-16-le", errors="replace")

    @property
    def amplitude_unit(self) -> str:
        """'dBm' or 'mV' (refScale); unknown codes are reported as such."""
        return {0: "dBm", 1: "mV"}.get(int(self.ref_scale), f"unknown (refScale {int(self.ref_scale)})")

    @property
    def is_db(self) -> bool:
        """True unless the amplitudes are linear millivolts (refScale 1)."""
        return int(self.ref_scale) != 1

    @property
    def sweep_record_size(self) -> int:
        """Bytes per stored sweep: 48-byte sweep header + 4 bytes per bin."""
        return SWEEP_HEADER_SIZE + AMPLITUDE_BYTES * int(self.sweep_length)

    @property
    def has_adc_overflow(self) -> bool:
        """Whether the sweep header's byte 32 is an ADC-overflow flag (version >= 2)."""
        return int(self.version) >= 2

    def frequencies_hz(self, col0: int = 0, col1: int | None = None) -> np.ndarray:
        """Frequency of bins col0..col1-1 in Hz: firstBinFreqHz + k * binSizeHz."""
        col1 = int(self.sweep_length) if col1 is None else int(col1)
        return float(self.first_bin_freq_hz) + np.arange(int(col0), col1, dtype=np.float64) * float(self.bin_size_hz)

    def label(self, field_name: str) -> str:
        """Readable value of an enumerated field (see enum_label)."""
        return enum_label(field_name, getattr(self, field_name))

    def enum_notes(self) -> list[str]:
        """One note per enumerated value that is not documented in the SDK."""
        notes = []
        for name in ENUM_FIELDS:
            code = int(getattr(self, name))
            confidence = enum_confidence(name, code)
            if confidence == "unknown":
                notes.append(f"{name} = {code} is not a known value; kept as a number")
            elif confidence != "documented":
                notes.append(f"{name} = {code} read as {self.label(name)}; not in Signal Hound's SDK")
        return notes

    def as_dict(self, labels: bool = True) -> dict[str, Any]:
        """All fields as plain Python values (enumerations as labels if asked)."""
        out: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name == "title_raw":
                out["title"] = self.title
                continue
            if item.name == "reserved2":
                out["reserved2_nonzero_bytes"] = sum(1 for b in bytes(value) if b)
                continue
            if labels and item.name in ENUM_FIELDS:
                value = self.label(item.name)
            out[item.name] = value
        return out

    def validation_errors(self) -> list[str]:
        """Problems that make the file unreadable (empty list = readable)."""
        errors = []
        if int(self.signature) != SHR_SIGNATURE:
            errors.append(f"signature 0x{int(self.signature):04X} is not 0x{SHR_SIGNATURE:04X} (not an .shr file)")
        if int(self.sweep_length) <= 0:
            errors.append(f"sweepLength {int(self.sweep_length)} must be positive")
        if not (math.isfinite(float(self.bin_size_hz)) and float(self.bin_size_hz) > 0):
            errors.append(f"binSizeHz {self.bin_size_hz!r} must be a positive number")
        if not math.isfinite(float(self.first_bin_freq_hz)):
            errors.append(f"firstBinFreqHz {self.first_bin_freq_hz!r} is not a number")
        if int(self.data_offset) < FILE_HEADER_SIZE:
            errors.append(f"dataOffset {int(self.data_offset)} lies inside the {FILE_HEADER_SIZE}-byte header")
        return errors

    def consistency_notes(self) -> list[str]:
        """Readable-but-odd values worth telling the user about."""
        notes = []
        if int(self.version) > SHR_MAX_KNOWN_VERSION:
            notes.append(f"file version {int(self.version)} is newer than the {SHR_MAX_KNOWN_VERSION} this reader "
                         f"knows; read with the version-{SHR_MAX_KNOWN_VERSION} layout")
        if int(self.version) < 2:
            notes.append("file version 1: the ADC overflow flag does not exist (reported as 0)")
        if int(self.data_offset) != FILE_HEADER_SIZE:
            notes.append(f"sweep data starts at byte {int(self.data_offset)} (not {FILE_HEADER_SIZE})")
        if any(bytes(self.reserved2)):
            notes.append("the header's reserved2 area is not all zero (a newer Spike may use it)")
        if int(self.ref_scale) not in (0, 1):
            notes.append(f"refScale {int(self.ref_scale)} unknown: amplitudes treated as dB")
        if int(self.channelize_enabled) == 1:
            notes.append("channelized recording: each 'bin' is a channel power "
                         f"({self.label('channel_output_units')}); bin axis as stored in the header")
        if self.rbw_hz and self.window_bandwidth and self.bin_size_hz:
            expected = float(self.window_bandwidth) * float(self.bin_size_hz)
            if not math.isclose(expected, float(self.rbw_hz), rel_tol=1e-6):
                notes.append(f"rbwHz {float(self.rbw_hz):g} differs from windowBandwidth x binSizeHz "
                             f"= {expected:g}")
        return notes + self.enum_notes()


# %% ===========================================================================
#    BLOCK OF SWEEPS (what every read returns)
# =============================================================================
@dataclass
class SweepBlock:
    """Sweeps read in one call: copies, never views of the mapped file.

    sweep_index are recording-wide sweep numbers (continuous across the files
    of a ShrFileSet); file_index says which file each sweep came from.
    amplitudes is float32 (n_sweeps, n_columns) in the file's unit.
    """

    sweep_index: np.ndarray
    timestamp_ms: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    altitude_m: np.ndarray
    adc_overflow: np.ndarray
    amplitudes: np.ndarray | None
    file_index: np.ndarray

    def __len__(self) -> int:
        return int(self.sweep_index.size)

    @classmethod
    def empty(cls, n_columns: int | None) -> "SweepBlock":
        """A block with no sweeps (amplitudes None when not requested)."""
        amp = None if n_columns is None else np.empty((0, n_columns), dtype=np.float32)
        return cls(np.empty(0, np.int64), np.empty(0, np.int64), np.empty(0), np.empty(0), np.empty(0),
                   np.empty(0, np.uint8), amp, np.empty(0, np.int32))

    @classmethod
    def concatenate(cls, blocks: Sequence["SweepBlock"], n_columns: int | None) -> "SweepBlock":
        """Join blocks in order (used across the files of a set)."""
        blocks = [b for b in blocks if len(b)]
        if not blocks:
            return cls.empty(n_columns)
        amps = None if blocks[0].amplitudes is None else np.concatenate([b.amplitudes for b in blocks])
        cat = lambda name: np.concatenate([getattr(b, name) for b in blocks])  # noqa: E731
        return cls(cat("sweep_index"), cat("timestamp_ms"), cat("latitude"), cat("longitude"),
                   cat("altitude_m"), cat("adc_overflow"), amps, cat("file_index"))


# %% ===========================================================================
#    HELPERS
# =============================================================================
def _normalise_range(n: int, start: int, stop: int | None, step: int) -> range:
    """Clip a (start, stop, step) request to 0..n (step >= 1)."""
    if step < 1:
        raise ValueError(f"step must be >= 1 (got {step})")
    stop = n if stop is None else min(int(stop), n)
    return range(max(0, int(start)), max(stop, 0), int(step))


def _normalise_columns(n_bins: int, col0: int, col1: int | None) -> tuple[int, int]:
    """Clip a column range to 0..n_bins and check it is not empty."""
    col1 = n_bins if col1 is None else min(int(col1), n_bins)
    col0 = max(0, int(col0))
    if col1 <= col0:
        raise ValueError(f"empty column range {col0}..{col1} (file has {n_bins} bins)")
    return col0, col1


def detect_amplitude_grid(values: np.ndarray, step_db: float = 0.01) -> dict[str, Any]:
    """Are the values whole multiples of step_db plus one common offset?

    The SM series min/max processing converts every FFT to 0.01 dB
    resolution [R4]; an average detector gives continuous values. Returns
    {"on_grid", "offset_db", "max_residual_db", "distinct_values", "samples"}.
    """
    finite = np.asarray(values, dtype=np.float64).ravel()
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {"on_grid": False, "offset_db": float("nan"), "max_residual_db": float("nan"),
                "distinct_values": 0, "samples": 0}
    distinct = np.unique(finite.astype(np.float32).astype(np.float64))
    scaled = distinct / step_db
    # Common fractional part as a circular mean, so an offset near 0 (values
    # just below and just above whole steps) is not averaged to 0.5.
    phase = np.exp(2j * np.pi * (scaled % 1.0))
    offset = float((np.angle(phase.mean()) / (2 * np.pi)) % 1.0)
    residual = np.abs(((scaled - offset + 0.5) % 1.0) - 0.5)       # distance to the shifted grid
    max_residual = float(residual.max() * step_db)
    # float32 resolution near |x| = 200 dB is ~1.5e-5 dB; allow a margin. Require
    # several distinct values, otherwise a constant trace would "be on the grid".
    on_grid = bool(distinct.size >= 16 and max_residual < 5e-4 * step_db / 0.01)
    return {"on_grid": on_grid, "offset_db": offset * step_db, "max_residual_db": max_residual,
            "distinct_values": int(distinct.size), "samples": int(finite.size)}


# %% ===========================================================================
#    ONE FILE
# =============================================================================
class ShrFile:
    """One .shr recording, validated, with memory-mapped block reads.

    Parameters
    ----------
    path : the .shr file.
    sweep_limit : read at most this many sweeps (worker processes pass the
        count the parent process decided, so every process agrees even if a
        recording is still growing).

    Attributes
    ----------
    header : ShrHeader as stored.
    n_sweeps : sweeps that will be read (complete sweeps present, bounded by
        the header count unless the count is 0, and by sweep_limit).
    stated_sweep_count : header.sweep_count exactly as written.
    complete_sweeps : complete sweep records physically in the file.
    trailing_bytes : bytes after the last complete sweep.
    notes : list of human-readable remarks (salvage, odd values).
    """

    def __init__(self, path: str | os.PathLike, sweep_limit: int | None = None) -> None:
        self.path = Path(path)
        self._sweep_limit = None if sweep_limit is None else int(sweep_limit)
        self._map: np.memmap | None = None
        self.notes: list[str] = []
        with open(self.path, "rb") as handle:
            raw = handle.read(FILE_HEADER_SIZE)
        if len(raw) < FILE_HEADER_SIZE:
            raise ShrFormatError(f"{self.path.name}: {len(raw)} bytes, shorter than the "
                                 f"{FILE_HEADER_SIZE}-byte .shr header")
        self.header = ShrHeader.from_bytes(raw)
        errors = self.header.validation_errors()
        if errors:
            raise ShrFormatError(f"{self.path.name}: " + "; ".join(errors))
        self.file_size = self.path.stat().st_size
        self.record_dtype = sweep_record_dtype(int(self.header.sweep_length))
        assert self.record_dtype.itemsize == self.header.sweep_record_size
        data_bytes = max(0, self.file_size - int(self.header.data_offset))
        self.complete_sweeps, self.trailing_bytes = divmod(data_bytes, self.record_dtype.itemsize)
        self.stated_sweep_count = int(self.header.sweep_count)
        self.n_sweeps = self._usable_sweeps()
        self.notes.extend(self.header.consistency_notes())

    # -- sweep count rules (salvage) ----------------------------------------------------
    def _usable_sweeps(self) -> int:
        """Decide how many sweeps to read, and say why when it is not obvious."""
        stated, complete = self.stated_sweep_count, int(self.complete_sweeps)
        if self._sweep_limit is not None:
            return max(0, min(self._sweep_limit, complete))
        if stated == 0:
            usable = complete
            if complete:
                self.notes.append(f"header sweep count is 0 (recording not closed?); reading the "
                                  f"{complete} complete sweeps present")
        elif stated > complete:
            usable = complete
            self.notes.append(f"header says {stated} sweeps but only {complete} are complete "
                              f"(recording cut short); reading {complete}")
        else:
            usable = stated
            if complete > stated:
                self.notes.append(f"{complete - stated} complete sweep(s) beyond the header count are ignored")
        if self.trailing_bytes:
            self.notes.append(f"{self.trailing_bytes} trailing byte(s) after the last complete sweep are ignored")
        return usable

    # -- convenience properties ----------------------------------------------------------
    @property
    def n_bins(self) -> int:
        return int(self.header.sweep_length)

    @property
    def paths(self) -> list[Path]:
        """Same API as ShrFileSet: the list of files (one here)."""
        return [self.path]

    @property
    def name(self) -> str:
        return self.path.name

    def frequencies_hz(self, col0: int = 0, col1: int | None = None) -> np.ndarray:
        return self.header.frequencies_hz(col0, col1)

    # -- mapping (opened lazily, released by close()) ---------------------------------------
    def _mapped(self) -> np.memmap:
        """The read-only memory map of all usable sweep records."""
        if self._map is None:
            if self.n_sweeps == 0:
                raise ShrFormatError(f"{self.path.name}: no complete sweep to read")
            self._map = np.memmap(self.path, dtype=self.record_dtype, mode="r",
                                  offset=int(self.header.data_offset), shape=(self.n_sweeps,))
        return self._map

    def close(self) -> None:
        """Release the memory map (on Windows the file can then be moved or deleted)."""
        mapped, self._map = self._map, None
        if mapped is not None:
            raw_map = getattr(mapped, "_mmap", None)
            del mapped
            if raw_map is not None:
                try:
                    raw_map.close()
                except (BufferError, ValueError):      # a view is still alive: leave it to GC
                    pass

    def __enter__(self) -> "ShrFile":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:                               # interpreter shutdown
            pass

    # -- pickling for spawn workers: path and count only, never the mapping --------------------
    def __getstate__(self) -> dict[str, Any]:
        return {"path": str(self.path), "sweep_limit": self.n_sweeps}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__init__(state["path"], sweep_limit=state["sweep_limit"])

    # -- reading -----------------------------------------------------------------------------
    def read(self, start: int = 0, stop: int | None = None, step: int = 1, col0: int = 0,
             col1: int | None = None, amplitudes: bool = True, _file_index: int = 0,
             _index_offset: int = 0) -> SweepBlock:
        """Sweeps start, start+step, ... < stop; bins col0..col1-1.

        One vectorised copy out of the memory map. amplitudes=False reads the
        sweep headers only (time stamps, GPS, overflow).
        """
        rows = _normalise_range(self.n_sweeps, start, stop, step)
        n_cols = None
        if amplitudes:
            col0, col1 = _normalise_columns(self.n_bins, col0, col1)
            n_cols = col1 - col0
        if len(rows) == 0:
            return SweepBlock.empty(n_cols)
        records = self._mapped()[rows.start:rows.stop:rows.step]      # a view, copied below
        overflow = (np.array(records["adc_overflow"], dtype=np.uint8) if self.header.has_adc_overflow
                    else np.zeros(len(rows), dtype=np.uint8))
        amps = (np.array(records["amplitude"][:, col0:col1], dtype=np.float32, order="C")
                if amplitudes else None)
        block = SweepBlock(
            sweep_index=np.arange(rows.start, rows.stop, rows.step, dtype=np.int64)[: len(rows)] + _index_offset,
            timestamp_ms=np.array(records["timestamp_ms"], dtype=np.int64),
            latitude=np.array(records["latitude"], dtype=np.float64),
            longitude=np.array(records["longitude"], dtype=np.float64),
            altitude_m=np.array(records["altitude_m"], dtype=np.float64),
            adc_overflow=overflow, amplitudes=amps,
            file_index=np.full(len(rows), _file_index, dtype=np.int32))
        del records
        return block

    def read_amplitudes(self, start: int = 0, stop: int | None = None, step: int = 1, col0: int = 0,
                        col1: int | None = None) -> np.ndarray:
        """Only the float32 amplitude array of read()."""
        return self.read(start, stop, step, col0, col1).amplitudes

    def get_sweep(self, index: int) -> SweepBlock:
        """One sweep (all bins) as a one-row SweepBlock."""
        if not 0 <= int(index) < self.n_sweeps:
            raise IndexError(f"sweep {index} outside 0..{self.n_sweeps - 1}")
        return self.read(int(index), int(index) + 1)

    def timestamps_ms(self, start: int = 0, stop: int | None = None, step: int = 1) -> np.ndarray:
        """Time stamps only (int64 ms since the Unix epoch)."""
        return self.read(start, stop, step, amplitudes=False).timestamp_ms

    def iter_blocks(self, block_sweeps: int, start: int = 0, stop: int | None = None, step: int = 1,
                    col0: int = 0, col1: int | None = None) -> Iterator[SweepBlock]:
        """Successive blocks of at most block_sweeps selected sweeps."""
        rows = _normalise_range(self.n_sweeps, start, stop, step)
        per_block = max(1, int(block_sweeps)) * rows.step
        for first in range(rows.start, rows.stop, per_block):
            yield self.read(first, min(first + per_block, rows.stop), rows.step, col0, col1)

    # -- checks ----------------------------------------------------------------------------------
    def check_timestamps(self) -> list[str]:
        """Notes about time stamps going backwards or repeating (reads all sweep headers)."""
        ts = self.timestamps_ms()
        notes = []
        if ts.size > 1:
            steps = np.diff(ts)
            back = int((steps < 0).sum())
            if back:
                notes.append(f"time stamps go backwards {back} time(s) (largest {int(-steps.min())} ms)")
        return notes

    def amplitude_grid(self, max_sweeps: int = 32) -> dict[str, Any]:
        """detect_amplitude_grid() on the first sweeps (a quick detector cross-check)."""
        if self.n_sweeps == 0 or not self.header.is_db:
            return detect_amplitude_grid(np.empty(0))
        return detect_amplitude_grid(self.read_amplitudes(0, min(self.n_sweeps, max_sweeps)))

    def summary_lines(self) -> list[str]:
        """Short human-readable description (CLI, logs)."""
        h = self.header
        f = h.frequencies_hz()
        lines = [f"File           : {self.path}",
                 f"Size           : {self.file_size:,} bytes, version {h.version}, data at byte {h.data_offset}",
                 f"Sweeps         : {self.n_sweeps} read (header {self.stated_sweep_count}, "
                 f"complete {self.complete_sweeps}) x {self.n_bins} bins",
                 f"Frequency      : {f[0] / 1e6:.6f} .. {f[-1] / 1e6:.6f} MHz, bin {h.bin_size_hz:.6f} Hz",
                 f"Centre / span  : {h.center_freq_hz / 1e6:.6f} / {h.span_hz / 1e6:.6f} MHz",
                 f"RBW / VBW      : {h.rbw_hz:g} / {h.vbw_hz:g} Hz, window {h.label('window')}",
                 f"Detector       : {h.label('detector')}, units {h.label('processing_units')}",
                 f"Reference      : {h.ref_level:g} {h.amplitude_unit}, {h.div:g}/div, "
                 f"atten {h.attenuation}, gain {h.gain}",
                 f"Decimation     : {h.label('decimation_type')} / {h.label('decimation_detector')}, "
                 f"count {h.decimation_count}, time {h.decimation_time_ms} ms",
                 f"Channelizer    : {'on' if h.channelize_enabled == 1 else 'off'}"
                 + (f", {h.label('channel_output_units')}, centre {h.channel_center_hz / 1e6:g} MHz, "
                    f"width {h.channel_width_hz / 1e6:g} MHz" if h.channelize_enabled == 1 else ""),
                 f"Title          : {h.title!r}"]
        if self.n_sweeps:
            ts = self.read(0, 1, amplitudes=False).timestamp_ms[0], \
                self.read(self.n_sweeps - 1, self.n_sweeps, amplitudes=False).timestamp_ms[0]
            lines.append(f"Time           : {_utc(ts[0])} .. {_utc(ts[1])} ({(ts[1] - ts[0]) / 1000:.3f} s)")
        lines += [f"Note           : {n}" for n in self.notes]
        return lines


def _utc(ms: int) -> str:
    """ISO-8601 UTC text of a millisecond time stamp."""
    import datetime as _dt
    return _dt.datetime.fromtimestamp(int(ms) / 1000.0, _dt.timezone.utc).isoformat(timespec="milliseconds")


# %% ===========================================================================
#    SEVERAL FILES OF ONE RECORDING
# =============================================================================
# Header fields that must agree for files to be joined (same bins, same axis,
# same unit); the others only produce a note when they differ.
JOIN_REQUIRED = ("sweep_length", "first_bin_freq_hz", "bin_size_hz", "ref_scale")
JOIN_NOTED = ("center_freq_hz", "span_hz", "rbw_hz", "vbw_hz", "detector", "processing_units", "window",
              "ref_level", "attenuation", "gain", "decimation_type", "decimation_detector",
              "decimation_count", "decimation_time_ms", "channelize_enabled", "channel_output_units")


class ShrFileSet:
    """Several .shr files read as one recording (same API as ShrFile).

    Files are ordered by their first time stamp (ties by name). Sweep numbers
    run continuously across the files. Files whose bin axes or units differ
    are refused (ShrFormatError); other differences become notes.
    """

    def __init__(self, paths: Sequence[str | os.PathLike], sweep_limits: Sequence[int] | None = None,
                 order_by_time: bool = True) -> None:
        if not paths:
            raise ValueError("ShrFileSet needs at least one file")
        limits = list(sweep_limits) if sweep_limits is not None else [None] * len(paths)
        files = [ShrFile(p, sweep_limit=lim) for p, lim in zip(paths, limits)]
        empty = [f for f in files if f.n_sweeps == 0]
        files = [f for f in files if f.n_sweeps > 0] or files[:1]
        dropped = [f.path.name for f in empty if f not in files]
        if order_by_time and sweep_limits is None:
            files.sort(key=lambda f: (int(f.timestamps_ms(0, 1)[0]) if f.n_sweeps else 0, f.path.name))
        self.files = files
        self.header = files[0].header
        self.notes: list[str] = [f"{name}: no complete sweep; left out of the set" for name in dropped]
        first = files[0].header
        for f in files[1:]:
            for name in JOIN_REQUIRED:
                if getattr(f.header, name) != getattr(first, name):
                    raise ShrFormatError(f"cannot join {f.path.name} to {files[0].path.name}: {name} "
                                         f"{getattr(f.header, name)!r} != {getattr(first, name)!r}")
            differing = [n for n in JOIN_NOTED if getattr(f.header, n) != getattr(first, n)]
            if differing:
                self.notes.append(f"{f.path.name}: settings differ from {files[0].path.name} "
                                  f"({', '.join(differing)})")
        for k, f in enumerate(files):
            self.notes.extend(f"{f.path.name}: {n}" for n in f.notes)
        self.offsets = np.concatenate([[0], np.cumsum([f.n_sweeps for f in files])]).astype(np.int64)
        self.n_sweeps = int(self.offsets[-1])
        self.gaps = self._gaps_between_files()

    # -- API shared with ShrFile -----------------------------------------------------------------
    @property
    def path(self) -> Path:
        return self.files[0].path

    @property
    def paths(self) -> list[Path]:
        return [f.path for f in self.files]

    @property
    def name(self) -> str:
        return f"{self.files[0].path.name} (+{len(self.files) - 1} file(s))" if len(self.files) > 1 \
            else self.files[0].path.name

    @property
    def n_bins(self) -> int:
        return int(self.header.sweep_length)

    @property
    def stated_sweep_count(self) -> int:
        return sum(f.stated_sweep_count for f in self.files)

    @property
    def complete_sweeps(self) -> int:
        return sum(int(f.complete_sweeps) for f in self.files)

    @property
    def file_size(self) -> int:
        return sum(f.file_size for f in self.files)

    def frequencies_hz(self, col0: int = 0, col1: int | None = None) -> np.ndarray:
        return self.header.frequencies_hz(col0, col1)

    def close(self) -> None:
        for f in self.files:
            f.close()

    def __enter__(self) -> "ShrFileSet":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __getstate__(self) -> dict[str, Any]:
        return {"paths": [str(f.path) for f in self.files], "limits": [f.n_sweeps for f in self.files]}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__init__(state["paths"], sweep_limits=state["limits"], order_by_time=False)

    def locate(self, index: int) -> tuple[int, int]:
        """(file number, sweep number inside that file) of a recording-wide sweep."""
        if not 0 <= int(index) < self.n_sweeps:
            raise IndexError(f"sweep {index} outside 0..{self.n_sweeps - 1}")
        k = int(np.searchsorted(self.offsets, int(index), side="right") - 1)
        return k, int(index) - int(self.offsets[k])

    def read(self, start: int = 0, stop: int | None = None, step: int = 1, col0: int = 0,
             col1: int | None = None, amplitudes: bool = True) -> SweepBlock:
        """Like ShrFile.read, across file boundaries (the step continues across files)."""
        rows = _normalise_range(self.n_sweeps, start, stop, step)
        n_cols = None
        if amplitudes:
            col0, col1 = _normalise_columns(self.n_bins, col0, col1)
            n_cols = col1 - col0
        parts = []
        for k, f in enumerate(self.files):
            lo, hi = int(self.offsets[k]), int(self.offsets[k + 1])
            if hi <= rows.start or lo >= rows.stop or hi == lo:
                continue
            # first selected index >= lo that is on the step grid
            first = rows.start if rows.start >= lo else rows.start + math.ceil((lo - rows.start) / rows.step) * rows.step
            last = min(rows.stop, hi)
            if first >= last:
                continue
            parts.append(f.read(first - lo, last - lo, rows.step, col0, col1, amplitudes,
                                _file_index=k, _index_offset=lo))
        return SweepBlock.concatenate(parts, n_cols)

    def read_amplitudes(self, start: int = 0, stop: int | None = None, step: int = 1, col0: int = 0,
                        col1: int | None = None) -> np.ndarray:
        return self.read(start, stop, step, col0, col1).amplitudes

    def get_sweep(self, index: int) -> SweepBlock:
        self.locate(index)                                  # bounds check
        return self.read(int(index), int(index) + 1)

    def timestamps_ms(self, start: int = 0, stop: int | None = None, step: int = 1) -> np.ndarray:
        return self.read(start, stop, step, amplitudes=False).timestamp_ms

    def iter_blocks(self, block_sweeps: int, start: int = 0, stop: int | None = None, step: int = 1,
                    col0: int = 0, col1: int | None = None) -> Iterator[SweepBlock]:
        rows = _normalise_range(self.n_sweeps, start, stop, step)
        per_block = max(1, int(block_sweeps)) * rows.step
        for first in range(rows.start, rows.stop, per_block):
            yield self.read(first, min(first + per_block, rows.stop), rows.step, col0, col1)

    def check_timestamps(self) -> list[str]:
        notes = []
        for f in self.files:
            notes.extend(f"{f.path.name}: {n}" for n in f.check_timestamps())
        return notes

    def amplitude_grid(self, max_sweeps: int = 32) -> dict[str, Any]:
        return self.files[0].amplitude_grid(max_sweeps)

    def _gaps_between_files(self) -> list[dict[str, Any]]:
        """Time between the last sweep of each file and the first sweep of the next."""
        gaps = []
        for a, b in zip(self.files, self.files[1:]):
            if not (a.n_sweeps and b.n_sweeps):
                continue
            end = int(a.timestamps_ms(a.n_sweeps - 1, a.n_sweeps)[0])
            begin = int(b.timestamps_ms(0, 1)[0])
            gaps.append({"after": a.path.name, "before": b.path.name, "gap_ms": begin - end})
            if begin < end:
                self.notes.append(f"{b.path.name} starts {end - begin} ms before {a.path.name} ends")
        return gaps

    def summary_lines(self) -> list[str]:
        lines = [f"Recording set  : {len(self.files)} file(s), {self.n_sweeps} sweeps x {self.n_bins} bins"]
        for k, f in enumerate(self.files):
            lines.append(f"  [{k}] {f.path.name}: sweeps {int(self.offsets[k])}..{int(self.offsets[k + 1]) - 1}")
        lines += [f"  gap {g['after']} -> {g['before']}: {g['gap_ms']} ms" for g in self.gaps]
        lines += [f"Note           : {n}" for n in self.notes]
        return lines


def open_recording(paths: str | os.PathLike | Sequence[str | os.PathLike]) -> ShrFile | ShrFileSet:
    """ShrFile for one path, ShrFileSet for several."""
    if isinstance(paths, (str, os.PathLike)):
        return ShrFile(paths)
    paths = list(paths)
    return ShrFile(paths[0]) if len(paths) == 1 else ShrFileSet(paths)


def group_recordings(paths: Iterable[str | os.PathLike], max_gap_s: float = 10.0,
                     max_gap_sweeps: float = 50.0) -> list[list[Path]]:
    """Group files into recordings by content: compatible headers, adjacent times.

    Spike starts a new, sequentially numbered file when the maximum file size
    is reached [R5], but the naming scheme is not documented, so files are
    joined when (1) their bin axis and unit agree (JOIN_REQUIRED) and (2) the
    next file starts no later than max(max_gap_s, max_gap_sweeps x median
    sweep interval) after the previous one ends. Unreadable files are left
    as groups of their own (the caller reports the error when opening).
    """
    infos = []
    for p in paths:
        p = Path(p)
        try:
            with ShrFile(p) as f:
                if f.n_sweeps == 0:
                    infos.append((p, None, None, None, None))
                    continue
                ts = f.timestamps_ms(0, min(f.n_sweeps, 64))
                last = int(f.timestamps_ms(f.n_sweeps - 1, f.n_sweeps)[0])
                interval = float(np.median(np.diff(ts))) if ts.size > 1 else 0.0
                key = tuple(getattr(f.header, n) for n in JOIN_REQUIRED)
                infos.append((p, key, int(ts[0]), last, interval))
        except (OSError, ShrFormatError):
            infos.append((p, None, None, None, None))
    readable = sorted((i for i in infos if i[1] is not None), key=lambda i: (i[2], i[0].name))
    groups: list[list[Path]] = []
    previous = None
    for info in readable:
        p, key, first, last, interval = info
        if previous is not None:
            _, pkey, _, plast, pinterval = previous
            tolerance_ms = max(1000.0 * max_gap_s, max_gap_sweeps * max(interval, pinterval))
            if key == pkey and 0 <= first - plast <= tolerance_ms:
                groups[-1].append(p)
                previous = info
                continue
        groups.append([p])
        previous = info
    groups.extend([i[0]] for i in infos if i[1] is None)
    return groups


# %% ===========================================================================
#    WRITER (synthetic files, tests, examples)
# =============================================================================
def write_shr(path: str | os.PathLike, amplitudes: np.ndarray, timestamps_ms: Sequence[int] | np.ndarray,
              header: ShrHeader | None = None, latitude: np.ndarray | float = 0.0,
              longitude: np.ndarray | float = 0.0, altitude_m: np.ndarray | float = 0.0,
              adc_overflow: np.ndarray | int = 0, title: str | None = None,
              sweep_count: int | None = None, **header_fields: Any) -> Path:
    """Write a complete .shr file.

    amplitudes: (n_sweeps, n_bins) values in the file unit. header (or
    header_fields such as first_bin_freq_hz=, bin_size_hz=, detector=,
    version=, data_offset=) sets the file header; sweep_length is taken from
    the data and sweep_count from the number of sweeps unless given (tests
    write 0 or wrong counts on purpose). Padding up to data_offset is zeros.
    """
    amps = np.ascontiguousarray(amplitudes, dtype="<f4")
    if amps.ndim != 2:
        raise ValueError("amplitudes must be 2-D (sweeps, bins)")
    n_sweeps, n_bins = amps.shape
    head = ShrHeader() if header is None else ShrHeader(**{f.name: getattr(header, f.name) for f in fields(header)})
    for name, value in header_fields.items():
        if not hasattr(head, name):
            raise TypeError(f"unknown header field {name!r}")
        setattr(head, name, value)
    head.sweep_length = n_bins
    head.sweep_count = n_sweeps if sweep_count is None else int(sweep_count)
    if title is not None:
        head.title_raw = ShrHeader.encode_title(title)
    records = np.zeros(n_sweeps, dtype=sweep_record_dtype(n_bins))
    records["timestamp_ms"] = np.asarray(timestamps_ms, dtype=np.uint64)
    records["latitude"] = latitude
    records["longitude"] = longitude
    records["altitude_m"] = altitude_m
    records["adc_overflow"] = adc_overflow
    records["amplitude"] = amps
    path = Path(path)
    with open(path, "wb") as handle:
        handle.write(head.to_bytes())
        handle.write(b"\x00" * (int(head.data_offset) - FILE_HEADER_SIZE))
        records.tofile(handle)
    return path


# %% ===========================================================================
#    SELF-TEST
# =============================================================================
def self_test(verbose: bool = True) -> bool:
    """Checks on synthetic files written with write_shr(); True if all pass."""
    import pickle
    results: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        results.append((name, bool(condition), detail))

    rng = np.random.default_rng(2026)
    with tempfile.TemporaryDirectory(prefix="shr_reader_test_") as tmp:
        tmp = Path(tmp)
        n_sw, n_bins = 40, 257
        amps = rng.normal(-90, 3, (n_sw, n_bins)).astype(np.float32)
        ts = 1_793_163_718_211 + np.arange(n_sw, dtype=np.int64) * 33
        base = dict(first_bin_freq_hz=13_836_029_052.734375, bin_size_hz=15_258.7890625,
                    center_freq_hz=13.9e9, span_hz=128e6, rbw_hz=30_000.0, vbw_hz=30_000.0,
                    window_bandwidth=1.96608, ref_level=-20.0)

        # 1-6 round trip --------------------------------------------------------------------
        p = write_shr(tmp / "a.shr", amps, ts, title="SM200C µW test — Ω", latitude=38.43,
                      longitude=-79.84, altitude_m=807.0, adc_overflow=(np.arange(n_sw) % 7 == 0), **base)
        with ShrFile(p) as f:
            blk = f.read()
            check("header size and offsets", HEADER_STRUCT.size == 472 and HEADER_OFFSETS["detector"] == 352
                  and HEADER_OFFSETS["reserved2"] == 408)
            check("round trip amplitudes bit-exact", np.array_equal(blk.amplitudes, amps))
            check("round trip time stamps", np.array_equal(blk.timestamp_ms, ts))
            check("round trip GPS and overflow", np.allclose(blk.latitude, 38.43) and
                  np.allclose(blk.altitude_m, 807.0) and int(blk.adc_overflow.sum()) == int((np.arange(n_sw) % 7 == 0).sum()))
            check("UTF-16 title", f.header.title == "SM200C µW test — Ω", repr(f.header.title))
            check("frequency axis", np.allclose(f.frequencies_hz()[[0, -1]],
                                                [base["first_bin_freq_hz"], base["first_bin_freq_hz"] + 256 * base["bin_size_hz"]]))
            check("no notes on a clean file", f.notes == [], str(f.notes))
            sub = f.read(3, 30, 4, 10, 20)
            check("step and column range", np.array_equal(sub.amplitudes, amps[3:30:4, 10:20]) and
                  np.array_equal(sub.sweep_index, np.arange(3, 30, 4)))
            joined = SweepBlock.concatenate(list(f.iter_blocks(5, 1, 39, 3, 7, 9)), 2)
            check("iter_blocks covers the selection", np.array_equal(joined.amplitudes, amps[1:39:3, 7:9]))
            hdr_only = f.read(0, 5, amplitudes=False)
            check("header-only read", hdr_only.amplitudes is None and np.array_equal(hdr_only.timestamp_ms, ts[:5]))
            clone = pickle.loads(pickle.dumps(f))
            check("pickle carries path and count", clone.n_sweeps == f.n_sweeps and
                  np.array_equal(clone.read(5, 9).amplitudes, amps[5:9]))
            clone.close()
            check("rbw = window bandwidth x bin size (no note)", not any("rbwHz" in n for n in f.notes))
            try:
                f.read(0, 2, col0=300)
                check("empty column range refused", False)
            except ValueError:
                check("empty column range refused", True)
            try:
                f.get_sweep(n_sw)
                check("sweep index bounds", False)
            except IndexError:
                check("sweep index bounds", True)

        # 7 close() releases the file (rename then delete) ---------------------------------------
        f = ShrFile(p)
        f.read(0, 3)
        f.close()
        moved = p.with_name("moved.shr")
        os.replace(p, moved)
        moved.unlink()
        check("close() releases the file", not moved.exists())

        # 8-10 enumerations: detector 2, unknown codes everywhere -----------------------------------
        p = write_shr(tmp / "det2.shr", amps, ts, detector=2, processing_units=2, **base)
        with ShrFile(p) as f:
            check("detector 2 opens and is labelled", f.header.label("detector") == "Max (code 2, inferred)",
                  f.header.label("detector"))
            check("detector 2 gives a note", any("detector = 2" in n for n in f.notes))
        unknown = dict(ref_scale=7, window=9, detector=11, processing_units=12, decimation_type=5,
                       decimation_detector=6, channel_output_units=8)
        p = write_shr(tmp / "unknown.shr", amps, ts, **{**base, **unknown})
        with ShrFile(p) as f:
            labels = [f.header.label(k) for k in unknown]
            check("unknown codes kept as numbers", all(lab.startswith("unknown (code") for lab in labels), str(labels))
            check("one note per unknown field", sum("not a known value" in n for n in f.notes) == len(unknown))
            check("unknown refScale treated as dB", f.header.is_db and np.array_equal(f.read_amplitudes(), amps))

        # 11 version 1: overflow byte not used -----------------------------------------------------
        p = write_shr(tmp / "v1.shr", amps, ts, version=1, adc_overflow=1, **base)
        with ShrFile(p) as f:
            check("version 1 reads, overflow reported 0", int(f.read().adc_overflow.sum()) == 0 and
                  any("version 1" in n for n in f.notes))

        # 12 newer version: read with a note ---------------------------------------------------------
        p = write_shr(tmp / "v3.shr", amps, ts, version=3, **base)
        with ShrFile(p) as f:
            check("version 3 read with a note", np.array_equal(f.read_amplitudes(), amps) and
                  any("newer" in n for n in f.notes))

        # 13 data offset beyond the header ---------------------------------------------------------------
        p = write_shr(tmp / "offset.shr", amps, ts, data_offset=1024, **base)
        with ShrFile(p) as f:
            check("dataOffset 1024 honoured", np.array_equal(f.read_amplitudes(), amps) and
                  any("byte 1024" in n for n in f.notes))

        # 14-17 salvage --------------------------------------------------------------------------------------
        p = write_shr(tmp / "zero.shr", amps, ts, sweep_count=0, **base)
        with ShrFile(p) as f:
            check("header count 0 -> complete sweeps", f.n_sweeps == n_sw and any("count is 0" in n for n in f.notes))
        p = write_shr(tmp / "cut.shr", amps, ts, **base)
        record = SWEEP_HEADER_SIZE + 4 * n_bins
        with open(p, "r+b") as handle:
            handle.truncate(FILE_HEADER_SIZE + 25 * record + 100)
        with ShrFile(p) as f:
            check("cut-short file salvaged", f.n_sweeps == 25 and f.trailing_bytes == 100 and
                  np.array_equal(f.read_amplitudes(), amps[:25]) and any("cut short" in n for n in f.notes))
        p = write_shr(tmp / "extra.shr", amps, ts, sweep_count=30, **base)
        with ShrFile(p) as f:
            check("sweeps beyond the header count ignored", f.n_sweeps == 30 and any("beyond" in n for n in f.notes))
        with ShrFile(p, sweep_limit=12) as f:
            check("sweep_limit bounds the count", f.n_sweeps == 12)

        # 18-19 refused files ------------------------------------------------------------------------------
        bad = tmp / "bad.shr"
        bad.write_bytes(b"\x00" * 600)
        try:
            ShrFile(bad)
            check("bad signature refused", False)
        except ShrFormatError:
            check("bad signature refused", True)
        p = write_shr(tmp / "nobins.shr", amps, ts, **base)
        raw = bytearray(p.read_bytes())
        struct.pack_into("<d", raw, HEADER_OFFSETS["bin_size_hz"], 0.0)
        p.write_bytes(bytes(raw))
        try:
            ShrFile(p)
            check("zero bin size refused", False)
        except ShrFormatError:
            check("zero bin size refused", True)

        # 20-25 file sets ----------------------------------------------------------------------------------
        a1 = write_shr(tmp / "set_b.shr", amps[:15], ts[:15], **base)          # names out of time order
        a2 = write_shr(tmp / "set_a.shr", amps[15:], ts[15:], **base)
        far = write_shr(tmp / "later.shr", amps[:5], ts[:5] + 3_600_000, **base)
        other = write_shr(tmp / "other_axis.shr", amps[:5, :100], ts[:5] + 1_000, **base)
        with ShrFileSet([a2, a1]) as s:
            blk = s.read()
            check("set ordered by time", [q.name for q in s.paths] == ["set_b.shr", "set_a.shr"])
            check("set reads continuously", np.array_equal(blk.amplitudes, amps) and
                  np.array_equal(blk.sweep_index, np.arange(n_sw)) and np.array_equal(blk.timestamp_ms, ts))
            check("set step across the boundary", np.array_equal(s.read(2, 40, 4).amplitudes, amps[2:40:4]))
            check("set file index and locate", s.locate(15) == (1, 0) and blk.file_index[14] == 0 and blk.file_index[15] == 1)
            check("set gap measured", s.gaps and s.gaps[0]["gap_ms"] == 33, str(s.gaps))
            clone = pickle.loads(pickle.dumps(s))
            check("set pickles", np.array_equal(clone.read(10, 20).amplitudes, amps[10:20]))
            clone.close()
        try:
            ShrFileSet([a1, other])
            check("incompatible files refused", False)
        except ShrFormatError:
            check("incompatible files refused", True)
        groups = group_recordings([far, a2, other, a1])
        names = sorted(sorted(q.name for q in g) for g in groups)
        check("group_recordings by content", names == [["later.shr"], ["other_axis.shr"], ["set_a.shr", "set_b.shr"]],
              str(names))

        # 26 amplitude grid ---------------------------------------------------------------------------------
        grid = np.round(amps.astype(np.float64), 2) + 0.00824
        on = detect_amplitude_grid(grid.astype(np.float32))
        off = detect_amplitude_grid(amps)
        check("0.01 dB grid detected", on["on_grid"] and abs(on["offset_db"] - 0.00824) < 2e-5 and not off["on_grid"],
              f"{on} / {off}")

        # 27 time stamps going backwards ------------------------------------------------------------------------
        back = ts.copy()
        back[20] = back[19] - 500
        p = write_shr(tmp / "back.shr", amps, back, **base)
        with ShrFile(p) as f:
            check("time stamps going backwards noted", any("backwards" in n for n in f.check_timestamps()))

    passed = sum(ok for _, ok, _ in results)
    if verbose:
        for name, ok, detail in results:
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
        print(f"shr_reader {__version__} self-test: {passed}/{len(results)} passed")
    return passed == len(results)


# %% ===========================================================================
#    COMMAND LINE
# =============================================================================
def main(argv: Sequence[str] | None = None) -> int:
    """Inspect .shr files (or run the self-test)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help=".shr files to describe")
    parser.add_argument("--join", action="store_true", help="read all files as one recording (ShrFileSet)")
    parser.add_argument("--group", action="store_true", help="show how the files group into recordings")
    parser.add_argument("--json", action="store_true", help="print the header(s) as JSON")
    parser.add_argument("--grid", action="store_true", help="check the 0.01 dB amplitude grid of the first sweeps")
    parser.add_argument("--selftest", action="store_true", help="run the self-test on synthetic files")
    parser.add_argument("--version", action="version", version=f"shr_reader {__version__}")
    args = parser.parse_args(argv)
    if args.selftest:
        return 0 if self_test() else 1
    if not args.files:
        parser.print_help()
        return 2
    if args.group:
        for k, group in enumerate(group_recordings(args.files)):
            print(f"recording {k}: " + ", ".join(p.name for p in group))
        return 0
    sources = [ShrFileSet(args.files)] if args.join else [ShrFile(p) for p in args.files]
    for source in sources:
        with source:
            if args.json:
                print(json.dumps(source.header.as_dict(), indent=1, default=str))
            else:
                print("\n".join(source.summary_lines()))
                if isinstance(source, ShrFileSet):
                    for f in source.files:
                        print("\n".join("    " + line for line in f.summary_lines()))
            if args.grid:
                print("amplitude grid:", source.amplitude_grid())
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
