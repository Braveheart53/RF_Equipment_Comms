# QuickSyn session reduction - session

Produced by `quicksyn_veusz_export_v0_0_9.py` on 2026-10-12 19:50:43 UTC.

## Instrument

| Field | Value |
| --- | --- |
| `*IDN?` | `Phase Matrix,FSL-0020,0000017f,1530200407,0008` |
| Model | FSL-0020 |
| Option word | `0000017f` (options 1, 2, 3, 4, 5, 6, 7, 9) |
| Serial number | `1530200407` |
| Firmware version | `0008` |
| Datasheet coverage | 0.65 - 20 GHz |
| Transport | COM5 at 115200 baud |

> `*IDN?` fields: manufacturer, model, option word, serial, firmware.
> [R1] does not define the order; it was confirmed against NI's soft
> front panels on an FSL-0020 (option bit n = option n+1).

## Acquisition timing

| Quantity | Value | Unit |
| --- | --- | --- |
| Samples | 1201 |  |
| Loaded from | chunks |  |
| Duration | 600 | s |
| Requested sample rate | 2 | Hz |
| Achieved sample rate | 2 | Hz |
| Mean sample interval | 500 | ms |
| Interval std (jitter) | 14.8413 | ms |
| Interval min / max | 312.000 / 688.000 | ms |
| Jitter relative to period | 29682.7 | ppm |
| Device I/O latency, mean | 11.7086 | ms |
| Device I/O latency, p95 | 16 | ms |
| Device I/O latency, max | 188 | ms |

The sample period is the reciprocal of the requested rate,

$$ \tau_0 = \frac{1}{f_s} $$

and the achievable rate is bounded by the number of serial round
trips each sample costs. With $N_q$ queries per sample and a mean
round-trip time $t_q$,

$$ f_{s,\max} = \frac{1}{N_q \, t_q} $$

so a sample that polls frequency, power, status, modulation and
temperature (the last counting twice when the conservative
double-issue rule is enabled) costs $N_q = 6$, and at
$t_q \approx 8$ ms gives $f_{s,\max} \approx 21$ Hz.

## Generated signal

| Quantity | Value | Unit |
| --- | --- | --- |
| Distinct frequencies observed | 1 |  |
| Frequency min | 1.000000000 | GHz |
| Frequency max | 1.000000000 | GHz |
| Power min | -10.0 | dBm |
| Power max | +5.0 | dBm |
| RF output on, fraction of samples | 0.127 | - |
| Samples with RF unlocked | 0 |  |
| Samples with reference unlocked | 0 |  |
| Samples with voltage error | 0 |  |

## Thermal

| Quantity | Value | Unit |
| --- | --- | --- |
| Internal temperature min | 26.8 | degC |
| Internal temperature max | 57.5 | degC |
| Rise over session | +2.1 | degC |
| Margin to the +75 degC limit | 17.5 | degC |

## Stability of the reported carrier

Fractional frequency error against the median commanded carrier
$f_c$ is $y_i = (f_i - f_c)/f_c$, and the overlapping Allan
deviation follows IEEE Std 1139-2008:

$$ \sigma_y^2(\tau) = \frac{1}{2\,(N-2m+1)\,\tau^2} \sum_{k=1}^{N-2m+1} \left( x_{k+2m} - 2x_{k+m} + x_k \right)^2 , \qquad \tau = m\,\tau_0 $$

with phase residuals $x_k = \tau_0 \sum_{i<k} y_i$.

> This characterises command fidelity and the logging time base, not
> carrier phase noise: `FREQ?` returns the commanded setting, not a
> measurement of the output. Phase noise is specified separately in
> the datasheet and cannot be inferred from this log.

| Averaging time tau (s) | ADEV |
| --- | --- |
| 0.5 | 0.000e+00 |
| 1 | 0.000e+00 |
| 2 | 0.000e+00 |
| 4 | 0.000e+00 |
| 8 | 0.000e+00 |
| 16 | 0.000e+00 |
| 32 | 0.000e+00 |
| 64 | 0.000e+00 |
| 128 | 0.000e+00 |
| 256 | 0.000e+00 |

## Reduction

| Quantity | Value |
| --- | --- |
| Compute backend | numpy |
| Reduction wall time | 13.6 ms |
| Script revision | 0.0.9 |
