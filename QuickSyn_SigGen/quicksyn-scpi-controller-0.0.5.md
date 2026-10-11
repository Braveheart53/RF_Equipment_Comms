# QuickSyn SCPI Controller and Logger — version 0.0.5

**Date:** 2026-10-11 · **Target:** Python 3.12, Qt.py → PySide6 · **Status:** verified against documentation, a built-in simulator and real Veusz 3.6.2 / 4.2.1 (and patched 4.2.1) on Python 3.12.3 and 3.13.16; **not yet run against hardware**

| | |
| --- | --- |
| Author | William W. Wallace · NRAO/GBO · wwallace@nrao.edu |
| Licence | GPL-3.0-or-later (SPDX), full text in `LICENSE`; no associated project |
| Versioning | Semantic Versioning 2.0.0 [15]; supersedes 0.0.4 |
| Archive | `quicksyn_scpi_controller_v0.0.5.7z` (13 files; SHA-256 `93d1c95b70d9125d1bab9e0305ff9723226964decacd9241bdac015a83ff0697`) |
| Reusable module | `claude/vszh5_writer.py` 0.0.5 in this project (SHA-256 `2cdf43d2…ae33c1c`); export script `claude/quicksyn_veusz_export_v0_0_5.py` |
| Companion release | `isp_speed_monitor_v1.7.2.7z` (script 1.3.1, `render_in_veusz.sh` 1.0.2; SHA-256 `959be0a2494d89d5a834ca18cf53ab7aef40a8a146f3fb66fb400435215c6ba9`) — commercial AdaptEd product, fixed directly, no GPL code imported |

## What changed in 0.0.5

| Item | Detail |
| --- | --- |
| **Live SCPI console** | View ▸ SCPI console (Ctrl+Shift+C), docked under the tabs: `HH:MM:SS.mmm`, source `GUI`/`POLL`, `→` command, `←` reply with latency, `✖` error; colours legible in light and dark themes; telemetry polls hidden by default; filter, pause/resume, auto-scroll, copy, save, clear. Queued signal from the sampler thread, 150 ms batched rendering, caps 5000 lines / 20 000 exchanges (≈ 5 MB measured). `transactions.csv` stays the full record |
| Render: Windows paths | PNG path bound on its own line outside the `exec()` string (0.0.4 unescaped it twice: `C:\Users…` failed, `\n` became a newline, a quote broke the string) |
| Render: fallback | `method="auto"` falls back to the Veusz Python package when the program **fails**, not only when missing; both errors reported if both fail |
| Render: robustness | A program that exits before reading its script (broken pipe, a race) or cannot be started → `RuntimeError`, not `BrokenPipeError`/`OSError`; stdout pipe closed; Veusz never left running after an error |
| Upstream Veusz patch | `upstream/veusz-4.2.1-vszh5-load-listen-quit.patch` + `upstream/VEUSZ_UPSTREAM_ISSUE.md` in the archive (see below) |
| Docs | README §5.4 (console), §6.2/§6.5 (fixes, patch), §10 rows, §11 history; licence open item closed; history entries ascending in every file |

## Findings from 0.0.4 — status

| # | Finding | Status |
| --- | --- | --- |
| 1 | `veusz --export file.vszh5` and embedded `Load()` cannot open `.vszh5` (`CommandInterpreter.Load()` reads every file as UTF-8 text) | **Fixed upstream-style**: patch makes `Load()` detect the HDF5 signature (offset 0, 512, 1024, …) and call `Document.load(mode='hdf5')`. Patched 4.2.1: PNG and 2-page PDF from the command line, embedded Load+Export OK, text `.vsz` unchanged; unpatched: segfault (139) / `IndexError`. Same code still on `master` 2026-10-11 [22]. Not yet submitted |
| 2 | Veusz 4.2.1 does not exit on `Quit()` in `--listen --quiet` (`quitProgram()` only closes a never-shown window) | **Fixed upstream-style**: patch adds `QCoreApplication.instance().quit()`; exits in 0.46 s (unpatched: still running after 30 s). Packages keep the marker + terminate workaround for released Veusz |
| 3 | `isp_speed_monitor.py` 1.3.0: render menu used invalid `--export … --export-dpi … %PAGE%`; `render_in_veusz.sh` relied on `timeout 180`; `vz_text` turned `\` into a line break, left `[ ]` | **Fixed in ISP 1.3.1 / bundle 1.7.2**: `render_vszh5_pages()` (listen + `loadHDF5Doc`, marker, paths outside `exec`), `--render-veusz FILE [--outdir]`, `vz_text` = Veusz `latexEscape`, script 1.0.2 uses an end marker. Also fixed a docstring `\b` (backspace) escape in its own history text |
| 4 | Ubuntu `/usr/bin/veusz` starts `/usr/bin/python3`; fails (`No module named 'PyQt5.sip'`) where that is not the packaged Python | **Handled**: QuickSyn `auto` falls back in-process; ISP reports Veusz's own error + `veusz --version` / env-var hint |

## Scope and hard constraints

Full SCPI control of the NI / Phase Matrix QuickSyn family over the USB virtual COM port, plus a timestamped log of every command generated and a telemetry stream at a user-set sample rate. All of [1, Table 5] is implemented.

- **115200 8N1, no flow control, CR (0x0D) terminator, 64-byte device buffer including the terminator** — fixed on USB. `DIAG:BAUD` retargets the debug port, **not** USB.
- **SCPI needs firmware ≥ 100**; SPI is native-only.
- Only `*IDN?`, `*RST`, `*SAV`, `*RCL` of IEEE 488.2 exist — **no error queue, no `*OPC`/`*ESR?`**; acceptance is confirmed by read-back.
- Mandatory delays applied automatically: 2 ms reset, 100 ms `*SAV`, 50 ms `*RCL`, 200 ms `LIST:ERAS`, 300 ms flash list point, 100 µs RAM point, 50 ms + 2.5 ms/pt `LIST:SAV`, seconds for the reference DAC, 1 ms `FREQ` with FM on.
- Lists and sweeps refused while FM is on; dwell quantised to 5 µs; power to 0.1 dB.

**Millihertz overflows the buffer in compound commands** (69 B for a 20 GHz `SWE:FAST:FREQ:SETUP`). `format_frequency()` picks the shortest exact spelling among mlHz/KHz/MHz/GHz; `_check_compound_length()` refuses anything that still will not fit.

## Veusz output (unchanged since 0.0.4)

`.vszh5` written directly with h5py by `vszh5_writer.py` (author's method from `isp_speed_monitor.py` 1.3.0 [21]); no text `.vsz` (7 significant digits: $q = 10^{k-6}$ GHz, $|\varepsilon| \le q/2$ → ≤ 500 Hz below 10 GHz, ≤ 5 kHz above). Tagged `raw/`, `events/`, `stability/`, `meta/`; overview + 6 pages; commanded values overlaid. The controller writes it at stop, on demand (Ctrl+E) and every N min; separate process. Render via `--listen` + `loadHDF5Doc`, Python-package fallback.

## Documentation conflicts and resolutions

| Conflict | Resolution |
| --- | --- |
| Post-reset blanking `ON` [1] vs `off` [2] | Never assumed; `STAT?` read after every reset |
| SCPI `*IDN?` field order undefined | All five raw fields shown; firmware gate advisory |
| Query double-issue unstated for SCPI | `TEMPERATURE_DOUBLE_QUERY = True`, recorded |
| Response terminator unspecified | Reader accepts CR / LF / CRLF |
| 0.01 dB [4] vs tenth-dBm [1] | Quantised to 0.1 dB |
| Missing comma in `SWE:FAST:FREQ:SETUP` example | Eight fields + optional `RUN` |
| "Start NF Sweep" typo | Treated as `...FREQ:STAR 1` |
| 32767 vs "32,000" list points | 32767 for range checks |
| `DIAG:BAUD` vs USB | Debug port only |
| mlHz default vs GHz examples | Shortest exact spelling, pre-flighted |

## Verification (0.0.5)

| Check | Result |
| --- | --- |
| `run_all.py` (release 102/102, smoke incl. console and GUI `.vszh5` export, reduction, `check_vszh5`) | PASS on 3.12.3 and 3.13.16, also from the extracted archive |
| `check_vszh5.py` with real Veusz | 41/41 with 4.2.1, patched 4.2.1 and 3.6.2 (new: Windows-style path with quote via stub `Export`, broken program `program`/`auto`, cannot-start, render into `odd \dir 'q'`) |
| New path test vs 0.0.4 writer | fails on 0.0.4 (`SyntaxError`) — confirms the regression test |
| SCPI console | 93–106 exchanges, 76–89 polls hidden by default, filter, pause/resume, `✖` error line, save; screenshots light/dark inspected |
| ISP 1.3.1 | `-W error` compile clean; `--selftest` OK; `gui_smoke.py` 9 shots; `--render-veusz` 7 PNGs with 4.2.1; quick-exit, non-executable and missing Veusz → clear error, exit 1; `render_in_veusz.sh` 7 PNGs with 4.2.1 (3.3 s), patched 4.2.1 (1.3 s), 3.6.2 (1.3 s), broken exe exit 1 |
| Patch | `patch -p1 --dry-run` clean on 4.2.1 sdist |
| Archives | 7-Zip 16.02 `t` OK; extraction identical to sources; ISP file list identical to 1.7.1 |

**Unverified:** Windows render (does the windowed `veusz.exe` read a piped script in `--listen` mode? fallback covers it); a real `mamba env create`; anything needing the instrument.

## Open items

1. Copyright holder / NRAO release approval (files name William W. Wallace).
2. NRAO/GBO header template, if one is mandated.
3. First hardware session: capture `transactions.csv` (and the console text) and the `*IDN?` line.
4. Windows: create env, log a short session, Veusz ▸ *Write .vszh5 and render*; try `--render-method program` to see whether the program path itself works.
5. File the Veusz issue + patch at [22] (needs a GitHub account).
6. ISP (not changed): Download panel legend overlaps data.

**Closed:** licence of the `isp_speed_monitor.py`-derived code — the author owns Adaptive Electrodynamics LLC dba AdaptEd; README §13 updated in 0.0.5.

## References

| # | Reference | URL |
| --- | --- | --- |
| [1] | National Instruments, "QuickSyn Microwave Synthesizers: Communications Specifications," Doc. No. 5580510-01, 2014. | Project upload |
| [2] | National Instruments, "QuickSyn Microwave Frequency Synthesizer: User Guide," Doc. No. 5580513-01, Rev. F. | Project upload |
| [3] | National Instruments, "QuickSyn … Calibration Software User's Manual," Doc. No. 5580515-01, Rev. B, 2014. | Project upload |
| [4] | National Instruments, "QuickSyn Frequency Synthesizers," brochure and datasheet, Oct. 2017. | Project upload |
| [5] | National Instruments, "Clearing QuickSyn Memory," application note. | Project upload |
| [6] | IEEE Std 488.2-1992, *IEEE Standard Codes, Formats, Protocols, and Common Commands…*, IEEE, 1992. | https://ieeexplore.ieee.org/document/8705775 |
| [7] | IEC 60488-2:2004 / IEEE 488.2, *Standard digital interface for programmable instrumentation — Part 2*, IEC, 2004. | https://www.vde-verlag.de/iec-normen/preview-pdf/info_iec60488-2%7Bed1.0%7Den.pdf |
| [8] | SCPI Consortium, *SCPI Volume 1: Syntax and Style*, Version 1999.0, May 1999. | https://www.ivifoundation.org/downloads/SCPI/scpi-99.pdf |
| [9] | IEEE Std 1139-2008, *IEEE Standard Definitions of Physical Quantities for Fundamental Frequency and Time Metrology*, IEEE, 2008. | https://ieeexplore.ieee.org/document/4797525 |
| [10] | IVI Foundation, "Specification Downloads." | https://www.ivifoundation.org/specifications/default.html |
| [11] | Veusz Developers, "Veusz — a scientific plotting package." | https://veusz.github.io/ |
| [12] | Phase Matrix, Inc., 20 GHz QuickSyn press release, IEEE MTT-S IMS 2010, May 2010. | https://www.rfcafe.com/miscellany/press-releases/2010/phase-matrix-5-20-2010.htm |
| [13] | Free Software Foundation, "GNU General Public License, version 3," 29 Jun. 2007. | https://www.gnu.org/licenses/gpl-3.0.html |
| [14] | SPDX Workgroup, "GPL-3.0-or-later," SPDX License List. | https://spdx.org/licenses/GPL-3.0-or-later.html |
| [15] | T. Preston-Werner, "Semantic Versioning 2.0.0." | https://semver.org/spec/v2.0.0.html |
| [16] | Python Software Foundation, "What's New In Python 3.13." | https://docs.python.org/3/whatsnew/3.13.html |
| [17] | Anaconda, Inc., conda-forge pages for `qt.py`, `veusz`, `h5py`. | https://anaconda.org/conda-forge/veusz |
| [18] | Veusz Developers, "Veusz 4.2.1" source, PyPI. | https://pypi.org/project/veusz/4.2.1/ |
| [19] | A. Collette *et al.*, "h5py 3.16.0," PyPI. | https://pypi.org/project/h5py/ |
| [20] | `7zip-bin` npm package (p7zip 16.02). | https://www.npmjs.com/package/7zip-bin |
| [21] | W. W. Wallace, *isp_speed_monitor.py* 1.3.0, Adaptive Electrodynamics LLC dba AdaptEd, Oct. 2026. | Supplied by the author (not public) |
| [22] | Veusz Developers, "veusz/veusz," GitHub repository (`master`: `document/commandinterpreter.py`, `veusz_listen.py`) and issue tracker, accessed 11 Oct. 2026. | https://github.com/veusz/veusz ; https://github.com/veusz/veusz/issues |
