# Changelog (newest first)

## SHR Converter 0.0.2 — 2026-10-28

| File | Version |
|---|---|
| shr_converter.py | 0.0.2 |
| shr_converter_gui.py | 0.0.2 |
| shr_converter_core.py | 0.0.2 |
| shr_reader.py | 0.0.1 (new) |
| vszh5_writer.py | 0.0.21 |

* **New reader, `shr_reader.py` 0.0.1** (NumPy only, built from Signal Hound's SDK `shr_parse.h`). It replaces py-shr-parser 1.0.0, which raised `ValueError: 2 is not a valid ShrVideoDetector` on an SM200C recording from Spike 4.0, so Inspect and Convert failed.
  * Enumerations: raw codes with labels and confidence ("Max (code 2, inferred)"); unknown codes become notes.
  * Validation and salvage: header count 0, cut-short files, trailing bytes, `dataOffset` > 472, file versions 1 and > 2.
  * Reading: memory-mapped block reads; `ShrFileSet` and `group_recordings()` for multi-file recordings; `write_shr()`; command line; 39-check self-test.
* Engine:
  * One vectorised read per block.
  * Multi-file recordings joined as one (`join_files`, `--join`).
  * CSV time decimation (`csv_decimate`, `--csv-decimate`, `--csv-decimate-detector`: max | power_mean | min) in every layout. Only the main CSV is decimated.
  * Detector on the statistics and header pages.
  * Notes: amplitudes on the 0.01 dB grid of the SM min/max path; time stamps going backwards; gaps between joined files.
  * Display: frequency axes switch to GHz before Veusz prints scientific tick labels; long file names are shortened in page titles; long header-page lines wrap.
  * `_header.csv` lists the files of a joined recording, the decimation and the reader version.
  * Command line: `--join` with `--info` shows the grouping; exit code 0 when no recording failed.
  * Self-test 55 checks (was 38).
* GUI: CSV "Combine N sweeps per row" with its detector; Selection "Join the files of one recording"; reader version in the log and About; every file of a joined recording gets its status; smoke test 12 checks (was 11).
* Launcher: `--reader` (shr_reader's command line); `--selftest` also runs the reader's self-test.
* **vszh5_writer 0.0.21**: `regularize_rows()` takes the grid step from the mean of the ordinary intervals and gives gaps rint(gap/step) slots. Real Spike time stamps (whole ms, 32–35 ms intervals on the SM200C) made 0.0.20 leave a false blank row every ~47 sweeps. Nothing else changed; drop-in results in `docs/WRITER_0.0.21_NOTES.md`.
* Tests:
  * Reader self-test in pytest.
  * SM200C file shipped in `tests/data`.
  * py-shr-parser only as an optional cross-check.
  * Writer jitter regression test.
  * `long_capture_check.py` with millisecond jitter and a false-gap check.
  * New `sm200c_rate_check.py`: a multi-file recording at the SM200C rate.
* Docs: README, manual v0.0.2, writer notes, Signal Hound support letter (draft), design brief.
* `requirements.txt` no longer lists py-shr-parser.

## SHR Converter 0.0.1 — 2026-10-28 (first internal draft)

| File | Version |
|---|---|
| shr_converter.py | 0.0.1 |
| shr_converter_gui.py | 0.0.1 |
| shr_converter_core.py | 0.0.1 |
| vszh5_writer.py | 0.0.20 |

* New: Qt.py/PySide6 GUI. It has menus, toolbar, light/dark/system themes, a preview (spectrogram, statistics, level versus time), Inspect without writing, batch conversion with Stop, Veusz open/render, saved settings, About, shortcuts, drag and drop, and a memory read-out with Free memory.
* New: engine on py-shr-parser 1.0.0.
  * Reading: robust opening of recordings that were cut short.
  * CSV: three layouts (lossless or fixed decimals), split by time, a disk-space check, and companion header, sweep and statistics tables.
  * Processing: streamed statistics (power mean in linear power), a peak-hold / min / power-mean spectrogram on an even time grid, and `.vszh5` pages with an optional bookmarked PDF and PNGs.
  * Selection and scale: sweep and frequency sub-ranges, parallel spawn workers, a RAM budget, a disk-mapped per-sweep table, and thinned series for multi-hour captures.
  * GPU and safety: optional CuPy with per-block CPU fallback, and a time-stamped name for a CSV locked by Excel.
  * Also: command line and a 38-check self-test.
* vszh5_writer 0.0.20 merges the two releases both numbered 0.0.18 (FSP logger 0.9.0 render fixes; AB Monitor 1.6.0 appender) with 0.0.19. It fixes the 0600 file mode of published documents and adds `image_page` date axes, `xy_page(datetime_format=)`, `render_pages(png_background=)`, `block_reduce()` and `regularize_rows()`.
