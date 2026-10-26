# Changelog — R&S FSP Logger bundle

Newest first. Versions follow Semantic Versioning 2.0.0. In 0.9.0 a new feature bumps the MINOR number.

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
