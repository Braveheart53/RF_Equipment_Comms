# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
"""Headless check of the live SCPI console (View > SCPI console).

Part of the QuickSyn SCPI controller package, version 0.0.6.
Author: William W. Wallace <wwallace@nrao.edu>, NRAO/GBO.
Licence: GPL-3.0-or-later (see ../LICENSE).

Run directly (``python tests/check_console.py``) or through ``tests/run_all.py``.
Needs no instrument and no display: Qt runs on the offscreen platform and
the QuickSyn is replaced by the built-in simulator transport. The GUI module
is found beside this folder (the newest ``quicksyn_scpi_gui_v*.py``), so the
check does not have to be edited when the version changes.

What it checks
---------------
* Line format: write, query, reply, error, empty reply, CR/LF inside a
  reply; the reply arrow sits exactly under the command arrow for both
  sources; the HTML form escapes markup and keeps spacing.
* Thread safety: exchanges emitted from a worker thread are filed on the GUI
  thread (queued signal) and none is lost.
* A full simulated GUI session: the commands you send appear with their
  replies; telemetry polls are hidden by default and shown on request; the
  console count equals the rows of the session's transactions.csv.
* Long pause (0.0.5 defect): 200 000 exchanges while paused hold a bounded
  amount of memory, Resume blocks the GUI only briefly, the view keeps its
  line limit with a notice line for the rest, and polls never push your own
  commands out of the history.
* Filter: applied after a typing pause, at once on Enter, and while paused
  it searches the frozen view only. Clear and Save.
"""

import csv
import gc
import os
import re
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True   # keep __pycache__ out of the package tree
PKG_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG_ROOT))


def newest_gui_module() -> str:
    """Name of the highest-versioned quicksyn_scpi_gui_v*_*_*.py beside tests/."""
    found = []
    for path in PKG_ROOT.glob("quicksyn_scpi_gui_v*_*_*.py"):
        m = re.fullmatch(r"quicksyn_scpi_gui_v(\d+)_(\d+)_(\d+)", path.stem)
        if m:
            found.append((tuple(int(x) for x in m.groups()), path.stem))
    if not found:
        raise SystemExit(f"no quicksyn_scpi_gui_v*.py in {PKG_ROOT}")
    return max(found)[1]


app = __import__(newest_gui_module())
from Qt import QtWidgets  # noqa: E402  (after the GUI module chose the binding)

print(f"module {app.__name__} v{app.__version__}  Qt={app.QT_ABSTRACTION}/{app.QT_BINDING}")
qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
T = app.Transaction
ARROW_CMD, ARROW_REPLY, CROSS, DOTS = "\u2192", "\u2190", "\u2716", "\u22ef"


def pump(seconds: float) -> None:
    """Run the Qt event loop for a while."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)


def plain(rows: list) -> list[str]:
    """Join (text, colour) segments into plain lines."""
    return ["".join(text for text, _ in row) for row in rows]


# ------------------------------------------------------------------ line format
theme = app.ThemeManager(qapp)
theme.apply(app.ThemeManager.LIGHT)
win = app.MainWindow(theme)
win.resize(1180, 960)
win.show()
pump(0.2)
con = win.console
now = time.time()

w = plain(con.format_segments(T(now, "FREQ 12500000000000", None, 0.0009, True), "GUI"))
assert len(w) == 1 and f"GUI  {ARROW_CMD} FREQ 12500000000000  (write, 0.9 ms)" in w[0], w
q = plain(con.format_segments(T(now, "FREQ?", "12500000000000", 0.0081, True, "", True), "GUI"))
assert len(q) == 2 and q[1].strip() == f"{ARROW_REPLY} 12500000000000  (8.1 ms)", q
assert q[0].index(ARROW_CMD) == q[1].index(ARROW_REPLY), "GUI reply not under command"
p = plain(con.format_segments(T(now, "STAT?", "00A8", 0.0067, True, "", True), "POLL"))
assert p[0].index(ARROW_CMD) == p[1].index(ARROW_REPLY), "POLL reply not under command"
assert q[0].index(ARROW_CMD) == p[0].index(ARROW_CMD), "GUI and POLL columns differ"
e = plain(con.format_segments(T(now, "POW?", None, 0.5, False, "empty response (timeout)", True), "GUI"))
assert e[1].strip().startswith(f"{CROSS} empty response (timeout)"), e
ew = plain(con.format_segments(T(now, "OUTP:STAT ON", None, 0.001, False, "port closed"), "GUI"))
assert len(ew) == 1 and f"{CROSS} port closed" in ew[0], ew
er = plain(con.format_segments(T(now, "*IDN?", "", 0.002, True, "", True), "GUI"))
assert "(empty reply)" in er[1], er
lf = plain(con.format_segments(T(now, "X?", "a\r\nb", 0.002, True, "", True), "GUI"))
assert len(lf) == 2 and "a\u21b5b" in lf[1], lf
h = con.format_lines(T(now, "DIAG:X <a&b>", None, 0.001, True), "GUI")[0]
assert "&lt;a&amp;b&gt;" in h and "&nbsp;" in h and "<a&b>" not in h, h
print("line format ....................... OK  write/query/error/empty/CR-LF; "
      f"reply under command at column {q[0].index(ARROW_CMD)} for GUI and POLL")

# ---------------------------------------------------------------- thread safety
on_gui_thread: list[bool] = []
win.controller.transactionLogged.connect(
    lambda *_: on_gui_thread.append(threading.current_thread() is threading.main_thread()))
N_THREAD = 5000


def worker() -> None:
    for i in range(N_THREAD):
        win.controller.transactionLogged.emit(
            T(time.time(), "STAT?", f"{i:04X}", 0.001, True, "", True), "POLL")


th = threading.Thread(target=worker)
th.start()
while th.is_alive():
    pump(0.02)
th.join()
pump(0.5)
assert len(on_gui_thread) == N_THREAD and all(on_gui_thread), (len(on_gui_thread), set(on_gui_thread))
assert con._n_total == N_THREAD and con._n_polls == N_THREAD, con.stats_label.text()
print(f"thread safety ..................... OK  {N_THREAD} exchanges from a worker "
      "thread, all filed on the GUI thread, none lost")
con.clear()

# ------------------------------------------------------- simulated GUI session
tmp = Path(tempfile.mkdtemp(prefix="qs_console_"))
win.tab_monitor.logdir_edit.setText(str(tmp))
ctl = win.controller
ctl.connect_instrument("SIM", 115200, True)
ctl.guard(lambda: ctl.driver.set_frequency(12.5e9))
ctl.guard(lambda: ctl.driver.get_frequency())
win.tab_monitor.rate_spin.setValue(20.0)
ctl.start_logging()
pump(1.5)
ctl.guard(lambda: ctl.driver.set_power(-3.0))
pump(0.5)
session_dir = ctl.session.directory
ctl.stop_logging()
pump(0.5)
text = con.view.toPlainText()
assert f"{ARROW_CMD} FREQ 12500000000000" in text, text[:400]
assert f"{ARROW_REPLY} 12500000000000" in text, "FREQ? reply missing"
assert f"{ARROW_CMD} POW -3.0" in text, "POW command missing"
assert " POLL " not in text, "polls shown although hidden by default"
assert con._n_polls > 10, con.stats_label.text()
with open(Path(session_dir) / "transactions.csv", newline="", encoding="utf-8") as fh:
    n_csv = sum(1 for _ in csv.DictReader(fh))
assert n_csv == con._n_total, (n_csv, con._n_total)
con.chk_polls.setChecked(True)
pump(0.2)
assert " POLL " in con.view.toPlainText(), "polls not shown on request"
con.chk_polls.setChecked(False)
pump(0.2)
print(f"GUI session ....................... OK  {con._n_total} exchanges = "
      f"{n_csv} rows of transactions.csv; {con._n_polls} polls hidden by default, "
      "shown on request")

# -------------------------------------------------------------- long pause (0.0.5)
N_PAUSE = 200_000
for show_polls in (False, True):
    con.clear()
    con.chk_polls.setChecked(show_polls)
    con.pause_button.setChecked(True)
    pump(0.05)
    shown_before = con.view.blockCount()
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    t0 = time.time()
    for i in range(N_PAUSE):
        con.add_transaction(T(t0 + i * 0.03, "STAT?", f"{i & 0xFF:04X}", 0.006,
                              True, "", True), "POLL")
        if i % 1000 == 0:
            con.add_transaction(T(t0 + i * 0.03, f"FREQ {i}", None, 0.001, True), "GUI")
    gc.collect()
    held_mb = (tracemalloc.get_traced_memory()[0] - base) / 1e6
    tracemalloc.stop()
    pump(0.3)                                    # paused ticks draw nothing
    assert con.view.blockCount() == shown_before, "view changed while paused"
    assert con.held_count == N_PAUSE + N_PAUSE // 1000, con.held_count
    assert "paused:" in con.stats_label.text(), con.stats_label.text()
    t1 = time.perf_counter()
    con.pause_button.setChecked(False)
    qapp.processEvents()
    resume_s = time.perf_counter() - t1
    lines = con.view.toPlainText().splitlines()
    assert held_mb < 10.0, f"{held_mb:.1f} MB held while paused"
    assert resume_s < 2.0, f"Resume blocked the GUI for {resume_s:.2f} s"
    assert con.view.blockCount() <= con.MAX_LINES
    assert all(len(s) <= con.MAX_RECORDS for s in con._store.values())
    # Polls never push your own commands out of the history: all are held,
    # and with polls hidden all of them are on screen.
    assert len(con._store["GUI"]) == N_PAUSE // 1000, len(con._store["GUI"])
    if show_polls:
        assert lines[0].startswith(DOTS) and "not shown here" in lines[0], lines[0]
        con.chk_polls.setChecked(False)
        qapp.processEvents()
        lines = con.view.toPlainText().splitlines()
    else:
        assert not lines[0].startswith(DOTS), lines[0]
    gui_lines = [s for s in lines if " GUI " in s]
    assert len(gui_lines) == N_PAUSE // 1000, len(gui_lines)
    label = f"long pause, polls {'shown' if show_polls else 'hidden'} "
    print(f"{label:.<35} OK  "
          f"{N_PAUSE + N_PAUSE // 1000} exchanges held {held_mb:.1f} MB, Resume "
          f"{resume_s * 1e3:.0f} ms, view within {con.MAX_LINES} lines"
          f"{' + notice' if show_polls else ''}, all {len(gui_lines)} own commands kept")
con.chk_polls.setChecked(False)
pump(0.1)

# ------------------------------------------------------------------- filter
con.clear()
for i in range(50):
    con.add_transaction(T(time.time(), f"POW {i}", None, 0.001, True), "GUI")
    con.add_transaction(T(time.time(), "FREQ?", "1", 0.001, True, "", True), "GUI")
pump(0.3)
con.filter_edit.setText("POW")
qapp.processEvents()
assert "FREQ?" in con.view.toPlainText(), "filter applied before the typing pause"
pump(0.5)
assert "FREQ?" not in con.view.toPlainText() and "POW 49" in con.view.toPlainText()
con.filter_edit.setText("FREQ")
con.filter_edit.returnPressed.emit()            # Enter applies at once
assert "POW 1" not in con.view.toPlainText()
con.filter_edit.setText("")
con.filter_edit.returnPressed.emit()
con.pause_button.setChecked(True)
con.add_transaction(T(time.time(), "POW 777", None, 0.001, True), "GUI")
con.filter_edit.setText("POW 7")
con.filter_edit.returnPressed.emit()
assert "POW 7" in con.view.toPlainText() and "POW 777" not in con.view.toPlainText()
con.pause_button.setChecked(False)
qapp.processEvents()
assert "POW 777" in con.view.toPlainText(), "Resume did not add the held exchange"
con.filter_edit.setText("")
con.filter_edit.returnPressed.emit()
print("filter ............................ OK  waits for typing pause, Enter at once, "
      "paused view searched frozen, Resume adds the rest")

# --------------------------------------------------------------- clear and save
n_saved = con.save_to(tmp / "console.txt")
assert n_saved == con.view.blockCount() and (tmp / "console.txt").stat().st_size > 0
con.clear()
assert con.view.blockCount() == 1 and con._n_total == 0 and con.records == []
print(f"clear and save .................... OK  {n_saved} lines saved, then cleared")

ctl.disconnect_instrument()
win.close()
qapp.processEvents()
print(f"\nALL CONSOLE CHECKS PASSED -> {tmp}")
