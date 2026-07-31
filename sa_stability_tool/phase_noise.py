"""
SSB Phase Noise Analysis -- L(f) Derivation and Frequency-Domain Noise ID
============================================================================
Computes single-sideband (SSB) phase noise L(f) [dBc/Hz] vs Fourier offset
frequency f, either:

  (a) directly from a spectrum analyzer's native phase-noise-personality
      trace export (frequency offset vs dBc/Hz, parsed via sa_convert.py), or
  (b) derived from a long-time-measurement phase/time-error series x(t) via
      Welch's method power spectral density estimate of the phase
      fluctuation phi(t) = 2*pi*f0*x(t), per NIST SP1065 Sec. 3.1-3.2:

          L(f) = 10*log10[ (1/2) * S_phi(f) ]     dBc/Hz

Also implements frequency-domain power-law noise-type classification from
the L(f) log-log slope vs f, the spectral-domain complement to the
time-domain ADEV/MDEV slope method in stability_core.py -- per SP1065
Table 1, the two domains must agree on noise type for a self-consistent
analysis (a valuable cross-check available whenever both a spectrum-
analyzer phase-noise mode AND long-time phase data exist for the same DUT).

References (IEEE format)
-------------------------
[1] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. [Online].
    Available: https://tf.nist.gov/general/pdf/2220.pdf
[2] "IEEE Standard Definitions of Physical Quantities for Fundamental
    Frequency and Time Metrology -- Random Instabilities," IEEE Std
    1139-2008, doi: 10.1109/IEEESTD.2008.4797525.
[3] P. Welch, "The Use of Fast Fourier Transform for the Estimation of
    Power Spectra: A Method Based on Time Averaging Over Short, Modified
    Periodograms," IEEE Trans. Audio Electroacoust., vol. 15, no. 2,
    pp. 70-73, Jun. 1967, doi: 10.1109/TAU.1967.1161901.
[4] E. Rubiola, "Phase Noise and Frequency Stability in Oscillators,"
    Cambridge Univ. Press, 2008, doi: 10.1017/CBO9780511812798.

Python 3.8 / 3.12 compatible.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from scipy import signal

# S_phi(f) power-law exponent alpha_phi (S_phi(f) ~ f^alpha_phi) determines
# the slope of L(f) IN dB PER DECADE of f. Since L(f)=10*log10(0.5*S_phi(f))
# is already expressed in dB, its log10(f)-slope is 10*alpha_phi, not
# alpha_phi itself -- confirmed numerically in validate_phase_noise.py
# (measured slopes -19.2/-29.2/-39.2 dB/decade for White/Flicker/RandomWalk
# FM synthetic data vs the -20/-30/-40 dB/decade textbook values, well
# within the expected Welch-estimator variance).
# Standard table (SP1065 Table 1 / Rubiola Ch. 2):
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


@dataclass
class PhaseNoiseResult:
    freq_hz: "np.ndarray"      # Fourier offset frequency, Hz
    l_f_dbc_hz: "np.ndarray"   # SSB phase noise, dBc/Hz
    method: str                 # 'welch_from_phase' or 'direct_sa_trace'
    f0_hz: Optional[float] = None
    window: Optional[str] = None
    nperseg: Optional[int] = None


@dataclass
class FreqNoiseClassification:
    f_lo_hz: float
    f_hi_hz: float
    slope_db_per_decade: float
    noise_type: str


def ssb_phase_noise_from_time_series(x_phase_s: "np.ndarray", tau0: float, f0_hz: float,
                                      window: str = "hann", nperseg: Optional[int] = None,
                                      detrend: str = "linear") -> PhaseNoiseResult:
    """Derive L(f) from a time-domain phase/time-error series x(t) [seconds]
    via Welch PSD of the equivalent phase fluctuation phi(t) = 2*pi*f0*x(t)
    [rad], per SP1065 Eq. (2)-(3): L(f) = 10*log10[0.5*S_phi(f)] dBc/Hz.

    window: 'hann' (default, good general-purpose leakage suppression per
        SP1065 Sec. 3.2), 'hamming', or 'boxcar' (rectangular / no window).
    detrend: passed to scipy.signal.welch; 'linear' removes any residual
        frequency-offset ramp in the phase record before PSD estimation
        (systematic drift must not be attributed to phase noise).
    """
    fs = 1.0 / tau0
    phi = 2.0 * math.pi * f0_hz * np.asarray(x_phase_s, dtype=float)
    if nperseg is None:
        nperseg = min(len(phi), max(256, int(len(phi) / 8)))
    f, s_phi = signal.welch(phi, fs=fs, window=window, nperseg=nperseg,
                             detrend=detrend, scaling="density")
    # Drop DC bin (f=0) -- undefined / dominated by removed drift term.
    f = f[1:]
    s_phi = s_phi[1:]
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


def _log_bin_average(f: "np.ndarray", l_f: "np.ndarray", points_per_decade: int = 8
                      ) -> Tuple["np.ndarray", "np.ndarray"]:
    """Average L(f) (in linear power, then back to dB) within log-spaced
    frequency bins. Raw Welch/FFT bins are extremely noisy on a log-log
    plot; log-bin smoothing is standard practice (used by essentially all
    commercial phase-noise analyzers) before slope/noise-ID is attempted."""
    f = np.asarray(f, dtype=float)
    l_f = np.asarray(l_f, dtype=float)
    valid = f > 0
    f, l_f = f[valid], l_f[valid]
    log_f = np.log10(f)
    n_bins = max(4, int(points_per_decade * (log_f.max() - log_f.min())))
    edges = np.linspace(log_f.min(), log_f.max(), n_bins + 1)
    idx = np.digitize(log_f, edges) - 1
    idx = np.clip(idx, 0, n_bins - 1)
    f_out, l_out = [], []
    lin_power = 10.0 ** (l_f / 10.0)
    for b in range(n_bins):
        mask = idx == b
        if not np.any(mask):
            continue
        f_out.append(10.0 ** np.mean(log_f[mask]))
        l_out.append(10.0 * np.log10(np.mean(lin_power[mask])))
    return np.array(f_out), np.array(l_out)


def classify_freq_domain_noise(result: PhaseNoiseResult, points_per_decade: int = 8
                                ) -> List[FreqNoiseClassification]:
    """Classify dominant power-law phase-noise type per log-frequency bin
    using the local slope of log-binned L(f) vs log10(f), in dB/decade
    (SP1065 Table 1 / Rubiola Ch. 2 -- see FREQ_NOISE_TABLE for the
    reference slopes). Log-bin averaging first (see _log_bin_average) is
    essential: a raw unaveraged Welch periodogram has ~100% per-bin
    variance and gives an unusably noisy slope estimate bin-to-bin.
    """
    f_b, l_b = _log_bin_average(result.freq_hz, result.l_f_dbc_hz, points_per_decade)
    log_f = np.log10(f_b)
    out = []
    for i in range(len(f_b) - 1):
        slope = (l_b[i + 1] - l_b[i]) / (log_f[i + 1] - log_f[i])
        best_name, best_d = "Unclassified", float("inf")
        for name, s in FREQ_NOISE_TABLE:
            d = abs(slope - s)
            if d < best_d:
                best_d, best_name = d, name
        out.append(FreqNoiseClassification(f_lo_hz=float(f_b[i]), f_hi_hz=float(f_b[i + 1]),
                                            slope_db_per_decade=float(slope), noise_type=best_name))
    return out


def l_f_to_sy(l_f_dbc_hz: "np.ndarray", f_hz: "np.ndarray", f0_hz: float) -> "np.ndarray":
    """Convert SSB phase noise L(f) [dBc/Hz] to fractional-frequency PSD
    Sy(f) [1/Hz], per SP1065 Eq. (7)-(8):
        S_phi(f) = 2 * 10^(L(f)/10)              [rad^2/Hz]
        Sy(f)    = (f^2 / f0^2) * S_phi(f)        [1/Hz]
    f0_hz is the nominal carrier/reference frequency the phase data was
    referenced to (must match the f0_hz used in ssb_phase_noise_from_time_series,
    or the SA's carrier setting for a direct trace).
    """
    s_phi = 2.0 * 10.0 ** (np.asarray(l_f_dbc_hz, dtype=float) / 10.0)
    return (np.asarray(f_hz, dtype=float) ** 2 / f0_hz ** 2) * s_phi
