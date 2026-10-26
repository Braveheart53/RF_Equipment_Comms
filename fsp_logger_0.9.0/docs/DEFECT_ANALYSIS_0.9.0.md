# Defect analysis: Auto / A / B had to be toggled before the right traces were read

Logger 0.8.3 → 0.9.0 · 2026-10-26 · William W. Wallace (owner) · AI-assisted analysis

## Symptom (as reported)

The *Auto* screen button and the *A* or *B* button had to be toggled in the GUI before
the logger pulled the correct traces.

## Background

The R&S FSP has two measurement screens. In remote control, the numeric suffix of
`SENSe<1|2>`, `DISPlay[:WINDow<1|2>]` and `TRACe<1|2>` selects the screen: 1 is Screen A
and 2 is Screen B. A header **without** a suffix is interpreted as suffix 1 [1], [2]:

* FSP manual, ch. 5, p. 5.12: "Entries without suffix are interpreted like entries with
  the suffix 1." [1]
* SCPI-99 vol. 1, §6.2.5.2: "If the suffix is absent, the command is treated as being
  designated for capability number one." [2]

## Root causes in 0.8.3

| # | Where | Defect | Effect |
|---|---|---|---|
| 1 | `FSPInstrument.active_traces()` | Sent `DISP:TRAC<n>:MODE?` with no WINDow suffix, which always addresses Screen A | With Screen B in use, the LEDs, the CSV columns and the traces fetched were Screen A's display state, while frequencies came from Screen B |
| 2 | `MainWindow.on_connect()` | Created a new `FSPInstrument` (Auto) and never applied the radio button that was shown | A or B selected before Connect (or kept from a previous connection) was ignored until the buttons were clicked again |
| 3 | `FSPInstrument._discover_active_screen()` | Ran once per connection (`_screen_discovered` stayed True) | Screen changes made on the analyzer were ignored until Auto was toggled off and on |
| 4 | `FSPInstrument._fetch_trace_with_syntax_discovery()` | Screen B's fetch list fell back to `TRAC? TRACE<n>` and `TRAC1? TRACE<n>` (Screen A forms); one template was cached per session, and automatic detection did not clear it | Silent Screen A data on Screen B; only `force_screen()` / `reset_screen_discovery()` cleared the cache, so toggling appeared to fix it |

## Evidence (0.8.3 code, simulator, 2026-10-26)

`python docs/repro_0.8.3_screen_defects.py <0.8.3 folder> <0.9.0 folder>` with Screen A near
start-up defaults (trace 1 only, 501 points) and Screen B configured (traces 1, 2 and 3,
801 points):

```text
logger version under test: 0.8.3
1) Auto selects screen 2 centre 13900000000.0 Hz
   active_traces() -> [1]    (Screen B shows traces 1, 2, 3)
   MODE queries sent: ['DISP:TRAC1:MODE?', 'DISP:TRAC2:MODE?', 'DISP:TRAC3:MODE?']
4) cached template 'TRAC? TRACE{n}' used on Screen B -> 501 points (Screen B has 801, Screen A 501)
   Screen B candidates include Screen A forms: ['"TRAC? TRACE{n}"', '"TRAC1? TRACE{n}"']
2) on_connect() in 0.8.3 never calls force_screen(): True
3) after the front-panel change Auto still uses screen 2 (A now has the higher centre); probe/start do not re-detect
```

The simulator follows the suffix rule of [1] and [2]. The physical FSP-38 (firmware 4.50)
has not been re-tested. The 0.8.3 code comments already record that Screen A queries return
start-up values and that `TRAC?` gives -100 on the inactive screen, which agrees with causes
1 and 4.

## Fixes in 0.9.0

| # | Fix | Test (tests/test_screen_and_reset.py) |
|---|---|---|
| 1 | Trace modes are read with `DISP:WIND<s>:TRAC<n>:MODE?` for the selected screen. The suffix-less form is only a fallback for Screen A. An unreadable screen raises a clear `FSPError` instead of reporting "no traces". | `test_auto_reads_trace_modes_from_detected_screen`, `test_forced_screen_a_reads_screen_a`, `test_unreadable_modes_raise_instead_of_reporting_none` |
| 2 | `on_connect()` calls `set_screen_mode()` with the shown choice before the first query. | `test_choice_applied_before_first_query`, `GuiTests.test_screen_choice_before_connect_is_applied` |
| 3 | `refresh_screen_selection()` makes Auto re-detect at Connect, Probe, Start, Diagnostics and Reset, but never between captures. | `test_auto_redetects_only_when_refreshed` |
| 4 | Fetch forms are restricted to the selected screen and cached per screen. | `test_fetch_template_is_per_screen`, `test_fetch_never_falls_back_to_other_screen` |
| — | A screen change re-reads trace modes and the LEDs; an *In use* label and LED mode tooltips make the active screen visible. | `GuiTests.test_screen_choice_before_connect_is_applied` |

## What to check on the analyzer

1. Connect with **B** selected and open **Diagnostics**. The *Per-screen settings and trace
   modes* table should show Screen B's real trace modes, and the *In use* label should say
   *Screen B (forced)*.
2. If Screen B's MODE column says *(no answer)*, the firmware rejects
   `DISP:WIND2:TRAC<n>:MODE?`. Send the Diagnostics text back, and the alternative form can
   be added.

## References

| No. | Reference | URL |
|---|---|---|
| [1] | Rohde & Schwarz, *R&S FSP Spectrum Analyzer Operating Manual*, 1164.4556.12, ch. 5, p. 5.12; ch. 6. | https://www.rohde-schwarz.com/us/manual/fsp/ |
| [2] | SCPI Consortium, *SCPI-99*, vol. 1 "Syntax and Style", §6.2.1 p. 6-2, §6.2.5.2 p. 6-8. | https://www.ivifoundation.org/downloads/SCPI/scpi-99.pdf |
