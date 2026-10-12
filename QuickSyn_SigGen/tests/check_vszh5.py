# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Veusz HDF5 document (.vszh5) checks: vszh5_writer.py and export_veusz().

Part of the QuickSyn SCPI controller package, version 0.0.7.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_vszh5.py``) or through ``tests/run_all.py``.
Needs h5py. Needs no instrument and no display.

What it checks
--------------
1. vszh5_writer: the HDF5 layout Veusz expects (groups, attributes, 1d /
   date / text datasets, error arrays, tags), name escaping, atomic .part
   write and abort, vz_text identical to Veusz latexEscape, Veusz date
   origin, and DST-aware local offsets.
2. export_veusz(): tagged raw/events/stability/meta datasets, bit-exact
   float64 data, commanded overlays equal to the reported values, an
   overview page plus one page per quantity, every trace pointing at an
   existing dataset, for each of the three time axes.
3. The command-line run writes a .vszh5 and never a text .vsz.
4. REAL VEUSZ, when importable here: the file loads through
   Document.load(mode='hdf5'), dataset types and values survive, all pages
   exist, the layout matches Veusz's own re-save, and the in-process render
   works. Set QUICKSYN_TEST_VEUSZ_EXE to a Veusz program to also test the
   --listen program render. Checks that cannot run are reported as SKIP.
5. Render plumbing without Veusz: a Windows path with a quote survives the
   --listen script, PDFs are exported with pdfdpi=72, a broken Veusz program
   or one that cannot start is a RuntimeError, and method='auto' falls back.
6. The rendered PDF (needs Veusz and pypdf): pages drawn full size (Veusz
   4.x drew them at 48 %), the bookmark hierarchy and document information,
   a render into a folder named odd \\dir 'q', and a re-render returning
   its files.
7. The LuaLaTeX report: tex_escape, the bookmark outline, a valid LuaLaTeX
   document with no unescaped underscores, and, when lualatex is found, a
   compiled PDF whose bookmarks follow the sections; the CLI writes it.

Exit status is 0 when every check that ran passed, 1 otherwise.
"""
import ast
import csv
import gzip
import importlib.util
import json
import os
import pickle
import re
import sys
import tempfile
import time
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree

import numpy as np   # noqa: E402
import h5py          # noqa: E402

import vszh5_writer as vw                      # noqa: E402
import quicksyn_veusz_export_v0_0_7 as qe      # noqa: E402

results: list[tuple[str, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> None:
    """Record and print one PASS/FAIL line."""
    status = "PASS" if ok else "FAIL"
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f"  - {detail}" if detail else ""))


def skip(name: str, why: str) -> None:
    """Record and print one SKIP line (a check that could not run)."""
    results.append(("SKIP", name, why))
    print(f"  [SKIP] {name}  - {why}")


def reference_latex_escape(text: str) -> str:
    """veusz.utils.textrender.latexEscape (Veusz 4.2.1), transcribed."""
    text = text.replace("\\", "\ue000")
    text = re.sub(r"([_\^\[\]\{\}])", r"\\\1", text)
    return text.replace("\ue000", "{\\backslash}")


def script_of(path: Path) -> str:
    """The document script stored in a .vszh5."""
    with h5py.File(path, "r") as h5:
        raw = h5["Veusz/Document/document"][0]
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)


work = Path(tempfile.mkdtemp(prefix="quicksyn_vszh5_"))

# =========================================================== 1. the writer module
print("1. vszh5_writer module")
t = np.linspace(0.0, 9.0, 10)
y = 9.876543210 + 1e-12 * np.arange(10)
doc = vw.VszDoc(generator="check_vszh5")
doc.add("page", "p")
doc.to("p")
doc.add("graph", "g")
doc.to("g")
doc.add("axis", "x")
doc.add("axis", "y")
doc.set("y/direction", "vertical")
doc.add("xy", "c")
doc.set("c/xData", "t")
doc.set("c/yData", "a/y")
doc.up()
doc.up()
check(doc.depth == 0, "VszDoc navigation returns to the root")
target = work / "unit.vszh5"
with vw.VeuszWriter(target, compress=False, writer_tag="check") as w:
    w.dataset_1d("t", t, tags=("raw",))
    w.dataset_1d("a/y", y, serr=np.full(10, 1e-9), tags=("raw", "freq"))
    w.dataset_1d("asym", y, perr=np.full(10, 2.0), nerr=np.full(10, 1.0))
    w.dataset_date("when", vw.epoch_to_veusz(1.8e9 + t), tags=("time",))
    w.dataset_text("note`s", ["alpha", "beta_\u03b3"], tags=("meta",))
    check((work / "unit.vszh5.part").exists() and not target.exists(),
          "writes to .part until finish()")
    w.finish(doc.text())
check(target.exists() and not (work / "unit.vszh5.part").exists(), "finish() publishes atomically")
with h5py.File(target, "r") as h5:
    v = h5["Veusz"]
    check(int(v.attrs["vsz_format"]) == 1 and "vsz_version" in v.attrs and "vsz_saved_at" in v.attrs,
          "Veusz group attributes (format 1)")
    d = v["Data"]
    check(sorted(d.keys()) == ["a`SLy", "asym", "note`BTs", "t", "when"],
          "names escaped as Veusz does ('/' -> `SL, '`' -> `BT)", str(sorted(d.keys())))
    dt = {k: (d[k].attrs["vsz_datatype"].decode() if isinstance(d[k].attrs["vsz_datatype"], bytes)
              else d[k].attrs["vsz_datatype"]) for k in d}
    check(dt == {"a`SLy": "1d", "asym": "1d", "note`BTs": "text", "t": "1d", "when": "date"},
          "datatypes 1d / date / text", str(dt))
    check(set(d["a`SLy"].keys()) == {"data", "serr"} and set(d["asym"].keys()) == {"data", "perr", "nerr"},
          "error arrays serr / perr / nerr")
    check(int(d["when/data"].attrs["vsz_convert_datetime"]) == 1, "date dataset flagged vsz_convert_datetime")
    check(np.array_equal(d["a`SLy/data"][...], y), "float64 values bit-exact")
    tags = {k: sorted(x.decode() for x in v["Document/Tags"][k][...]) for k in v["Document/Tags"]}
    check(tags == {"freq": ["a/y"], "meta": ["note`s"], "raw": ["a/y", "t"], "time": ["when"]},
          "tags group lists the dataset names", str(tags))
try:
    with vw.VeuszWriter(work / "aborted.vszh5") as w:
        w.dataset_1d("x", [1.0])
        raise RuntimeError("simulated failure")
except RuntimeError:
    pass
check(not any(work.glob("aborted.vszh5*")), "an exception discards the partial file")
cases = ["20261011_120000_FSW-0020", r"a\b_c^d{e}[f]", "plain", "x^2_{i}", "C:\\data\\run_1"]
check(all(vw.vz_text(c) == reference_latex_escape(c) for c in cases),
      "vz_text identical to Veusz latexEscape", f"{len(cases)} cases")
check(vw.epoch_to_veusz(1230768000.0) == 0.0 and vw.UNIX_TO_VEUSZ_S == -1230768000.0,
      "Veusz date origin 2009-01-01 00:00:00")
if hasattr(time, "tzset"):
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/New_York"
    time.tzset()
    # US DST ended 2026-11-01 06:00 UTC: EDT (-4 h) before, EST (-5 h) after.
    offs = vw.local_utc_offsets([1793512800.0 - 3600, 1793512800.0 + 3600])
    if old_tz is None:
        os.environ.pop("TZ")
    else:
        os.environ["TZ"] = old_tz
    time.tzset()
    check(list(offs) == [-14400.0, -18000.0], "local offsets follow a DST change", str(list(offs)))
else:
    skip("local offsets follow a DST change", "time.tzset is not available on this platform")

# =========================================================== 2. export_veusz()
print("2. export_veusz()")
n = 6000
rec = np.zeros(n, dtype=qe.TELEMETRY_DTYPE)
rec["idx"] = np.arange(n)
rec["t_mono"] = 500.0 + np.arange(n) * 0.1
rec["t_unix"] = 1.9e9 + rec["t_mono"]
carriers = np.array([9.876543210e9, 9.876543210e9 + 1e-3, 14.75e9])
rec["freq_hz"] = carriers[(np.arange(n) * 3) // n]
rec["power_dbm"] = -4.2
rec["temp_c"] = 30 + 8 * (1 - np.exp(-np.arange(n) / 900))
rec["status"] = 0xA8
rec["latency_s"] = 0.008 + 1e-4 * np.sin(np.arange(n))
rec["rate_hz"] = 10.0
meta = {"sampler": {"rate_hz": 10.0}}
stats = qe.reduce_session(rec, "synthetic", meta, use_gpu=False)
session = work / "20261011_120000_FSW-0020_test"
session.mkdir()
with (session / "state_events.csv").open("w", newline="") as fh:
    wcsv = csv.writer(fh)
    wcsv.writerow(["seq", "iso_utc", "t_unix", "parameter", "value", "source"])
    for k, (i, par, val) in enumerate([(0, "frequency_hz", "9876543210.0"),
                                       (n // 3, "frequency_hz", "9876543210.001"),
                                       (2 * n // 3, "frequency_hz", "14750000000.0"),
                                       (0, "power_dbm", "-4.2"), (5, "rf_output", "True")], 1):
        wcsv.writerow([k, "", f"{rec['t_unix'][i] - 0.01:.6f}", par, val, "gui"])

per_axis = {}
for axis in qe.TIME_AXES:
    out = qe.export_veusz(session, rec, stats, meta, time_axis=axis, compress=True,
                          path=session / f"axis_{axis}.vszh5")
    script = script_of(out)
    tree = ast.parse(script)
    sets = [(ast.literal_eval(n_.value.args[0]), ast.literal_eval(n_.value.args[1])) for n_ in tree.body
            if isinstance(n_, ast.Expr) and isinstance(n_.value, ast.Call)
            and n_.value.func.id == "Set"]
    refs = {val for key, val in sets if key.endswith(("xData", "yData"))}
    with h5py.File(out, "r") as h5:
        names = {k.replace("`SL", "/").replace("`BT", "`") for k in h5["Veusz/Data"].keys()}
    per_axis[axis] = (out, script, refs, names)
    check(refs <= names, f"[{axis}] every trace names an existing dataset",
          "" if refs <= names else str(sorted(refs - names)))

out, script, refs, names = per_axis["local"]
pages = re.findall(r"Add\('page', name='([^']+)'", script)
check(pages == ["page_overview", "page_carrier", "page_level", "page_thermal",
                "page_latency", "page_interval", "page_stability"], "overview + one page per quantity",
      str(pages))
with h5py.File(out, "r") as h5:
    d = h5["Veusz/Data"]
    tags = sorted(h5["Veusz/Document/Tags"].keys())
    check(tags == ["events", "meta", "raw", "stability"], "tags raw / events / stability / meta", str(tags))
    check(np.array_equal(d["raw`SLfreq_ghz/data"][...], rec["freq_hz"] / 1e9), "raw/freq_ghz bit-exact")
    check(np.unique(d["raw`SLfreq_ghz/data"][...]).size == 3, "carriers 1 mHz apart stay distinct")
    check(np.array_equal(d["raw`SLtime_utc/data"][...], vw.epoch_to_veusz(rec["t_unix"])),
          "raw/time_utc is the Veusz date of t_unix")
    cmd = d["events`SLfreq_ghz/data"][...]
    check(set(cmd) <= set(np.unique(d["raw`SLfreq_ghz/data"][...])),
          "commanded values equal the reported ones (same arithmetic)", str(list(cmd)))
    check(d["raw`SLfreq_ghz/data"].compression == "gzip", "long arrays compressed")
    js = json.loads(d["meta`SLreduction_summary_json/data"][0])
    check(js["n_samples"] == n, "reduction summary embedded under meta/")
    flags = d["raw`SLrf_on/data"][...]
    check(flags.min() == 1.0 and d["raw`SLrf_unlocked/data"][...].max() == 0.0,
          "status flags decoded (0xA8: RF on, locked)")
check("Set('x/mode', 'datetime')" in script and "Set('x/mode', 'datetime')" not in per_axis["elapsed"][1],
      "date axes for local/utc, numeric axis for elapsed")
check(f"Set('title/label', {vw.vz_text('Overview  -  ' + session.name)[:30]!r}"[:-1] in script,
      "titles escaped with vz_text")

# =========================================================== 3. command line
print("3. Command-line run")
cli = work / "20261011_130000_FSW-0020_cli"
cli.mkdir()
with gzip.open(cli / "telemetry_chunk_0000.pkl.gz", "wb") as fh:
    pickle.dump({"records": rec}, fh)
(cli / "session_metadata.json").write_text(json.dumps(meta))
rc = qe.main([str(cli), "--workers", "1", "--no-render"])
made = sorted(p.name for p in cli.iterdir())
check(rc == 0 and "quicksyn_session.vszh5" in made, "CLI writes quicksyn_session.vszh5")
check(not any(p.endswith((".vsz", ".part")) for p in made), "no text .vsz and no leftover .part", str(made))

# =========================================================== 4. real Veusz
print("4. Real Veusz")


def veusz_usable() -> tuple[bool, str]:
    """True only if Veusz and its Qt binding really import here."""
    if importlib.util.find_spec("veusz") is None:
        return False, "Veusz is not installed for this interpreter"
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import veusz.qtall  # noqa: F401
        import veusz.document  # noqa: F401
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"Veusz found but not importable ({type(exc).__name__}: {exc})"


ok_vz, why = veusz_usable()
real_names = ("loads via Document.load(mode='hdf5')", "dataset types and values survive",
              "all seven pages present", "layout matches Veusz's own re-save",
              "in-process render (PDF + every page PNG)")
if not ok_vz:
    for name in real_names:
        skip(name, why)
else:
    import veusz.qtall as vqt
    qapp = vqt.QApplication.instance() or vqt.QApplication([])
    import veusz.document as vdoc
    import veusz.widgets  # noqa: F401
    import veusz.dataimport  # noqa: F401
    import veusz.utils as vutils
    print(f"   Veusz {vutils.version()}")
    vd = vdoc.Document()
    vd.load(str(out), mode="hdf5")
    check(bool(vd.basewidget.children), real_names[0])
    types = {k: type(vd.data[k]).__name__ for k in ("raw/freq_ghz", "raw/time_local", "events/parameter")}
    same = (np.array_equal(vd.data["raw/freq_ghz"].data, rec["freq_hz"] / 1e9)
            and np.array_equal(vd.data["raw/time_utc"].data, vw.epoch_to_veusz(rec["t_unix"])))
    check(same and types == {"raw/freq_ghz": "Dataset", "raw/time_local": "DatasetDateTime",
                             "events/parameter": "DatasetText"}, real_names[1], str(types))
    check([p.name for p in vd.basewidget.children] == pages, real_names[2])
    resaved = work / "resaved_by_veusz.vszh5"
    vd.save(str(resaved), mode="hdf5")

    def layout(p: Path) -> dict:
        with h5py.File(p, "r") as h5:
            res = {"doc": (h5["Veusz/Document/document"].shape,
                           h5["Veusz/Document/document"].dtype.kind),
                   "tags": sorted(h5["Veusz/Document/Tags"].keys())}
            for k in h5["Veusz/Data"]:
                g = h5["Veusz/Data"][k]
                res[k] = (sorted(g.attrs), sorted(g.keys()), g["data"].dtype.kind,
                          sorted(g["data"].attrs))
            return res
    ours, theirs = layout(out), layout(resaved)
    diff = sorted(k for k in set(ours) | set(theirs) if ours.get(k) != theirs.get(k))
    check(not diff, real_names[3], "" if not diff else f"differs at {diff[:4]}")
    files = vw.render_pages(out, outdir=work / "render_ip", dpi=40, png_pages="all", method="inprocess")
    check(len([f for f in files if f.suffix == ".png"]) == 7 and any(f.suffix == ".pdf" for f in files),
          real_names[4], f"{len(files)} files")

exe = os.environ.get("QUICKSYN_TEST_VEUSZ_EXE", "")
if exe:
    t0 = time.monotonic()
    files = vw.render_pages(out, outdir=work / "render_prog", dpi=40, png_pages="all",
                            veusz_exe=exe, method="program")
    check(len(files) == 8, "Veusz program render via --listen (PDF + 7 PNG)",
          f"{Path(exe).name}, {time.monotonic() - t0:.1f} s")
else:
    skip("Veusz program render via --listen", "set QUICKSYN_TEST_VEUSZ_EXE to run it")

# =========================================================== 5. render plumbing
print("5. Render plumbing (no Veusz needed)")


class _Recorder:
    """Stand-in for Veusz's Export(): records the file names it is given."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, filename, **kw):
        self.calls.append((filename, kw))


win_src = Path(r"C:\Users\new\tmp 'q'\doc.vszh5")
win_stem = Path(r"C:\Users\new\tmp 'q'\doc")
lines = vw._render_script(win_src, Path(r"C:\Users\new\tmp 'q'\doc.pdf"), win_stem, "all", 40).splitlines()
rec_export = _Recorder()
namespace = {"Export": rec_export, "names": ["page_overview", "page_carrier"],
             "len": len, "range": range, "list": list}
for line in lines:
    if line.startswith(("Export(", "vszh5_png_stem", "exec(")):
        exec(line, namespace)   # the same statements Veusz would run
pngs = [c[0] for c in rec_export.calls if c[0].endswith(".png")]
pdfs = [c for c in rec_export.calls if c[0].endswith(".pdf")]
check(pngs == [str(win_stem) + "_p00_page_overview.png", str(win_stem) + "_p01_page_carrier.png"],
      "Windows path with a quote survives the --listen script", pngs[0] if pngs else "no PNG")
check(len(pdfs) == 1 and pdfs[0][0] == r"C:\Users\new\tmp 'q'\doc.pdf"
      and pdfs[0][1].get("pdfdpi") == vw.PDF_DPI == 72,
      "PDF exported with pdfdpi=72 (Veusz 4.x page-scale fix)", str(pdfs[0][1]) if pdfs else "")

fake_dir = work / "fake_veusz"
fake_dir.mkdir()
fake_py = fake_dir / "fake_veusz.py"
fake_py.write_text("import sys\nsys.stderr.write('fake veusz: cannot start Qt\\n')\nsys.exit(3)\n")
if os.name == "nt":
    broken = fake_dir / "fake_veusz.bat"
    broken.write_text(f'@"{sys.executable}" "{fake_py}" %*\r\n')
else:
    broken = fake_dir / "fake_veusz"
    broken.write_text(f"#!{sys.executable}\n" + fake_py.read_text())
    broken.chmod(0o755)
try:
    vw.render_pages(target, outdir=work / "broken_prog", veusz_exe=str(broken), method="program")
    check(False, "broken Veusz program reported (method='program')", "no exception")
except RuntimeError as exc:
    msg = str(exc)
    check("fake veusz: cannot start Qt" in msg and "--version" in msg,
          "broken Veusz program reported (method='program')", msg.splitlines()[0][:90])
not_exec = fake_dir / "not_a_program.txt"
not_exec.write_text("plain text\n")
try:
    vw.render_pages(target, outdir=work / "noexec", veusz_exe=str(not_exec), method="program")
    check(False, "a program that cannot start is a RuntimeError", "no exception")
except RuntimeError as exc:
    check("cannot start" in str(exc), "a program that cannot start is a RuntimeError, not OSError",
          str(exc).splitlines()[0][:90])
except OSError as exc:
    check(False, "a program that cannot start is a RuntimeError, not OSError", repr(exc))


if ok_vz:
    files = vw.render_pages(target, outdir=work / "broken_auto", veusz_exe=str(broken),
                            method="auto", png_pages="first")
    check(any(f.suffix == ".pdf" for f in files),
          "broken program, method='auto': falls back to the Veusz package", f"{len(files)} files")
else:
    try:
        vw.render_pages(target, outdir=work / "broken_auto", veusz_exe=str(broken), method="auto")
        check(False, "broken program, method='auto': both errors reported", "no exception")
    except RuntimeError as exc:
        check("Veusz program" in str(exc) and "In-process fallback" in str(exc),
              "broken program, method='auto': both errors reported (no Veusz package here)")

# =========================================================== 6. rendered PDF
print("6. Rendered PDF: page scale, bookmarks, re-render")
EXE = os.environ.get("QUICKSYN_TEST_VEUSZ_EXE", "")
have_pypdf = importlib.util.find_spec("pypdf") is not None
render_how = ("program", EXE) if EXE else (("inprocess", "") if ok_vz else (None, ""))
pdf_names = ("render into a folder named odd \\dir 'q'", "PDF pages drawn full size",
             "PDF bookmark hierarchy (session > overview, time series, stability)",
             "PDF document information and outline pane", "re-render returns its files",
             "bookmark pointing outside the PDF is refused")
plots_pdf = None


def text_reach(pdf: Path, index: int) -> float:
    """Rightmost text position on a PDF page as a fraction of its width."""
    from pypdf import PdfReader

    page = PdfReader(str(pdf)).pages[index]
    xs: list[float] = []

    def visit(text, cm, tm, _font, _size):
        if text.strip():
            xs.append(tm[4] * cm[0] + tm[5] * cm[2] + cm[4])

    page.extract_text(visitor_text=visit)
    return max(xs) / float(page.mediabox.width) if xs else 0.0


def outline_tree(pdf: Path) -> list:
    """The PDF outline as nested (title, page number, children) tuples."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))

    def walk(items) -> list:
        out_: list = []
        for item in items:
            if isinstance(item, list):
                out_[-1] = (out_[-1][0], out_[-1][1], walk(item))
            else:
                out_.append((item.title, reader.get_destination_page_number(item), []))
        return out_
    return walk(reader.outline)


if render_how[0] is None:
    for name in pdf_names:
        skip(name, "no Veusz here: set QUICKSYN_TEST_VEUSZ_EXE or install the veusz package")
elif not have_pypdf:
    for name in pdf_names:
        skip(name, "pypdf is not installed")
else:
    from pypdf import PdfReader

    odd = work / "odd \\dir 'q'"
    files = vw.render_pages(out, outdir=odd, dpi=40, png_pages="all", veusz_exe=render_how[1],
                            method=render_how[0],
                            bookmarks=lambda names: qe.session_outline(names, session.name),
                            pdf_info={"title": f"QuickSyn session {session.name}",
                                      "subject": "check_vszh5"})
    plots_pdf = odd / "axis_local.pdf"
    check(len(files) == 8 and plots_pdf.is_file(), pdf_names[0],
          f"{render_how[0]} {Path(render_how[1]).name}".strip() + f", {len(files)} files")
    reach = [text_reach(plots_pdf, i) for i in range(len(PdfReader(str(plots_pdf)).pages))]
    check(min(reach) > 0.85, pdf_names[1], "text reaches " + ", ".join(f"{r:.2f}" for r in reach))
    tree = outline_tree(plots_pdf)
    expected = [(f"QuickSyn session {session.name}", 0, [
        ("Overview (all quantities)", 0, []),
        ("Time series", 1, [("Carrier frequency", 1, []), ("Output level", 2, []),
                            ("Internal temperature", 3, []), ("Serial I/O latency", 4, []),
                            ("Sample interval", 5, [])]),
        ("Stability", 6, [("Allan deviation of the reported carrier", 6, [])])])]
    check(tree == expected, pdf_names[2], "10 bookmarks, 3 levels" if tree == expected else str(tree))
    reader = PdfReader(str(plots_pdf))
    check(reader.metadata.title == f"QuickSyn session {session.name}"
          and reader.metadata.subject == "check_vszh5" and reader.page_mode == "/UseOutlines",
          pdf_names[3], f"title {reader.metadata.title!r}, page mode {reader.page_mode}")
    again = vw.render_pages(out, outdir=odd, dpi=40, png_pages="all", veusz_exe=render_how[1],
                            method=render_how[0])
    check(len(again) == 8, pdf_names[4], f"{len(again)} files the second time")
    try:
        vw.add_pdf_bookmarks(odd / "axis_local.pdf", [("Nowhere", 99)])
        check(False, pdf_names[5], "no exception")
    except ValueError as exc:
        check("page 99" in str(exc), pdf_names[5])
    # Restore the full outline for the report check below.
    vw.add_pdf_bookmarks(plots_pdf, qe.session_outline(
        [f"page_{p}" for p in ("overview", "carrier", "level", "thermal", "latency",
                               "interval", "stability")], session.name))

# =========================================================== 7. LuaLaTeX report
print("7. LuaLaTeX report")
check(qe.tex_escape(r"a_b%c$d#e&f{g}h~i^j\k") ==
      r"a\_b\%c\$d\#e\&f\{g\}h\textasciitilde{}i\textasciicircum{}j\textbackslash{}k",
      "tex_escape covers every LaTeX special character")
outline = qe.session_outline(["page_overview", "page_carrier", "page_stability"], "S_1")
check(outline == [("QuickSyn session S_1", 0, [("Overview (all quantities)", 0),
                                                ("Time series", None, [("Carrier frequency", 1)]),
                                                ("Stability", None,
                                                 [("Allan deviation of the reported carrier", 2)])])],
      "session_outline builds the bookmark hierarchy from page names")
check(qe.vszh5_page_names(out) == pages, "page names read back from the .vszh5")
rep_dir = work / "20261011_140000_FSW-0020_report"
rep_dir.mkdir()
meta_rep = {"identity": {"raw": "Phase Matrix,FSW-0020,00000007,0106,300A", "model": "FSW-0020",
                         "options": "00000007", "firmware": "0106", "firmware_value": 106,
                         "serial": "300A"},
            "capability": {"f_min_hz": 0.5e9, "f_max_hz": 20e9},
            "transport": {"port": "SIM", "baudrate": 115200, "simulated": True},
            "sampler": {"rate_hz": 10.0}}
if plots_pdf is not None:
    import shutil as _shutil
    _shutil.copy(plots_pdf, rep_dir / "quicksyn_session.pdf")
tex = qe.write_latex_report(rep_dir, rec, stats, meta_rep,
                            (rep_dir / "quicksyn_session.pdf") if plots_pdf is not None else None,
                            pages, render_note="" if plots_pdf is not None else "test without Veusz")
tex_text = tex.read_text(encoding="utf-8")
check(tex.name == "quicksyn_session_report.tex" and "% !TeX program = lualatex" in tex_text
      and "\\usepackage{fontspec}" in tex_text and "bookmarksopen=true" in tex_text
      and "pdfpagemode=UseOutlines" in tex_text, ".tex is a LuaLaTeX document with hyperref bookmarks")
body = tex_text.split("\\begin{document}", 1)[1]
body = re.sub(r"\\begin\{equation\}.*?\\end\{equation\}", "", body, flags=re.S)
body = re.sub(r"\$[^$]*\$", "", body)
body = re.sub(r"\\includegraphics\[[^\]]*\]\{[^}]*\}", "", body)
body = re.sub(r"\\url\{[^}]*\}", "", body)
loose = [ln.strip() for ln in body.splitlines() if re.search(r"(?<!\\)_", ln)]
check(not loose, "no unescaped underscore in the report text", "; ".join(loose)[:120])
check("SIMULATED SESSION" in tex_text, "simulated session flagged in the report")
lualatex = qe.find_lualatex()
if not lualatex:
    for name in ("report compiles with LuaLaTeX", "report bookmark hierarchy",
                 "report outline pane and title"):
        skip(name, "lualatex not found (install TeX Live or MiKTeX, or set QUICKSYN_LUALATEX)")
elif not have_pypdf:
    skip("report checks", "pypdf is not installed")
else:
    from pypdf import PdfReader

    t0 = time.monotonic()
    report, log_tail = qe.compile_latex(tex, lualatex)
    check(report is not None and report.is_file(), "report compiles with LuaLaTeX",
          f"{time.monotonic() - t0:.1f} s" if report else log_tail[:120])
    if report is not None:
        tree = outline_tree(report)
        titles = [t[0] for t in tree]
        plot_children = next((t[2] for t in tree if t[0].endswith("Plots")), [])
        want_plots = 7 if plots_pdf is not None else 0
        check(titles[:1] == ["Contents"] and any(t.endswith("Instrument") for t in titles)
              and any(t.endswith("Stability of the reported carrier") for t in titles)
              and titles[-1:] == ["References"]
              and len(plot_children) == want_plots, "report bookmark hierarchy",
              f"{len(titles)} top-level, {len(plot_children)} under Plots")
        reader = PdfReader(str(report))
        check(reader.page_mode == "/UseOutlines" and (reader.metadata.title or "").startswith(
              "QuickSyn session report"), "report outline pane and title",
              f"{len(reader.pages)} pages")
        check(not any(tex.with_suffix(s).exists() for s in (".aux", ".out", ".toc")),
              "auxiliary files removed after the build")

if render_how[0] is not None and lualatex:
    cli2 = work / "20261011_150000_FSW-0020_cli_render"
    cli2.mkdir()
    with gzip.open(cli2 / "telemetry_chunk_0000.pkl.gz", "wb") as fh:
        pickle.dump({"records": rec}, fh)
    (cli2 / "session_metadata.json").write_text(json.dumps(meta_rep))
    argv = [str(cli2), "--workers", "1", "--png-pages", "first", "--dpi", "40"]
    argv += ["--veusz-exe", EXE] if EXE else ["--render-method", "inprocess"]
    rc = qe.main(argv)
    made = sorted(p.name for p in cli2.iterdir())
    check(rc == 0 and {"quicksyn_session.pdf", "quicksyn_session_report.pdf",
                       "quicksyn_session_report.tex"} <= set(made),
          "CLI render writes the plots PDF and the LuaLaTeX report", ", ".join(m for m in made
                                                                        if "report" in m))
else:
    skip("CLI render writes the plots PDF and the LuaLaTeX report", "needs Veusz and lualatex")

# =========================================================== summary
failed = [r for r in results if r[0] == "FAIL"]
skipped = [r for r in results if r[0] == "SKIP"]
passed = len(results) - len(failed) - len(skipped)
print(f"\n{passed} passed, {len(failed)} failed, {len(skipped)} skipped")
if failed:
    for _, name, detail in failed:
        print(f"  FAILED: {name} {detail}")
    sys.exit(1)
print("ALL VSZH5 CHECKS PASSED" + (" (some checks skipped)" if skipped else ""))
