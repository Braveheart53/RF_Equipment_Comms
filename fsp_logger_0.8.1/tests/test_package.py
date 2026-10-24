# %% DETERMINISTIC SOFTWARE FIXTURES (NOT RF MEASUREMENTS)
import ast
import csv
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
import h5py
import numpy as np
import pytest
from qtpy import QtWidgets
import fsp_background as background
import fsp_reports as reports
import rs_fsp_logger as logger
import vszh5_writer as writer


def fixture_csv(path, captures=3, points=4, traces=(1, 3)):
    with path.open("w", newline="", encoding="utf-8") as stream:
        output = csv.writer(stream)
        output.writerow(["date", "time", "timestamp_iso", "freq_hz"] + ["trace%d_dBm" % number for number in traces])
        for capture in range(captures):
            instant = datetime(2026, 10, 23, 12) + timedelta(seconds=capture * (capture + 1) / 2)
            for point in range(points):
                output.writerow([instant.strftime("%Y-%m-%d"), instant.strftime("%H:%M:%S.%f")[:-3],
                                 instant.isoformat(timespec="milliseconds"), 1e9 + point * 1e6] +
                                [-80 + number + capture * 10 + point for number in traces])
    return path


def wait_until(application, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert predicate(), "Timed out waiting for asynchronous operation"


# %% WRITER / COMPATIBILITY

def test_versions_and_python38_parse():
    assert logger.APP_VERSION == "0.8.1"
    assert writer.__version__ == "0.0.15"
    for module in (logger, writer, reports, background):
        source = Path(module.__file__).read_text(encoding="utf-8")
        ast.parse(source, feature_version=(3, 8))
        assert "# %%" in source


def test_atomic_failure_preserves_old_target(tmp_path):
    target = tmp_path / "existing.vszh5"
    target.write_bytes(b"old data")
    with pytest.raises(ValueError):
        with writer.VeuszWriter(target) as document:
            document.dataset_1d("a", [1])
            document.dataset_1d("a", [2])
    assert target.read_bytes() == b"old data"
    assert not list(tmp_path.glob("*.part"))


def test_private_temporary_files(tmp_path):
    first = writer.VeuszWriter(tmp_path / "same.vszh5")
    second = writer.VeuszWriter(tmp_path / "same.vszh5")
    try:
        assert first.path != second.path
        first.dataset_1d("a", [1])
        first.finish(writer.VszDoc().text())
        second.abort()
        assert writer.dataset_names(tmp_path / "same.vszh5") == ["a"]
    finally:
        first.abort()
        second.abort()


def test_renderer_completion_marker_flush():
    assert "print('VSZH5_DONE', flush=True)" in writer._render_script(Path("file.vszh5"), None, None, "none", 150)


# %% REPORT CONTENT AND VALIDATION
@pytest.mark.parametrize("captures,points,traces", [(1, 1, (2,)), (3, 4, (1, 3)), (4, 8, (1, 2, 3))])
def test_report_data_statistics_pages_and_provenance(tmp_path, captures, points, traces):
    source = fixture_csv(tmp_path / "synthetic.csv", captures, points, traces)
    original = source.read_bytes()
    metadata = reports.create_reports(source, tmp_path / "result")
    assert source.read_bytes() == original
    assert metadata["source_sha256"] == hashlib.sha256(original).hexdigest()
    assert len(metadata["pages"]) == 2 + 3 * len(traces)
    assert writer.page_names(tmp_path / "result/fsp_report.vszh5") == metadata["pages"]
    assert not list(tmp_path.glob(".result.*"))
    for name in ("report.md", "report.json", "spectral_statistics.csv", "capture_statistics.csv"):
        assert (tmp_path / "result" / name).stat().st_size > 0
    with h5py.File(str(tmp_path / "result/fsp_report.vszh5"), "r") as native:
        for number in traces:
            expected = np.asarray([[-80 + number + capture * 10 + point for point in range(points)] for capture in range(captures)])
            np.testing.assert_allclose(native["Veusz/Data/trace%d_raw_dbm/data" % number][()], expected)
            np.testing.assert_allclose(native["Veusz/Data/trace%d_linear_mean_dbm/data" % number][()],
                                       10 * np.log10(np.mean(10 ** (expected / 10), axis=0)))


@pytest.mark.parametrize("damage", ["truncated", "frequency", "nan", "columns", "empty", "duplicate_header", "date", "reverse_time"])
def test_bad_csv_refused_without_partial_bundle(tmp_path, damage):
    source = fixture_csv(tmp_path / "bad.csv")
    lines = source.read_text().splitlines()
    if damage == "truncated":
        lines = lines[:-1]
    elif damage == "frequency":
        values = lines[-1].split(","); values[3] = "1005000000"; lines[-1] = ",".join(values)
    elif damage == "nan":
        lines[-1] = lines[-1].rsplit(",", 1)[0] + ",nan"
    elif damage == "columns":
        lines[-1] += ",extra"
    elif damage == "empty":
        lines = lines[:1]
    elif damage == "duplicate_header":
        lines[0] = lines[0].replace("trace3_dBm", "trace1_dBm")
    elif damage == "date":
        lines[-1] = "2000-01-01" + lines[-1][10:]
    elif damage == "reverse_time":
        lines = [line.replace("12:00:03.000", "11:59:00.000") for line in lines]
    source.write_text("\n".join(lines) + "\n")
    with pytest.raises(reports.ReportValidationError):
        reports.create_reports(source, tmp_path / "result")
    assert not (tmp_path / "result").exists()
    assert not list(tmp_path.glob(".result.*"))


def test_existing_directory_and_matrix_budget(tmp_path):
    source = fixture_csv(tmp_path / "synthetic.csv", captures=5, points=10000, traces=(1, 2, 3))
    with pytest.raises(reports.ReportValidationError, match="max-matrix"):
        reports.create_reports(source, tmp_path / "result", max_matrix_mib=1)
    (tmp_path / "existing").mkdir()
    with pytest.raises(FileExistsError):
        reports.create_reports(source, tmp_path / "existing")


def test_optional_render_failure_keeps_native_reports(tmp_path, monkeypatch):
    source = fixture_csv(tmp_path / "synthetic.csv")
    def render_error(*args, **kwargs):
        raise RuntimeError("deliberately unavailable renderer")
    monkeypatch.setattr(writer, "render_pages", render_error)
    metadata = reports.create_reports(source, tmp_path / "result", render=True)
    assert metadata["rendering"]["status"] == "unavailable_or_failed"
    assert (tmp_path / "result/fsp_report.vszh5").exists()


def test_changed_input_is_rejected(tmp_path, monkeypatch):
    source = fixture_csv(tmp_path / "synthetic.csv")
    original = reports.iter_capture_blocks
    def mutate(path):
        yield from original(path)
        with path.open("a") as stream:
            stream.write("\n")
    monkeypatch.setattr(reports, "iter_capture_blocks", mutate)
    with pytest.raises(reports.ReportValidationError, match="changed"):
        reports.create_reports(source, tmp_path / "result")


# %% CONCURRENCY AND BACKPRESSURE

def test_csv_order_and_copied_ownership(tmp_path):
    output = background.AsyncCaptureCsvWriter(tmp_path / "out.csv", np.arange(4), [1], queue_capacity=8)
    for capture in range(6):
        values = np.full(4, capture, dtype=float)
        output.submit(datetime(2026, 1, 1) + timedelta(seconds=capture), {1: values})
        values[:] = -999
    output.close()
    with (tmp_path / "out.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 24
    assert [float(rows[index * 4]["trace1_dBm"]) for index in range(6)] == list(range(6))
    assert not output.consumer_thread.is_alive()


def test_saturation_preserves_terminal_capture(tmp_path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = background.AsyncCaptureCsvWriter._write_payload
    def stalled(self, *args):
        entered.set()
        assert release.wait(5)
        return original(self, *args)
    monkeypatch.setattr(background.AsyncCaptureCsvWriter, "_write_payload", stalled)
    output = background.AsyncCaptureCsvWriter(tmp_path / "full.csv", np.arange(3), [1], queue_capacity=1)
    try:
        output.submit(datetime(2026, 1, 1), {1: np.zeros(3)})
        assert entered.wait(2)
        output.submit(datetime(2026, 1, 1, 0, 0, 1), {1: np.ones(3)})
        with pytest.raises(background.CsvBacklogError):
            output.submit(datetime(2026, 1, 1, 0, 0, 2), {1: np.full(3, 2)})
    finally:
        release.set()
        output.close()
    with (tmp_path / "full.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert [float(rows[index * 3]["trace1_dBm"]) for index in range(3)] == [0, 1, 2]


def test_disk_error_propagates(tmp_path, monkeypatch):
    def fail(*args):
        raise OSError("test disk failure")
    monkeypatch.setattr(background.AsyncCaptureCsvWriter, "_write_payload", fail)
    output = background.AsyncCaptureCsvWriter(tmp_path / "error.csv", np.arange(3), [1])
    output.submit(datetime.now(), {1: np.zeros(3)})
    with pytest.raises(RuntimeError, match="test disk failure"):
        output.close()


def test_mailbox_coalesces_display_not_data():
    mailbox = background.LatestCaptureMailbox()
    for index in range(100):
        mailbox.publish(index, np.arange(3), {1: np.zeros(3)})
    assert mailbox.take()[0] == 99
    assert mailbox.take() is None


# %% QT LIFECYCLE AND REPORT QPROCESS

def test_gui_idle_and_active_interlocks(application, tmp_path, dialog_messages):
    window = logger.MainWindow()
    window.file_edit.setText(str(fixture_csv(tmp_path / "done.csv")))
    window._update_report_availability()
    assert window.report_btn.isEnabled()
    window.thread = object()
    window._update_report_availability()
    assert not window.report_btn.isEnabled()
    window.on_create_reports()
    assert window.report_process is None
    window.thread = None
    window.close()
    assert not dialog_messages


def test_gui_report_process_blocks_sampling(application, tmp_path, monkeypatch, dialog_messages):
    window = logger.MainWindow()
    window.file_edit.setText(str(fixture_csv(tmp_path / "done.csv")))
    window.instrument = logger.MockFSPInstrument(sweep_time=0.01)
    destination = tmp_path / "gui_report"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    window.on_create_reports()
    assert window.report_process is not None
    assert not window.start_manual_btn.isEnabled()
    window.on_start(False)
    assert window.thread is None
    wait_until(application, lambda: window.report_process is None, timeout=20)
    assert (destination / "fsp_report.vszh5").exists()
    assert not dialog_messages
    window.close()


def test_capture_stop_drain_restart(application, tmp_path, dialog_messages):
    window = logger.MainWindow()
    window.instrument = logger.MockFSPInstrument(sweep_time=0.01, n_pts=51)
    window.interval_spin.setValue(0.1)
    for run in range(2):
        window.file_edit.setText(str(tmp_path / ("capture%d.csv" % run)))
        window.on_start(False)
        assert window.thread is not None, dialog_messages
        assert not window.report_btn.isEnabled()
        assert not window.probe_btn.isEnabled()
        wait_until(application, lambda: window.display_mailbox.latest_capture is not None or bool(window._plot_curves))
        window.on_stop()
        wait_until(application, lambda: window.thread is None)
        assert window.worker is None
        assert window.report_btn.isEnabled()
    assert not dialog_messages
    window.close()


def test_close_defers_until_worker_and_csv_finish(application, tmp_path, dialog_messages):
    window = logger.MainWindow()
    window.instrument = logger.MockFSPInstrument(sweep_time=0.02, n_pts=31)
    window.file_edit.setText(str(tmp_path / "closing.csv"))
    window.interval_spin.setValue(0.1)
    window.show()
    window.on_start(False)
    assert window.thread is not None, dialog_messages
    window.close()
    wait_until(application, lambda: window.thread is None and window.instrument is None)
    assert not dialog_messages


# %% OPTIONAL REAL RENDERER
@pytest.mark.skipif(not os.environ.get("VEUSZ_EXE"), reason="Set VEUSZ_EXE to a working standalone Veusz")
def test_real_veusz_all_pages(tmp_path):
    source = fixture_csv(tmp_path / "synthetic_render.csv", traces=(1, 2, 3))
    metadata = reports.create_reports(source, tmp_path / "result", render=True)
    assert metadata["rendering"]["status"] == "completed", metadata["rendering"]
    assert len(list((tmp_path / "result/rendered").glob("*.png"))) == 11
    assert (tmp_path / "result/rendered/fsp_report.pdf").stat().st_size > 1000


# %% ADDITIONAL STATE AND OWNERSHIP REGRESSIONS

def test_scheduled_wait_disables_reports(application, tmp_path, dialog_messages):
    window = logger.MainWindow()
    window.instrument = logger.MockFSPInstrument(sweep_time=0.01, n_pts=11)
    window.file_edit.setText(str(tmp_path / "scheduled.csv"))
    window.interval_spin.setValue(0.1)
    window.start_dt.setDateTime(datetime.now() + timedelta(seconds=60))
    window.on_start(True)
    assert window.thread is not None, dialog_messages
    assert not window.report_btn.isEnabled()
    window.on_stop()
    wait_until(application, lambda: window.thread is None)
    assert not dialog_messages
    window.close()


def test_reports_remain_disabled_until_csv_drain_finishes(application, tmp_path, monkeypatch, dialog_messages):
    entered = threading.Event()
    release = threading.Event()
    original = background.AsyncCaptureCsvWriter._write_payload
    def slow_output(self, *args):
        entered.set()
        assert release.wait(5)
        return original(self, *args)
    monkeypatch.setattr(background.AsyncCaptureCsvWriter, "_write_payload", slow_output)
    window = logger.MainWindow()
    window.instrument = logger.MockFSPInstrument(sweep_time=0.01, n_pts=11)
    window.file_edit.setText(str(tmp_path / "drain.csv"))
    window.interval_spin.setValue(0.1)
    try:
        window.on_start(False)
        wait_until(application, entered.is_set)
        window.on_stop()
        for _ in range(20):
            application.processEvents()
            time.sleep(0.01)
        assert window.thread is not None
        window._update_report_availability()
        assert not window.report_btn.isEnabled()
        window.on_create_reports()
        assert window.report_process is None
    finally:
        release.set()
        window.on_stop()
        wait_until(application, lambda: window.thread is None)
        window.close()
    assert not dialog_messages


def test_instrument_trigger_and_fetch_share_single_owner(application, tmp_path, dialog_messages):
    class TrackingInstrument(logger.MockFSPInstrument):
        def __init__(self):
            super().__init__(sweep_time=0.01, n_pts=11)
            self.operation_threads = []
        def trigger_and_wait(self, timeout_s):
            self.operation_threads.append(threading.get_ident())
            super().trigger_and_wait(timeout_s)
        def fetch_trace(self, trace_number):
            self.operation_threads.append(threading.get_ident())
            return super().fetch_trace(trace_number)
    instrument = TrackingInstrument()
    window = logger.MainWindow()
    window.instrument = instrument
    window.file_edit.setText(str(tmp_path / "serial.csv"))
    window.interval_spin.setValue(0.1)
    window.on_start(False)
    wait_until(application, lambda: len(instrument.operation_threads) >= 3)
    window.on_stop()
    wait_until(application, lambda: window.thread is None)
    assert len(set(instrument.operation_threads)) == 1
    assert instrument.operation_threads[0] != threading.get_ident()
    assert not dialog_messages
    window.close()
