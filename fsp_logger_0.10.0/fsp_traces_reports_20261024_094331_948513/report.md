# R&S FSP measurement report

## Acquisition

| Item | Value |
|---|---|
| source_csv | C:\Users\wwallace\fsp_traces.csv |
| source_sha256 | a0f7b86e3dd2cae2b8e0e2a679b845aada7d59d6d1740555ce660f3de5f8d21d |
| captures | 3 |
| frequency_points | 801 |
| traces | [1, 2] |
| first_timestamp | 2026-10-24T09:43:18.579 |
| last_timestamp | 2026-10-24T09:43:28.212 |
| duration_s | 9.633 |

## Trace extrema

| Trace | Peak (dBm) | Frequency (Hz) | Capture |
|---|---:|---:|---:|
| 1 | -28.5038 | 1300000000.000000 | 1 |
| 2 | -23.8329 | 1550000000.000000 | 0 |

## Frequency-time plots

One Freq_N_GHz page per frequency, showing independent analyzer traces.
Combined_Freq_vs_Time has one panel per analyzer trace and N GHz keys.
Naive CSV wall time preserved; reporting-host timezone not applied.
Raw values: no averaging, interpolation or decimation in frequency-time plots.
All prior report/envelope/waterfall/peak-history/last-capture pages retained.

## Interpretation

All means are linear-power averages converted back to dBm; no cross-channel mean.
Waterfall row = capture index; capture_datetime and elapsed_s retain irregular timing.

Legacy CSV lacks RBW/VBW/detector/impedance/calibration metadata.
No EMC compliance claim or integrated channel-power assertion.
Single-bin/capture image extents use +/-0.5 display units.
Legacy CSV cannot independently prove first/sole capture completeness.
All bins included: large sweeps generate many pages and crowded combined legends.

## Rendering

```json
{
  "requested": false,
  "status": "not_requested"
}
```
