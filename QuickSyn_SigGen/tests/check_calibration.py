# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Calibration tab (program-side) and the 10 MHz output status bit.

Part of the QuickSyn SCPI controller package, version 0.0.10.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_calibration.py``) or through
``tests/run_all.py``. Needs no instrument, no meter, no display and no
PyVISA: Qt runs offscreen, the synthesizer is the built-in simulator, and
the power meter and counter are fake PyVISA resource managers passed in
through ``InstrumentReader(rm_factory=...)``.

What it checks
---------------
1. Path loss: constant, CSV (units from the header or by magnitude, S21
   given as negative dB), Touchstone v1 (DB, MA, RI) and v2 (both
   [Two-Port Data Order] values, noise data ignored), refusal of 1- and
   3-port files, and no extrapolation.
2. Power tables: interpolation, the band edge, level correction
   (command_for_target) against a synthetic unit, JSON and CSV round trip,
   refusal of another file kind and of a newer schema.
3. Reference tuning: the secant search reaches +/-20 Hz at 10 GHz against a
   slightly non-linear OCXO model, from either side, and stays in range.
4. Per-unit store under QUICKSYN_CAL_DIR, and the PyVISA reader with a
   fake resource manager (IDN, pre-command with the frequency, numeric
   reply, errors), plus the "PyVISA not installed" message.
5. NI soft-front-panel commands captured on the FSL-0020 (2026-10-13/14):
   power 03xxxx for -13 ... +20 dBm, RF 0F00/0F01, reference output
   0800/0801, reference source 0600/0601, 100 MHz = 0x174876E800 mHz.
6. GUI on a simulated FSL-0020: a 20-point plan, typed readings (Enter
   records and moves on), an automatic run with the fake meter, save,
   reload on reconnect, the expected level on the Main tab, CSV and
   .vszh5 export; OCXO tuning with the fake counter, save, and the value
   re-sent on connect.
7. 10 MHz output on a unit whose STAT? bit 5 stays set (as on the
   FSL-0020): with and without OUTP:ROSC:STAT? answering.
8. GUI on a simulated FSW-0020 (power control): a 3-level table and the
   commanded level corrected so the typed level appears at RF OUT; a table
   of another unit is not extended.
"""

import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree

WORK = Path(tempfile.mkdtemp(prefix="quicksyn_cal_check_"))
os.environ["QUICKSYN_CAL_DIR"] = str(WORK / "cal")    # before the GUI reads it

import numpy as np  # noqa: E402

import quicksyn_scpi_gui_v0_0_10 as app  # noqa: E402

print(f"module v{app.__version__}  work folder {WORK}")
CE = app.CalibrationError


def raises(exc_type, fn, *args, **kw) -> str:
    """Call fn and return the message of the expected exception (or fail)."""
    try:
        fn(*args, **kw)
    except exc_type as exc:
        return str(exc)
    raise AssertionError(f"{fn.__name__} did not raise {exc_type.__name__}")


# ===================================================================== 1. path loss
assert app.PathLoss().loss_at(5e9) == 0.0
assert app.PathLoss(kind="constant", constant_db=1.25).loss_at(19e9) == 1.25
csv1 = WORK / "loss_ghz.csv"
csv1.write_text("freq_GHz,loss_dB\n1,0.5\n10,2.0\n20,3.0\n", encoding="utf-8")
pl = app.PathLoss.from_csv(csv1)
assert math.isclose(pl.loss_at(5.5e9), 1.25) and math.isclose(pl.loss_at(15e9), 2.5)
assert "outside" in raises(CE, pl.loss_at, 25e9).lower() or "range" in raises(CE, pl.loss_at, 25e9).lower()
csv2 = WORK / "s21_hz.csv"                       # no header, Hz by magnitude, S21 negative
csv2.write_text("1000000000,-0.5\n10000000000,-2.0\n20000000000,-3.0\n", encoding="utf-8")
assert math.isclose(app.PathLoss.from_csv(csv2).loss_at(10e9), 2.0)
csv3 = WORK / "mhz.csv"
csv3.write_text("frequency (MHz),loss\n1000,0.5\n20000,3.0\n", encoding="utf-8")
assert math.isclose(app.PathLoss.from_csv(csv3).loss_at(20e9), 3.0)

# Touchstone: a cable with |S21| = 10^(-L/20), L = 0.6 sqrt(f/GHz) + 0.05 f/GHz [Pozar]
fghz = np.array([1.0, 5.0, 10.0, 15.0, 20.0])
loss = 0.6 * np.sqrt(fghz) + 0.05 * fghz
mag = 10 ** (-loss / 20)
ph = -360.0 * fghz * 0.3                          # arbitrary phase, must not matter
rows_db = [f"{f} -0.0 0 {-l:.6f} {p:.3f} {-l:.6f} {p:.3f} -30 0" for f, l, p in zip(fghz, loss, ph)]
rows_ma = [f"{f} 0.01 0 {m:.9f} {p:.3f} {m:.9f} {p:.3f} 0.01 0" for f, m, p in zip(fghz, mag, ph)]
rows_ri = [f"{f} 0.01 0 {m * math.cos(math.radians(p)):.9f} {m * math.sin(math.radians(p)):.9f} "
           f"{m:.9f} 0 0.01 0" for f, m, p in zip(fghz, mag, ph)]
for fmt, rows in (("DB", rows_db), ("MA", rows_ma), ("RI", rows_ri)):
    path = WORK / f"cable_{fmt}.s2p"
    path.write_text(f"! test cable\n# GHz S {fmt} R 50\n" + "\n".join(rows) + "\n", encoding="utf-8")
    t = app.PathLoss.from_touchstone(path)
    for f, l in zip(fghz, loss):
        assert abs(t.loss_at(f * 1e9) - l) < 1e-5, (fmt, f, t.loss_at(f * 1e9), l)
# v2 with the 21_12 order: S21 is the 2nd pair; v2 with 12_21: S21 is the 3rd pair
for order, s21_col in (("21_12", 1), ("12_21", 2)):
    lines = ["[Version] 2.0", "# MHz S DB R 50", "[Number of Ports] 2",
             f"[Two-Port Data Order] {order}", "[Number of Frequencies] 3",
             "[Network Data]"]
    for f_mhz, l in ((1000, 0.5), (10000, 2.0), (20000, 3.0)):
        pairs = [[-30.0, 0.0], [-9.0, 0.0], [-9.0, 0.0], [-30.0, 0.0]]
        pairs[s21_col] = [-l, 10.0]
        lines.append(f"{f_mhz} " + " ".join(f"{a} {b}" for a, b in pairs))
    lines += ["[Noise Data]", "1000 1.0 0.5 10 0.2", "[End]"]
    path = WORK / f"cable_v2_{order}.s2p"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert math.isclose(app.PathLoss.from_touchstone(path).loss_at(10e9), 2.0, abs_tol=1e-9), order
s1p = WORK / "load.s1p"
s1p.write_text("# GHz S DB R 50\n1 -20 0\n2 -20 0\n", encoding="utf-8")
assert ".s2p" in raises(CE, app.PathLoss.from_touchstone, s1p)
d = app.PathLoss.from_touchstone(WORK / "cable_DB.s2p").to_dict()
assert math.isclose(app.PathLoss.from_dict(d).loss_at(10e9), loss[2], abs_tol=1e-6)
print("path loss ........................ OK  constant, CSV (GHz/MHz/Hz, S21 sign), "
      "Touchstone DB/MA/RI, v2 21_12/12_21, .s1p refused")

# ===================================================================== 2. power tables
fixed = app.PowerCalTable(model="FSL-0020", serial="1530200407")
for f in (1e9, 10e9, 20e9):
    out = 12.0 - 0.4 * f / 1e9                  # synthetic FSL-0020 level at RF OUT
    fixed.add(app.PowerCalPoint(f, None, out - 1.5, 1.5, time.time(), "test"))
assert fixed.levels() == [None]
assert math.isclose(fixed.expected_output(5.5e9), 12.0 - 0.4 * 5.5)
assert fixed.expected_output(0.7e9) is None and fixed.expected_output(20.5e9) is None
assert fixed.command_for_target(10e9, 5.0, -10, 13) is None   # nothing to command
p = fixed.save(WORK / "fixed.json")
back = app.PowerCalTable.load(p)
assert back.to_dict() == fixed.to_dict()
csv_rows = (WORK / "fixed.csv")
fixed.to_csv(csv_rows)
assert csv_rows.read_text(encoding="utf-8").count("\n") == 4
bad = json.loads(p.read_text(encoding="utf-8"))
bad["schema"] = 99
(WORK / "newer.json").write_text(json.dumps(bad), encoding="utf-8")
assert "newer" in raises(CE, app.PowerCalTable.load, WORK / "newer.json")
(WORK / "other.json").write_text(json.dumps({"kind": "something"}), encoding="utf-8")
assert "Not a QuickSyn" in raises(CE, app.PowerCalTable.load, WORK / "other.json")


def fsw_unit(set_dbm: float, f_hz: float) -> float:
    """Synthetic FSW: RF OUT = set - (0.5 + 0.15 f/GHz) + 0.02 set (dBm)."""
    return set_dbm - (0.5 + 0.15 * f_hz / 1e9) + 0.02 * set_dbm


levelled = app.PowerCalTable(model="FSW-0020", serial="X1")
for lvl in (-10.0, 0.0, 13.0):
    for f in (2e9, 6e9, 10e9, 14e9, 18e9):
        levelled.add(app.PowerCalPoint(f, lvl, fsw_unit(lvl, f), 0.0))
assert levelled.levels() == [-10.0, 0.0, 13.0]
for f, target in ((10e9, 0.0), (4e9, -5.0), (16e9, 8.0), (18e9, 9.0)):
    cmd = levelled.command_for_target(f, target, -10.0, 13.0)
    exact = (target + 0.5 + 0.15 * f / 1e9) / 1.02
    assert abs(cmd - exact) <= 0.05 + 1e-9, (f, target, cmd, exact)
    assert abs(fsw_unit(cmd, f) - target) <= 0.06, (f, target, cmd)
assert levelled.command_for_target(18e9, 13.0, -10.0, 13.0) == 13.0       # clamped
assert levelled.command_for_target(19e9, 0.0, -10.0, 13.0) is None        # outside the band
print("power tables ..................... OK  fixed and 3-level tables, band edges, "
      "command_for_target within 0.05 dB, JSON/CSV, newer schema refused")

# ===================================================================== 3. reference tuning
DAC0 = 31234                                       # synthetic on-frequency DAC word


def ocxo(dac: int, f_out: float = 10e9) -> float:
    """Synthetic OCXO: ~0.3 Hz/count at 10 GHz with a little curvature."""
    x = dac - DAC0
    return f_out * (1 + 3.0e-11 * x + 2.0e-16 * x * x)


for start in (30000, 33500, 12000):
    tuner = app.RefCalTuner(10e9, 20.0, 500, start)
    dac = start
    for _ in range(10):
        tuner.record(dac, ocxo(dac))
        if tuner.converged():
            break
        dac = tuner.next_dac()
    assert tuner.converged(), (start, [(i.dac, i.error_hz) for i in tuner.iterations])
    assert len(tuner.iterations) <= 6, len(tuner.iterations)
    assert abs(tuner.best().error_hz) <= 20.0 and tuner.next_dac() == tuner.best().dac
t2 = app.RefCalTuner(10e9, 20.0, 500, 65400)
t2.record(65400, 10e9 - 5000)
assert t2.next_dac() == 65535                      # clamped to the 16-bit range
assert "not usable" in raises(CE, t2.record, 100, float("nan"))
print("reference tuning ................. OK  converges to +/-20 Hz at 10 GHz from 3 starts "
      "(<= 6 measurements), DAC clamped")

# ===================================================================== 4. store and reader
assert app.cal_dir() == WORK / "cal"
store = app.CalStore()
dated, active = store.save_power(fixed)
assert dated.exists() and dated.with_suffix(".csv").exists() and active.name == "active_power_cal.json"
assert store.load_active_power("FSL-0020", "1530200407").to_dict() == fixed.to_dict()
assert store.load_active_power("FSL-0020", "nope") is None
rec = app.RefCalRecord("FSL-0020", "1530200407", 31230, 30000, 10e9, 10e9 + 1.2,
                       "2026-10-14T12:00:00Z", True)
store.save_ref(rec)
rec.dac = 31231
store.save_ref(rec)
assert store.load_ref("FSL-0020", "1530200407").dac == 31231
hist = (store.unit_dir("FSL-0020", "1530200407") / "ref_cal_history.csv").read_text(encoding="utf-8")
assert hist.count("\n") == 3, hist


class FakeInstrument:
    """Minimal stand-in for a PyVISA message-based resource."""

    def __init__(self, reply_fn, idn: str) -> None:
        self.reply_fn = reply_fn
        self.idn = idn
        self.timeout = 0
        self.read_termination = self.write_termination = None
        self.writes: list[str] = []
        self.freq_hz = 0.0
        self.closed = False

    def write(self, command: str) -> None:
        self.writes.append(command)
        if command.upper().startswith("SENS:FREQ"):
            self.freq_hz = float(command.split()[1])

    def query(self, command: str) -> str:
        self.writes.append(command)
        return self.idn + "\n" if command == "*IDN?" else self.reply_fn(self) + "\n"

    def close(self) -> None:
        self.closed = True


class FakeRM:
    """Minimal stand-in for pyvisa.ResourceManager."""

    def __init__(self, inst: FakeInstrument) -> None:
        self.inst = inst
        self.backends: list[str] = []

    def __call__(self, backend: str) -> "FakeRM":     # used as rm_factory
        self.backends.append(backend)
        return self

    def open_resource(self, name: str) -> FakeInstrument:
        if not name.startswith("GPIB0::13"):
            raise OSError(f"VI_ERROR_RSRC_NFOUND {name}")
        return self.inst

    def list_resources(self) -> tuple[str, ...]:
        return ("GPIB0::13::INSTR", "USB0::0x2A8D::0x1F01::MY1234::INSTR")

    def close(self) -> None:
        pass


meter = FakeInstrument(lambda inst: f"{-3.21:+.5E}", "Agilent Technologies,E4418B,GB0000,A2.10")
rm = FakeRM(meter)
cfg = app.MeterConfig(resource="GPIB0::13::INSTR", backend="@py", query="MEAS?",
                      pre_command="SENS:FREQ {freq_hz:.0f}")
reader = app.InstrumentReader(cfg, rm_factory=rm)
assert reader.open().startswith("Agilent Technologies,E4418B")
assert reader.read(12.5e9) == -3.21 and meter.writes[-2:] == ["SENS:FREQ 12500000000", "MEAS?"]
assert rm.backends == ["@py"] and len(reader.list_resources()) == 2
reader.close()
assert meter.closed and not reader.is_open
bad_cfg = app.MeterConfig(resource="GPIB0::22::INSTR")
assert "RSRC_NFOUND" in raises(CE, app.InstrumentReader(bad_cfg, rm_factory=rm).open)
assert "No VISA resource" in raises(CE, app.InstrumentReader(app.MeterConfig()).open)
junk = app.InstrumentReader(cfg, rm_factory=FakeRM(FakeInstrument(lambda i: "OVLD", "x")))
assert "not a number" in raises(CE, junk.read, 1e9)
have_pyvisa = app.InstrumentReader.available()
if not have_pyvisa:
    assert "mamba install -c conda-forge pyvisa" in raises(CE, app.InstrumentReader(cfg).open)
print(f"store and PyVISA reader ........... OK  per-unit JSON/CSV/history; fake E4418B: IDN, "
      f"SENS:FREQ, MEAS?, errors (pyvisa installed: {have_pyvisa})")

# ===================================================================== 5. NI panel vectors
NI_POWER = {"03FFEA": -2.2, "03FFD8": -4.0, "03FFD4": -4.4, "03FFCC": -5.2, "03FFC9": -5.5,
            "03FFC7": -5.7, "03FFC5": -5.9, "030000": 0.0, "030096": 15.0, "0300C8": 20.0,
            "03FF7E": -13.0}
for command, dbm in NI_POWER.items():
    assert app.native_power_command(dbm) == command, (dbm, app.native_power_command(dbm))
    assert app.decode_native_power(command[2:]) == dbm, command
for header, name in ((app.NATIVE_RF_OUTPUT, "0F"), (app.NATIVE_REF_OUTPUT, "08"),
                     (app.NATIVE_REF_SOURCE, "06")):
    assert (app.native_switch_command(header, False), app.native_switch_command(header, True)) \
        == (f"{name}00", f"{name}01"), name
assert app.hz_to_mlhz(100e6) == 0x174876E800 and f"0C{app.hz_to_mlhz(100e6):012X}" == "0C00174876E800"
print("NI panel command vectors ......... OK  11 power words (-13 ... +20 dBm), 0F/08/06 "
      "switches, 100 MHz = 0x174876E800 mHz")

# ===================================================================== 6. GUI, FSL-0020
from Qt import QtCore, QtTest, QtWidgets  # noqa: E402

app.WAIT_REF_DAC_S = 0.0           # the simulator does not need the OCXO settle time
qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
ORIGINAL_SIM = app.SimulatedTransport


class FslSim(ORIGINAL_SIM):
    """Simulated FSL-0020: fixed output, STAT? bit 5 held set (as measured)."""

    def __init__(self, on_transaction=None) -> None:
        super().__init__(on_transaction=on_transaction, model="FSL-0020", power_control=False)
        self.refout_status_bit_follows = False
        self.refout_query_supported = False


def pump(seconds: float = 0.2) -> None:
    """Run the Qt event loop for a short time (lets singleShot actions fire)."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        qapp.processEvents()
        time.sleep(0.003)


def pump_until(predicate, timeout_s: float = 20.0) -> None:
    """Run the event loop until predicate() is true (or fail)."""
    end = time.perf_counter() + timeout_s
    while not predicate():
        if time.perf_counter() > end:
            raise AssertionError("timed out waiting for the GUI")
        qapp.processEvents()
        time.sleep(0.003)


theme = app.ThemeManager(qapp)
win = app.MainWindow(theme)
win.resize(1500, 950)
win.show(); qapp.processEvents()
cal = win.tab_cal
cal_idx = win.tabs.indexOf(cal)
assert win.tabs.tabText(cal_idx) == "Calibration"
assert win.tabs.isTabEnabled(cal_idx), "Calibration must stay open offline"
assert not win.tabs.isTabEnabled(win.tabs.indexOf(win.tab_main))
assert str(WORK / "cal") in cal.findChildren(QtWidgets.QLabel)[0].text()
sent: list[str] = []
win.controller.transactionLogged.connect(lambda t, src: sent.append(t.command))

app.SimulatedTransport = FslSim
win.controller.connect_instrument("SIM", 115200, True); pump()
sim = win.controller.transport
assert win.controller.driver.identity.model == "FSL-0020"
serial = win.controller.driver.identity.serial
assert not cal.levels_edit.isEnabled() and not cal.correct_check.isEnabled()
assert "no power calibration" in win.tab_main.cal_output_label.text()


def fsl_level(inst: FakeInstrument) -> str:
    """Fake power meter on the FSL: 12 - 0.4 f/GHz at RF OUT, 1.5 dB path, RF state honoured."""
    f = sim._state["freq_mlhz"] / 1e12
    assert abs(inst.freq_hz / 1e9 - f) < 1e-9, "meter told the wrong frequency"
    level = (12.0 - 0.4 * f - 1.5) if sim._state["rf_out"] else -70.0
    return f"{level:+.4E}"


win.tabs.setCurrentWidget(cal)
cal.subtabs.setCurrentIndex(0)
cal.start_f.setValue(1.0); cal.stop_f.setValue(20.0); cal.step_f.setValue(1.0)
cal.generate_button.click(); pump()
assert len(cal.plan) == 20 and "20 points" in cal.plan_label.text(), cal.plan_label.text()
cal.path_combo.setCurrentIndex(cal.path_combo.findData("constant"))
cal.path_const.setValue(1.5); pump()
assert "1.5" in cal.path_label.text() and "path loss 1.50 dB" in cal.point_label.text()
sim._state["rf_out"] = False
sent.clear()
cal.goto_button.click(); pump()
assert sim._state["rf_out"] and abs(sim._state["freq_mlhz"] - 1e12) < 1, sent
assert not any(c.startswith("POW") for c in sent), "fixed-output model must not get POW"
for k in range(3):                                  # typed readings, Enter records and moves on
    f_ghz = k + 1.0
    cal.reading_spin.setFocus(); cal.reading_spin.selectAll()
    QtTest.QTest.keyClicks(cal.reading_spin, f"{12.0 - 0.4 * f_ghz - 1.5:.2f}")
    QtTest.QTest.keyClick(cal.reading_spin, QtCore.Qt.Key.Key_Return)
    pump()
    assert len(cal.table.points) == k + 1, (k, win.statusBar().currentMessage())
    assert abs(sim._state["freq_mlhz"] / 1e12 - (f_ghz + 1.0)) < 1e-9, "auto-advance did not set"
assert cal.power_table.rowCount() == 3 and cal.power_table.item(0, 5).text() == "+11.600"
assert cal.power_table.item(0, 6).text() == "+1.60 vs spec"
# the rest with the (fake) power meter, automatically
cal.meter_widgets["power"]["resource"].setText("GPIB0::13::INSTR")
cal._apply_meter_fields()
cal.readers["power"] = app.InstrumentReader(
    cal.power_meter_cfg, rm_factory=FakeRM(FakeInstrument(fsl_level, "Agilent,E4418B,1,A2")))
cal.settle_spin.setValue(0.0)
cal.auto_run_button.click()
pump_until(lambda: not cal._auto_running)
assert "finished" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
assert len(cal.table.points) == 20 and cal.table.meter.startswith("Agilent,E4418B")
outs = [p.output_dbm for p in cal.table.points]
assert np.allclose(outs, [12.0 - 0.4 * f for f in range(1, 21)], atol=1e-3), outs
assert cal.power_table.item(19, 6).text() == "-6.00 vs spec"
cal.save_button.click(); pump()
unit_dir = WORK / "cal" / f"FSL-0020_{serial}"
assert (unit_dir / "active_power_cal.json").exists(), win.statusBar().currentMessage()
assert "20 points" in cal.active_label.text()
# Main tab: level expected at RF OUT
win.tabs.setCurrentWidget(win.tab_main)
win.tab_main.freq_spin.setValue(10.5); win.tab_main.set_freq_button.click(); pump()
assert "+7.80 dBm expected at 10.500000 GHz" in win.tab_main.cal_output_label.text(), \
    win.tab_main.cal_output_label.text()
win.tab_main.freq_spin.setValue(0.8); win.tab_main.set_freq_button.click(); pump()
assert "outside the calibrated band" in win.tab_main.cal_output_label.text()
cal.show_expected_check.setChecked(False)
assert "hidden" in win.tab_main.cal_output_label.text()
cal.show_expected_check.setChecked(True)
# exports
cal._export_csv_dialog(str(WORK / "fsl_cal.csv"))
assert (WORK / "fsl_cal.csv").read_text(encoding="utf-8").count("\n") == 21
written = app.export_power_cal_vszh5(cal.table, WORK / "fsl_cal.vszh5")
import h5py  # noqa: E402

with h5py.File(written, "r") as h5:
    names = sorted(h5["Veusz/Data"].keys())
    script = h5["Veusz/Document/document"][0]
    script = script.decode() if isinstance(script, bytes) else str(script)
assert "cal_freq_ghz_fixed" in names and "cal_spec_dbm" in names, names
assert "Add('page', name='page_power_cal'" in script and "datasheet minimum +10 dBm" in script
win.tabs.setCurrentWidget(cal); pump(0.3)
shot = WORK / "calibration_tab_power.png"
cal.grab().save(str(shot))
# reconnect: the active table comes back by itself
win.controller.disconnect_instrument(); pump()
assert win.tabs.isTabEnabled(cal_idx)
win.controller.connect_instrument("SIM", 115200, True); pump()
sim = win.controller.transport
assert cal.active_table is not None and len(cal.active_table.points) == 20
cal._load_table_dialog(str(unit_dir / "active_power_cal.json"))
assert len(cal.table.points) == 20
print("GUI power calibration (FSL-0020) . OK  20 points: 3 typed (Enter + auto-advance), 17 by the "
      "fake meter; saved, reloaded on connect,")
print("                                   Main tab +7.80 dBm at 10.5 GHz, out-of-band noted; "
      "CSV and .vszh5 exports")


# --- reference tuning with a fake counter
def counter_reading(inst: FakeInstrument) -> str:
    """Fake counter on RF OUT: the simulator's frequency through the OCXO model."""
    assert sim._state["ref_source"] == "INT" and sim._state["rf_out"]
    return f"{ocxo(sim._state['ref_dac'], sim._state['freq_mlhz'] / 1e3):.3f}"


cal.subtabs.setCurrentIndex(1)
cal.ref_start_button.click(); pump()
assert cal.tuner is not None and cal.tuner.original_dac == 30000, win.statusBar().currentMessage()
cal.meter_widgets["counter"]["resource"].setText("GPIB0::13::INSTR")
cal._apply_meter_fields()
cal.readers["counter"] = app.InstrumentReader(
    cal.counter_cfg, rm_factory=FakeRM(FakeInstrument(counter_reading, "Pendulum,CNT-90,1,1")))
for _ in range(8):
    cal.ref_read_counter_button.click(); pump()
    if cal.tuner.converged():
        break
assert cal.tuner.converged(), [(i.dac, i.error_hz) for i in cal.tuner.iterations]
best = cal.tuner.best()
assert "Within tolerance" in win.statusBar().currentMessage()
assert cal.ref_table.rowCount() == len(cal.tuner.iterations) <= 6
cal.ref_apply_on_connect.setChecked(True)
cal.ref_save_button.click(); pump()
saved = json.loads((unit_dir / "ref_cal.json").read_text(encoding="utf-8"))
assert saved["dac"] == best.dac and saved["apply_on_connect"] is True and saved["original_dac"] == 30000
cal.ref_restore_button.click(); pump()
assert sim._state["ref_dac"] == 30000
n_reads = len(cal.tuner.iterations)
win.controller.disconnect_instrument(); pump()
sent.clear()
win.controller.connect_instrument("SIM", 115200, True); pump()
sim = win.controller.transport
assert f"DIAG:CAL:REF:DAC {best.dac}" in sent and sim._state["ref_dac"] == best.dac, sent
assert "Reference calibration applied" in win.statusBar().currentMessage()
print(f"GUI reference tuning ............. OK  DAC 30000 -> {best.dac} in "
      f"{n_reads} counter reads ({best.error_hz:+.2f} Hz at 10 GHz); "
      f"restore; re-sent on connect")

# ===================================================================== 7. REF OUT bit 5 stale
main = win.tab_main
win.tabs.setCurrentWidget(main)
drv = win.controller.driver
assert sim.refout_query_supported is False and sim.refout_status_bit_follows is False
main.refout_check.setChecked(True)
sent.clear()
main.refout_check.click(); pump()                   # OFF: SCPI, STAT?, native, STAT? again
# (OUTP:ROSC:STAT? already found unanswered by "Read all" on connect)
assert drv.refout_query_supported is False
assert sent == ["OUTP:ROSC:STAT OFF", "STAT?", "0800", "STAT?"], sent
assert sim._state["ref_out"] is False and drv.refout_status_reliable is False
assert "not reported" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
assert "not reported (last sent OFF)" in main.led_ref_out.text() and not main.refout_check.isChecked()
sent.clear()
main.refout_check.click(); pump()                   # ON: SCPI alone, no warning, no native
assert sent == ["OUTP:ROSC:STAT ON", "STAT?"], sent
assert sim._state["ref_out"] is True and main.refout_check.isChecked()
assert "does not report" in win.statusBar().currentMessage()
main.refout_check.click(); pump()                   # OFF again
assert sim._state["ref_out"] is False
main.sync_button.click(); pump()                    # Read all: bit 5 (set) must not tick the box
assert not main.refout_check.isChecked() and "not reported" in main.led_ref_out.text()
# with OUTP:ROSC:STAT? answering, the query is trusted over the stale bit
sim.refout_query_supported = True
drv.refout_query_supported = None
drv.refout_status_reliable = None
main.refout_check.setChecked(True); sim._state["ref_out"] = True
sent.clear()
main.refout_check.click(); pump()
assert sent == ["OUTP:ROSC:STAT OFF", "OUTP:ROSC:STAT?", "STAT?"], sent
assert "confirmed by OUTP:ROSC:STAT?" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
assert "Ref output off (OUTP:ROSC:STAT?)" in main.led_ref_out.text() and drv.refout_status_reliable is False
main.sync_button.click(); pump()
assert not main.refout_check.isChecked() and "Ref output off" in main.led_ref_out.text()
print("10 MHz output, stale STAT? bit 5 . OK  no query: 'not reported' after the double failure, "
      "then OUTP:ROSC:STAT alone;")
print("                                   query answering: trusted over bit 5, no native sent")

# ===================================================================== 8. GUI, FSW-0020
win.controller.disconnect_instrument(); pump()
app.SimulatedTransport = ORIGINAL_SIM
win.controller.connect_instrument("SIM", 115200, True); pump()
sim = win.controller.transport
assert win.controller.driver.capability.has_power_control
assert cal.levels_edit.isEnabled() and cal.correct_check.isEnabled() and cal.active_table is None
win.tabs.setCurrentWidget(cal); cal.subtabs.setCurrentIndex(0)
cal.start_f.setValue(2.0); cal.stop_f.setValue(18.0); cal.step_f.setValue(4.0)
cal.levels_edit.setText("-10, 0, 13")
cal.generate_button.click(); pump()
assert len(cal.plan) == 15 and "5 frequencies x 3 levels" in cal.plan_label.text()
cal.path_combo.setCurrentIndex(cal.path_combo.findData("none")); cal._path_changed()
cal.reading_spin.setValue(0.0)
cal.record_button.click(); pump()                     # the FSL table must not be extended
assert "belongs to FSL-0020" in win.statusBar().currentMessage(), win.statusBar().currentMessage()
cal.clear_button.click(); pump()


def fsw_level(inst: FakeInstrument) -> str:
    """Fake power meter on the FSW: synthetic unit, no path loss."""
    return f"{fsw_unit(sim._state['power_dbm'], sim._state['freq_mlhz'] / 1e3):+.4E}"


cal.readers["power"] = app.InstrumentReader(
    cal.power_meter_cfg, rm_factory=FakeRM(FakeInstrument(fsw_level, "Agilent,E4418B,1,A2")))
cal.auto_run_button.click()
pump_until(lambda: not cal._auto_running)
assert len(cal.table.points) == 15 and cal.table.levels() == [-10.0, 0.0, 13.0]
cal.save_button.click(); pump()
assert cal.active_table is not None and cal.active_table.model == "FSW-0020"
cal.correct_check.setChecked(True)
assert cal.correction_enabled()
win.tabs.setCurrentWidget(main)
main.freq_spin.setValue(10.0); main.set_freq_button.click(); pump()
sent.clear()
main.power_spin.setValue(0.0); main.set_power_button.click(); pump()
want = app.quantise_power_dbm((0.0 + 0.5 + 1.5) / 1.02)          # +2.0 dBm
assert f"POW {want:+.1f}" in sent, sent
assert "for +0.0 dBm at RF OUT" in main.power_readback.text(), main.power_readback.text()
assert f"target +0.0 dBm, commanded {want:+.1f} dBm" in main.cal_output_label.text(), \
    main.cal_output_label.text()
sent.clear()
main.freq_spin.setValue(18.0); main.set_freq_button.click(); pump()   # correction follows frequency
want18 = app.quantise_power_dbm((0.0 + 0.5 + 0.15 * 18) / 1.02)
assert f"POW {want18:+.1f}" in sent, sent
cal.correct_check.setChecked(False)
sent.clear()
main.power_spin.setValue(0.0); main.set_power_button.click(); pump()
assert "POW +0.0" in sent, sent
print(f"GUI level correction (FSW-0020) .. OK  15 points (5 f x 3 levels) by the fake meter; "
      f"0 dBm at RF OUT -> POW {want:+.1f} at 10 GHz,")
print(f"                                   POW {want18:+.1f} after moving to 18 GHz; another unit's "
      f"table not extended")

win.controller.disconnect_instrument(); win.close(); qapp.processEvents()
print(f"\nALL CALIBRATION CHECKS PASSED -> {WORK}")
