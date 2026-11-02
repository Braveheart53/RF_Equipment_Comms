# Changelog — R&S FSP Logger bundle

Newest first. Versions follow Semantic Versioning 2.0.0. In 0.9.0 a new feature bumps the MINOR number.

## 0.10.0 — 2026-10-29 (finished 2026-11-02)

Modules: `rs_fsp_logger.py` 0.10.0, `fsp_batch_convert.py` 0.0.1 (new), `fsp_batch_core.py`
0.0.1 (new), `fsp_gui_theme.py` 0.0.1 (new), `fsp_reports.py` 0.1.5, `vszh5_writer.py` 0.0.21;
`fsp_background.py` 0.2.0 and `fsp_simulator.py` 0.0.1 unchanged.

### Added
- **Batch convert CSV files to Veusz plots…**, in the *File* and *Tools* menus (Ctrl+Shift+R). One
  dialog converts a single CSV, several CSVs or whole folders, optionally with sub-folders.
  Inputs come from *Add files*, *Add folder*, drag and drop, or the command line, and only logger
  CSVs are listed. Each CSV gets a new report folder from `fsp_reports.py`, either next to the
  CSV or under one folder, with the sub-folder structure optionally kept. Conversions run in
  parallel processes, with *Cancel* and *Skip CSVs that already have a report folder*. Per-file
  status, a log and *Open report folder* show the results. Optional PDF + PNG.
- The dialog is also a stand-alone program: `python fsp_batch_convert.py [files/folders]`,
  `run_batch_converter.bat`, or `--cli` for a run without a window (`--dry-run`,
  `--skip-existing`, `--render`, `--jobs`, `--flat`, `--no-recursive`). Exit codes are 0, 1 and 2.
- `fsp_gui_theme.py`: the logger's Dark / Light / System palette and style sheet, with values
  unchanged, shared with the dialog. The theme setting is stored once for both.
- `run_fsp_logger.bat`, which activates the mamba environment `fsp-logger` when present.
- Tests: `tests/test_batch_convert.py` (24 tests); 68 in all.

### Changed
- `vszh5_writer.py` 0.0.18 → **0.0.21**, the one writer of all projects, byte-identical to SHR
  Converter 0.0.2. The 0.0.18 render fixes are kept.
- Interlocks: sampling cannot start while a batch converts, and a batch cannot start while the
  logger samples, waits or drains. Closing the logger waits for a running batch.
- `fsp_reports.py` 0.1.5: header only (writer 0.0.21, batch use).
- 0.9.0 evidence moved to `docs/history_0.9.0/`.

### Fixed during development (not in any release)
- PySide6 garbage-collected a chained temporary menu wrapper in a test, which only affected the
  test.
- In `--cli`, Ctrl+C waited for running conversions to finish. It now kills them at once and
  removes their staging folders.

## 0.9.0 — 2026-10-26

Modules: `rs_fsp_logger.py` 0.9.0, `fsp_background.py` 0.2.0, `fsp_reports.py` 0.1.4,
`vszh5_writer.py` 0.0.18, `fsp_simulator.py` 0.0.1 (new).

### Added
- **Reset Active Traces** (button, F7, Acquisition/Tools menus, toolbar). Every displayed
  trace of the screen in use goes to Clear/Write and back to its own mode. View traces are
  re-frozen after one fresh sweep; Blank traces are untouched. Idle, it runs on its own worker
  thread. While recording, the acquisition worker runs it between captures. The prompt can be
  turned off (Tools > Confirm before trace reset).
- `<csv stem>_events.csv`: one row per trace for each reset made during a run
  (`fsp_background.CaptureEventLog`).
- `fsp_simulator.py`: a simulated two-screen FSP SCPI session. Demo Mode now runs the real
  `FSPInstrument` over it.
- *In use: Screen X (auto/forced)* label, LED tooltips with each trace's mode, LEDs filled at
  connect, a two-screen Diagnostics table, and About module versions read from the sources.
- Tests: `tests/test_screen_and_reset.py` (22 tests) and `tests/test_writer_render.py` (5 tests); 44 in all with the 0.8.3 suite.

### Fixed
- Auto / A / B had to be toggled before the right traces were read. There were four causes:
  trace modes came from Screen A, the selection was not applied at connect, Auto detected
  only once, and trace fetches fell back across screens. See `docs/DEFECT_ANALYSIS_0.9.0.md`.
- `fsp_reports.py`: the logger version was hard-coded as "0.8.3" in `report.json` and the
  generator line.
- `vszh5_writer.py` 0.0.18: `png_pages="first"` produced no PNG on Veusz 4.2.1. A dotted
  stem lost the end of the PDF name. A load or Export error inside `veusz --listen` was
  reported as success with no files. The revision history had a duplicate 0.0.17 block.
- The toolbar overflowed once the reset action was added; it now uses the short text
  "Reset active traces", and the full explanation is in the tooltip.

### Changed
- Demo Mode uses the simulator instead of `MockFSPInstrument`, which is kept for scripts.
- The unused helpers `_query_trace_state()` and `_is_displayed()`, which held the suffix-less
  queries, were removed.
- The 0.8.3 merge evidence moved to `docs/history_0.8.3/`.

## 0.8.3 — 2026-10-23

All-bin Freq_N_GHz and Combined_Freq_vs_Time native datetime plots; every prior plot
retained. Full text menu/toolbar, dark/light/system themes, persistent preference and
author/About information. Writer 0.0.17 (linear-power mean), reports 0.1.3, background
0.1.2. Evidence: `docs/history_0.8.3/`.

## 0.8.2

Frequency-versus-time pages (writer 0.0.16, reports 0.1.2).

## 0.8.1

Isolated reporting, bounded async CSV, coalesced live display, serial VISA ownership,
cooperative stop/drain/close and reciprocal interlocks.
