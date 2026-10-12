#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""SSB phase noise analysis - L(f) derivation and frequency-domain noise ID.

===============================================================================
 Title          : SSB Phase Noise Analysis
 Filename       : phase_noise.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3 (GUI: Time_Stability_App.py)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13 (3.8 syntax kept on purpose)
 Requires       : numpy, scipy (signal.welch, fft)
 Licence        : GPL-3.0-or-later (GNU General Public License v3.0 or later)
 Copyright      : Copyright (C) 2026 William W. Wallace
 Status         : Internal draft - validated on synthetic data only
===============================================================================

LICENCE
-------
This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
The full text is in the file LICENSE distributed with this program.

DESCRIPTION
-----------
Computes single-sideband (SSB) phase noise L(f) [dBc/Hz] vs Fourier offset
frequency f, either:

  (a) directly from a spectrum analyzer's phase-noise trace export
      (frequency offset vs dBc/Hz, parsed via sa_convert.py), or
  (b) from a long-time-measurement phase/time-error series x(t), via the
      Welch power spectral density [3] of the phase fluctuation
      phi(t) = 2 pi f0 x(t) (IEEE 1139 [2]; SP1065 Sec. 3 [1]):

          L(f) = 10 log10[ (1/2) S_phi(f) ]   dBc/Hz,   S_phi one-sided

Also classifies the power-law noise type from the L(f) slope against
log10 f, the spectral complement of the ADEV/MDEV slope method in
stability_core.py; both domains should name the same noise type for a
self-consistent analysis (a cross-check whenever an analyzer phase-noise
trace AND long-time phase data exist for the same device).

Noise identification (0.0.3): L(f) is first averaged in log-spaced bins
(linear power), then the slope of each bin pair is a least-squares fit over
all bins within +/- fit_halfwidth_decades (default 0.25 decade) instead of
the 0.0.1 two-bin difference. Measured on 15 synthetic records (white
PM ... random-walk FM, three seeds each, 0.05-20 Hz at fs = 100 Hz): the
two-bin method named the injected type in 47-84 % of the segments (mean
67 %), the windowed fit in 95-100 % (mean 99 %); validate_phase_noise.py
repeats the check. fit_halfwidth_decades=0 restores 0.0.1.

PARALLEL
--------
The Welch FFTs run with scipy.fft's worker threads (workers argument,
default: all CPUs available to the process).

REFERENCES (IEEE format)
------------------------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf
[2] IEEE Standard Definitions of Physical Quantities for Fundamental
    Frequency and Time Metrology - Random Instabilities, IEEE Std
    1139-2008, 2009, doi: 10.1109/IEEESTD.2008.4797525.
[3] P. Welch, "The use of fast Fourier transform for the estimation of
    power spectra: a method based on time averaging over short, modified
    periodograms," IEEE Trans. Audio Electroacoust., vol. 15, no. 2,
    pp. 70-73, Jun. 1967, doi: 10.1109/TAU.1967.1161901.
[4] E. Rubiola, Phase Noise and Frequency Stability in Oscillators.
    Cambridge, U.K.: Cambridge Univ. Press, 2008,
    doi: 10.1017/CBO9780511812798.
[5] P. Virtanen et al., "SciPy 1.0: fundamental algorithms for scientific
    computing in Python," Nature Methods, vol. 17, pp. 261-272, 2020,
    doi: 10.1038/s41592-019-0686-2.

REVISION HISTORY
----------------
0.0.1  (baseline)  As received (unversioned archive sa_stability_tool.7z).
0.0.2  2026-10-11  Full header, version dunders, Spyder cells; code unchanged.
0.0.3  2026-10-11  classify_freq_domain_noise(): windowed least-squares slope
                   over +/- fit_halfwidth_decades (default 0.25) of log-binned
                   L(f), not the two-bin difference. Welch FFTs threaded
                   (workers). L(f) of a zero PSD bin is -inf with no
                   warning. The 0.8 dB/decade offset of the 0.0.1 slope test
                   is explained (one shared random realisation). References
                   completed (Welch title, SciPy).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy import fft as sp_fft
from scipy import signal

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"        # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"


# %% ===========================================================================
#    FREQUENCY-DOMAIN NOISE TABLE
# =============================================================================
# S_phi(f) ~ f^alpha_phi gives an L(f) slope of 10*alpha_phi dB per decade,
# because L(f) = 10*log10(0.5*S_phi(f)) is already in dB. With S_y(f) ~ f^alpha
# and S_phi = (f0/f)^2 S_y, alpha_phi = alpha - 2 (IEEE 1139 / Rubiola Ch. 2):
#   White PM:         0 dB/decade  (alpha_phi =  0)
#   Flicker PM:     -10 dB/decade  (alpha_phi = -1)
#   White FM:       -20 dB/decade  (alpha_phi = -2)
#   Flicker FM:     -30 dB/decade  (alpha_phi = -3)
#   Random Walk FM: -40 dB/decade  (alpha_phi = -4)
FREQ_NOISE_TABLE = [
    ("White PM",          0),
    ("Flicker PM",      -10),
    ("White FM",        -20),
    ("Flicker FM",      -30),
    ("Random Walk FM",  -40),
]


# %% ===========================================================================
#    RESULT DATA CLASSES
# =============================================================================
@dataclass
class PhaseNoiseResult:
    freq_hz: "np.ndarray"      # Fourier offset frequency, Hz
    l_f_dbc_hz: "np.ndarray"   # SSB phase noise, dBc/Hz
    method: str                # 'welch_from_phase' or 'direct_sa_trace'
    f0_hz: Optional[float] = None
    window: Optional[str] = None
    nperseg: Optional[int] = None


@dataclass
class FreqNoiseClassification:
    f_lo_hz: float
    f_hi_hz: float
    slope_db_per_decade: float
    noise_type: str


# %% ===========================================================================
#    SSB PHASE NOISE L(f)
# =============================================================================
def _cpus() -> int:
    """CPUs available to this process (affinity-aware, 3.8-compatible)."""
    getter = getattr(os, "sched_getaffinity", None)
    if getter is not None:
        try:
            return max(1, len(getter(0)))
        except OSError:  # pragma: no cover
            pass
    return max(1, os.cpu_count() or 1)


def ssb_phase_noise_from_time_series(x_phase_s: "np.ndarray", tau0: float, f0_hz: float,
                                     window: str = "hann", nperseg: Optional[int] = None,
                                     detrend: str = "linear",
                                     workers: Optional[int] = None) -> PhaseNoiseResult:
    """L(f) from a phase/time-error series x(t) [s] via the Welch PSD of
    phi(t) = 2 pi f0 x(t) [rad]: L(f) = 10 log10[0.5 S_phi(f)] dBc/Hz [1], [2].

    window: 'hann' (default, good general-purpose leakage suppression),
        'hamming', or 'boxcar' (rectangular / no window).
    nperseg: segment length; default min(N, max(256, N/8)).
    detrend: passed to scipy.signal.welch; 'linear' removes a residual
        frequency-offset ramp per segment (systematic drift must not be
        attributed to phase noise).
    workers: scipy.fft threads (default: all available CPUs).
    """
    fs = 1.0 / tau0
    phi = 2.0 * math.pi * f0_hz * np.asarray(x_phase_s, dtype=float)
    if nperseg is None:
        nperseg = min(len(phi), max(256, int(len(phi) / 8)))
    with sp_fft.set_workers(workers or _cpus()):
        f, s_phi = signal.welch(phi, fs=fs, window=window, nperseg=nperseg,
                                detrend=detrend, scaling="density")
    # Drop the DC bin (f=0): undefined / dominated by the removed drift term.
    f = f[1:]
    s_phi = s_phi[1:]
    with np.errstate(divide="ignore"):
        l_f = 10.0 * np.log10(0.5 * s_phi)
    return PhaseNoiseResult(freq_hz=f, l_f_dbc_hz=l_f, method="welch_from_phase",
                            f0_hz=f0_hz, window=window, nperseg=nperseg)


def parse_direct_phase_noise_trace(freq_hz: "np.ndarray", l_f_dbc_hz: "np.ndarray") -> PhaseNoiseResult:
    """Wrap an already-measured L(f) trace (e.g. exported directly from a
    spectrum/signal analyzer's phase-noise personality) for downstream
    plotting and noise-ID alongside a Welch-derived curve."""
    order = np.argsort(freq_hz)
    return PhaseNoiseResult(freq_hz=np.asarray(freq_hz)[order],
                            l_f_dbc_hz=np.asarray(l_f_dbc_hz)[order],
                            method="direct_sa_trace")


# %% ===========================================================================
#    FREQUENCY-DOMAIN NOISE CLASSIFICATION
# =============================================================================
def _log_bin_average(f: "np.ndarray", l_f: "np.ndarray", points_per_decade: int = 8
                     ) -> Tuple["np.ndarray", "np.ndarray"]:
    """Average L(f) (in linear power, then back to dB) within log-spaced
    frequency bins. Raw Welch/FFT bins are very noisy on a log-log plot;
    log-bin smoothing is standard practice before slope/noise-ID."""
    f = np.asarray(f, dtype=float)
    l_f = np.asarray(l_f, dtype=float)
    valid = (f > 0) & np.isfinite(l_f)
    f, l_f = f[valid], l_f[valid]
    if f.size < 2:
        return f, l_f
    log_f = np.log10(f)
    n_bins = max(4, int(points_per_decade * (log_f.max() - log_f.min())))
    edges = np.linspace(log_f.min(), log_f.max(), n_bins + 1)
    idx = np.clip(np.digitize(log_f, edges) - 1, 0, n_bins - 1)
    lin_power = 10.0 ** (l_f / 10.0)
    counts = np.bincount(idx, minlength=n_bins)
    keep = counts > 0
    mean_logf = np.bincount(idx, weights=log_f, minlength=n_bins)[keep] / counts[keep]
    mean_pow = np.bincount(idx, weights=lin_power, minlength=n_bins)[keep] / counts[keep]
    return 10.0 ** mean_logf, 10.0 * np.log10(mean_pow)


def _nearest_freq_noise(slope: float) -> str:
    """Name of the FREQ_NOISE_TABLE entry closest to ``slope`` (dB/decade)."""
    return min(FREQ_NOISE_TABLE, key=lambda row: abs(slope - row[1]))[0]


def classify_freq_domain_noise(result: PhaseNoiseResult, points_per_decade: int = 8,
                               fit_halfwidth_decades: float = 0.25
                               ) -> List[FreqNoiseClassification]:
    """Classify the dominant power-law phase-noise type between adjacent
    log-frequency bins from the L(f) slope in dB/decade (SP1065 Table 1 /
    Rubiola Ch. 2; reference slopes in FREQ_NOISE_TABLE).

    L(f) is first log-bin averaged (_log_bin_average). The slope for the
    segment [f_i, f_i+1] is the least-squares slope of the binned L(f)
    against log10 f over every bin whose centre lies within
    fit_halfwidth_decades of the segment ends; 0 uses only the two bins
    (0.0.1 behaviour, ~100 % per-bin variance). Read the trend over a
    decade rather than a single row.
    """
    f_b, l_b = _log_bin_average(result.freq_hz, result.l_f_dbc_hz, points_per_decade)
    if f_b.size < 2:
        return []
    log_f = np.log10(f_b)
    out = []
    for i in range(len(f_b) - 1):
        lo = log_f[i] - fit_halfwidth_decades
        hi = log_f[i + 1] + fit_halfwidth_decades
        sel = (log_f >= lo - 1e-12) & (log_f <= hi + 1e-12)
        if fit_halfwidth_decades > 0 and int(sel.sum()) >= 3:
            slope = float(np.polyfit(log_f[sel], l_b[sel], 1)[0])
        else:
            slope = float((l_b[i + 1] - l_b[i]) / (log_f[i + 1] - log_f[i]))
        out.append(FreqNoiseClassification(f_lo_hz=float(f_b[i]), f_hi_hz=float(f_b[i + 1]),
                                           slope_db_per_decade=slope,
                                           noise_type=_nearest_freq_noise(slope)))
    return out


# %% ===========================================================================
#    L(f) <-> S_y(f) CONVERSION
# =============================================================================
def l_f_to_sy(l_f_dbc_hz: "np.ndarray", f_hz: "np.ndarray", f0_hz: float) -> "np.ndarray":
    """Convert SSB phase noise L(f) [dBc/Hz] to the fractional-frequency
    PSD S_y(f) [1/Hz] (IEEE 1139 [2]):
        S_phi(f) = 2 * 10^(L(f)/10)              [rad^2/Hz]
        S_y(f)   = (f^2 / f0^2) * S_phi(f)        [1/Hz]
    f0_hz is the nominal carrier the phase data were referenced to (the
    f0_hz used in ssb_phase_noise_from_time_series, or the analyzer's
    carrier for a direct trace).
    """
    s_phi = 2.0 * 10.0 ** (np.asarray(l_f_dbc_hz, dtype=float) / 10.0)
    return (np.asarray(f_hz, dtype=float) ** 2 / f0_hz ** 2) * s_phi


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# import stability_core as sc
# x = sc.generate_power_law_phase(65536, 0.01, alpha=0, seed=17)   # white FM
# res = ssb_phase_noise_from_time_series(x, 0.01, 10e6)
# for c in classify_freq_domain_noise(res)[:8]:
#     print(f"{c.f_lo_hz:8.3f}-{c.f_hi_hz:8.3f} Hz  {c.slope_db_per_decade:+6.1f} dB/dec  {c.noise_type}")
