---
title: vszh5_writer 0.0.21 - one writer for every program
author: William W. Wallace (NRAO/GBO)
date: 2026-10-28
version: 0.0.21
licence: GPL-3.0-or-later
---

# vszh5_writer 0.0.21

0.0.21 is 0.0.20 with one fix in `regularize_rows()`, the spectrogram helper added in 0.0.20. Use it in place of every copy of `vszh5_writer.py`, exactly as planned for 0.0.20:
- the R&S FSP logger
- the AB Power Meter Monitor
- SA Time Stability Tools
- the QuickSyn package
- EMF Envelope FFT
- the RFI evaluator
- the SHR Converter

**No call changes.** Every public name, parameter, position and default of 0.0.5, 0.0.10, both 0.0.18 copies, 0.0.19 and 0.0.20 is unchanged.

## What changed in 0.0.21

| Item | Before (0.0.20) | Now (0.0.21) |
|---|---|---|
| `regularize_rows()` grid step | Median interval, "refined" over the span | **Mean of the ordinary intervals**. An interval longer than (1 + 2 × `tolerance`) median intervals is a gap and gets rint(gap / step) slots. |
| Effect on a real SM200C recording (sweep intervals 32–35 ms, median 33 ms, mean 33.35 ms) | A false blank (NaN) row about every 47 sweeps: white lines across the spectrogram | No blank rows. A real pause still gives the right number of blank rows (2 s pause: 60 rows). |
| `tolerance` parameter | Distance from the grid that counted as "regular" | Gap threshold (default 0.25 → 1.5 median intervals) |
| Return values, `"regular"` / `"gaps"` / `"even"` | — | Same meaning. Rows that are not strictly increasing still give `"even"`. |

Why it matters: Spike stores whole-millisecond time stamps of the PC clock, so real sweep intervals jitter by a few ms. The median of such intervals is biased, and slots taken from it drift away from the rows until one slot stays empty. The synthetic 0.0.20 tests used exact intervals and did not show this; the regression test `test_jittered_millisecond_stamps_have_no_false_gaps` now uses the SM200C pattern.

## Drop-in results with 0.0.21 (each program's own tests)

No program other than the SHR Converter calls `regularize_rows()` (grep: 0 callers in each). Logs: `docs/validation/writer_compatibility_0.0.21/`.

| Program | Suite | Result with 0.0.21 | Note |
|---|---|---|---|
| R&S FSP logger 0.9.0 | `pytest tests` (44), PySide6, Veusz 4.2.1 | **44/44** | Its About-dialog test names the writer version: set `"0.0.21"` in `tests/test_screen_and_reset.py` (`test_about_versions_read_from_modules`) |
| AB Power Meter Monitor 1.7.0 | 8 suites | **45 PASS, 0 FAIL** | The monitor's own check (`>= 0.0.18` and `VeuszAppender`) accepts 0.0.21 |
| SA Time Stability Tools 0.0.3 | `run_all.py`; `validate_vszh5_in_veusz.py` | **7/7**; **22/22** (Veusz 4.2.1) | None |
| QuickSyn package 0.0.10 | `tests/run_all.py` | **44 pass**; 3 version-pinned checks fail | The same three as with 0.0.19 and 0.0.20: `check_release_metadata.py` expects the writer to say 0.0.10 (header and `__version__`), and `check_vszh5.py` looks for the literal temporary name `unit.vszh5.part` (private `unit.vszh5.<random>.part` names since 0.0.15). Update those literals when moving QuickSyn to 0.0.21. |
| EMF Envelope FFT 0.0.4, RFI evaluator 0.0.5 | not in the repositories | API check only | They use the 0.0.13/0.0.14 API, all of which 0.0.21 contains unchanged |

### One-line patch for the FSP logger test

```diff
--- tests/test_screen_and_reset.py
+++ tests/test_screen_and_reset.py
-        self.assertEqual(L.MainWindow.sibling_module_version("vszh5_writer.py"), "0.0.18")
+        self.assertEqual(L.MainWindow.sibling_module_version("vszh5_writer.py"), "0.0.21")
```

(If you already changed it to `"0.0.20"`, change that to `"0.0.21"`.)

## What 0.0.20 brought (still in 0.0.21)

0.0.20 replaced the two releases that were both numbered 0.0.18, together with 0.0.19:

| Release | Built from | Contained | Missing |
|---|---|---|---|
| 0.0.18 in **FSP logger 0.9.0** | 0.0.17 | 3 render fixes, repaired history | VeuszAppender |
| 0.0.18 in **AB Monitor 1.6.0** | 0.0.17 | VeuszAppender, `resizable=True` | the 3 render fixes |
| 0.0.19 in **AB Monitor 1.6.2 to 1.7.0** | AB 0.0.18 | "Traceback, no pages" = failed render | the 3 render fixes |
| **0.0.20 / 0.0.21** | both | everything above, plus the additions below | nothing |

| Item | Origin | Effect |
|---|---|---|
| PNG of the first page no longer silently missing | 0.0.18 FSP | The `--listen` bound is `(1 if names else 0)`, not `min(1, n)`, which Veusz 4.2.1 turned into `numpy.min` |
| PDF name keeps every dot | 0.0.18 FSP | `run v0.0.2.vszh5` gives `run v0.0.2.pdf` |
| A render that wrote nothing is an error | 0.0.18 FSP | A requested PDF/PNG that is missing raises `RuntimeError` |
| No page loaded = failed render | 0.0.19, widened | Fails with or without a Traceback; then falls back to the veusz package |
| `VeuszAppender`, `AppendLockedError`, `VeuszWriter(resizable=True)` | 0.0.18 AB | Unchanged |
| Published files no longer mode 0600 (Linux/macOS) | 0.0.20 | Mode of the replaced file, or 0666 minus the umask |
| `render_pages(png_background="white")` | 0.0.20 | Opaque PNGs |
| `image_page(xmode=, ymode=, datetime_format=, left_margin=)`, `xy_page(datetime_format=)` | 0.0.20 | Date/time axes |
| `block_reduce()` | 0.0.20 | Peak-hold / min / mean / power-mean decimation, NumPy or CuPy |
| `regularize_rows()` | 0.0.20, fixed in 0.0.21 | Uneven image rows onto an even grid (Veusz's fast path), pauses as blank rows |

## Notes for every caller

* `render_pages()` **raises** when Veusz wrote nothing (0.0.19 returned an empty list).
* For spectrograms, give `dataset_2d` even axes. For time axes with jitter or pauses, call `regularize_rows()` first; with 0.0.21 that is safe for real, jittered time stamps.
* GitHub: nothing was pushed. The repositories were only read.
