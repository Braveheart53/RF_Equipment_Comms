"""
Veusz Plot Export (.vszh5)
============================================================================
Generates Veusz documents (saved in Veusz's native HDF5-backed .vszh5
format) containing raw and processed plots: the input time series, the
drift-removed residual, the ADEV/OADEV/MDEV/TDEV/OHDEV/Theo1/ThêoH
sigma-tau overlay, and the SSB phase-noise L(f) curve with noise-ID
overlay bands.

IMPORTANT PROCESS-ISOLATION NOTE: Veusz's `embed` module loads PyQt6
internally. This tool's GUI (gui_app.py) uses PySide6. Loading both Qt
bindings into the SAME Python process can cause Qt runtime conflicts
(duplicate QApplication instances, symbol/plugin clashes). To avoid this,
call this module's `export_all_plots()` via a SEPARATE subprocess (see
`export_all_plots_subprocess()` below), never by directly importing
veusz_export inside a running PySide6 GUI process.

Headless operation requires QT_QPA_PLATFORM=offscreen (set automatically
by this module if not already set) since Veusz's rendering backend still
needs a Qt platform plugin even with no visible window.

References (IEEE format)
-------------------------
[1] "Veusz Documentation," Veusz project. [Online].
    Available: https://veusz.github.io/docs/
[2] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008.
    Available: https://tf.nist.gov/general/pdf/2220.pdf

Python 3.8 / 3.12 compatible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def export_all_plots(output_path: str,
                      t_s, x_raw, x_residual: Optional[list],
                      sigma_tau_series: Dict[str, Dict[str, list]],
                      phase_noise_freq: Optional[list] = None,
                      phase_noise_lf: Optional[list] = None,
                      title: str = "SA Stability Analysis") -> str:
    """Build a multi-page Veusz document and save as .vszh5.

    sigma_tau_series: dict of {label: {'tau': [...], 'dev': [...]}} for
        each deviation type (ADEV, OADEV, MDEV, TDEV, OHDEV, Theo1, ThêoH),
        each plotted as a log-log overlay on one page.
    phase_noise_freq/lf: optional SSB phase-noise L(f) trace for a third page.
    Must be called in a process that has NOT imported PySide6/PyQt in a
    way that already created a QApplication -- see module docstring.
    """
    import veusz.embed as ve  # local import: only touches Qt in this process

    g = ve.Embedded(title, hidden=True)
    try:
        # --- Page 1: raw + residual time series ---
        g.SetData("t_s", list(t_s))
        g.SetData("x_raw", list(x_raw))
        page1 = g.Root.Add("page", name="raw_data")
        page1.Add("label", label=title, xPos=0.5, yPos=0.97, alignHorz="centre")
        gr1 = page1.Add("graph", name="graph_raw")
        gr1.x.label.val = "Time (s)"
        gr1.y.label.val = "Phase / time error x(t) (s)"
        xy1 = gr1.Add("xy", name="raw")
        xy1.xData.val = "t_s"
        xy1.yData.val = "x_raw"
        xy1.marker.val = "none"
        xy1.PlotLine.color.val = "#2b6cb0"
        if x_residual is not None:
            g.SetData("x_resid", list(x_residual))
            gr1b = page1.Add("graph", name="graph_resid")
            gr1b.x.label.val = "Time (s)"
            gr1b.y.label.val = "Drift-removed residual (s)"
            xy1b = gr1b.Add("xy", name="resid")
            xy1b.xData.val = "t_s"
            xy1b.yData.val = "x_resid"
            xy1b.marker.val = "none"
            xy1b.PlotLine.color.val = "#dd6b20"

        # --- Page 2: sigma-tau overlay (log-log) ---
        page2 = g.Root.Add("page", name="sigma_tau")
        page2.Add("label", label="Frequency Stability (Sigma-Tau)",
                   xPos=0.5, yPos=0.97, alignHorz="centre")
        gr2 = page2.Add("graph", name="graph_sigmatau")
        gr2.x.log.val = True
        gr2.y.log.val = True
        gr2.x.label.val = "Averaging time tau (s)"
        gr2.y.label.val = "Deviation (dimensionless / s)"
        palette = ["#2b6cb0", "#dd6b20", "#38a169", "#805ad5", "#e53e3e",
                   "#2c5282", "#c05621"]
        for i, (label, series) in enumerate(sigma_tau_series.items()):
            tau_name = "tau_{0}".format(i)
            dev_name = "dev_{0}".format(i)
            g.SetData(tau_name, list(series["tau"]))
            g.SetData(dev_name, list(series["dev"]))
            xy = gr2.Add("xy", name="curve_{0}".format(i))
            xy.xData.val = tau_name
            xy.yData.val = dev_name
            xy.marker.val = "circle"
            xy.markerSize.val = "2pt"
            xy.PlotLine.color.val = palette[i % len(palette)]
            xy.MarkerFill.color.val = palette[i % len(palette)]
            xy.key.val = label
        gr2.Add("key", name="key1")

        # --- Page 3: SSB phase noise (optional) ---
        if phase_noise_freq is not None and phase_noise_lf is not None:
            page3 = g.Root.Add("page", name="phase_noise")
            page3.Add("label", label="SSB Phase Noise L(f)",
                       xPos=0.5, yPos=0.97, alignHorz="centre")
            gr3 = page3.Add("graph", name="graph_phasenoise")
            gr3.x.log.val = True
            gr3.x.label.val = "Fourier frequency offset f (Hz)"
            gr3.y.label.val = "L(f) (dBc/Hz)"
            g.SetData("pn_f", list(phase_noise_freq))
            g.SetData("pn_lf", list(phase_noise_lf))
            xy3 = gr3.Add("xy", name="phase_noise_curve")
            xy3.xData.val = "pn_f"
            xy3.yData.val = "pn_lf"
            xy3.marker.val = "none"
            xy3.PlotLine.color.val = "#c53030"

        g.Save(output_path)
    finally:
        g.Close()
    return output_path


def export_all_plots_subprocess(output_path: str,
                                 t_s, x_raw, x_residual: Optional[list],
                                 sigma_tau_series: Dict[str, Dict[str, list]],
                                 phase_noise_freq: Optional[list] = None,
                                 phase_noise_lf: Optional[list] = None,
                                 title: str = "SA Stability Analysis",
                                 timeout_s: int = 300) -> str:
    """Run export_all_plots() in a fresh subprocess so the calling process
    (e.g. the PySide6 GUI) never imports veusz's PyQt6 dependency itself.
    Data is passed via a temporary JSON payload file to avoid command-line
    length limits with large time series."""
    payload = {
        "output_path": output_path,
        "t_s": list(t_s),
        "x_raw": list(x_raw),
        "x_residual": list(x_residual) if x_residual is not None else None,
        "sigma_tau_series": {k: {"tau": list(v["tau"]), "dev": list(v["dev"])}
                              for k, v in sigma_tau_series.items()},
        "phase_noise_freq": list(phase_noise_freq) if phase_noise_freq is not None else None,
        "phase_noise_lf": list(phase_noise_lf) if phase_noise_lf is not None else None,
        "title": title,
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        payload_path = f.name
    try:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "veusz_export.py")
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, script, "--payload", payload_path],
            capture_output=True, text=True, timeout=timeout_s, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "veusz_export subprocess failed (exit {0}):\n{1}".format(
                    result.returncode, result.stderr[-4000:]))
    finally:
        try:
            os.remove(payload_path)
        except OSError:
            pass
    return output_path


def _main_cli() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Veusz .vszh5 export worker (invoked as a subprocess)")
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    args = parser.parse_args()
    with open(args.payload, "r") as f:
        payload = json.load(f)
    export_all_plots(
        output_path=payload["output_path"],
        t_s=payload["t_s"],
        x_raw=payload["x_raw"],
        x_residual=payload.get("x_residual"),
        sigma_tau_series=payload["sigma_tau_series"],
        phase_noise_freq=payload.get("phase_noise_freq"),
        phase_noise_lf=payload.get("phase_noise_lf"),
        title=payload.get("title", "SA Stability Analysis"),
    )
    print("OK: wrote {0}".format(payload["output_path"]))


if __name__ == "__main__":
    _main_cli()
