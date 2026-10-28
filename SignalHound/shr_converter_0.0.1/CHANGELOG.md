# Changelog (newest first)

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
* vszh5_writer 0.0.20 merges the two releases both numbered 0.0.18 (FSP logger 0.9.0 render fixes; AB Monitor 1.6.0 appender) with 0.0.19. It fixes the 0600 file mode of published documents and adds `image_page` date axes, `xy_page(datetime_format=)`, `render_pages(png_background=)`, `block_reduce()` and `regularize_rows()`. Drop-in results: `docs/WRITER_0.0.20_NOTES.md`.
