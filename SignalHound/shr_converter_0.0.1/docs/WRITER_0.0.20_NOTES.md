---
title: vszh5_writer 0.0.20 - one writer for every program
author: William W. Wallace (NRAO/GBO)
date: 2026-10-28
version: 0.0.20
licence: GPL-3.0-or-later
---

# vszh5_writer 0.0.20

0.0.20 replaces every copy of `vszh5_writer.py`: the R&S FSP logger, the AB Power Meter Monitor, SA Time Stability Tools, the QuickSyn package, EMF Envelope FFT, the RFI evaluator and the SHR Converter. Copy the file over the old one. **No call changes**: every public name, parameter, position and default of 0.0.5, 0.0.10, both 0.0.18 copies and 0.0.19 is unchanged. This was checked by machine (signature comparison) and by each program's own test suite.

## Why it was needed: two writers both numbered 0.0.18

| Release | Built from | Contained | Missing |
|---|---|---|---|
| 0.0.18 in **FSP logger 0.9.0** (RF_Equipment_Comms) | 0.0.17 | 3 render fixes, repaired history | VeuszAppender |
| 0.0.18 in **AB Monitor 1.6.0** (GBO_Maser_Control) | 0.0.17 | VeuszAppender, `resizable=True` | the 3 render fixes |
| 0.0.19 in **AB Monitor 1.6.2 to 1.7.0** | AB 0.0.18 | "Traceback, no pages" = failed render | the 3 render fixes |
| **0.0.20** (this) | both | everything above, plus the fixes and additions below | nothing |

## What 0.0.20 contains

| Item | Origin | Effect |
|---|---|---|
| PNG of the first page no longer silently missing | 0.0.18 FSP | Veusz 4.2.1 runs listen scripts with NumPy's names imported, so `min(1, n)` became `numpy.min` and raised `AxisError`. The bound is now `(1 if names else 0)` |
| PDF name keeps every dot | 0.0.18 FSP | `run v0.0.2.vszh5` now gives `run v0.0.2.pdf`, not `run v0.0.pdf` |
| A render that wrote nothing is an error | 0.0.18 FSP | A requested PDF/PNG that is missing raises `RuntimeError` instead of returning `[]` |
| No page loaded = failed render | 0.0.19, widened | Fails whether or not Veusz printed a Traceback; then falls back to the veusz package (`method="auto"`) |
| `VeuszAppender`, `AppendLockedError`, `VeuszWriter(resizable=True)` | 0.0.18 AB | Unchanged |
| Spyder `# %%` markers of the 0.0.16 and 0.0.17 sections | 0.0.18 FSP | Each marker sits above its own code again |
| **FIX: published files were mode 0600** (Linux/macOS) | new | Since 0.0.15 the private `mkstemp` temporary file gave every `.vszh5` owner-only permissions. Files now keep the mode of the file they replace, or get 0666 minus the umask. Matters on the RHEL 9 host; no effect on Windows |
| `render_pages(png_background="white")` | new | Opaque PNGs; the default `""` keeps Veusz's transparent background |
| `image_page(xmode=, ymode=, datetime_format=, left_margin=)` | new | Date/time image axes (spectrogram with UTC on y) |
| `xy_page(datetime_format=)` | new | Tick format of a date x axis in one call |
| `block_reduce()` | new | Peak-hold / min / mean / power-mean decimation of 2-D arrays; NumPy or CuPy |
| `regularize_rows()` | new | Uneven image rows onto an even grid, with pauses as NaN rows. Veusz renders uneven axes through a slow path: on a 3-hour spectrogram, 30 s and 3.2 GB versus 2.7 s and 0.31 GB |
| Revision history | | One entry per version, newest first; both 0.0.18 releases described under one 0.0.18 entry |

## Drop-in results (each program's own tests, unchanged except where noted)

| Program | Suite | Result with 0.0.20 | Note |
|---|---|---|---|
| R&S FSP logger 0.9.0 | `pytest tests` (44), PyQt5 and PySide6, each with Veusz 3.6.2 and 4.2.1 | **44/44** in all four | Its About-dialog test expects the writer version string: change `"0.0.18"` to `"0.0.20"` in `tests/test_screen_and_reset.py` (`test_about_versions_read_from_modules`) |
| AB Power Meter Monitor 1.7.0 | 8 suites (appender, offline, memory release, file locks, exporter, Grafana, IP separation, live plots) | **45/45**, real renders in Veusz 4.2.1 and 3.6.2 | The monitor's own check (`>= 0.0.18` and `VeuszAppender`) accepts 0.0.20 |
| SA Time Stability Tools 0.0.3 | `run_all.py` (7 scripts); `validate_vszh5_in_veusz.py` | **7/7**; **22/22** (Veusz 4.2.1) | None |
| QuickSyn package 0.0.10 | `tests/run_all.py` | **44 pass**; 3 version-pinned checks fail | Those three fail the **same way with 0.0.19**. `check_release_metadata.py` expects the writer to say 0.0.10. `check_vszh5.py` looks for the literal temporary name `unit.vszh5.part`, but the writer has used private `unit.vszh5.<random>.part` names since 0.0.15 (so concurrent writers cannot delete each other's files). Update those literals when moving QuickSyn to 0.0.20 |
| EMF Envelope FFT 0.0.4, RFI evaluator 0.0.5 | not in the repositories | API check only | They use the 0.0.13/0.0.14 API, all of which 0.0.20 contains unchanged |

The logs are in `docs/validation/writer_compatibility/`, run against the writer whose SHA-256 is listed in `writer_sha256.txt`. After those runs only the 0.0.20 history text changed, recording these results.

### Two-line patch for the FSP logger test

```diff
--- tests/test_screen_and_reset.py
+++ tests/test_screen_and_reset.py
-        self.assertEqual(L.MainWindow.sibling_module_version("vszh5_writer.py"), "0.0.18")
+        self.assertEqual(L.MainWindow.sibling_module_version("vszh5_writer.py"), "0.0.20")
```

In the FSP logger's own files, update the "Companions … vszh5_writer 0.0.18" header line and the `fsp_reports.py` "Native writer: 0.0.18" docstring at your next version bump. Neither affects behaviour.

## Notes for every caller

* `render_pages()` now **raises** when Veusz wrote nothing. 0.0.19 returned an empty list in that case. Callers that wrap it in `try/except RuntimeError` (the FSP logger, the SHR Converter) report the reason. The AB monitor itself does not call it.
* For spectrograms, give `dataset_2d` even axes. Use `xrange`/`yrange`, or edges/centres that are even; for time axes with jitter or pauses, call `regularize_rows()` first.
* GitHub: nothing was pushed. Both repositories were only read (cloned with `--depth 1`).
