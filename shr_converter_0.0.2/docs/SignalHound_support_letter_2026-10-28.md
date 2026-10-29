---
title: Questions to Signal Hound support on the SHR sweep-recording format
author: William W. Wallace (NRAO/GBO)
date: 2026-10-28
to: support@signalhound.com
status: Draft for the author to send (nothing has been sent)
---

**To:** support@signalhound.com
**Subject:** SHR sweep-recording format: detector codes 2/3, multi-file sets, triggered and channelized recordings (SM200C, Spike 4.0)

Hello,

I convert Spike sweep recordings (.shr) from our SM200C to CSV and Veusz documents with a Python reader built from the definition in your SDK (`shr_parser/shr_parse.h` in the 2026-10-05 SDK). A recording made with the current Spike release (4.0.17 according to your change log) carries `detector = 2` (byte 352 of the file header), a value that `SHRVideoDetector` in `shr_parse.h` does not list (0 = MinMax, 1 = Average). The file is otherwise exactly as the header file describes: version 2, `dataOffset` 472, 460 sweeps of 8384 bins. I can send this 15 MB sample if it helps.

From the data, I infer that code 2 is the Max detector added in Spike 3.5.7. Every amplitude lies on a 0.01 dB grid, as your SM product manual describes for min/max processing, and the noise statistics match a max hold of about 500 FFTs. I would be grateful if you could confirm or correct the following:

1. **Detector codes.** What are the values of the `detector` field for Average, Min/Max, Min and Max? Is 2 = Max and 3 = Min? Are there others?
2. **Min/Max recordings.** A sweep stores one array. When the detector is Min/Max, does the file hold the max array, the min array, or something else?
3. **Amplitude grid offset.** In this recording every value is a multiple of 0.01 dB plus a constant +0.00824 dB. Is that constant a correction (reference level, calibration, path loss) added after the 0.01 dB quantisation? Is the quantisation the same in sweep mode and real-time mode?
4. **Sweep vs real-time mode.** Does a recording say whether it was made in sweep or real-time mode, or with which real-time accumulation? If not, is the sweep time or FFT count per output trace recorded anywhere?
5. **Multi-file recordings (Spike 3.9.7).** How are the files of one recording named and numbered? Does each file have a complete header with its own `sweepCount`? Is there anything in the header that links the files of one recording?
6. **Limit-line-triggered recordings (Spike 4.0.17).** Are the sweeps that do not exceed the limit lines simply left out, with no marker? Does any header or sweep-header field (for example the reserved bytes) change?
7. **Channelized recordings.** When `channelizeEnabled` = 1, do `firstBinFreqHz`, `binSizeHz` and `sweepLength` describe the channels (centre of the first channel, channel spacing, number of channels)? Are the values channel powers in the unit of `channelOutputUnits`?
8. **Time decimation.** With `decimationType` = Time or Count, which instant does a sweep's time stamp mark: the first, last or middle sweep of the window?
9. **Time stamps.** Are they the PC clock in milliseconds since 1970 UTC, or GPS time when the SM200C's GPS is locked? Do they mark the start or the end of the sweep's acquisition?
10. **Interrupted recordings.** Is `sweepCount` written only when a recording is closed, so that a crash leaves 0 or a stale value?
11. **Attenuation and gain.** For the SM200C, are `attenuation` and `gain` indices or dB values, and does 0 mean "auto"?
12. **Title and future versions.** Is the title UTF-16LE (`uint16_t title[128]`)? Are the 64 reserved bytes at the end of the header, and file versions above 2, planned for use?

An updated `shr_parse.h` with the full enumerations would be very helpful.

A small issue in the same SDK example: `SHRGetSweep()` in `shr_parse.cpp` compares `sweepBytesRead` with `sweepSizeInBytes`. The latter includes the 48-byte sweep header, so the function returns false even when the read succeeds. Comparing with `sizeof(float) * state.header.sweepLength` would fix it.

Thank you,

William W. Wallace
NRAO / Green Bank Observatory
wwallace@nrao.edu

---

*Note for the author (not part of the email):*
- Check the Spike version in Help > About before sending.
- Attach the sample if you want them to look at it (`tests/data/75fb3092-...-01h01m58s.shr`, 15.4 MB).
- Their answers map to the open items:
  - **Detector codes:** `shr_reader.ENUM_FIELDS["detector"]`.
  - **Multi-file sets:** `group_recordings()`.
  - **Channelized recordings:** the header note in `ShrHeader.consistency_notes()`.
  - **Time stamps:** CSV time columns and the spectrogram rows.
