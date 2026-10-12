#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 William W. Wallace <wwallace@nrao.edu>
# %% ===========================================================================
#    MODULE HEADER
# =============================================================================
"""Time/frequency stability core - long-time-measurement analysis engine.

===============================================================================
 Title          : Time/Frequency Stability Core
 Filename       : stability_core.py
 Version        : 0.0.3  (Semantic Versioning 2.0.0, MAJOR.MINOR.PATCH)
 Package        : SA Time Stability Tools 0.0.3 (GUI: Time_Stability_App.py)
 Author         : William W. Wallace
 Company        : NRAO/GBO
 Email          : wwallace@nrao.edu
 Created        : 0.0.1 baseline (authoring date not recorded)
 Modified       : 2026-10-11
 Language       : Python 3.8 - 3.13 (3.8 syntax kept on purpose)
 Requires       : numpy
 Optional       : threadpoolctl (caps BLAS threads inside the thread pool;
                  without it a BLAS-free kernel is used), cupy (GPU path
                  for the Thêo1/ThêoBR sums)
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
Core numerical engine for time drift and frequency-stability statistics of
a long-time-measurement phase/time-error series acquired on a spectrum
analyzer (or any time-interval / phase-comparison instrument), following
NIST SP 559 [1] and the NIST Handbook of Frequency Stability Analysis,
SP 1065 [2].

Implements, all in the overlapping form used by Stable32 unless noted:
    - Standard (non-overlapping) Allan deviation    ADEV
    - Overlapping Allan deviation                   OADEV
    - Modified Allan deviation                      MDEV
    - Time deviation                                TDEV
    - Overlapping Hadamard deviation                OHDEV
    - Thêo1, bias-removed ThêoBR and hybrid ThêoH   [7], [10], [11]
    - Polynomial (order 1/2) drift fit and removal
    - Power-law noise identification from OADEV/MDEV/OHDEV log-log slopes

The phase-form estimators are checked against the independent allantools
implementation [6] in validate_core.py (agreement to rounding). Thêo1 is
checked against allantools.theo1 as well (same SP 1065 Eq. (30)).

PARALLEL AND GPU EXECUTION
--------------------------
Thêo1 costs O((N - m) m / 2) per averaging factor, so a ThêoH curve of a
long record dominates the run time (0.0.2: 218 s for N = 100 000 on one
core). From 0.0.3:

  * the Thêo1 inner sum uses array views and preallocated buffers (no
    temporaries, no index arrays) - several times faster per core;
  * every Thêo1 a ThêoH curve needs (the ThêoBR bias ladder - about two
    thirds of the work at N = 100 000 - and the ThêoBR grid) is computed in
    one batch, largest first (theo1_batch). Records of PROCESS_MIN_N =
    100 000 points or more use a spawn process pool (no GIL between
    workers, each holds one copy of x); 50 000 to 100 000 points use a
    thread pool (NumPy releases the GIL inside the vector operations); a
    pool that cannot start falls back to threads;
  * the AVAR-family sweep runs one thread per averaging factor for long
    records;
  * one large Thêo1 evaluation is split over the w-range across threads;
  * BLAS (np.dot) is limited to one thread while the pool runs, through
    threadpoolctl when installed - OpenBLAS's own threads otherwise
    oversubscribe the CPUs and made 2 workers SLOWER than 1 (4.4 s vs
    2.4 s per point); without threadpoolctl a BLAS-free einsum kernel is
    used;
  * with use_gpu=True and CuPy installed, the Thêo1 sums run on the GPU.

Workers default to the CPUs available to the process (available_cpus(),
affinity-aware) and are capped at that count; set_default_workers(n) or
workers=n overrides it, and workers=1 gives the serial path. Thêo1/ThêoH
use threads only for records of at least PARALLEL_MIN_N = 50 000 points:
measured on 2 CPUs, N = 100 000 runs 1.6x faster on 2 threads, while at
N = 30 000 the per-step vector work (~20 us) is too small and threads lose
to the serial loop. Results equal the serial ones to rounding (summation
order only).

NOISE TYPES  (sigma_y^2(tau) ~ tau^mu,  S_y(f) ~ f^alpha) [2], [3]
-----------
mu = -alpha - 1 for -4 <= alpha < 1 and mu ~ -2 for alpha >= 1, so the
ADEV log-log slope is mu/2. AVAR (and MVAR) converge only for alpha > -3:
the Flicker-Walk (alpha = -3) and Random-Run (alpha = -4) rows are the
Hadamard (HDEV) slopes, which converge to alpha > -5. A linear frequency
drift D gives sigma_y(tau) = D tau / sqrt(2), i.e. ADEV slope +1 (the same
as Flicker-Walk FM), while the Hadamard deviation is blind to it; the
classifier uses that difference to report drift.

REFERENCES (IEEE format)
------------------------
[1] G. Kamas and M. A. Lombardi, "Time and Frequency Users Manual," NIST
    Special Publication 559 (Rev. 1990), Sep. 1990.
    https://tf.nist.gov/general/pdf/461.pdf
[2] W. J. Riley, "Handbook of Frequency Stability Analysis," NIST Special
    Publication 1065, Jul. 2008. https://tf.nist.gov/general/pdf/2220.pdf
[3] IEEE Standard Definitions of Physical Quantities for Fundamental
    Frequency and Time Metrology - Random Instabilities, IEEE Std
    1139-2008, 2009, doi: 10.1109/IEEESTD.2008.4797525.
[4] D. W. Allan, "Statistics of atomic frequency standards," Proc. IEEE,
    vol. 54, no. 2, pp. 221-230, Feb. 1966, doi: 10.1109/PROC.1966.4634.
[5] "Allan variance," Wikipedia. https://en.wikipedia.org/wiki/Allan_variance
[6] A. Wallin et al., "allantools," documentation and source.
    https://allantools.readthedocs.io/ ; https://github.com/aewallin/allantools
[7] D. A. Howe, "ThêoH: a hybrid, high-confidence statistic that improves
    on the Allan deviation," Metrologia, vol. 43, no. 4, pp. S322-S331,
    2006, doi: 10.1088/0026-1394/43/4/S20.
[8] C. A. Greenhall and W. J. Riley, "Uncertainty of stability variances
    based on finite differences," in Proc. 35th Annu. Precise Time and
    Time Interval (PTTI) Meeting, San Diego, CA, USA, Dec. 2003.
    https://ntrs.nasa.gov/citations/20050061319
[9] W. J. Riley, "Stable32 User Manual," Hamilton Technical Services
    (Stable32 is now distributed by the IEEE UFFC Society).
    https://ieee-uffc.org/technical-committees/frequency-control/educational-resources/frequency-control-software
[10] D. A. Howe and T. N. Tasset, "Theo1: characterization of very
    long-term frequency stability," in Proc. 18th European Frequency and
    Time Forum (EFTF), 2004, pp. 725-728.
    https://tf.nist.gov/general/pdf/1990.pdf
[11] D. A. Howe, J. McGee-Taylor and T. Tasset, "ThêoH bias-removal
    method," in Proc. 2006 IEEE Int. Frequency Control Symp., Miami, FL,
    USA, Jun. 2006, pp. 788-792.
    https://www.nist.gov/publications/theoh-bias-removal-method
[12] R. Okuta, Y. Unno, D. Nishino, S. Hido and C. Loomis, "CuPy: a
    NumPy-compatible library for NVIDIA GPU calculations," in Proc.
    Workshop on Machine Learning Systems (LearningSys), NIPS 2017.
    https://learningsys.org/nips17/assets/papers/paper_16.pdf

REVISION HISTORY
----------------
0.0.1  (baseline)  As received (unversioned archive sa_stability_tool.7z).
0.0.2  2026-10-11  Full header, version dunders, Spyder cells; code unchanged.
0.0.3  2026-10-11  FIX: frequency-column CSVs returned len(x) = len(t) + 1
                   (time tags now extended by one interval). FIX: NOISE_TABLE
                   row "Linear Freq. Drift" (+1.5) was Random-Run FM; drift
                   (slope +1) is now detected with OHDEV. FIX: drift_rate
                   documented in 1/s. New load_canonical_series() (fast
                   np.loadtxt parser, optional f0, reports the source
                   column; load_canonical_csv() keeps its 0.0.1 return).
                   Drift fit on a scaled domain (Polynomial.fit). Thêo1:
                   view/buffer kernel (4.5-5.5x faster per core), threaded
                   over w, BLAS capped to one thread inside the pools,
                   optional CuPy; ThêoH computes ladder + grid as one Thêo1
                   batch (theo1_batch: processes >= 100 000 points, threads
                   >= 50 000, else serial); AVAR sweep threaded for long
                   records; ThêoH AVAR range now m < k (Howe eq. 7) and the
                   grid ends at the largest even m <= N - 1 (coverage 75 %,
                   was 62.8 %). available_cpus, set_default_workers,
                   gpu_available, theo1_batch. References verified
                   and corrected ([7] DOI/pages, [8] authors/meeting, new
                   [10]-[12]). Unused import removed. A time_s column that
                   does not increase is rejected (tau0 > 0). Spawned pool
                   workers never re-run the caller's __main__ (hidden while
                   a pool starts; a lock serialises concurrent starts).
===============================================================================
"""

# %% ===========================================================================
#    IMPORTS
# =============================================================================
from __future__ import annotations

import contextlib
import csv
import importlib
import math
import multiprocessing
import os
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

try:  # optional: caps OpenBLAS/MKL threads while our own threads run
    from threadpoolctl import threadpool_limits as _threadpool_limits
except ImportError:  # pragma: no cover - einsum fallback below
    _threadpool_limits = None

__version__ = "0.0.3"                   # Semantic Versioning 2.0.0
__author__ = "William W. Wallace"
__email__ = "wwallace@nrao.edu"
__company__ = "NRAO/GBO"
__license__ = "GPL-3.0-or-later"        # SPDX identifier
__copyright__ = "Copyright (C) 2026 William W. Wallace"


# %% ===========================================================================
#    PARALLEL AND GPU EXECUTION HELPERS
# =============================================================================
#: AVAR sweeps smaller than this many element-operations run serially.
PARALLEL_MIN_OPS = 2_000_000
#: Thêo1/ThêoH run on threads only when the summed vectors are at least this
#: long. Measured on 2 CPUs: N = 100 000 -> 1.6x faster with 2 threads; at
#: N = 30 000 threads were slower (per-w Python overhead and GIL hand-off
#: outweigh the ~20 us of vector work per step).
PARALLEL_MIN_N = 50_000

_default_workers: Optional[int] = None
_gpu_state: Optional[Tuple[bool, str]] = None


def available_cpus() -> int:
    """CPUs this process may use (affinity/cgroup aware; 3.8-compatible).

    os.process_cpu_count() exists only from Python 3.13, so the scheduler
    affinity mask is read where the OS offers it (Linux), else cpu_count().
    """
    getter = getattr(os, "sched_getaffinity", None)
    if getter is not None:
        try:
            return max(1, len(getter(0)))
        except OSError:  # pragma: no cover - unusual kernels only
            pass
    return max(1, os.cpu_count() or 1)


def set_default_workers(workers: Optional[int]) -> None:
    """Default thread count for all estimators (None = available_cpus())."""
    global _default_workers
    _default_workers = None if workers is None else max(1, int(workers))


def _workers(workers: Optional[int]) -> int:
    """Resolve a worker count: explicit, module default, or CPU count.

    Never more than the CPUs available: oversubscribed threads only fight
    for the GIL (measured: 4 threads on 2 CPUs ran ThêoH 2x slower).
    """
    n = int(workers) if workers is not None else (_default_workers or available_cpus())
    return max(1, min(n, available_cpus()))


def gpu_available() -> Tuple[bool, str]:
    """(True, device name) when CuPy imports and a CUDA device works.

    Imported lazily and cached: CuPy start-up is slow and must not cost
    anything when the GPU path is not used.
    """
    global _gpu_state
    if _gpu_state is None:
        try:  # pragma: no cover - depends on host hardware
            import cupy as cp
            cp.zeros(1).sum()                      # forces a CUDA context
            name = cp.cuda.runtime.getDeviceProperties(0)["name"]
            _gpu_state = (True, name.decode() if isinstance(name, bytes) else str(name))
        except Exception as exc:  # noqa: BLE001 - CuPy raises many types
            _gpu_state = (False, f"{type(exc).__name__}: {exc}")
    return _gpu_state


_blas_lock = threading.Lock()
_spawn_lock = threading.RLock()
_blas_depth = 0
_blas_limiter: Any = None


@contextlib.contextmanager
def _blas_single_thread() -> Iterator[None]:
    """Run the enclosed code with BLAS limited to one thread.

    np.dot calls OpenBLAS/MKL, which starts its own threads; inside our
    thread pool that oversubscribes the CPUs (measured, N = 100 000,
    m = 20 000, 2 CPUs: 2 workers 3.89 s uncapped, 0.95 s capped, serial
    1.48 s). The limit is process-wide, so
    it is reference counted: the first entrant sets it, the last restores
    the original - concurrent analyses (GUI) cannot leave BLAS capped.
    Without threadpoolctl this is a no-op and the kernel uses einsum.
    """
    global _blas_depth, _blas_limiter
    if _threadpool_limits is None:
        yield
        return
    with _blas_lock:
        if _blas_depth == 0:
            _blas_limiter = _threadpool_limits(limits=1, user_api="blas")
        _blas_depth += 1
    try:
        yield
    finally:
        with _blas_lock:
            _blas_depth -= 1
            if _blas_depth == 0 and _blas_limiter is not None:
                _blas_limiter.restore_original_limits()
                _blas_limiter = None


@contextlib.contextmanager
def _main_hidden_from_spawn() -> Iterator[None]:
    """Stop spawned workers from re-running the parent's __main__ script.

    multiprocessing's spawn start method re-executes the parent's main
    script (or module) in every worker so that functions defined there can
    be unpickled. Our worker functions live in this module, imported by
    name, so that is not needed - and it is harmful: a cell-style script
    without an ``if __name__ == "__main__"`` guard (validation scripts, a
    Spyder console whose namespace holds __file__ during runcell) would run
    again in each worker, and the GUI script would import Qt in each. While
    the pool starts, __main__.__spec__ is None and __main__.__file__ is
    hidden; both are restored afterwards. A lock makes two pool starts on
    different threads (GUI) take turns, so neither restores the other's
    saved values.
    """
    with _spawn_lock:
        main = sys.modules.get("__main__")
        saved: Dict[str, Any] = {}
        if main is not None:
            try:
                for name in ("__file__", "__spec__"):
                    if name in vars(main):
                        saved[name] = vars(main)[name]
                main.__spec__ = None
                if "__file__" in vars(main):
                    del main.__file__
            except (AttributeError, TypeError):  # pragma: no cover - exotic __main__
                pass
        try:
            yield
        finally:
            if main is not None:
                for name, value in saved.items():
                    setattr(main, name, value)
                if "__spec__" not in saved and "__spec__" in vars(main):
                    try:
                        del main.__spec__
                    except AttributeError:  # pragma: no cover
                        pass


def _sumsq_numpy(b: "np.ndarray") -> float:
    """Sum of squares: BLAS dot when its threads can be capped, else einsum
    (einsum's own loop needs no BLAS and releases the GIL)."""
    if _threadpool_limits is not None:
        return np.dot(b, b)
    return np.einsum("i,i->", b, b)


def _parallel_map(fn: Callable[[Any], Any], items: Sequence[Any],
                  workers: Optional[int], cost: Optional[Callable[[Any], float]] = None) -> List[Any]:
    """map(fn, items) on a thread pool, results in input order.

    With ``cost`` the jobs are submitted largest first, so the long Thêo1
    evaluations do not end up last on one thread.
    """
    items = list(items)
    n_work = min(_workers(workers), len(items))
    if n_work <= 1:
        return [fn(it) for it in items]
    order = list(range(len(items)))
    if cost is not None:
        order.sort(key=lambda i: cost(items[i]), reverse=True)
    out: List[Any] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=n_work, thread_name_prefix="stability") as pool:
        futures = {pool.submit(fn, items[i]): i for i in order}
        for fut, i in futures.items():
            out[i] = fut.result()
    return out


# %% ===========================================================================
#    NOISE-TYPE SLOPE TABLE (NIST SP1065 / IEEE 1139)
# =============================================================================
# mu is the log-log slope of ADEV (sigma_y) vs tau: sigma_y(tau) ~ tau^mu
# alpha is the S_y(f) power-law exponent: S_y(f) ~ f^alpha
# ADEV slope = (-alpha - 1)/2 for -4 <= alpha < 1, about -1 for alpha >= 1.
# The last two rows hold for the Hadamard deviation (AVAR diverges there).
NOISE_TABLE = [
    # name,                 alpha(Sy), mu_ADEV, mu_MDEV
    ("White PM",             2,       -1.0,    -1.5),
    ("Flicker PM",           1,       -1.0,    -1.0),
    ("White FM",             0,       -0.5,    -0.5),
    ("Flicker FM",          -1,        0.0,     0.0),
    ("Random Walk FM",      -2,        0.5,     0.5),
    ("Flicker Walk FM",     -3,        1.0,     1.0),
    ("Random Run FM",       -4,        1.5,     1.5),
]
#: ADEV (and MDEV) slope of a linear frequency drift: sigma_y = D tau / sqrt(2).
LINEAR_DRIFT_SLOPE = 1.0
LINEAR_DRIFT_LABEL = "Linear Freq. Drift"


# %% ===========================================================================
#    RESULT DATA CLASSES
# =============================================================================
@dataclass
class DriftFitResult:
    order: int                      # 1 = constant + linear phase, 2 = adds quadratic (aging)
    coeffs: List[float]             # polynomial coefficients, highest power first (np.polyfit convention)
    residual_x: "np.ndarray"        # detrended phase residuals (s)
    drift_rate: float               # D = d y/dt = 2 a2 in 1/s (fractional frequency per second); 0 for order 1
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
    confidence: str          # "high" (slopes agree) / "low" (ambiguous)
    slope_hdev: float = float("nan")   # OHDEV slope (0.0.3; used for drift)


@dataclass
class CanonicalSeries:
    """A canonical CSV as phase, with where it came from (0.0.3)."""

    t: "np.ndarray"               # time tags of the phase samples (s), len(t) == len(x)
    x: "np.ndarray"               # phase / time error (s)
    source_column: str            # 'phase_s', 'freq_hz' or 'frac_freq'
    tau0: float                   # median sample spacing (s)
    f0_hz: Optional[float]        # carrier used to normalise freq_hz, else None
    n_rows: int                   # data rows read from the file


# %% ===========================================================================
#    I/O
# =============================================================================
_VALUE_COLUMNS = ("phase_s", "freq_hz", "frac_freq")


def _read_two_columns(path: str, names: List[str], t_col: int, v_col: int) -> Tuple["np.ndarray", "np.ndarray"]:
    """Fast numeric read of two CSV columns; csv-module fallback."""
    try:
        data = np.loadtxt(path, delimiter=",", skiprows=1, usecols=(t_col, v_col),
                          ndmin=2, encoding="utf-8-sig", comments="#")
        return data[:, 0].astype(float), data[:, 1].astype(float)
    except (ValueError, IndexError):
        # Quoted cells, blank cells or ragged rows: the tolerant slow path.
        t_list, v_list = [], []
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.reader(fh)
            next(reader, None)
            for row in reader:
                if not row or row[0].lstrip().startswith("#"):
                    continue
                try:
                    t_list.append(float(row[t_col]))
                    v_list.append(float(row[v_col]))
                except (ValueError, IndexError):
                    continue
        return np.asarray(t_list, dtype=float), np.asarray(v_list, dtype=float)


def load_canonical_series(path: str, f0_hz: Optional[float] = None) -> CanonicalSeries:
    """Load a canonical CSV as a phase series with its time tags.

    Expected columns (header row required, any order, case-insensitive):
        time_s     elapsed measurement time, s (monotonic after sorting)
        phase_s    phase / time error, s                  - or -
        freq_hz    measured frequency, Hz                 - or -
        frac_freq  fractional frequency y = (f - f0)/f0

    Frequency columns are integrated to phase (SP1065 Sec. 4.1),
    x_0 = 0 and x_{k+1} = x_k + y_k tau0. N frequency readings give N + 1
    phase points, so the time tags are extended by one interval: reading
    k is taken to cover [t_k, t_k + tau0]. ``freq_hz`` is normalised by
    ``f0_hz`` when given, else by its own median (a constant fractional
    offset does not change any AVAR-family statistic).

    Raises
    ------
    ValueError
        No rows, no time_s column, or no known value column.
    """
    with open(path, newline="", encoding="utf-8-sig") as fh:
        header = next(csv.reader(fh), [])
    names = [c.strip().lower() for c in header]
    if "time_s" not in names:
        raise ValueError(f"{path}: header must contain time_s (found {header})")
    value = next((c for c in _VALUE_COLUMNS if c in names), None)
    if value is None:
        raise ValueError("CSV must contain one of: phase_s, freq_hz, frac_freq (plus time_s).")
    t, v = _read_two_columns(path, names, names.index("time_s"), names.index(value))
    if t.size == 0:
        raise ValueError(f"No data rows found in {path}")
    order = np.argsort(t, kind="stable")
    t, v = t[order], v[order]
    tau0 = float(np.median(np.diff(t))) if t.size > 1 else 1.0
    if not (math.isfinite(tau0) and tau0 > 0):
        raise ValueError(f"{path}: time_s does not increase (median spacing {tau0!r} s)")
    if value == "phase_s":
        return CanonicalSeries(t, v, value, tau0, None, int(t.size))
    f0_used: Optional[float] = None
    if value == "freq_hz":
        f0_used = float(f0_hz) if f0_hz else float(np.median(v))
        y = (v - f0_used) / f0_used
    else:
        y = v
    x = freq_to_phase(y, tau0)
    t_x = np.concatenate((t, [t[-1] + tau0]))
    return CanonicalSeries(t_x, x, value, tau0, f0_used, int(t.size))


def load_canonical_csv(path: str) -> Tuple["np.ndarray", "np.ndarray", str]:
    """0.0.1-compatible loader: returns (t, x_phase_seconds, 'phase').

    Frequency inputs are integrated to phase; from 0.0.3 ``t`` has the same
    length as ``x`` (0.0.1 returned one time tag fewer). Use
    load_canonical_series() to learn which column was read.
    """
    s = load_canonical_series(path)
    return s.t, s.x, "phase"


# %% ===========================================================================
#    PHASE <-> FREQUENCY CONVERSION
# =============================================================================
def phase_to_freq(x: "np.ndarray", tau0: float) -> "np.ndarray":
    """Fractional-frequency series y[k] from phase series x[k] (both length N;
    y has length N-1). y[k] = (x[k+1]-x[k]) / tau0."""
    return np.diff(x) / tau0


def freq_to_phase(y: "np.ndarray", tau0: float, x0: float = 0.0) -> "np.ndarray":
    """Integrate a fractional-frequency series into an equivalent phase
    series (length N = len(y)+1), per SP1065 Sec. 4.1."""
    x = np.concatenate(([x0], x0 + np.cumsum(y) * tau0))
    return x


# %% ===========================================================================
#    DRIFT FIT AND REMOVAL (SP1065 Sec. 4.2)
# =============================================================================
# Systematics must be removed before AVAR-family statistics, otherwise a
# deterministic frequency drift masquerades as Flicker-Walk / Random-Run
# noise at long tau.
def fit_and_remove_drift(x: "np.ndarray", t: "np.ndarray", order: int = 2) -> DriftFitResult:
    """Fit and subtract a polynomial drift model from the phase series.

    order=1: constant + linear phase term (removes a fixed frequency offset)
    order=2: adds a quadratic phase term (removes linear frequency drift /
             aging), the SP1065-recommended model for oscillators with a
             measurable aging rate.

    The least-squares fit is done on a time axis mapped to [-1, 1]
    (numpy.polynomial.Polynomial.fit), which stays well conditioned for
    long records where t^2 reaches 1e12 s^2. ``coeffs`` are reported in
    the unscaled time axis, highest power first (np.polyfit convention).
    For order 2, x(t) = a2 t^2 + a1 t + a0 gives the frequency drift
    D = dy/dt = 2 a2 in 1/s.
    """
    if order not in (1, 2):
        raise ValueError("order must be 1 or 2")
    x = np.asarray(x, dtype=float)
    t = np.asarray(t, dtype=float)
    if x.shape != t.shape:
        raise ValueError(f"x has {x.size} samples but t has {t.size}")
    poly = np.polynomial.Polynomial.fit(t, x, order)
    resid = x - poly(t)
    low_first = poly.convert().coef
    low_first = np.pad(low_first, (0, order + 1 - low_first.size))
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((x - np.mean(x)) ** 2)) or 1.0
    r2 = 1.0 - ss_res / ss_tot
    drift_rate = 2.0 * float(low_first[2]) if order == 2 else 0.0
    return DriftFitResult(order=order, coeffs=[float(c) for c in low_first[::-1]],
                          residual_x=resid, drift_rate=drift_rate, r_squared=r2)


# %% ===========================================================================
#    AVERAGING-FACTOR (TAU) GRID
# =============================================================================
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


# %% ===========================================================================
#    DEVIATION ESTIMATORS (PHASE FORM)
# =============================================================================
def adev_nonoverlapping(x: "np.ndarray", tau0: float, m: int,
                        y: Optional["np.ndarray"] = None) -> Tuple[float, int]:
    """Standard (non-overlapping) Allan deviation via non-overlapping
    frequency-cluster averages -- SP1065 Eq. (6)-(8), classical definition.
    Returns (sigma_y, n_pairs_used). ``y`` = phase_to_freq(x, tau0) may be
    passed to avoid recomputing it for every m."""
    if y is None:
        y = phase_to_freq(x, tau0)      # length N-1, base tau0
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


# %% ===========================================================================
#    THEO1, THEOBR AND THEOH
# =============================================================================
def _theo1_partial(x: Any, m: int, n: int, w_lo: int, w_hi: int, xp: Any) -> float:
    """sum_{w=w_lo}^{w_hi-1} (1/w) sum_{i<n} [(x_i - x_{i+w}) + (x_{i+m} - x_{i+m-w})]^2

    The differences are formed pairwise (small minus small) before squaring,
    which keeps full precision when x carries a large offset - expanding
    the square into correlation sums would cancel catastrophically. Array
    views and two preallocated buffers: no temporaries per w. ``xp`` is
    numpy or cupy; on CuPy the total stays on the device until the end.
    """
    sumsq = _sumsq_numpy if xp is np else (lambda b: xp.dot(b, b))
    b1 = xp.empty(n, dtype=xp.float64)
    b2 = xp.empty(n, dtype=xp.float64)
    a0 = x[0:n]
    am = x[m:m + n]
    total = 0.0
    for w in range(w_lo, w_hi):
        xp.subtract(a0, x[w:w + n], out=b1)
        xp.subtract(am, x[m - w:m - w + n], out=b2)
        xp.add(b1, b2, out=b1)
        total = total + sumsq(b1) / w
    return float(total)


def _theo1_sum(x: "np.ndarray", m: int, workers: Optional[int], use_gpu: bool) -> float:
    """Double sum of Thêo1 for even m (serial, threaded over w, or GPU)."""
    n = len(x) - m
    half = m // 2
    if use_gpu and gpu_available()[0]:  # pragma: no cover - needs a GPU
        import cupy as cp
        return _theo1_partial(cp.asarray(x, dtype=cp.float64), m, n, 1, half + 1, cp)
    n_work = _workers(workers)
    with _blas_single_thread():
        if n_work <= 1 or n < PARALLEL_MIN_N or half < 2 * n_work:
            return _theo1_partial(x, m, n, 1, half + 1, np)
        edges = np.linspace(1, half + 1, num=min(half, 4 * n_work) + 1).astype(int)
        spans = [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:]) if b > a]
        parts = _parallel_map(lambda s: _theo1_partial(x, m, n, s[0], s[1], np), spans, n_work)
    return float(math.fsum(parts))


def theo1(x: "np.ndarray", tau0: float, m: int, workers: Optional[int] = None,
          use_gpu: bool = False) -> Tuple[float, int]:
    """Thêo1 deviation -- NIST SP1065 Eq. (30), Howe & Tasset [10].

    m must be even with 10 <= m <= N-1 (an odd m is lowered by one). Thêo1
    reports stability at the stride tau = 0.75 m tau0 [10] and reaches
    75 % of the record length (AVAR family: 50 %). It is unbiased relative
    to AVAR only for white FM; theobr_bias_factor() corrects the others.

    Theo1(m, tau0, N) =
        1 / [0.75 (N-m) (m tau0)^2] *
        sum_{i=1}^{N-m} sum_{delta=0}^{m/2-1} 1/(m/2-delta) *
            [ (x_i - x_{i-delta+m/2}) + (x_{i+m} - x_{i+delta+m/2}) ]^2

    With w = m/2 - delta (w = 1..m/2) and 0-based i = 0..N-m-1:
        term(i, w) = (x[i] - x[i+w]) + (x[i+m] - x[i+m-w])
        Theo1 = sum_i sum_w term(i, w)^2 / w / [0.75 (N-m) (m tau0)^2]

    Parameters
    ----------
    workers:
        Threads for one large evaluation (None = module default).
    use_gpu:
        Run the sums with CuPy when a CUDA device is available.

    Returns
    -------
    (deviation, N - m); (nan, 0) outside the valid m range.
    """
    x = np.asarray(x, dtype=float)
    N = len(x)
    if m % 2 != 0:
        m -= 1  # Thêo1 requires even m
    if m < 10 or m > N - 1:
        return float("nan"), 0
    n_i = N - m
    var = _theo1_sum(x, m, workers, use_gpu) / (0.75 * n_i * (m * tau0) ** 2)
    if var < 0:
        return float("nan"), n_i
    return math.sqrt(var), n_i


def theo1_effective_tau(tau0: float, m: int) -> float:
    """Thêo1's effective averaging time (stride) tau = 0.75 m tau0, not
    m tau0 -- Howe & Tasset [10]: "Theo1 averages every permissible squared
    second-difference ... in a given span or stride tau_s = 0.75 m tau0"."""
    return 0.75 * m * tau0


def _theobr_ladder(Nx: int, max_ladder_pairs: int) -> List[Tuple[int, int]]:
    """(m_AVAR, m_Theo1) pairs of the ThêoBR bias ladder [7] Eq. (6)."""
    n = int(math.floor(0.1 * Nx / 3.0 - 3))
    if n < 0:
        return []
    i_values = np.unique(np.linspace(0, n, num=min(n + 1, max_ladder_pairs), dtype=int))
    pairs = []
    for i in i_values:
        m_avar, m_theo = 9 + 3 * int(i), 12 + 4 * int(i)
        if m_theo % 2:
            m_theo += 1
        if 10 <= m_theo < Nx - 1 and m_avar >= 1:
            pairs.append((m_avar, m_theo))
    return pairs


# ---- process pool for long records (no GIL between workers) -----------------
#: From this record length the Thêo1 batch runs in a process pool ("auto").
PROCESS_MIN_N = 100_000
_PROC_X: Optional["np.ndarray"] = None
_PROC_LIMITER: Any = None


def _proc_init(x: "np.ndarray") -> None:
    """Process-pool initializer: keep the series, cap BLAS to one thread."""
    global _PROC_X, _PROC_LIMITER
    _PROC_X = x
    if _threadpool_limits is not None:
        _PROC_LIMITER = _threadpool_limits(limits=1, user_api="blas")


def _proc_theo1(job: Tuple[float, int]) -> float:
    """Process-pool task: one serial Thêo1 deviation of the stored series."""
    tau0, m = job
    return theo1(_PROC_X, tau0, m, workers=1)[0]


def _theo1_batch_processes(x: "np.ndarray", tau0: float, ms: List[int],
                           n_work: int) -> Optional[List[float]]:
    """Thêo1 for every m in a spawn process pool; None if no pool can run.

    The functions are taken from the module imported BY NAME so they
    pickle as 'stability_core._proc_theo1' even when this file runs as
    __main__ (Spyder cell, script); a pool that cannot start (frozen app,
    console without the module on the path) returns None -> threads.
    """
    try:
        mod = importlib.import_module("stability_core")
        ctx = multiprocessing.get_context("spawn")
        with _main_hidden_from_spawn(), \
                ProcessPoolExecutor(max_workers=n_work, mp_context=ctx,
                                    initializer=mod._proc_init, initargs=(x,)) as pool:
            return list(pool.map(mod._proc_theo1, [(tau0, m) for m in ms]))
    except Exception:  # noqa: BLE001 - any pool failure: use threads
        return None


def theo1_batch(x: "np.ndarray", tau0: float, ms: Sequence[int], workers: Optional[int] = None,
                use_gpu: bool = False, backend: str = "auto") -> Dict[int, float]:
    """Thêo1 deviations {m: dev} for many m, scheduled largest first.

    backend: "auto" (processes for len(x) >= PROCESS_MIN_N, threads for
    len(x) >= PARALLEL_MIN_N, else serial), "processes", "threads" or
    "serial". use_gpu runs every m on the GPU (serially, one device).
    """
    x = np.ascontiguousarray(x, dtype=float)
    Nx = len(x)
    ms = sorted(set(int(m) for m in ms), key=lambda m: -(Nx - m) * m)
    n_work = _workers(workers)
    if backend not in ("auto", "processes", "threads", "serial"):
        raise ValueError("backend must be auto, processes, threads or serial")
    if use_gpu and gpu_available()[0]:  # pragma: no cover - needs a GPU
        return {m: theo1(x, tau0, m, use_gpu=True)[0] for m in ms}
    if backend == "auto":
        backend = ("serial" if n_work <= 1 or Nx < PARALLEL_MIN_N or len(ms) < 2 else
                   "processes" if Nx >= PROCESS_MIN_N else "threads")
    if backend == "processes" and n_work > 1:
        vals = _theo1_batch_processes(x, tau0, ms, n_work)
        if vals is not None:
            return dict(zip(ms, vals))
        backend = "threads"
    with _blas_single_thread():
        if backend == "threads" and n_work > 1:
            vals = _parallel_map(lambda m: theo1(x, tau0, m, workers=1)[0], ms, n_work)
        else:
            vals = [theo1(x, tau0, m, workers=workers)[0] for m in ms]
    return dict(zip(ms, vals))


def _bias_from_values(x: "np.ndarray", tau0: float, pairs: List[Tuple[int, int]],
                      theo: Dict[int, float]) -> Tuple[float, int]:
    """G = mean of AVAR(m_a) / Theo1(m_t) over the usable ladder rungs."""
    ratios = []
    for m_avar, m_theo in pairs:
        oa_val, _ = oadev(x, tau0, m_avar)
        th_val = theo.get(m_theo, float("nan"))
        if not (math.isnan(oa_val) or math.isnan(th_val) or th_val == 0):
            ratios.append((oa_val ** 2) / (th_val ** 2))
    if not ratios:
        return 1.0, 0
    return float(np.mean(ratios)), len(ratios)


def theobr_bias_factor(x: "np.ndarray", tau0: float, max_ladder_pairs: int = 40,
                       workers: Optional[int] = None, use_gpu: bool = False,
                       backend: str = "auto") -> Tuple[float, int]:
    """ThêoBR bias factor G per Howe's ThêoH algorithm [7] Eq. (6):

        G = (1/(n+1)) * sum_{i=0}^{n} Avar(m=9+3i) / Theo1(m=12+4i),
        n = floor(0.1*Nx/3 - 3)

    G captures the noise-type-dependent Thêo1 bias (Thêo1 under-reads AVAR
    for every noise type except white FM, where G ~ 1), sampled on the
    short-tau ladder where both statistics are well determined, and is
    applied to Thêo1 at every m (ThêoBR). For long records the full ladder
    (n can reach the hundreds) is subsampled to ``max_ladder_pairs`` evenly
    spaced rungs. The rungs run in parallel (theo1_batch). Returns
    (G, pairs used); G = 1.0 if too few points are available.
    """
    x = np.asarray(x, dtype=float)
    pairs = _theobr_ladder(len(x), max_ladder_pairs)
    if not pairs:
        return 1.0, 0
    theo = theo1_batch(x, tau0, [p[1] for p in pairs], workers, use_gpu, backend)
    return _bias_from_values(x, tau0, pairs, theo)


def theobr(x: "np.ndarray", tau0: float, m: int, bias_g: float,
           workers: Optional[int] = None, use_gpu: bool = False) -> Tuple[float, int]:
    """Bias-removed Thêo1 (ThêoBR) [7] Eq. (6): ThêoBR(m) = sqrt(G) *
    Thêo1(m), at the Thêo1 stride tau = 0.75 m tau0. G comes from
    theobr_bias_factor()."""
    th_val, n = theo1(x, tau0, m, workers=workers, use_gpu=use_gpu)
    if math.isnan(th_val):
        return float("nan"), n
    return math.sqrt(bias_g) * th_val, n


def theoh_m_grid(Nx: int, stitch_frac: float = 0.1, growth: float = 1.3) -> Tuple[List[int], List[int]]:
    """Averaging factors of the ThêoH curve: (AVAR m's, ThêoBR m's).

    Howe [7] Eq. (7): AVAR for 1 <= m < k/tau0 and ThêoBR for
    k/(0.75 tau0) <= m <= Nx - 1 (m even), with k = stitch_frac * T
    (10 % of the record). AVAR uses octave m; ThêoBR grows by ``growth``
    per step and always ends at the largest even m <= Nx - 1.
    """
    k = max(4, int(stitch_frac * Nx))
    avar_m = [m for m in octave_m_values(Nx, max_frac=stitch_frac) if m < k]
    m = int(math.ceil(k / 0.75))
    m += m % 2
    m_last = (Nx - 1) - ((Nx - 1) % 2)
    theo_m: List[int] = []
    while m <= m_last:
        theo_m.append(m)
        m = int(round(m * growth))
        m += m % 2
    if theo_m and theo_m[-1] != m_last and m_last >= 10:
        theo_m.append(m_last)
    return avar_m, theo_m


def compute_theoh_family(x: "np.ndarray", tau0: float, stitch_frac: float = 0.1,
                         workers: Optional[int] = None, use_gpu: bool = False,
                         backend: str = "auto",
                         max_ladder_pairs: int = 40) -> List[Tuple[float, int, float, str]]:
    """Build the full ThêoH hybrid curve (SP1065 Eq. 31-34 / [7] Eq. 7).

    AVAR (OADEV) below the splice k = stitch_frac * Nx and bias-removed
    Thêo1 (ThêoBR, at tau = 0.75 m tau0) from m = k/0.75 to Nx - 1, which
    extends the usable range to 75 % of the record (OADEV: 50 %; SP1065
    Sec. 5.2.16).

    Every Thêo1 needed - the bias-ladder rungs AND the ThêoBR grid - is
    computed in ONE batch (theo1_batch), largest first, so the expensive
    ladder (about two thirds of the work at N = 100 000) shares the
    workers with the grid. backend: see theo1_batch().

    Returns a list of (tau, m, deviation, source_label) tuples sorted by
    tau, source_label in {'AVAR', 'ThêoBR'}.
    """
    x = np.asarray(x, dtype=float)
    Nx = len(x)
    avar_m, theo_m = theoh_m_grid(Nx, stitch_frac)
    pairs = _theobr_ladder(Nx, max_ladder_pairs)
    theo = theo1_batch(x, tau0, [p[1] for p in pairs] + theo_m, workers, use_gpu, backend)
    bias_g, _ = _bias_from_values(x, tau0, pairs, theo)

    out: List[Tuple[float, int, float, str]] = []
    for m in avar_m:
        val, _ = oadev(x, tau0, m)
        if not math.isnan(val):
            out.append((m * tau0, m, val, "AVAR"))
    for m in theo_m:
        val = theo.get(m, float("nan"))
        if not math.isnan(val):
            out.append((theo1_effective_tau(tau0, m), m, math.sqrt(bias_g) * val, "ThêoBR"))
    return out


# %% ===========================================================================
#    FULL STABILITY-ANALYSIS SWEEP
# =============================================================================
def compute_all_deviations(x: "np.ndarray", tau0: float, m_values: Optional[List[int]] = None,
                           include_theo: bool = True,
                           workers: Optional[int] = None) -> List[StabilityPoint]:
    """Compute ADEV, OADEV, MDEV, TDEV and OHDEV on tau = m*tau0, m up to
    0.5*N (the AVAR coverage limit -- SP1065 Sec. 3.4.1), one thread per
    averaging factor. Thêo1/ThêoBR/ThêoH live on a different grid
    (tau = 0.75*m*tau0) reaching 75 % of the record and come from
    compute_theoh_family(); ``include_theo`` is accepted for 0.0.1
    compatibility and ignored (the theo1/theoh fields stay None).
    """
    del include_theo
    x = np.asarray(x, dtype=float)
    N = len(x)
    if m_values is None:
        m_values = octave_m_values(N, max_frac=0.5)
    y = phase_to_freq(x, tau0)

    def one(m: int) -> StabilityPoint:
        tau = m * tau0
        a_val, _ = adev_nonoverlapping(x, tau0, m, y=y)
        oa_val, oa_n = oadev(x, tau0, m)
        md_val, _ = mdev(x, tau0, m)
        oh_val, _ = ohdev(x, tau0, m)
        return StabilityPoint(tau=tau, m=m, n_used=oa_n, adev=a_val, oadev=oa_val,
                              mdev=md_val, tdev=tdev_from_mdev(md_val, tau),
                              ohdev=oh_val, theo1=None, theoh=None)

    # Each m costs O(N): parallel only pays for long records.
    w = workers if N * len(m_values) >= PARALLEL_MIN_OPS else 1
    return _parallel_map(one, list(m_values), w)


# %% ===========================================================================
#    NOISE-TYPE IDENTIFICATION (SLOPE METHOD)
# =============================================================================
def _nearest_noise_type(mu: float) -> str:
    best_name, best_d = "Unclassified", float("inf")
    for name, _alpha, mu_a, _mu_m in NOISE_TABLE:
        d = abs(mu - mu_a)
        if d < best_d:
            best_d, best_name = d, name
    return best_name


def _log10_or_nan(values: Sequence[float]) -> "np.ndarray":
    """log10 of positive finite values, NaN elsewhere (no warnings)."""
    v = np.asarray(values, dtype=float)
    out = np.full(v.shape, np.nan)
    good = np.isfinite(v) & (v > 0)
    out[good] = np.log10(v[good])
    return out


def classify_noise(points: List[StabilityPoint]) -> List[NoiseClassification]:
    """Classify the dominant power-law noise type in each octave from the
    local log-log slopes of OADEV, MDEV and OHDEV vs tau (SP1065 Table 1 /
    IEEE 1139).

    * White PM and Flicker PM both give an OADEV slope near -1; MDEV
      (-1.5 vs -1.0) separates them (why MDEV was defined, SP1065 3.4.4).
    * A linear frequency drift gives an OADEV slope near +1 like
      Flicker-Walk FM, but the Hadamard deviation does not see it. A +1
      OADEV slope with an OHDEV slope at least 0.5 lower (or an OHDEV of
      zero) is reported as "Linear Freq. Drift".
    """
    results = []
    taus = np.array([p.tau for p in points], dtype=float)
    log_t = _log10_or_nan(taus)
    log_a = _log10_or_nan([p.oadev for p in points])
    log_m = _log10_or_nan([p.mdev for p in points])
    log_h = _log10_or_nan([p.ohdev for p in points])
    zero_h = np.array([p.ohdev == 0.0 for p in points])
    for i in range(len(points) - 1):
        if not (np.isfinite(log_a[i]) and np.isfinite(log_a[i + 1])):
            continue
        dlt = log_t[i + 1] - log_t[i]
        slope_a = (log_a[i + 1] - log_a[i]) / dlt
        slope_m = float("nan")
        if np.isfinite(log_m[i]) and np.isfinite(log_m[i + 1]):
            slope_m = (log_m[i + 1] - log_m[i]) / dlt
        slope_h = float("nan")
        if np.isfinite(log_h[i]) and np.isfinite(log_h[i + 1]):
            slope_h = (log_h[i + 1] - log_h[i]) / dlt

        if -1.3 < slope_a < -0.7 and np.isfinite(slope_m):
            # Disambiguate White/Flicker PM using the MDEV slope
            noise = "White PM" if slope_m < -1.25 else "Flicker PM"
            conf = "high"
        elif (abs(slope_a - LINEAR_DRIFT_SLOPE) < 0.3
              and ((zero_h[i] and zero_h[i + 1])
                   or (np.isfinite(slope_h) and slope_h < slope_a - 0.5))):
            noise = LINEAR_DRIFT_LABEL
            conf = "high" if np.isfinite(slope_h) or (zero_h[i] and zero_h[i + 1]) else "low"
        else:
            noise = _nearest_noise_type(slope_a)
            conf = "high" if np.isfinite(slope_m) and abs(slope_m - slope_a) < 0.4 else "low"

        results.append(NoiseClassification(
            tau=float(taus[i]), m=points[i].m, slope_adev=float(slope_a),
            slope_mdev=float(slope_m), noise_type=noise, confidence=conf,
            slope_hdev=float(slope_h),
        ))
    return results


# %% ===========================================================================
#    SYNTHETIC POWER-LAW NOISE (VALIDATION ONLY)
# =============================================================================
def generate_power_law_phase(n: int, tau0: float, alpha: int, amp: float = 1.0,
                             seed: int = 1234) -> "np.ndarray":
    """Generate a synthetic phase series x(t) whose fractional-frequency PSD
    follows Sy(f) ~ f^alpha (the IEEE 1139 power-law model) by FFT spectral
    shaping of white Gaussian noise (in the spirit of Kasdin & Walter's
    discrete power-law simulation). Used only to validate the estimators
    against the expected ADEV/MDEV slopes -- NOT for real measurement data.
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


# %% ===========================================================================
#    INTERACTIVE SCRATCH CELL (Spyder)
# =============================================================================
# import time
# x = generate_power_law_phase(100_000, 1.0, alpha=0, seed=1)      # white FM
# t0 = time.perf_counter(); fam = compute_theoh_family(x, 1.0)
# print(f"ThêoH: {len(fam)} points in {time.perf_counter() - t0:.1f} s "
#       f"on {available_cpus()} CPUs; GPU: {gpu_available()}")
# for c in classify_noise(compute_all_deviations(x, 1.0)):
#     print(f"{c.tau:8.0f} s  {c.noise_type:18s} {c.confidence}")
