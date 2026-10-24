# %% OFFSCREEN TEST CONFIGURATION
import os
import sys
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
from qtpy import QtWidgets


@pytest.fixture(scope="session")
def application():
    instance = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


@pytest.fixture
def dialog_messages(monkeypatch):
    messages = []
    for name in ("critical", "warning", "information"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name, lambda *args: messages.append(args[-1]))
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.Yes)
    return messages
