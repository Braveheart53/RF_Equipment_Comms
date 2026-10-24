# Validation record — 2026-10-23

## Actual results

| Runtime | Platform | Result |
|---|---|---|
| CPython 3.8.20 | Linux x86-64; PyQt5 offscreen | 30 passed, including real standalone Veusz 4.2.1 rendering |
| CPython 3.12.8 | Linux x86-64; PyQt5 offscreen | 30 passed, including real standalone Veusz 4.2.1 rendering |

See captured test logs and environment inventories. Tests use explicitly synthetic fixtures and the supplied mock instrument, NOT analyzer measurements. A three-trace rendering fixture created 11 native pages, a PDF and 11 PNGs on both runtimes using the official standalone Veusz 4.2.1 executable.

Python 3.8 used its own compatible SIP extension and the same separately located Qt5 runtime as 3.12 to avoid installing duplicate Qt binary runtimes. Python packages were installed into the independent 3.8 virtual environment. This is endpoint compatibility testing, not certification of all OS/dependency combinations.

## Coverage

- Python 3.8 grammar; actual imports/execution under both endpoints.
- Atomic-write failure preserves previous target; private concurrent temporary names.
- Renderer completion-marker flushing.
- Raw data round trip, linear-power mean math, SHA-256 provenance and page names.
- Single-capture/bin and multi-trace files.
- Malformed/incomplete rows, changing grid, NaN, duplicate headers, empty input, inconsistent dates and reversed timestamps.
- Changed source, raw-matrix budget, existing directory, optional rendering failure.
- CSV order/copy ownership, bounded saturation/terminal capture and disk-error propagation.
- Latest-frame display mailbox.
- GUI admission controls and actual QProcess reports with sampling blocked.
- Stop/drain/restart; close during acquisition.
- Scheduled waiting and deliberately stalled CSV drain remain interlocked.
- Trigger/fetch calls share one instrument-owner thread.

## Not validated

- No physical FSP analyzer: no hardware sampling-rate, communication reliability or RF accuracy assertion.
- No Windows/macOS or interactive Spyder runtime test. Target-host testing remains necessary.
- No hard-real-time latency, worst-case scheduling, crash/power-loss recovery or multi-instance file locking guarantee.
- Older Veusz releases were not retested; actual renderer here is 4.2.1.
- No IEEE, ANSI, IEC or CISPR compliance assertion.

## Design references

| Ref. | Bibliographic entry | URL |
|---|---|---|
| [1] | The Qt Company, “QThread Class,” Qt documentation, accessed Oct. 23, 2026. | https://doc.qt.io/qt-6/qthread.html |
| [2] | The Qt Company, “QProcess Class,” Qt documentation, accessed Oct. 23, 2026. | https://doc.qt.io/qt-6/qprocess.html |
| [3] | Veusz contributors, “Download Veusz,” Veusz project website, accessed Oct. 23, 2026. | https://veusz.github.io/download/ |

These references describe lifecycle/process concepts; the packaged binding is PyQt5, not a Qt6 requirement.

## Built-wheel verification

The universal py3-none-any wheel was independently installed into separate target directories and the same full test suite ran against those installed module copies, not just the source tree:

| Wheel runtime | Result |
|---|---|
| CPython 3.8.20 | 30 passed, including real Veusz rendering |
| CPython 3.12.8 | 30 passed, including real Veusz rendering |

Captured logs are wheel_test_python38.txt and wheel_test_python312.txt. The universal wheel contains Python application code, not binary dependency wheels.
