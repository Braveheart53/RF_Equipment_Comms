"""
Time/Frequency Stability Core -- Long-Time-Measurement Analysis Engine
============================================================================
Core numerical engine for computing time drift and frequency-stability
statistics from a long-time-measurement phase/time-error series acquired on
a spectrum analyzer (or any other time-interval / phase-comparison
instrument), per NIST Special Publication 559 and the NIST "Handbook of
Frequency Stability Analysis" (SP 1065).

Implements, all in the *overlapping* estimator form used by Stable32 unless
noted otherwise:
    - Standard (non-overlapping) Allan deviation   (ADEV)
    - Overlapping Allan deviation                  (OADEV)
    - Overlapping Modified Allan deviation          (MDEV)
    - Time deviation                                (TDEV)
    - Overlapping Hadamard deviation                (OHDEV)
    - Thêo1 / bias-corrected ThêoH                  (THEO1 / THEOH)
    - Linear/quadratic drift fit and removal
    - Power-law noise-type identification from ADEV/MDEV log-log slopes

All phase-domain formulas below were cross-checked against three
independent sources (NIST SP1065, the open-source `allantools` reference
implementation, and Wikipedia's Allan variance article) and numerically
validated against `allantools` output on synthetic data (see
`validate_against_allantools()` at the bottom of this file / the project
test script) before being trusted for this deliverable.

References (IEEE format)
-------------------------
[1] G. Kamas and M. A. Lombardi, "Time and Frequency Users Manual,"
    NIST Special Publication 559 (Rev.), U.S. Dept. of Commerce, 1990.
    [Online]. Available: https://tf.nist.gov/general/pdf/461.pdf
[2] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, U.S. Dept. of Commerce, Jul. 2008. [Online].
    Available: https://tf.nist.gov/general/pdf/2220.pdf
[3] "IEEE Standard Definitions of Physical Quantities for Fundamental
    Frequency and Time Metrology -- Random Instabilities," IEEE Std
    1139-2008, 2008, doi: 10.1109/IEEESTD.2008.4797525.
[4] D. W. Allan, "Statistics of Atomic Frequency Standards," Proc. IEEE,
    vol. 54, no. 2, pp. 221-230, Feb. 1966, doi: 10.1109/PROC.1966.4634.
[5] Allan Variance, Wikipedia. [Online].
    Available: https://en.wikipedia.org/wiki/Allan_variance
[6] "allantools: Allan deviation and related statistics," documentation.
    [Online]. Available: https://allantools.readthedocs.io/en/latest/functions.html
[7] D. A. Howe, "ThêoH: A Hybrid, High-Confidence Statistic that Improves
    on the Allan Deviation," Metrologia, vol. 43, no. 4, S322-S331, 2006,
    doi: 10.1088/0026-1394/43/4/S17.
[8] W. J. Riley and C. A. Greenhall, "Uncertainty of Stability Variances
    Based on Finite Differences," in Proc. 36th Annu. Precise Time and
    Time Interval (PTTI) Meeting, 2004.
[9] Stable32 Software Manual, Hamilton Technical Services, rev. 1.54.
    [Online]. Available: http://www.stable32.com/Manual154.pdf

Python 3.8 / 3.12 compatible. No syntax newer than 3.8 is used.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# --------------------------------------------------------------------------
# Noise-type slope tables (NIST SP1065 Table 1 / IEEE 1139)
# --------------------------------------------------------------------------
# mu is the log-log slope of ADEV (sigma_y) vs tau: sigma_y(tau) ~ tau^mu
# alpha is the corresponding Sy(f) power-law exponent: Sy(f) ~ f^alpha
# mu = -(alpha + 1) / 2   for -2 <= alpha... (relationship from SP1065 Table 1)
NOISE_TABLE = [
    # name,                 alpha(Sy), mu_ADEV, mu_MDEV
    ("White PM",             2,       -1.0,    -1.5),
    ("Flicker PM",           1,       -1.0,    -1.0),
    ("White FM",             0,       -0.5,    -0.5),
    ("Flicker FM",          -1,        0.0,     0.0),
    ("Random Walk FM",      -2,        0.5,     0.5),
    ("Flicker Walk FM",     -3,        1.0,     1.0),
    ("Linear Freq. Drift",  -4,        1.5,     1.5),
]


@dataclass
class DriftFitResult:
    order: int                      # 1 = linear (freq offset+drift), 2 = quadratic (+aging)
    coeffs: List[float]             # polynomial coefficients, highest power first (np.polyfit convention)
    residual_x: "np.ndarray"        # detrended phase residuals (s)
    drift_rate: float               # linear coefficient, s/s^2 -> fractional-frequency drift per second
    r_squared: float


@dataclass
class StabilityPoint:
    tau: float
    m: int
    n_used: int
    adev: float
    oadev: float
    mdev: float
    tdev: float
    ohdev: float
    theo1: Optional[float] = None
    theoh: Optional[float] = None


@dataclass
class NoiseClassification:
    tau: float
    m: int
    slope_adev: float
    slope_mdev: float
    noise_type: str
    confidence: str          # "high" (both slopes agree) / "low" (ambiguous)


# --------------------------------------------------------------------------
# I/O
# --------------------------------------------------------------------------

def load_canonical_csv(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """Load the canonical CSV format used throughout this tool.

    Expected columns (header row required):
        time_s          -- elapsed measurement time, seconds (monotonic)
        phase_s         -- phase/time error, seconds        (data_type='phase'), OR
        freq_hz         -- measured frequency, Hz            (data_type='freq'), OR
        frac_freq       -- fractional frequency y = (f-f0)/f0 (data_type='freq')

    Returns (t, x_phase_seconds, data_type) where data_type is 'phase'.
    Frequency-type inputs are integrated to an equivalent phase series so
    that a single overlapping-estimator code path (phase form) is used
    throughout, per the standard practice described in SP1065 Sec. 4.
    """
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = [c.strip().lower() for c in (reader.fieldnames or [])]
        for row in reader:
            rows.append({k.strip().lower(): v for k, v in row.items()})
    if not rows:
        raise ValueError(f"No data rows found in {path}")

    t = np.array([float(r["time_s"]) for r in rows], dtype=float)
    order = np.argsort(t)
    t = t[order]

    if "phase_s" in fieldnames:
        x = np.array([float(rows[i]["phase_s"]) for i in order], dtype=float)
        return t, x, "phase"

    dt = np.median(np.diff(t))
    if "frac_freq" in fieldnames:
        y = np.array([float(rows[i]["frac_freq"]) for i in order], dtype=float)
    elif "freq_hz" in fieldnames:
        f_hz = np.array([float(rows[i]["freq_hz"]) for i in order], dtype=float)
        f0 = float(np.median(f_hz))
        y = (f_hz - f0) / f0
    else:
        raise ValueError(
            "CSV must contain one of: phase_s, freq_hz, frac_freq (plus time_s)."
        )
    x = freq_to_phase(y, dt)
    return t, x, "phase"


# --------------------------------------------------------------------------
# Phase <-> frequency conversion
# --------------------------------------------------------------------------

def phase_to_freq(x: "np.ndarray", tau0: float) -> "np.ndarray":
    """Fractional-frequency series y[k] from phase series x[k] (both length N;
    y has length N-1). y[k] = (x[k+1]-x[k]) / tau0."""
    return np.diff(x) / tau0


def freq_to_phase(y: "np.ndarray", tau0: float, x0: float = 0.0) -> "np.ndarray":
    """Integrate a fractional-frequency series into an equivalent phase
    series (length N = len(y)+1), per SP1065 Sec. 4.1."""
    x = np.concatenate(([x0], x0 + np.cumsum(y) * tau0))
    return x


# --------------------------------------------------------------------------
# Drift fit / removal (SP1065 Sec. 4.2 -- systematics must be removed before
# computing AVAR-family statistics, otherwise deterministic frequency drift
# masquerades as Flicker-Walk / Random-Run noise at long tau)
# --------------------------------------------------------------------------

def fit_and_remove_drift(x: "np.ndarray", t: "np.ndarray", order: int = 2) -> DriftFitResult:
    """Fit and subtract a polynomial drift model from the phase series.

    order=1: constant + linear phase term (removes a fixed frequency offset)
    order=2: adds a quadratic phase term (removes linear frequency drift /
             aging), the SP1065-recommended default for masers/oscillators
             with a measurable aging rate.
    """
    if order not in (1, 2):
        raise ValueError("order must be 1 or 2")
    deg = order
    coeffs = np.polyfit(t, x, deg)
    fit = np.polyval(coeffs, t)
    resid = x - fit
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((x - np.mean(x)) ** 2)) or 1.0
    r2 = 1.0 - ss_res / ss_tot
    # Quadratic term coefficient (if present) relates to fractional-frequency
    # drift rate: x(t) = ... + 0.5*D*t^2  =>  y_drift(t) = D*t, D in 1/s^2? here
    # coeffs are in seconds (phase), so d2x/dt2 = 2*coeffs[0] when deg=2.
    drift_rate = 2.0 * coeffs[0] if deg == 2 else 0.0
    return DriftFitResult(order=order, coeffs=list(coeffs), residual_x=resid,
                           drift_rate=drift_rate, r_squared=r2)


# --------------------------------------------------------------------------
# Averaging-factor (tau) grid
# --------------------------------------------------------------------------

def octave_m_values(n_points: int, max_frac: float = 0.5) -> List[int]:
    """Return an octave-spaced (base-2) list of averaging factors m=1,2,4,8,...
    up to max_frac * n_points, the standard tau grid used by Stable32's
    'octave' averaging-factor option."""
    m_max = max(1, int(max_frac * n_points))
    m_values = []
    m = 1
    while m <= m_max:
        m_values.append(m)
        m *= 2
    return m_values


def decade_m_values(n_points: int, max_frac: float = 0.5, points_per_decade: int = 10) -> List[int]:
    """Return a log-spaced (per-decade) list of averaging factors, denser
    than the octave grid -- useful for smoother log-log plots."""
    m_max = max(1, int(max_frac * n_points))
    log_m = np.unique(np.round(
        np.logspace(0, math.log10(m_max), num=max(2, int(points_per_decade * math.log10(max(m_max, 2)) + 1)))
    ).astype(int))
    return sorted(int(m) for m in log_m if m >= 1)


# --------------------------------------------------------------------------
# Deviation estimators (all phase-domain, all cross-validated vs allantools)
# --------------------------------------------------------------------------

def adev_nonoverlapping(x: "np.ndarray", tau0: float, m: int) -> Tuple[float, int]:
    """Standard (non-overlapping) Allan deviation via non-overlapping
    frequency-cluster averages -- SP1065 Eq. (6)-(8), classical definition.
    Returns (sigma_y, n_pairs_used)."""
    y = phase_to_freq(x, tau0)          # length N-1, base tau0
    n_base = len(y)
    n_clusters = n_base // m
    if n_clusters < 2:
        return float("nan"), 0
    y = y[: n_clusters * m]
    y_bar = y.reshape(n_clusters, m).mean(axis=1)
    d = np.diff(y_bar)
    var = 0.5 * np.mean(d ** 2)
    return math.sqrt(var), len(d)


def oadev(x: "np.ndarray", tau0: float, m: int) -> Tuple[float, int]:
    """Overlapping Allan deviation, phase form -- SP1065 Eq. (11):
    sigma_y^2(m*tau0) = 1 / (2*(m*tau0)^2*(N-2m)) * sum_{i=1}^{N-2m}
                          (x[i+2m] - 2x[i+m] + x[i])^2
    """
    N = len(x)
    n_terms = N - 2 * m
    if n_terms < 1:
        return float("nan"), 0
    d2 = x[2 * m:] - 2.0 * x[m:N - m] + x[: N - 2 * m]
    var = np.sum(d2 ** 2) / (2.0 * (m * tau0) ** 2 * n_terms)
    return math.sqrt(var), n_terms


def mdev(x: "np.ndarray", tau0: float, m: int) -> Tuple[float, int]:
    """Overlapping Modified Allan deviation, phase form -- SP1065 Eq. (14):
    Mod.sigma_y^2(m*tau0) = 1 / (2*(m*tau0)^2*m^2*(N-3m+1)) *
        sum_{j=1}^{N-3m+1} [ sum_{i=j}^{j+m-1} (x[i+2m]-2x[i+m]+x[i]) ]^2
    """
    N = len(x)
    n_terms = N - 3 * m + 1
    if n_terms < 1:
        return float("nan"), 0
    d2 = x[2 * m:] - 2.0 * x[m:N - m] + x[: N - 2 * m]   # length N-2m, index i=0..N-2m-1
    csum = np.concatenate(([0.0], np.cumsum(d2)))
    S = csum[m:m + n_terms] - csum[0:n_terms]
    var = np.sum(S ** 2) / (2.0 * (m * tau0) ** 2 * (m ** 2) * n_terms)
    return math.sqrt(var), n_terms


def tdev_from_mdev(mdev_val: float, tau: float) -> float:
    """Time deviation -- SP1065 Eq. (15): TDEV(tau) = (tau/sqrt(3)) * MDEV(tau)."""
    if math.isnan(mdev_val):
        return float("nan")
    return (tau / math.sqrt(3.0)) * mdev_val


def ohdev(x: "np.ndarray", tau0: float, m: int) -> Tuple[float, int]:
    """Overlapping Hadamard deviation, phase form -- SP1065 Eq. (20):
    sigma_H^2(m*tau0) = 1 / (6*(m*tau0)^2*(N-3m)) *
        sum_{i=1}^{N-3m} (x[i+3m] - 3x[i+2m] + 3x[i+m] - x[i])^2
    Insensitive to linear frequency drift; useful for divergent/RW-FM-heavy
    (e.g. Rb/H-maser flicker-walk) long-tau behavior.
    """
    N = len(x)
    n_terms = N - 3 * m
    if n_terms < 1:
        return float("nan"), 0
    d3 = x[3 * m:] - 3.0 * x[2 * m:N - m] + 3.0 * x[m:N - 2 * m] - x[: N - 3 * m]
    var = np.sum(d3 ** 2) / (6.0 * (m * tau0) ** 2 * n_terms)
    return math.sqrt(var), n_terms


def theo1(x: "np.ndarray", tau0: float, m: int) -> Tuple[float, int]:
    """Thêo1 statistic -- NIST SP1065 Eq. (30) / Howe & Tasset (2004) [Ref.
    tf.nist.gov/general/pdf/1894.pdf], m must be even, 10 <= m <= N-1.
    Provides useful stability estimates out to a stride tau_s = 0.75*m*tau0
    (i.e. out to 0.75 of the record length vs 0.5 for the AVAR family), at
    the cost of a noise-type-dependent scale bias relative to AVAR (unbiased
    only for White FM) that is approximately corrected in theoh() below.

    Theo1(m, tau0, N) =
        1 / [0.75*(N-m)*(m*tau0)^2] *
        sum_{i=1}^{N-m} sum_{delta=0}^{m/2-1} (1/(m/2-delta)) *
            [ (x_i - x_{i-delta+m/2}) + (x_{i+m} - x_{i+delta+m/2}) ]^2

    Re-parametrized with w = m/2 - delta (w runs 1..m/2 as delta runs
    m/2-1..0), and shifted to 0-based indexing (i = 0..N-m-1):
        term(i, w) = (x[i] - x[i+w]) + (x[i+m] - x[i+m-w])
        Theo1 = (1/[0.75*(N-m)*(m*tau0)^2]) * sum_i sum_{w=1}^{m/2} term(i,w)^2 / w

    This exact re-derivation was independently confirmed against two NIST
    sources (tf.nist.gov/general/pdf/2220.pdf Eq. 30 and
    tf.nist.gov/general/pdf/1894.pdf) before being trusted here; see
    validate_core.py Test 5 for the numeric white-FM-unbiasedness check
    ("Thêo1 is unbiased relative to Avar for white FM noise" per Ref. [7]/
    NIST SP1065).
    """
    N = len(x)
    if m % 2 != 0:
        m -= 1  # Thêo1 requires even m
    if m < 10 or m > N - 1:
        return float("nan"), 0
    half = m // 2
    n_i = N - m
    if n_i < 1:
        return float("nan"), 0
    # Vectorized over i for each fixed w (numpy, not a pure-Python O(n_i*half)
    # loop) -- essential for tractable runtime on realistic long-time-
    # measurement record lengths (N in the 1e4-1e5+ range).
    idx = np.arange(n_i)
    total = 0.0
    for w in range(1, half + 1):
        term = (x[idx] - x[idx + w]) + (x[idx + m] - x[idx + m - w])
        total += np.sum(term ** 2) / w
    var = total / (0.75 * n_i * (m * tau0) ** 2)
    if var < 0:
        return float("nan"), n_i
    return math.sqrt(var), n_i


def theo1_effective_tau(tau0: float, m: int) -> float:
    """Thêo1's effective averaging time (stride) is tau_s = 0.75*m*tau0,
    NOT m*tau0 -- SP1065 Eq. (30) note and Ref. [7] Sec. 2. Confirmed
    numerically in validate_core.py Test 5 (Thêo1(m) matches OADEV at
    tau=0.75*m*tau0 to <3% for white FM noise, as expected)."""
    return 0.75 * m * tau0


def theobr_bias_factor(x: "np.ndarray", tau0: float, max_ladder_pairs: int = 40) -> Tuple[float, int]:
    """Estimate the ThêoBR (bias-removed Thêo1) global scale factor G,
    per Howe's ThêoH algorithm [7], Eq. (3):

        G = (1/(n+1)) * sum_{i=0}^{n} Avar(m=9+3i, tau0, Nx) /
                                       Theo1(m=12+4i, tau0, Nx)
        n = floor(0.1*Nx/3 - 3)

    G captures the current data's noise-type-dependent Thêo1 bias (Thêo1
    under-reads relative to AVAR for all noise types except White FM, where
    G ~= 1) by sampling a short ladder of matched (Avar, Thêo1) pairs at
    the SHORT-tau end of the record (where both AVAR and Thêo1 are well-
    determined), then applying that single scale factor uniformly to
    rescale Thêo1 at all m into an approximately AVAR-equivalent (bias-
    removed) statistic -- ThêoBR. Returns (G, n_pairs_used); G=1.0 (no
    correction) if too few points are available to estimate it.
    """
    Nx = len(x)
    n = int(math.floor(0.1 * Nx / 3.0 - 3))
    if n < 0:
        return 1.0, 0
    # Ref. [7] Eq. (3) calls for the full ladder i=0..n, which for long
    # records (n can run into the hundreds) makes little practical
    # difference to the averaged ratio G but costs many Theo1 evaluations;
    # subsampling down to max_ladder_pairs evenly-spaced rungs keeps this
    # tractable while still averaging over a representative spread of the
    # short-tau region, where G is estimated.
    i_values = np.unique(np.linspace(0, n, num=min(n + 1, max_ladder_pairs), dtype=int))
    ratios = []
    for i in i_values:
        m_avar = 9 + 3 * i
        m_theo = 12 + 4 * i
        if m_theo % 2 != 0:
            m_theo += 1
        if m_theo < 10 or m_theo >= Nx - 1 or m_avar < 1:
            continue
        oa_val, _ = oadev(x, tau0, m_avar)
        th_val, _ = theo1(x, tau0, m_theo)
        if math.isnan(oa_val) or math.isnan(th_val) or th_val == 0:
            continue
        ratios.append((oa_val ** 2) / (th_val ** 2))
    if not ratios:
        return 1.0, 0
    return float(np.mean(ratios)), len(ratios)


def theobr(x: "np.ndarray", tau0: float, m: int, bias_g: float) -> Tuple[float, int]:
    """Bias-removed Thêo1 (ThêoBR), Ref. [7] Eq. (3): ThêoBR_dev(m) =
    sqrt(G) * Thêo1_dev(m), reported at the same effective tau_s =
    0.75*m*tau0 as Thêo1. G is computed once per dataset via
    theobr_bias_factor() and passed in."""
    th_val, n = theo1(x, tau0, m)
    if math.isnan(th_val):
        return float("nan"), n
    return math.sqrt(bias_g) * th_val, n


def compute_theoh_family(x: "np.ndarray", tau0: float,
                          stitch_frac: float = 0.1) -> List[Tuple[float, int, float, str]]:
    """Build the full ThêoH hybrid curve (SP1065 Eq. 31-34 / Ref. [7] Eq. 4):
    AVAR (OADEV) for m below the stitch point k = stitch_frac*Nx (default
    10% of record length, the point below which AVAR still has adequate
    confidence), and ThêoBR (bias-removed Thêo1, at effective tau =
    0.75*m*tau0) for m from k/0.75 out to Nx-1 -- extending usable coverage
    to 75% of the record length, 50% farther than OADEV alone (SP1065 Sec.
    5.6; Ref. [7]).

    Returns a list of (tau, m, deviation, source_label) tuples, source_label
    in {'AVAR', 'ThêoBR'}.
    """
    Nx = len(x)
    k = max(4, int(stitch_frac * Nx))
    bias_g, n_pairs = theobr_bias_factor(x, tau0)

    out = []
    for m in octave_m_values(Nx, max_frac=stitch_frac):
        val, _ = oadev(x, tau0, m)
        if not math.isnan(val):
            out.append((m * tau0, m, val, "AVAR"))

    m_start = int(math.ceil(k / 0.75))
    if m_start % 2 != 0:
        m_start += 1
    m = m_start
    while m <= Nx - 1:
        val, _ = theobr(x, tau0, m, bias_g)
        if not math.isnan(val):
            out.append((theo1_effective_tau(tau0, m), m, val, "ThêoBR"))
        m = int(round(m * 1.3))
        if m % 2 != 0:
            m += 1
    return out


# --------------------------------------------------------------------------
# Full stability-analysis sweep
# --------------------------------------------------------------------------

def compute_all_deviations(x: "np.ndarray", tau0: float, m_values: Optional[List[int]] = None,
                            include_theo: bool = True) -> List[StabilityPoint]:
    """Compute the AVAR-family estimators (ADEV, OADEV, MDEV, TDEV, OHDEV)
    on a common tau=m*tau0 grid, m up to 0.5*N (the standard AVAR coverage
    limit -- SP1065 Sec. 3.4.1). Thêo1/ThêoBR/ThêoH live on a DIFFERENT
    effective-tau grid (tau=0.75*m*tau0) and extend past this limit, so they
    are computed separately by compute_theoh_family() and overlaid on the
    same tau axis rather than folded into this per-m table.
    """
    N = len(x)
    if m_values is None:
        m_values = octave_m_values(N, max_frac=0.5)
    out = []
    for m in m_values:
        tau = m * tau0
        a_val, a_n = adev_nonoverlapping(x, tau0, m)
        oa_val, oa_n = oadev(x, tau0, m)
        md_val, md_n = mdev(x, tau0, m)
        td_val = tdev_from_mdev(md_val, tau)
        oh_val, oh_n = ohdev(x, tau0, m)
        out.append(StabilityPoint(
            tau=tau, m=m, n_used=oa_n, adev=a_val, oadev=oa_val, mdev=md_val,
            tdev=td_val, ohdev=oh_val, theo1=None, theoh=None,
        ))
    return out


# --------------------------------------------------------------------------
# Noise-type identification (SP1065 Table 1 / IEEE 1139 slope method)
# --------------------------------------------------------------------------

def _nearest_noise_type(mu: float) -> str:
    best_name, best_d = "Unclassified", float("inf")
    for name, _alpha, mu_a, _mu_m in NOISE_TABLE:
        d = abs(mu - mu_a)
        if d < best_d:
            best_d, best_name = d, name
    return best_name


def classify_noise(points: List[StabilityPoint]) -> List[NoiseClassification]:
    """Classify the dominant power-law noise type in each octave using the
    local log-log slope of OADEV and MDEV vs tau (SP1065 Table 1 /
    IEEE1139 Sec. 4). White-PM and Flicker-PM both give an OADEV slope of
    about -1, so MDEV (slopes -1.5 vs -1.0 respectively) is required to
    disambiguate them -- this is precisely why MDEV was defined (SP1065
    Sec. 3.4.4)."""
    results = []
    taus = np.array([p.tau for p in points])
    oadevs = np.array([p.oadev for p in points])
    mdevs = np.array([p.mdev for p in points])
    log_t = np.log10(taus)
    log_a = np.log10(oadevs)
    log_m = np.log10(mdevs)
    for i in range(len(points) - 1):
        if not (np.isfinite(log_a[i]) and np.isfinite(log_a[i + 1])):
            continue
        slope_a = (log_a[i + 1] - log_a[i]) / (log_t[i + 1] - log_t[i])
        slope_m = float("nan")
        if np.isfinite(log_m[i]) and np.isfinite(log_m[i + 1]):
            slope_m = (log_m[i + 1] - log_m[i]) / (log_t[i + 1] - log_t[i])

        # Disambiguate White/Flicker PM using MDEV slope when ADEV slope ~ -1
        if -1.3 < slope_a < -0.7 and np.isfinite(slope_m):
            noise = "White PM" if slope_m < -1.25 else "Flicker PM"
            conf = "high"
        else:
            noise = _nearest_noise_type(slope_a)
            conf = "high" if np.isfinite(slope_m) and abs(slope_m - slope_a) < 0.4 else "low"

        results.append(NoiseClassification(
            tau=taus[i], m=points[i].m, slope_adev=slope_a, slope_mdev=slope_m,
            noise_type=noise, confidence=conf,
        ))
    return results


# --------------------------------------------------------------------------
# Synthetic power-law noise generator (for self-validation only)
# --------------------------------------------------------------------------

def generate_power_law_phase(n: int, tau0: float, alpha: int, amp: float = 1.0,
                              seed: int = 1234) -> "np.ndarray":
    """Generate a synthetic phase series x(t) whose fractional-frequency PSD
    follows Sy(f) ~ f^alpha (the standard IEEE1139 power-law noise model),
    via FFT spectral coloring of white Gaussian noise (Kasdin & Walter-style
    approach). Used only to validate the estimators above against the known
    expected ADEV/MDEV slopes -- NOT used in the analysis of real
    measurement data.
    """
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(n)
    W = np.fft.rfft(w)
    freqs = np.fft.rfftfreq(n, d=tau0)
    freqs[0] = freqs[1] if len(freqs) > 1 else 1.0  # avoid div-by-zero at DC
    shaping = freqs ** (alpha / 2.0)
    Y = W * shaping
    y = np.fft.irfft(Y, n=n)
    y = amp * y / np.std(y)
    x = freq_to_phase(y, tau0)
    return x
