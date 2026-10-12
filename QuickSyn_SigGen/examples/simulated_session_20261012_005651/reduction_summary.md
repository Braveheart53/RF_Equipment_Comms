# QuickSyn session reduction - 20261012_005651_FSW-0020_00000007

Produced by `quicksyn_veusz_export_v0_0_6.py` on 2026-10-12 00:57:53 UTC.

## Instrument

| Field | Value |
| --- | --- |
| `*IDN?` | `Phase Matrix,FSW-0020,00000007,0106,300A` |
| Model | FSW-0020 |
| Option field | `00000007` |
| Software version field | `0106` (= 106, decimal) |
| Serial field | `300A` |
| Datasheet coverage | 0.5 - 20 GHz |
| Transport | SIM at 115200 baud (SIMULATED) |

> The `*IDN?` field order is inferred from the native Get ID order in
> [R1] Table 4; it is not specified for the SCPI form.

## Acquisition timing

| Quantity | Value | Unit |
| --- | --- | --- |
| Samples | 401 |  |
| Loaded from | chunks |  |
| Duration | 39.9992 | s |
| Requested sample rate | 10 | Hz |
| Achieved sample rate | 10.0002 | Hz |
| Mean sample interval | 99.9979 | ms |
| Interval std (jitter) | 2.56112 | ms |
| Interval min / max | 82.566 / 113.767 | ms |
| Jitter relative to period | 25611.7 | ppm |
| Device I/O latency, mean | 6.1296 | ms |
| Device I/O latency, p95 | 8.9224 | ms |
| Device I/O latency, max | 10.424 | ms |

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
| Distinct frequencies observed | 4 |  |
| Frequency min | 8.250000000 | GHz |
| Frequency max | 19.500000000 | GHz |
| Power min | -3.0 | dBm |
| Power max | +8.0 | dBm |
| RF output on, fraction of samples | 1.000 | - |
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
| 0.1 | 2.137e-02 |
| 0.2 | 2.623e-02 |
| 0.4 | 3.570e-02 |
| 0.8 | 5.042e-02 |
| 1.6 | 7.262e-02 |
| 3.2 | 1.074e-01 |
| 6.4 | 1.687e-01 |
| 12.8 | 3.058e-01 |

## Reduction

| Quantity | Value |
| --- | --- |
| Compute backend | numpy |
| Reduction wall time | 6.6 ms |
| Script revision | 0.0.6 |
