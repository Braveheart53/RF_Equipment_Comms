# Revision history

## Logger 0.8.1 — 2026-10-23

- Complete source package, wheel/source build configuration, tests and 7z delivery.
- Report button uses supplied native writer in isolated QProcess.
- Reciprocal interlocks cover sampling, scheduled waits, CSV drain and reporting.
- Bounded asynchronous CSV consumer with ordered terminal-capture preservation on saturation.
- One serialized instrument owner; no detached per-trigger SCPI helper thread.
- Reused plot curves and latest-display mailbox; only display frames coalesce.
- Cooperative stop/close and correct QThread.finished cleanup.
- Confirm before replacing acquisition CSV; never overwrite report directories.
- Retain supplied analyzer query/fallback logic.
- Spyder cells, detailed comments and dependency pins.

## Integration design 0.8.0

Previously described but not delivered as a complete archive. This completed package is 0.8.1.

## Writer 0.0.15 — 2026-10-23

- Python 3.8-safe Bookmarks typing alias.
- Private sibling temporary files for atomic writes.
- Flushed renderer protocol markers avoid waiting after completed export.
- Native schema and public page/dataset APIs unchanged.

## Background/report modules 0.1.1 — 2026-10-23

- Strict two-pass CSV validation, repeated-grid checks and source change detection.
- Disk-backed matrices, chunked/parallel statistics, linear-power mean calculation.
- Native report, spectral-envelope, waterfall, peak-history and last-capture pages.
- SHA-256 provenance, JSON/Markdown reports and statistical CSV tables.
- Optional PDF/PNG render failure cannot discard completed native output.
