---
type: procedure
title: "UED bring-up, stage by stage"
description: "The eight Run 7 bring-up stages (gun ramp to time zero) as the ued_tuning tools run them, with what each needs first, when it is done, and when it stops for an operator."
timestamp: "2026-10-30"
tags: [ued, procedure, bringup]
---

# UED bring-up, stage by stage

Each stage is one tool of the `ued_tuning` server. Before any beam stage (2-8), `check_beam_prerequisites` must show gate valves 240, 272, 280 and 295 all OPEN. The pump shutter is closed first and after any step that opens it. Every write is checked against the safety ranges in the setup file. On the real machine the tools are read-only: a stage stops at its first write and reports what it read.

| # | Tool | Needs first | Done when | Stops for an operator when |
|---|---|---|---|---|
| 1 | `gun_ramp` | Operator confirms the panel: AREQ at 0, modulator in TRIG, HV at full voltage (VoltSet 980 V). | AREQ at target, both feedbacks Active | temperature leaves 33-37 C, a feedback trips, AACT stops tracking AREQ |
| 2 | `schottky_scan` | Diagnostic screen inserted by an operator (`diag_screen_by_operator=true`) | Emission phase found on the scope; PREQ = emission + 30 deg | only dark current on the screen; no emission window |
| 3 | `set_bunch_charge` | Operator confirms Cameron's UV feedback loop is stopped (`feedback_loop_off=true`) | 10 fC (-1.7 mV on scope CH2), then the handoff to the loop | charge won't reach the target |
| 4 | `beam_on_screens` | Diagnostic screen out; taught `yag` and `andor` positions | e-beam on the YAG cross, beam on the Andor | no beam; e-beam far from the cross |
| 5 | `align_collimator` | Stage 4 accepted | Collimator near 90 mm (200 um hole) at the most Andor counts | no transmission |
| 5b | `plan_beam_optimization` | Stage 5 accepted | A Badger VOCS for the spot size on the Andor (procedures/beam-optimization) | the routine doesn't converge |
| 6 | `overlap_pump_laser` | `pump.hwp_min_energy_deg` (8 deg) | e-beam and pump laser on the cross; pump shutter closed | e-beam off the cross; laser not seen |
| 7 | `tune_sample_position` | Taught sample position (e.g. `bi`); `andor.through_hole_px` | Always stops: the operator judges the pattern, then `save_position` | main beam not in the through hole; saturation |
| 8 | `find_time_zero` | Stage 6 overlap still good; `pump.hwp_pump_probe_deg` (22 deg) | t0 fitted | the overlap check fails |

## Stage notes

- **1.** See procedures/gun-ramp.
- **2.** The emission phase is where the scope charge first rises 5 sigma above the trace noise, with the UV throttle at ~51 deg. `method='bsa'` replaces the fine scan with an amortized posterior (physics/schottky-emission-phase).
- **3.** 10 fC on the scope is -1.7 mV below baseline (`scope.mV_per_fC: -0.17`). Teach the loop at 10 fC ("set low charge") and 30 fC ("set high charge").
- **4.** Camera views (full view, e-beam, laser) set exposure, gain and the chamber light: references/setup-file. The e-beam cross is moved to the beam only if it is within `cross.max_move_px`.
- **6-8.** The pump energy comes from the Harmonics HWP: references/pump-hwp-calibration. Coarse time zero is expected near 200 mm on the pump long delay.
