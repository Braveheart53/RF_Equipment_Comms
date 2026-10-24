# R&S FSP Trace Logger — complete Python package

Release **0.8.1**, updated **2026-10-23**. Tested Python endpoints: **3.8.20** and **3.12.8**.

This distribution integrates the supplied FSP logger and native Veusz writer. It includes all application source, installable wheel/build configuration, tests, requirements, revision patches and validation logs. Third-party dependencies and the standalone Veusz application are **not bundled**. No physical analyzer or Windows/Spyder host was available for testing.

## Contents

| Module | Revision | Purpose |
|---|---:|---|
| `rs_fsp_logger.py` | 0.8.1 | GUI, serialized VISA acquisition, report button |
| `fsp_background.py` | 0.1.1 | Bounded CSV writer and latest-display mailbox |
| `fsp_reports.py` | 0.1.1 | CSV validation, parallel statistics, plots and reports |
| `vszh5_writer.py` | 0.0.15 | Updated supplied native HDF5 document writer |
| `requirements.txt` | Release-pinned | Core runtime dependencies |
| `requirements-render.txt` | Release-pinned | Optional PDF-bookmark dependency |
| `requirements-dev.txt` | Release-pinned | Runtime, pytest, build frontend |
| `pyproject.toml` | 0.8.1 | Wheel/source build and command-line entry points |
| `tests/`, `docs/` | Release tests | Tests, actual logs, environment inventory and patch diffs |
| `dist/` | 0.8.1 | Wheel/source distribution included in outer archive |

## Install and launch

Use a fresh virtual environment to avoid mixing Qt bindings. On Windows, replace `3.12` with `3.8` for that endpoint:

```bat
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python rs_fsp_logger.py --demo
```

On Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python rs_fsp_logger.py --demo
```

Alternatively install the included wheel in your chosen environment:

```sh
python -m pip install dist/rs_fsp_logger-0.8.1-py3-none-any.whl
rs-fsp-logger --demo
```

For real use, omit `--demo`, select your resource/backend, and connect. `@ivi` may require vendor VISA; `@py` uses PyVISA-py. GUI use requires OS Qt/OpenGL libraries and a graphical session. Python 3.8 compatibility is legacy application support, not ongoing interpreter security maintenance.

## Spyder

Keep all four Python modules together, or install the wheel in Spyder's selected interpreter. Use the appropriate Python 3.8/3.12 environment with Qt integration and a dedicated console. Source uses `# %%` cells. Do not re-execute class-body cells out of order during acquisition. Terminal execution is the simplest independent diagnostic if the IDE event loop differs. Spyder itself was not available for runtime testing.

## GUI report workflow

1. Record normally, press **Stop**, and wait for **Idle; CSV writer closed.**
2. Select a completed CSV in **Output File**, if needed. Analyzer connection is not required for reporting.
3. Optionally select **Also render PDF + PNG (requires Veusz)**.
4. Click **Create Veusz Plots / Reports…** and choose a **new folder name**. The save-name dialog names a new directory, not a single file.
5. Wait for completion. Acquisition remains disabled until the report process exits.

Reports are disabled during acquisition, scheduled waiting and CSV draining. Starting acquisition is also disabled throughout report processing. This conservative policy protects this logger instance; it cannot control external applications, other instances, OS scheduling or front-panel changes. It does not guess a safe CPU-load threshold.

Command-line equivalents:

```sh
python fsp_reports.py --csv recording.csv --output-dir recording_reports
python fsp_reports.py --csv recording.csv --output-dir rendered_reports --render
python fsp_reports.py --csv recording.csv --output-dir large_reports --max-matrix-mib 2048
```

Use only closed inputs. Source signatures detect ordinary changes during validation/import/hash but do not provide a cross-process file lock.

## Generated deliverables

For T traces, the native document has 2 + 3*T pages.

| Output | Contents |
|---|---|
| `fsp_report.vszh5` | Embedded raw matrices, frequency/time axes, timestamps, statistics, metadata and editable native plots |
| Report page | Acquisition/provenance context and interpretation limits |
| Per-trace spectral envelope | Per-bin minimum, maximum and linear-power mean |
| Per-trace waterfall | Every capture without decimation; vertical coordinate = capture index |
| Per-trace peak history | Peak level and corresponding frequency versus elapsed time |
| Last-capture overlay | All traces from the last complete capture |
| `spectral_statistics.csv` | Per-frequency minimum, linear-power mean, maximum |
| `capture_statistics.csv` | Timestamps, elapsed time and per-capture peaks |
| `report.json` | Source SHA-256, provenance, extrema, page list and renderer status |
| `report.md` | Human-readable tabular report and limitations |
| `rendered/` (optional) | Multipage PDF and PNG for each page |

The source CSV is never modified by reporting. Destinations must be new. Required output is written in a private staging directory and then renamed. Optional renderer failure preserves native/numerical output and records the failure in both reports.

## Optional Veusz rendering

Native generation needs h5py but **does not require an installed Veusz Python module**. Open/edit native files with standalone Veusz. For automated PDF/PNG, install standalone Veusz separately and set its executable if not on PATH:

```bat
set "VEUSZ_EXE=C:\Program Files\Veusz\veusz.exe"
.venv\Scripts\python -m pip install -r requirements-render.txt
```

```sh
export VEUSZ_EXE=/path/to/veusz
python -m pip install -r requirements-render.txt
```

The standalone executable may use its own bundled Python. Do not force-install Veusz 4.x into the application's Python 3.8 environment. Real rendering in this release was tested with **Veusz 4.2.1**; older Veusz versions were not revalidated.

## Numerical interpretation

- Mean levels are averaged in **linear power per frequency bin**, not arithmetic dBm. A scaled calculation avoids exponential overflow.
- Peaks cover recorded bins only. Tied maxima select the first bin/capture.
- No summed-bin value is presented as integrated channel power. Legacy CSV lacks RBW/VBW, detector response, impedance, calibration and correction metadata.
- No IEEE/ANSI/IEC/CISPR compliance or pass/fail assertion is made. This is a data report, not a qualified EMC measurement.
- Parser requires unique logger columns, finite values, strictly increasing frequency, a fixed repeated grid and strictly increasing capture timestamps. Incomplete repeated captures are rejected, not truncated.
- Contiguous timestamp groups define captures because legacy CSV lacks explicit capture identifiers. Identical timestamps cannot identify distinct captures; the expected size of a first/sole capture cannot be independently proven from CSV.
- Naive timestamps preserve local wall time; backward DST changes are refused as nonmonotonic. Aware and naive timestamps cannot be mixed.
- Single-bin/single-capture image extent uses arbitrary +/-0.5 display units, not physical bandwidth/time uncertainty.

## Resource and sampling policy

Default **512 MiB** budget limits total raw trace matrices, not total resident process memory. Disk-backed matrices and chunked reductions reduce working memory; compression, renderers, Python objects and file cache add overhead. Increase the limit only with adequate RAM/disk, or split input. Free-space preflight cannot predict worst-case rendered-image size.

VISA operations remain serial in one acquisition thread. CSV formatting/output overlaps instrument work in one ordered consumer. Queue capacity is bounded by capture count and a nominal 64 MiB array budget. On saturation, the current capture is retained in one reserved terminal slot, sampling stops explicitly and queued data drains in order. Disk failures are surfaced. Per-capture flush is not a power-loss fsync guarantee.

GUI polls a latest-frame mailbox every 100 ms and reuses curves. Only intermediate **display frames** coalesce; completed captures remain in CSV. Report processing uses QProcess and up to three per-trace tasks; backend numerical thread counts are bounded in the GUI child. This is not a hard-real-time system.

Stop waits cooperatively for the current instrument operation and configured timeout. Closing during sampling requests Stop and waits for CSV drain, then closes the instrument. Closing during report generation is refused until processing finishes. No running thread/SCPI operation/HDF5 writer is force-killed.

## Tests and rebuild

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m build
```

Set VEUSZ_EXE to include the optional real renderer test; otherwise that test skips. Fixtures are explicitly synthetic software inputs, not measurements. See `docs/VALIDATION.md` and logs. Build creates wheel/source distributions in dist/. Source attribution is retained; see NOTICE.md.
