#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# %% MODULE HEADER
"""
Dark / Light / System theme shared by the logger window and its dialogs
======================================================================
===============================================================================
 Title          : FSP Logger GUI theme
 Filename       : fsp_gui_theme.py
 Version        : 0.0.1 (Semantic Versioning 2.0.0)
 Author         : William W. Wallace (application owner)
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 2026-10-29
 Modified       : 2026-10-29
 Language       : Python 3.8 through 3.12
 Requires       : QtPy with PyQt5 (default) or PySide6
 Licence        : Same terms as rs_fsp_logger.py (not declared by the owner;
                  no grant inferred).
 Attribution    : AI-assisted (Claude). The palette and style sheet are the
                  0.8.3 MainWindow.apply_theme() values, moved here unchanged
                  so the batch dialog looks exactly like the logger.
 Status         : Internal draft.
===============================================================================

DESCRIPTION
-----------
build_theme() returns the palette and style sheet of one mode; apply_theme()
puts them on a window. Themes are scoped to that window (and its children),
never to the QApplication, so running inside Spyder does not restyle Spyder.

The chosen mode is stored once, under the logger's QSettings key "theme"
(organisation "William W Wallace", application "R&S FSP Trace Logger"), so
the logger and the stand-alone batch converter open in the same theme.

REVISION HISTORY (newest first)
-------------------------------
0.0.1  2026-10-29  First version, logger bundle 0.10.0 (from rs_fsp_logger
                   0.9.0 MainWindow.apply_theme).
===============================================================================
"""

from __future__ import annotations

# %% IMPORTS
from dataclasses import dataclass

from qtpy import QtCore, QtGui

__version__ = "0.0.1"

#: QSettings location shared by the logger and the batch converter.
SETTINGS_ORGANISATION = "William W Wallace"
SETTINGS_APPLICATION = "R&S FSP Trace Logger"
SETTINGS_THEME_KEY = "theme"
THEME_MODES = (("system", "System / application"), ("dark", "Dark"), ("light", "Light"))


# %% THEME
@dataclass
class Theme:
    """Everything a window needs to draw itself in one mode."""
    mode: str
    dark: bool
    palette: object
    stylesheet: str
    foreground: str
    background: str
    base: str
    border: str


def shared_settings():
    """The QSettings object the logger and the batch converter share."""
    return QtCore.QSettings(SETTINGS_ORGANISATION, SETTINGS_APPLICATION)


def saved_mode(settings=None) -> str:
    """Stored theme mode, 'system' when unset or unknown."""
    value = str((settings or shared_settings()).value(SETTINGS_THEME_KEY, "system"))
    return value if value in dict(THEME_MODES) else "system"


def build_theme(base_palette, mode: str) -> Theme:
    """Palette and style sheet for 'dark', 'light' or 'system'.

    'system' keeps the platform palette (base_palette) and only derives
    whether it is dark; 'dark' and 'light' set every role explicitly.
    """
    if mode not in dict(THEME_MODES):
        mode = "system"
    palette = QtGui.QPalette(base_palette)
    if mode == "system":
        dark = palette.color(QtGui.QPalette.Window).lightness() < 128
    else:
        dark = mode == "dark"
        colors = {"window": "#24272e" if dark else "#f3f4f6", "base": "#171a20" if dark else "#ffffff",
                  "text": "#f1f3f7" if dark else "#17212b", "button": "#353b46" if dark else "#e5e9ef",
                  "disabled": "#9098a5" if dark else "#6b7280", "highlight": "#406bb5" if dark else "#245eb4"}
        for role, color in ((QtGui.QPalette.Window, colors["window"]), (QtGui.QPalette.WindowText, colors["text"]),
                            (QtGui.QPalette.Base, colors["base"]), (QtGui.QPalette.AlternateBase, colors["window"]),
                            (QtGui.QPalette.Text, colors["text"]), (QtGui.QPalette.Button, colors["button"]),
                            (QtGui.QPalette.ButtonText, colors["text"]), (QtGui.QPalette.ToolTipBase, colors["base"]),
                            (QtGui.QPalette.ToolTipText, colors["text"]), (QtGui.QPalette.Highlight, colors["highlight"]),
                            (QtGui.QPalette.HighlightedText, "#ffffff"), (QtGui.QPalette.Link, "#66b7ff" if dark else "#154caa")):
            palette.setColor(role, QtGui.QColor(color))
        for role in (QtGui.QPalette.Text, QtGui.QPalette.ButtonText, QtGui.QPalette.WindowText):
            palette.setColor(QtGui.QPalette.Disabled, role, QtGui.QColor(colors["disabled"]))
    foreground = palette.color(QtGui.QPalette.WindowText).name()
    base = palette.color(QtGui.QPalette.Base).name()
    background = palette.color(QtGui.QPalette.Window).name()
    button = palette.color(QtGui.QPalette.Button).name()
    disabled = palette.color(QtGui.QPalette.Disabled, QtGui.QPalette.Text).name()
    border = "#626b7a" if dark else "#9ba5b4"
    stylesheet = """
QWidget { background-color: %s; color: %s; }
QProgressBar { background: %s; color: %s; border: 1px solid %s; text-align: center; }
QProgressBar::chunk { background: #406bb5; }
QCheckBox::indicator, QRadioButton::indicator { width: 13px; height: 13px; border: 1px solid #8d99aa; background: palette(base); }
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked { background: #406bb5; border: 2px solid #82b8ff; }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { border-color: #626b7a; }
QMenuBar, QMenu, QToolBar { background: %s; color: %s; }
QMenuBar::item:selected, QMenu::item:selected { background: #406bb5; color: white; }
QMenu::item:disabled { color: %s; }
QLineEdit, QAbstractSpinBox, QComboBox, QTextEdit, QTextBrowser { background: %s; color: %s; selection-background-color: #406bb5; }
QPushButton, QToolButton { background: %s; color: %s; border: 1px solid %s; border-radius: 3px; padding: 5px; }
QPushButton:disabled, QToolButton:disabled { color: %s; }
QPushButton:hover:enabled, QToolButton:hover:enabled { border: 1px solid #5b9beb; }
QGroupBox { border: 1px solid %s; border-radius: 4px; margin-top: 9px; padding-top: 7px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }
QToolTip { background: %s; color: %s; border: 1px solid %s; }
""" % (background, foreground, base, foreground, border, background, foreground, disabled,
       base, foreground, button, foreground, border, disabled, border, base, foreground, border)
    return Theme(mode, dark, palette, stylesheet, foreground, background, base, border)


def apply_theme(widget, base_palette, mode: str) -> Theme:
    """Apply build_theme(mode) to one window (scoped, not app-wide)."""
    theme = build_theme(base_palette, mode)
    widget.setPalette(theme.palette)
    widget.setStyleSheet(theme.stylesheet)
    return theme
