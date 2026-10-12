# Changelog — SA Time Stability Tools / Time Stability App

All notable changes to this package. Versions follow
[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html); `0.0.x` are
internal drafts. Every Python file carries its version in its header and in
`__version__`.

## 0.0.3 — 2026-10-11

Pass 2 of 2: every defect found in the 0.0.2 review fixed, analysis
parallelised, GUI moved to Qt.py with menus and a light/dark display, all
references re-checked. `vszh5_writer.py` stays 0.0.5 (byte-identical to
QuickSyn's copy); its issues are worked around in `veusz_export.py` and listed
in the README for the next writer release.

### Fixed (0.0.2 known issues 1–13)
1. `freq_hz`/`frac_freq` CSVs loaded with `len(x) = len(t) + 1` → time tags
   extended by one interval (`stability_core.load_canonical_series()`).
2. Loading new data kept the previous drift fit and results → cleared on
   load; results of a job that finishes after new data arrive are discarded.
3. GUI logged "converting to phase" on every load → logs the column read;
   `f0` is filled from `freq_hz` data. README wording corrected.
4. Decimal-comma exports (`;`/tab/white space) read as "no numeric data" →
   delimiter chosen from the data lines, decimal commas read.
5. Canonical CSV kept 11 significant digits → shortest exact decimal.
6. Stable32 writer left a partial file on a rejected last-point gap →
   validation before writing, atomic `.part` + rename, basename in header.
7. `NOISE_TABLE` "Linear Freq. Drift" (+1.5) → "Random Run FM"; linear drift
   (ADEV slope +1) detected with the OHDEV slope (`LINEAR_DRIFT_LABEL`).
8. Drift rate logged "s/s^2" → `D = 2 a2` in 1/s; drift fit on a scaled axis
   (`Polynomial.fit`), same result as `np.polyfit`.
9. Single-threaded, on the GUI thread → see *Performance* below.
10. References corrected (see below).
11. Validation scripts always exited 0 → PASS/FAIL exit status everywhere.
12. `PySide6~=6.6.3` pin (no Python 3.13 wheels) → version-gated pins.
13. GUI on PySide6 directly, no menus, no light/dark → Qt.py, menu bar,
    View › Light/Dark display (Fusion palette + plot colours, remembered).

### Performance and parallelism
- Thêo1 kernel on array views with two reused buffers (BLAS capped to one
  thread): 4.5–5.5× faster per core than 0.0.2 at N = 100 000 (identical
  results to rounding).
- ThêoH: all Thêo1 values (bias ladder + grid) in one batch, largest first;
  spawn process pool ≥ 100 000 points, thread pool ≥ 50 000, serial below
  (threads measured slower on short records); `theo1_batch()`.
- BLAS capped to one thread inside the pools (threadpoolctl, reference
  counted); BLAS-free einsum kernel when threadpoolctl is absent.
- Optional CuPy GPU path for the Thêo1 sums (not run here: no GPU).
- Workers capped at the CPUs available; `available_cpus()`,
  `set_default_workers()`, `gpu_available()`.
- Spawned workers do not re-run the parent's `__main__` (cell-style scripts,
  Spyder consoles, the GUI): `__file__`/`__spec__` hidden while a pool starts;
  a lock makes concurrent pool starts (GUI threads) take turns.
- GUI analyses on a worker thread with Qt signals; Run All; Threads and GPU
  controls.
- Welch FFT on `scipy.fft` worker threads; batch snapshot parsing in a
  process pool.
- ThêoH N = 100 000 on the 2-vCPU test VM: 218.1 s (0.0.2) → 26.5 s serial →
  23.0 s with 2 processes.

### Changed
- ThêoH grid follows Howe eq. 7 exactly (AVAR for m < k) and ends at the
  largest even m ≤ N − 1: coverage 75 % (was 62.8 %).
- Phase-noise identification: windowed least-squares slope over ±0.25 decade
  of log-binned L(f) (99 % correct on synthetic noise; two-bin method 67 %).
- Veusz export: min/max display envelope (`plot/*`) for series longer than
  200 000 points; `noise_id/slope_hdev`.
- Stable32: value-only layout (`timetags=False`); sigma-tau table skips
  non-finite rows; frequency and sigma-tau export from the GUI.
- SA conversion: white-space files; the GUI asks what a time series holds
  (`phase_s`, `freq_hz`, `frac_freq`); a converted trace is classified.
- GUI: tau0 down to 1 ns; long series drawn from an envelope; File › Close
  Data frees memory; Help › About; Export › Render a `.vszh5`.
- Validation: `validate_core` T7–T11 (allantools.theo1, parallel = serial,
  CSV loader, drift detection, drift fit); independent seeds and an accuracy
  test in `validate_phase_noise`; decimal comma, precision and parallel batch
  in `validate_sa_convert`; envelope in `validate_veusz_export`; long-series
  document in `validate_vszh5_in_veusz`; menus, themes, threads, reload and
  exports in `validate_gui`.

### Added
- `validate_stable32_export.py` (0.0.1's README claimed a Stable32 round-trip
  test that did not exist), `run_all.py` (parallel suite runner).
- `README_LuaLaTeX.pdf` and its source `latex/README_LuaLaTeX.tex`: the README
  typeset with LuaLaTeX (numbered sections, table of contents, live links,
  bookmark hierarchy). Build: `latexmk -lualatex README_LuaLaTeX.tex`.
- Both README PDFs carry a PDF bookmark hierarchy (sections > subsections),
  document metadata and open with the bookmark pane; `README.pdf` URLs are
  live links.
- README: the equation appendix and "Rendering" are sub-headings (they show
  in Obsidian's outline and in the bookmarks); BLAS figures re-measured.

### References corrected
- ThêoH: *Metrologia* 43(4) pp. **S322–S331**, DOI `10.1088/0026-1394/43/4/`**`S20`**
  (0.0.1: S322–S327 / `S17`).
- Thêo1: D. A. Howe and **T. N. Tasset**, Proc. 18th EFTF 2004, pp. 725–728
  (0.0.1: "F. Vernotte (T. N. Tasset)").
- ThêoH bias removal: Howe, McGee-Taylor and Tasset, Proc. 2006 IEEE IFCS,
  pp. 788–792 (0.0.1: "Purdue University OxideMEMS Lab").
- Greenhall and Riley (Greenhall first), **35th** PTTI meeting, 2003
  (0.0.1: Riley first, "36th").
- SP 559 is Kamas & Lombardi, *Time and Frequency Users Manual* (Rev. 1990);
  0.0.1's [2] merged it with NIST TN 1337 (*Characterization of Clocks and
  Oscillators*). Both now cited separately.
- Thêo1's τ = 0.75 m τ₀ attributed to Howe & Tasset, not IEEE 1139.
- Stable32: distribution via IEEE UFFC; `stable32.com/Manual154.pdf` not
  verified. Added SciPy, NumPy, CuPy, Qt.py, threadpoolctl, Python
  multiprocessing and spyder-kernels. Removed the uncited, unverifiable MHM
  2010 maser guide.

### Also fixed
- `load_canonical_series()` rejects a `time_s` column that does not increase
  (a zero or negative median spacing gave tau0 <= 0).

### Documented as data gaps
- Stable32 interpretation of numeric time tags (MJD days or not).
- Keysight/R&S manual document numbers.

## 0.0.2 — 2026-10-11

Pass 1 of 2: the Veusz output is rebuilt on the native HDF5 writer and the
GUI is renamed. The analysis code (`stability_core`, `phase_noise`,
`sa_convert`, `stable32_export`) is **unchanged**: every function and class
is AST-identical to 0.0.1. Defects found in review are listed under *Known
issues* and are fixed in 0.0.3.

### Changed
- **`veusz_export.py` rewritten on `vszh5_writer.py` 0.0.5**, the writer
  from `isp_speed_monitor.py` 1.3.0 shipped with QuickSyn 0.0.5
  (byte-identical copy, SHA-256 `2cdf43d2…ae33c1c`). The `.vszh5` is now a
  real Veusz HDF5 document written with h5py; no Veusz, PyQt or qmake is
  needed to write it.
  - Stores every result at float64: x(t), residual, y(t),
    ADEV/OADEV/MDEV/OHDEV, TDEV (s), ThêoH with the estimator of each point,
    both noise-ID tables, L(f), drift fit and run metadata. Tags `raw`,
    `stability`, `noise_id`, `phase_noise`, `curves`, `meta`.
  - Six pages: overview, phase, fractional frequency, sigma-tau, TDEV, L(f).
    TDEV moved off the dimensionless sigma-tau axes.
  - Atomic write (`.part` + `os.replace`); a failed export keeps the old
    file. A name without an HDF5 extension gets `.vszh5` appended.
  - Optional PDF/PNG render from the `.vszh5` (`render_vszh5()`, CLI
    `--render`, `render_vszh5_subprocess()` for Qt programs). Veusz program
    searched in `TIME_STABILITY_VEUSZ`, `VEUSZ_EXE`, then `PATH`.
  - `export_all_plots()` / `export_all_plots_subprocess()` kept as
    0.0.1-compatible wrappers.
- **`gui_app.py` renamed `Time_Stability_App.py`**; window title
  "Time Stability App 0.0.2 – …".
  - Veusz export in-process (no process isolation needed); every computed
    result is exported, not only OADEV/MDEV/TDEV.
  - "Render PDF/PNG (needs Veusz)" option: child process on a worker
    thread, result via a Qt signal; the GUI does not block and Veusz's Qt
    never loads next to PySide6.
  - Export logic moved to `export_veusz_to()` and `export_stable32_to()`.
  - Spyder: `QApplication` reused; no `sys.exit()` in IPython; window
    stays live with a Qt console backend; `matplotlib.use()` dropped (the
    QtAgg canvas is imported directly, leaving the console backend alone).
- **Every `.py` file**: full header (title, filename, version, author,
  company, licence, requirements, status, revision history), version
  dunders, Spyder `# %%` cells, script path captured once (Spyder defines
  `__file__` only while a cell runs).
- `requirements.txt`: `h5py` required; Veusz optional (render only).
- README rewritten for 0.0.2; equations in `$$` for Obsidian.

### Added
- `vszh5_writer.py` 0.0.5 (shared module, unchanged).
- `validate_vszh5_in_veusz.py`: round trip through Veusz's own HDF5 loader
  (bit-exact data, types, tags, plot references, in-process and program
  renders). 12/12 with Veusz 3.6.2 and 4.2.1.
- `environment.yml` (mamba / conda-forge), `LICENSE` (GPL-3.0),
  `CHANGELOG.md`, `README.pdf` (rendered from README.md; replaces the 0.0.1
  `SA Time Stability Tools-1785528572557.pdf`).

### Fixed
- **The 0.0.1 `.vszh5` could not be opened in Veusz.** `Embedded.Save(path)`
  defaults to `mode='vsz'`, so 0.0.1 wrote a *text* `.vsz` under the
  `.vszh5` name (7 significant digits). Veusz's File › Open picks the HDF5
  loader for `.vszh5` → "Unable to open file (file signature not found)"
  (Veusz 3.6.2).
- `validate_veusz_export.py` only checked the file size (> 1000 B), which
  the text file passed. It now checks the HDF5 layout and bit-exact data.
- Validation scripts imported from `/home/user/workspace/…` and wrote to
  `/tmp`; they now use their own folder and a temporary folder.
- `validate_gui.py` now drives the window's export methods (0.0.1 called
  the modules directly although the README said otherwise).

### Worked around (shared writer `vszh5_writer.py` 0.0.5, reported upstream)
- `render_pages()` names the PDF `stem.with_suffix(".pdf")`: the PDF of
  `run v0.0.2.vszh5` became `run v0.0.pdf`.
- `render_pages()` lists only files that did not exist before, so a
  re-render returned an empty list.
- `png_pages="first"` wrote **no PNG** with Veusz 4.2.1: the listen script
  uses `min(1, len(names))`, and Veusz 4.2.1 runs scripts with NumPy's
  names imported, so `min` is `numpy.min(1, axis=n)` → `AxisError`. The
  error is printed, not raised, and the done marker still arrives.
- `render_vszh5()` renders a plain-named copy in a private folder, renders
  "first" as "all" and keeps page 0, moves the results to their proper
  names, and raises if an expected file is missing.

### Removed
- `gui_app.py` (renamed); the `veusz.embed`/PyQt6 requirement for writing;
  the 0.0.1 PDF of the README (replaced by `README.pdf`).

### Known issues (fixed in 0.0.3)
1. A canonical CSV with `freq_hz` or `frac_freq` loads with
   `len(x) = len(t) + 1`; drift removal, plotting and export then fail.
2. Loading a new file keeps the previous drift fit and results.
3. The GUI logs "converting to phase" on every load; the README said
   `load_canonical_csv()` returns the column type (it returns `'phase'`).
4. Semicolon exports with decimal commas parse to "no numeric data".
5. `convert_to_canonical_csv()` keeps 11 significant digits (10 GHz series:
   3.7 mHz error, steps 1.2 mHz).
6. The Stable32 writer leaves a partial file when it rejects a last-point gap.
7. `NOISE_TABLE` "Linear Freq. Drift" (+1.5) is Random-Run FM; linear
   drift gives +1.
8. Drift-rate log line says "s/s^2"; D has units of 1/s.
9. Analysis on the GUI thread; no parallel or GPU path.
10. Several README/docstring references garbled or unverified.
11. Three validation scripts always exit 0.
12. `requirements.txt` pin `PySide6~=6.6.3` has no Python 3.13 wheels.
13. GUI uses PySide6 directly (not Qt.py); no menu bar, no light/dark option.

## 0.0.1 — baseline (as received)

Unversioned archive `sa_stability_tool.7z`: `gui_app.py`, `stability_core.py`,
`phase_noise.py`, `sa_convert.py`, `stable32_export.py`, `veusz_export.py`
(veusz.embed), five validation scripts, README and a PDF of it, and an
example phase record.
