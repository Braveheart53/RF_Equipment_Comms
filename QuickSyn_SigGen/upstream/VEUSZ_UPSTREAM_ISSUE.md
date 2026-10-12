# Veusz 4.2.1: `.vszh5` cannot be loaded from the command line or `Load()`, `Quit()` does not end `--listen --quiet`, and scripted PDF export is drawn at 48 % scale

Ready-to-file issue text for <https://github.com/veusz/veusz/issues>, with a
patch (`veusz-4.2.1-vszh5-load-quit-pdfdpi.patch`, beside this file) and a
reproduction script (`check_veusz_patch.py`). Prepared with QuickSyn SCPI
controller package 0.0.6, 2026-10-11. The same code was read on the `master`
branch on 2026-10-11 and has not changed.

---

## Environment

| Item | Value |
| --- | --- |
| Veusz | 4.2.1 from the PyPI source distribution (SHA-256 `fadc46d4…408dd09`), built against PyQt 6.6.1 / Qt 6.4.2, Python 3.12.3, Ubuntu 24.04 |
| Comparison | Veusz 3.6.2 (Ubuntu package, PyQt5 / Qt 5.15.13) |
| Display | `QT_QPA_PLATFORM=offscreen`; the PDF result is the same under Xvfb |

## 1. The command line and the embedded `Load()` cannot open a `.vszh5`

`veusz --export=out.pdf doc.vszh5` passes the file to
`CommandInterpreter.Load()` (`veusz_main.export()`), which always reads it
as UTF-8 text and runs it as a script. An HDF5 document therefore gives an
empty document. On 4.2.1 the export then crashes with a segmentation fault
(exit −11); on 3.6.2 it exits 0 without writing a file. `Load('doc.vszh5')`
typed in `--listen` mode or sent through the embedding interface fails the
same way. The GUI opens the same file correctly, because
`Document.load(filename, mode='hdf5')` is used there.

**Fix (patch, `document/commandinterpreter.py`):** `Load()` checks for the
HDF5 signature (`\x89HDF\r\n\x1a\n` at offset 0, 512, 1024, …, as the HDF5
format allows a user block) and then calls
`self.document.load(filename, mode='hdf5')`. Text documents take the
existing path unchanged.

## 2. `Quit()` does not end `veusz --listen --quiet` (4.2.1)

`InputListener.quitProgram()` only calls `self.window.close()`.
`veusz_main.py` ends the program through `lastWindowClosed`, but Qt emits
that signal only when the last *visible* window closes. With `--quiet` the
window was never shown, so the event loop keeps running and the process
never exits. Veusz 3.6.2 exits.

**Fix (patch, `veusz_listen.py`):** after closing the window, call
`qt.QCoreApplication.instance().quit()`.

## 3. Scripted PDF export draws every page at 72/150 scale

`AsyncExport.getDPI('.pdf')` rounds `pdfdpi` to the nearest resolution in
`QPrinter.supportedResolutions()` for the PDF format, which is `[72]` on
Qt 5.15 and Qt 6.4. The page helpers are laid out at 72 dpi.
`ExportPDFRunnable.doExport()`, however, calls
`printer.setResolution(self.aexport.pdfdpi)` with the requested value.

`CommandInterface.Export()` defaults to `pdfdpi=150`, so every PDF made by
`Export()` in a script, in `--listen` mode, or by `veusz --export` is drawn
in the top-left 72/150 = 48 % of the page. The page size itself is correct,
and the GUI export dialog (default 72) is not affected. Veusz 3.6.2 did not
round, so it is correct.

**Fix (patch, `document/export.py`):** set the printer to the resolution
the pages were laid out at, `round(self.phelpers[0].dpi[0])`. Passing
`pdfdpi=72` to `Export()` works around it on unpatched 4.x.

## Results

Output of `python check_veusz_patch.py veusz421 veusz421p veusz362`
(unpatched 4.2.1, patched 4.2.1, 3.6.2). "Text reaches" is the rightmost
text position on page 1 as a fraction of the page width; about 0.97 means
the drawing fills the page.

| Check | 4.2.1 | 4.2.1 + patch | 3.6.2 |
| --- | --- | --- | --- |
| `--export` `.vszh5` to PDF | fails (exit −11, no file) | OK, text reaches 0.97 of page | fails (exit 0, no file) |
| `--export` `.vszh5` to PNG | fails (exit −11, no file) | OK | fails (exit 0, no file) |
| `Load()` `.vszh5` + `Export()` of 2 pages | fails (no PDF) | OK, 2 pages, text reaches 0.97 of page | fails (no PDF) |
| `Quit()` in `--listen --quiet` | still running 30 s after `DONE` (killed) | exits 0.12 s after `DONE` | exits 0.11 s after `DONE` |
| text `.vsz` `--export` to PDF | OK, text reaches **0.47** of page | OK, text reaches 0.97 of page | OK, text reaches 0.97 of page |

The patch applies to the 4.2.1 source with `patch -p1` (checked with
`--dry-run`). It changes three functions, leaves text documents on their
existing path, and needs no new dependency: `h5py` is already required for
`.vszh5`.

## Workarounds used until a release carries the fix

- Load `.vszh5` with `veusz.document.loader.loadHDF5Doc(Root._ci.document, path)`
  in a script piped to `veusz --listen --quiet`, or with `Document.load(path, mode='hdf5')`
  from Python.
- Print a marker after the last `Export()`, then terminate the process if
  it has not exited within a few seconds.
- Pass `pdfdpi=72` to every `Export()` that writes a PDF.
