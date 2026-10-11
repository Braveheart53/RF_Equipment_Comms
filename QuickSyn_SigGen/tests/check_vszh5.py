# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Veusz HDF5 document (.vszh5) checks: vszh5_writer.py and export_veusz().

Part of the QuickSyn SCPI controller package, version 0.0.4.
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
import quicksyn_veusz_export_v0_0_4 as qe      # noqa: E402

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
