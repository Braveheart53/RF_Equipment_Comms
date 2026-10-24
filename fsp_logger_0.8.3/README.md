# R&S FSP Logger 0.8.3 — merged release

Author/application owner: William W. Wallace, NRAO/GBO, wwallace@nrao.edu.
AI-assisted integration, 2026-10-23. Owner attribution and existing writer GPL
notices retained. Original logger licensing is not inferred or changed.

## Install and run (Python 3.8–3.12 target)

Keep all four Python modules together. Dependencies are NOT bundled.

```console
python -m pip install -r requirements.txt
python rs_fsp_logger.py --demo
python -m unittest discover -s tests -v
```

Remove --demo for hardware. Spyder cell markers and author headers are retained.
Choose CSV, connect, verify settings and Start. Stop and allow CSV to drain before
Create Veusz Plots / Reports. Select a NEW report directory. Optional PDF/PNG
requires a working Veusz installation (select executable from Tools or VEUSZ_EXE).
Native .vszh5 creation requires h5py, but does not require Veusz installed.

## Versions

| Component | Version |
|---|---:|
| rs_fsp_logger.py | 0.8.3 |
| fsp_reports.py | 0.1.3 |
| fsp_background.py | 0.1.2 |
| vszh5_writer.py | 0.0.17 |

## Verified source merge

This release compares the ACTUAL supplied 0.8.1 and 0.8.2 components, rather than
reconstructing 0.8.1. Source hashes, diffs and comparison evidence are in docs.
The 0.8.2 plot set includes all 0.8.1 plot families; the union is retained without
duplicating equivalent pages. All prior embedded data arrays are retained.

| Page | Description |
|---|---|
| measurement_report | Provenance and interpretation notes |
| last_capture | Last complete frequency sweep, all analyzer channels |
| traceN_spectral_envelope | Per-bin min, LINEAR-POWER mean and max |
| traceN_waterfall | All raw captures vs frequency, capture-index ordinate |
| traceN_peak_history | Peak dBm and peak frequency vs elapsed time |
| Freq_N_GHz | One page per frequency, dBm vs recorded datetime |
| Combined_Freq_vs_Time | Every frequency with exact N GHz key labels |

Individual frequency pages overlay independent analyzer channels. The combined
page has one panel per analyzer channel, avoiding ambiguous duplicate keys or
merging clear/write, max-hold and average channels. All bins and captures remain;
no implicit averaging/interpolation/decimation. At 801 bins and three channels,
813 pages are constructed (one report page). Large legends can become crowded.

## All averaging is linear power

Shared implementation: vszh5_writer.linear_power_mean_dbm(). Reports call this
helper. Conversion is relative linear milliwatts, equivalent to:

    mean_dBm = 10 * log10(mean(10 ** (samples_dBm / 10)))

Max-referenced scaling and bounded chunks avoid overflow and a second full power
matrix. Equal capture weights are used, not dwell-time weights. Nonfinite or empty
samples are rejected. No arithmetic mean of dBm is used. Independent analyzer
channels are never averaged together. GUI automatic display downsampling is
explicitly disabled to prevent any hidden logarithmic mean downsampling. Min,
max and peak selections are not averages. Analyzer-internal averaging already
applied before capture cannot be retrospectively changed by this software.

## Safe parallelism and UI

CSV formatting/writes overlap serial instrument I/O using a bounded consumer queue.
The latest-frame display mailbox avoids unbounded GUI signal queues. Per-channel
NumPy statistics use up to three workers. Reporting runs in a separate QProcess;
HDF5 writing has one owner. A shared VISA session NEVER has concurrent commands.
Acquisition worker and instrument code preserve the 0.8.1 implementations.

Reports are blocked during scheduled waiting, sampling and CSV drain. Sampling is
blocked while reports run. Close cooperatively drains acquisition; a running report
must finish before closing. Queue saturation preserves a terminal capture and stops
sampling explicitly. Flush is not an fsync/power-loss guarantee. This is best-effort
desktop sampling, not a hard-real-time scheduler or an interprocess file lock.

File / Connection / Acquisition / View / Tools / Help menus and text toolbar,
Dark / Light / System themes, author About dialog and report button are retained.
All plot generation is through the same GUI-button/CLI pipeline. Exported documents
remain publication-style; GUI themes do not recolor reports.

## Validation and limitations (THIS delivery)

16 tests passed; one real-HDF5 integration test skipped because h5py is unavailable.
Tested CPython 3.12.8 numerical reductions, CSV ordering/backpressure, memory-recorded
document construction and 801-bin page commands. Actual supplied 0.8.1/0.8.2 report
generators were compared using the same synthetic software fixture: 11 and 15 pages,
respectively; merged output has the full 15-page union and unchanged dataset values.
Instrument and acquisition ASTs match 0.8.1. Python 3.8 grammar checks pass.

NOT rerun here: Python 3.8 runtime, Qt GUI, real HDF5 creation, real Veusz PDF/PNG,
physical hardware, Windows/macOS or interactive Spyder. Earlier release validation
is NOT presented as fresh verification of this release. Run included tests after
installing requirements; the actual-HDF5 test will then run rather than skip.
Do not regard this release as hardware-validated. Preserve your working versions.
Legacy synchronous connect/diagnostics can still pause on a faulty link.

Legacy CSV lacks RF calibration/detector/RBW metadata. No IEC/CISPR/ANSI/IEEE/AMTA
measurement-conformance claim is made. No measurement standard is needed or newly
asserted by this code-only merge.

## Archive

The .7z uses standard Copy (uncompressed) streams for portability in the restricted
build environment. ZIP is provided as an alternative. Both contain the same source,
tests, docs and SHA-256 manifest. No dependencies or fabricated RF measurements are
included. Archive CRCs/payload hashes were checked by the bundled release build.
