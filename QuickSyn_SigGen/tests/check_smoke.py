# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Headless smoke test: driver, simulator, logging, sampler and full GUI.

Part of the QuickSyn SCPI controller package, version 0.0.6.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_smoke.py``) or through ``tests/run_all.py``.
Needs no instrument and no display: Qt runs on the offscreen platform and
the QuickSyn is replaced by the built-in simulator transport.

What it checks
---------------
Command formatting against the vendor examples, the 64-byte buffer guard,
FM interlocks, range checks, the sampler and its rate budget, the ring
buffer and spill files, writer-thread shutdown (a Python 3.12 regression),
GUI construction and themes, a full GUI-driven logging session, and
capability gating by model.
"""

import os, sys, time, csv, gzip, pickle, json
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree
from pathlib import Path

import quicksyn_scpi_gui_v0_0_6 as app

print(f"module v{app.__version__}  Qt={app.QT_ABSTRACTION}/{app.QT_BINDING}")
print(f"pyserial={app.HAVE_PYSERIAL} pyqtgraph={app.HAVE_PYQTGRAPH} "
      f"psutil={app.HAVE_PSUTIL}")

# ---------------------------------------------------------------- unit checks
assert app.hz_to_mlhz(9.876543210e9) == 9_876_543_210_000, "mlHz conversion"
assert app.quantise_power_dbm(-8.34) == -8.3
assert app.quantise_dwell_us(7) == 5 and app.quantise_dwell_us(8) == 10
assert app.quantise_dwell_us(0) == 0
assert app.format_dwell(3_000_000) == "3s"
assert app.format_dwell(50_000) == "50ms"
assert app.format_dwell(2_505) == "2505us"
assert app.parse_int_response("00A8") == 0xA8
assert app.parse_int_response("10") == 0x10
st = app.StatusWord.from_raw(0x00A8)   # [R1] Table 5 example response
assert (st.rf_locked, st.ref_locked, st.rf_output_on) == (True, True, True)
assert (st.ref_output_on, st.blanking_on, st.ext_ref_present) == (True, False, False)
assert st.lock_recovery_on is True and st.voltage_error is False
mw = app.ModulationWord.from_raw(0x10)  # [R1] Table 5 example -> FM WIDE
assert mw.fm_wide and not (mw.pulse or mw.am or mw.fm_nb1 or mw.fm_nb2 or mw.phase)
print("unit checks ....................... OK  (STAT? 00A8, DIAG:MOD? 10 decoded)")

# ---------------------------------------------------------- command formatting
seen = []
sim = app.SimulatedTransport(on_transaction=lambda t: seen.append(t))
sim.open("SIM")
dut = app.QuickSyn(sim)
ident = dut.identify()
assert ident.model == "FSW-0020", ident
assert ident.firmware_value == 106 and ident.scpi_supported is True, ident
assert ident.serial == "300A" and ident.options == "00000007"
assert len(ident.fields) == 5
print(f"identity ......................... OK  {ident.raw}")
assert dut.capability.model == "FSW-0020" and dut.capability.has_modulation

f_set = dut.set_frequency(9.876543210e9)
assert seen[-1].command == "FREQ 9876543210000", seen[-1].command
dut.set_power(-8.34)
assert seen[-1].command == "POW -8.3", seen[-1].command
dut.set_rf_output(True);            assert seen[-1].command == "OUTP:STAT ON"
dut.set_blanking(False);            assert seen[-1].command == "OUTP:BLAN OFF"
dut.set_reference_source(app.RefSource.EXTERNAL)
assert seen[-1].command == "ROSC:SOUR EXT"
dut.set_reference_output(True);     assert seen[-1].command == "OUTP:ROSC:STAT ON"
dut.set_lock_recovery(True);        assert seen[-1].command == "FREQ:LRSTAT ON"
dut.set_pulse_modulation(True);     assert seen[-1].command == "PULM:STAT ON"
dut.set_am(True);                   assert seen[-1].command == "AM:STAT ON"
dut.set_am_depth(2000);             assert seen[-1].command == "AM:DEPT 2000"
dut.set_fm_mode(app.FMMode.FM_WIDE); assert seen[-1].command == "FM:MODE 2"
dut.set_fm_sensitivity(2000);       assert seen[-1].command == "FM:SENS 2000"
dut.set_reference_dac(30000)
assert seen[-1].command == "DIAG:CAL:REF:DAC 30000"
dut.save_state(1);                  assert seen[-1].command == "*SAV 1"
dut.recall_state(0);                assert seen[-1].command == "*RCL 0"
dut.reset();                        assert seen[-1].command == "*RST"
print(f"main/modulation commands ......... OK  (set {f_set/1e9:.9f} GHz)")

# list mode, mirroring the [R1] Table 2b worked example
dut.erase_list();                   assert seen[-1].command == "LIST:ERAS"
dut.write_list_point(app.ListPoint(index=1, freq_hz=9.111222333e9,
                                   power_dbm=12.0, dwell_us=3_000_000,
                                   pulse_mod=False, rf_output=True))
assert seen[-1].command == "LIST:PVEC 1,9111222333000,12.0dBm,3s,OFF,ON", seen[-1].command
dut.write_list_point(app.ListPoint(index=2, freq_hz=8.333222111e9,
                                   power_dbm=-12.0, dwell_us=4_000_000,
                                   pulse_mod=False, rf_output=True,
                                   save_to_flash=True))
assert seen[-1].command == "LIST:PVEC 2,8333222111000,-12.0dBm,4s,OFF,ON,F", seen[-1].command
dut.run_list_point(2);              assert seen[-1].command == "LIST:PVEC:RUN 2"
dut.setup_list(10_000_000, 3, app.TriggerMode.POINT_TRIGGER,
               app.SweepDirection.UP, run_now=True)
assert seen[-1].command == "LIST:SETUP 10s,3,2,0,RUN", seen[-1].command
dut.start_list(5);                  assert seen[-1].command == "LIST:STAR 5"
dut.stop_list();                    assert seen[-1].command == "LIST:STOP"
dut.save_list(2);                   assert seen[-1].command == "LIST:SAV"
print("list-mode commands ............... OK  ([R1] Table 2b examples reproduced)")

# sweeps
dut.setup_fast_frequency_sweep(2e9, 10e9, 80, 2.0, 1_000_000, 10,
                               app.TriggerMode.SOFTWARE, app.SweepDirection.UP)
assert seen[-1].command == \
    "SWE:FAST:FREQ:SETUP 2GHz,10GHz,80,2.0dBm,1s,10,0,0", seen[-1].command
dut.setup_normal_frequency_sweep(2e9, 8e9, 1e9, 0.0, 5_000, 200,
                                 app.TriggerMode.POINT_TRIGGER,
                                 app.SweepDirection.UP_DOWN, run_now=True)
assert seen[-1].command == \
    "SWE:NORM:FREQ:SETUP 2GHz,8GHz,1GHz,0.0dBm,5ms,200,2,2,RUN", seen[-1].command
dut.setup_fast_power_sweep(1.2, 5.2, 40, 10e9, 500_000, 0,
                           app.TriggerMode.FULL_TRIGGER,
                           app.SweepDirection.UP_DOWN, run_now=True)
assert seen[-1].command == \
    "SWE:FAST:POW:SETUP 1.2,5.2,40,10GHz,500ms,0,1,2,RUN", seen[-1].command
dut.setup_normal_power_sweep(-2.0, 5.0, 1.0, 5e9, 50_000, 0,
                             app.TriggerMode.FULL_TRIGGER,
                             app.SweepDirection.UP_DOWN)
assert seen[-1].command == \
    "SWE:NORM:POW:SETUP -2.0,5.0,1.0,5GHz,50ms,0,1,2", seen[-1].command
for kind, mnem in (("fast_freq", "SWE:FAST:FREQ:STAR"),
                   ("normal_freq", "SWE:NORM:FREQ:STAR"),
                   ("fast_power", "SWE:FAST:POW:STAR"),
                   ("normal_power", "SWE:NORM:POW:STAR")):
    dut.start_sweep(kind, 1); assert seen[-1].command == f"{mnem} 1"
dut.stop_sweep();                   assert seen[-1].command == "SWE:STOP"
print("sweep commands ................... OK  ([R1] Table 5 examples reproduced)")
for cmd, want in (
    (app.format_frequency(2.0e9), "2GHz"),
    (app.format_frequency(10.0e9), "10GHz"),
    (app.format_frequency(9.111222333e9), "9111222333000"),
    (app.format_frequency(0.1e9), "0.1GHz"),
    (app.format_frequency(2.2e9), "2.2GHz"),
    (app.format_frequency(9.876543210001e9), "9876543210001"),
):
    assert cmd == want, (cmd, want)
# every compound command must survive the 64-byte buffer
for t_ in seen:
    assert len(t_.command.encode()) + 1 <= app.MAX_COMMAND_BYTES, t_.command
longest = max(seen, key=lambda t_: len(t_.command))
print(f"64-byte budget ................... OK  longest of {len(seen)} commands "
      f"= {len(longest.command)+1} B  ({longest.command[:44]}...)")
# a frequency needing full mHz precision in a 3-frequency sweep cannot fit,
# and must be refused with advice rather than truncated by the device
try:
    dut.setup_normal_frequency_sweep(9.876543210001e9, 19.876543210001e9,
                                     1.000000000001e9, 0.0, 5000, 1,
                                     app.TriggerMode.SOFTWARE,
                                     app.SweepDirection.UP)
except app.CommandTooLongError as exc:
    assert "Round the start, stop and step" in str(exc)
    print("overflow pre-flight .............. OK  (refused with rounding advice)")
else:
    raise AssertionError("over-long sweep was not refused")

# ------------------------------------------------------------ guard behaviour
try:
    app.SerialTransport.encode("LIST:PVEC " + "9" * 60)
except app.CommandTooLongError as exc:
    print(f"64-byte buffer guard ............. OK  ({str(exc)[:46]}...)")
else:
    raise AssertionError("64-byte guard did not fire")

dut.set_fm(True)
for call, label in ((lambda: dut.setup_list(1000, 1, app.TriggerMode.SOFTWARE,
                                            app.SweepDirection.UP), "list"),
                    (lambda: dut.setup_fast_frequency_sweep(
                        2e9, 3e9, 10, 0.0, 1000, 1, app.TriggerMode.SOFTWARE,
                        app.SweepDirection.UP), "sweep")):
    try:
        call()
    except app.ParameterError:
        pass
    else:
        raise AssertionError(f"FM interlock did not block {label}")
print("FM interlock ..................... OK  (list and sweep both blocked)")
dut.set_fm(False)

for bad, label in (
    (lambda: dut.set_frequency(30e9), "frequency above FSW-0020 range"),
    (lambda: dut.set_power(40.0), "power above control range"),
    (lambda: dut.set_am_depth(5000), "AM DAC over 4095"),
    (lambda: dut.set_fm_sensitivity(-1), "FM DAC below 0"),
    (lambda: dut.set_reference_dac(70000), "ref DAC over 65535"),
    (lambda: dut.save_state(3), "*SAV slot 3"),
    (lambda: dut.recall_state(9), "*RCL slot 9"),
    (lambda: dut.run_list_point(99999), "list index over 32767"),
):
    try:
        bad()
    except app.ParameterError:
        continue
    raise AssertionError(f"range check missed: {label}")
print("range checks ..................... OK  (8 out-of-range cases rejected)")

# -------------------------------------------------------- session + telemetry
root = Path(tempfile.mkdtemp(prefix="quicksyn_smoke_"))
session = app.SessionLogger(root, tag="FSW-0020_smoketest")
writer = app.TelemetryWriter(session); writer.start()
ring = app.TelemetryRingBuffer(capacity=100, on_spill=writer.submit_spill)
assert ring.capacity == app.MIN_RING_CAPACITY
cfg = app.SamplerConfig(rate_hz=20.0, poll_modulation=True,
                        temperature_decimation=3)
print(f"rate budget ...................... {cfg.queries_per_sample()} queries/sample, "
      f"period {cfg.period_s*1e3:.0f} ms")

for t in seen:
    session.log_transaction(t)
session.write_metadata({"identity": app.asdict(ident),
                        "capability": app.asdict(dut.capability),
                        "sampler": app.asdict(cfg)})

qapp = app.QtWidgets.QApplication.instance() or app.QtWidgets.QApplication([])
sampler = app.TelemetrySampler(dut, cfg, ring, writer)
got = []
sampler.sampleReady.connect(lambda row: got.append(row))
errs = []
sampler.samplerError.connect(lambda m: errs.append(m))
sampler.start()
t_end = time.time() + 2.0
while time.time() < t_end:
    qapp.processEvents(); time.sleep(0.02)
sampler.stop(); sampler.wait(4000)
ring.flush(); writer.stop(); session.close()
# Regression (0.0.3): on Python 3.12 a Thread subclass attribute named
# `_stop` shadowed Thread._stop() and join() raised TypeError. Stopping
# must return cleanly and the thread must really have exited.
assert not writer.is_alive(), "telemetry writer thread still running after stop()"

assert not errs, errs[:3]
assert len(got) >= 10, f"only {len(got)} samples in 2 s"
print(f"sampler .......................... OK  {len(got)} samples in 2.0 s, "
      f"{ring.total_written} buffered, 0 errors")

d = session.directory
rows = list(csv.DictReader((d / "telemetry.csv").open()))
assert len(rows) >= 10 and rows[0]["freq_hz"] and rows[0]["status_hex"]
chunks = sorted(d.glob("telemetry_chunk_*.pkl.gz"))
assert chunks, "stop-time flush produced no chunk"
with gzip.open(chunks[0], "rb") as fh:
    blob = pickle.load(fh)
assert blob["records"].dtype == app.TELEMETRY_DTYPE
assert blob["n_records"] == ring.total_written, (blob["n_records"],
                                                 ring.total_written)
txn = list(csv.DictReader((d / "transactions.csv").open()))
ste = list(csv.DictReader((d / "state_events.csv").open()))
meta = json.loads((d / "session_metadata.json").read_text())
assert meta["identity"]["model"] == "FSW-0020"
assert meta["app_version"] == app.__version__
print(f"artefacts ........................ OK  telemetry={len(rows)} rows, "
      f"transactions={len(txn)}, state_events={len(ste)}, "
      f"chunks={len(chunks)} ({blob['n_records']} rec each)")
print(f"                                   ring RAM {ring.nbytes} B for "
      f"{ring.capacity} rec ({app.TELEMETRY_DTYPE.itemsize} B/rec)")

# ---- automatic overflow spill, exercised without waiting on the link
spills = []
ring2 = app.TelemetryRingBuffer(capacity=100, on_spill=spills.append)
for i in range(250):
    ring2.append((i, time.time(), i * 0.05, 1e10, 0.0, 30.0, 0xA8, 0x10,
                  0.004, 20.0))
tail = ring2.flush()
assert [b.size for b in spills] == [100, 100, 50], [b.size for b in spills]
assert ring2.total_written == 250 and ring2.fill == 0
assert spills[0]["idx"][0] == 0 and spills[1]["idx"][0] == 100
print(f"ring overflow .................... OK  250 records -> spills of "
      f"{[b.size for b in spills]}, steady-state RAM {ring2.nbytes/1e3:.1f} kB")

# ------------------------------------------------------------------ full GUI
theme = app.ThemeManager(qapp)
win = app.MainWindow(theme)
win.show(); qapp.processEvents()
for mode in (app.ThemeManager.LIGHT, app.ThemeManager.DARK,
             app.ThemeManager.SYSTEM):
    theme.apply(mode); qapp.processEvents()
print(f"GUI construction ................. OK  {win.tabs.count()} tabs, "
      f"3 themes applied")

win.tab_connection.simulate_check.setChecked(True)
win.controller.connect_instrument("SIM", 115200, True)
qapp.processEvents()
assert win.controller.driver is not None, "simulated connect failed"
assert win.tab_connection.fields_table.rowCount() == 5
mod_idx = win.tabs.indexOf(win.tab_modulation)
assert win.tabs.isTabEnabled(mod_idx), "modulation tab wrongly disabled"
win.tab_main.freq_spin.setValue(12.5)
win.tab_main.set_freq_button.click(); qapp.processEvents()
assert "12.500000000" in win.tab_main.freq_readback.text(), \
    win.tab_main.freq_readback.text()
win.tab_list.gen_points.setValue(5); win.tab_list._generate()
assert win.tab_list.table.rowCount() == 5
pts = win.tab_list.collect_points()
assert len(pts) == 5 and pts[0].index == 1
win._panic_rf_off(); qapp.processEvents()
assert win.controller.driver.get_rf_output() is False, "panic RF-off failed"
print("GUI round trip ................... OK  connect, set 12.5 GHz, "
      "5-point list, panic RF-off")

# ---- the headline requirement: a GUI-driven session logs what was generated
gui_root = root / "gui"
win.tab_monitor.logdir_edit.setText(str(gui_root))
win.tab_monitor.rate_spin.setValue(10.0)
win.tab_monitor.chk_mod.setChecked(True)
win.controller.start_logging(); qapp.processEvents()
gui_session = win.controller.session
assert gui_session is not None, "start_logging did not open a session"
gui_dir = gui_session.directory
for ghz in (8.25, 11.0, 14.75):
    win.tab_main.freq_spin.setValue(ghz)
    win.tab_main.set_freq_button.click()
    qapp.processEvents(); time.sleep(0.15)
win.tab_main.power_spin.setValue(-4.2); win.tab_main.set_power_button.click()
win.tab_main.rf_check.setChecked(True); win.tab_main.rf_check.click()
qapp.processEvents(); time.sleep(0.6)


def wait_for_export(timeout_s: float = 180.0) -> None:
    """Pump the event loop until the controller's export process is done."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        qapp.processEvents()
        ctl = win.controller
        if ctl._export_proc is None and ctl.last_export_ok is not None \
                and ctl._export_pending is None:
            return
        time.sleep(0.05)
    raise AssertionError("Veusz export process did not finish in time")


import h5py  # noqa: E402  (only needed from here on)
import numpy as np  # noqa: E402

# ---- .vszh5 refreshed WHILE logging (RAM spilled first, sampling continues)
vz_file = gui_dir / app.SESSION_VSZH5_NAME
win.controller.last_export_ok = None
win.controller.export_vszh5(render=False)
wait_for_export()
assert win.controller.last_export_ok, "mid-session .vszh5 export failed"
assert win.controller.sampler is not None, "logging stopped during the export"
with h5py.File(vz_file, "r") as h5:
    n_mid = h5["Veusz/Data/raw`SLfreq_ghz/data"].shape[0]
assert n_mid >= 4, n_mid
assert not list(gui_dir.glob("*.part")), "partial files left behind"
qapp.processEvents(); time.sleep(0.4)

win.controller.last_export_ok = None
win.controller.stop_logging(); qapp.processEvents()
wait_for_export()                           # automatic export at stop

ev = list(csv.DictReader((gui_dir / "state_events.csv").open()))
tl = list(csv.DictReader((gui_dir / "telemetry.csv").open()))
tx = list(csv.DictReader((gui_dir / "transactions.csv").open()))
params = [r["parameter"] for r in ev]
freqs = [float(r["value"]) for r in ev if r["parameter"] == "frequency_hz"]
assert freqs == [8.25e9, 11.0e9, 14.75e9], freqs
assert "power_dbm" in params and "rf_output" in params
assert all(r["iso_utc"].endswith("Z") for r in ev)
assert len(tl) >= 4 and tl[-1]["mod_hex"] and tl[-1]["rate_hz"]
meta2 = json.loads((gui_dir / "session_metadata.json").read_text())
assert meta2["sampler"]["rate_hz"] == 10.0
assert meta2["transport"]["simulated"] is True
assert meta2["transport"]["max_command_bytes"] == 64
print(f"GUI session logging .............. OK  {len(ev)} state events "
      f"{[p for p in params]}, {len(tl)} telemetry rows, {len(tx)} transactions")
print(f"                                   commanded freqs logged: "
      f"{[f/1e9 for f in freqs]} GHz at {meta2['sampler']['rate_hz']} Hz")

# ---- the .vszh5 written by the controller at stop holds the whole session
assert win.controller.last_export_ok, "end-of-session .vszh5 export failed"
assert not list(gui_dir.glob("*.vsz")), "a text .vsz was written"
with h5py.File(vz_file, "r") as h5:
    data = h5["Veusz/Data"]
    n_end = data["raw`SLfreq_ghz/data"].shape[0]
    tags = sorted(h5["Veusz/Document/Tags"].keys())
    commanded = list(data["events`SLfreq_ghz/data"][...])
    script = h5["Veusz/Document/document"][0]
    script = script.decode() if isinstance(script, bytes) else str(script)
    csv_freq = np.array([float(r["freq_hz"]) for r in tl]) / 1e9
    freq_vz = data["raw`SLfreq_ghz/data"][...]
assert n_end == len(tl), (n_end, len(tl))            # every logged sample
assert n_end > n_mid, (n_mid, n_end)                 # refresh was mid-session
assert np.allclose(freq_vz, csv_freq, rtol=0, atol=1e-12), "freq differs from CSV"
assert commanded == [8.25, 11.0, 14.75], commanded
assert tags == ["events", "meta", "raw"] or tags == ["events", "meta", "raw", "stability"], tags
assert "Add('page', name='page_overview'" in script
print(f"GUI .vszh5 export ................ OK  {n_mid} samples mid-session, "
      f"{n_end} at stop (= telemetry.csv), commanded {[float(c) for c in commanded]} GHz, tags {tags}")

# reconnect for the capability-gating check
win.controller.connect_instrument("SIM", 115200, True); qapp.processEvents()

# capability gating for a model with no modulation hardware
win.controller.driver.capability = app.MODEL_TABLE["FSL-2740"]
win.controller._apply_capability_limits(); qapp.processEvents()
assert not win.tabs.isTabEnabled(mod_idx), "FSL-2740 modulation tab not hidden"
assert win.tab_main.freq_spin.maximum() == 40.0
print("capability gating ................ OK  FSL-2740 hides Modulation, "
      "clamps to 40 GHz")

win.controller.disconnect_instrument(); win.close(); qapp.processEvents()
print(f"\nALL CHECKS PASSED -> {d}")
