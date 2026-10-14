# QuickSyn session reduction - 20261014_163313_FSW-0020_0000007f

Produced by `quicksyn_veusz_export_v0_0_10.py` on 2026-10-14 16:34:00 UTC.

## Instrument

| Field | Value |
| --- | --- |
| `*IDN?` | `Phase Matrix,FSW-0020,0000007f,1530200001,0008` |
| Model | FSW-0020 |
| Option word | `0000007f` (options 1, 2, 3, 4, 5, 6, 7) |
| Serial number | `1530200001` |
| Firmware version | `0008` |
| Datasheet coverage | 0.5 - 20 GHz |
| Transport | SIM at 115200 baud (SIMULATED) |

> `*IDN?` fields: manufacturer, model, option word, serial, firmware.
> [R1] does not define the order; it was confirmed against NI's soft
> front panels on an FSL-0020 (option bit n = option n+1).

## Acquisition timing

| Quantity | Value | Unit |
| --- | --- | --- |
| Samples | 414 |  |
| Loaded from | chunks |  |
| Duration | 41.2965 | s |
| Requested sample rate | 10 | Hz |
| Achieved sample rate | 10.0009 | Hz |
| Mean sample interval | 99.9914 | ms |
| Interval std (jitter) | 2.73932 | ms |
| Interval min / max | 78.215 / 124.930 | ms |
| Jitter relative to period | 27395.5 | ppm |
| Device I/O latency, mean | 5.96576 | ms |
| Device I/O latency, p95 | 8.72443 | ms |
| Device I/O latency, max | 11.9666 | ms |

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
| Distinct frequencies observed | 5 |  |
| Frequency min | 8.250000000 | GHz |
| Frequency max | 19.500000000 | GHz |
| Power min | -3.0 | dBm |
| Power max | +13.0 | dBm |
| RF output on, fraction of samples | 0.000 | - |
| Samples with RF unlocked | 0 |  |
| Samples with reference unlocked | 0 |  |
| Samples with voltage error | 0 |  |

## Thermal

| Quantity | Value | Unit |
| --- | --- | --- |
| Internal temperature min | 29.0 | degC |
| Internal temperature max | 29.5 | degC |
| Rise over session | +0.5 | degC |
| Margin to the +75 degC limit | 45.5 | degC |

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
| 0.09999 | 1.622e-02 |
| 0.2 | 1.991e-02 |
| 0.4 | 2.681e-02 |
| 0.7999 | 3.710e-02 |
| 1.6 | 5.325e-02 |
| 3.2 | 7.859e-02 |
| 6.399 | 1.239e-01 |
| 12.8 | 2.292e-01 |

## Reduction

| Quantity | Value |
| --- | --- |
| Compute backend | numpy |
| Reduction wall time | 8.7 ms |
| Script revision | 0.0.10 |
