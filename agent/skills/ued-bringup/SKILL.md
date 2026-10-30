---
name: ued-bringup
description: >
  Run or rehearse the UED beamline bring-up with the ued_tuning tools, stage by
  stage: gun RF ramp-up, emission-phase (Schottky) scan, bunch charge, beam on
  the sample YAG and the Andor, collimator, pump-laser spatial overlap, sample
  position, time zero. Use when the operator asks to bring up, check, tune or
  rehearse a UED stage, asks what comes next in the bring-up, or asks why a
  stage stopped.
summary: Stage-by-stage UED bring-up with the ued_tuning tools
---

# UED bring-up

The `ued_tuning` MCP server has one tool per bring-up stage, plus checks and
automation tools. Work through the stages in order, one at a time, with the
operator.

## First, every time

1. Call `ued_tuning_info`. It names the backend, the setup file, and what that
   file still lacks (`setup_missing`: taught positions, laser setpoints).
   - `epics` is the real machine and refuses every write. A stage that stops
     at its first write is the expected outcome: say so plainly, report what
     it read before stopping, and don't retry. Never try to write a PV another
     way.
   - `sim` is the virtual machine, for rehearsal.
   - `pv_access` says how PVs are reached. From S3DF (`accel_pv_prefix`
     set), the accelerator-side PVs (gun RF, magnets, correctors, gate
     valves, diagnostic screen, scope) come through the EPICS gateway under
     a prefix. On 2026-10-29 the gateway served some of them only as
     never-processed placeholders (0.0, timestamp 1990-01-01). The tools
     report those as unavailable ("a gateway placeholder"), never as values.
     Say so; don't present a 0 from them as the machine's state.
2. For a beam stage (2-8), call `check_beam_prerequisites`. All four gate
   valves (`gv240`, `gv272`, `gv280`, `gv295`) must read OPEN. If one doesn't,
   stop and tell the operator which ones; the stage tools stop there anyway.
   Relay every entry in its `warnings` (pump power meter IN, a closed
   valve, the pump outcoupling mirror IN) and its `not_checked` list (e.g.
   the outcoupling mirror's IN/OUT positions not set yet:
   ask the operator to confirm it is out before pump-probe). The ePix valve
   `gv320` is reported for information only.

## Rules

- **Diagnostic screen.** The screen (YAGS:AS01:270) is moved by an operator,
  never by the agent. When a stage asks for it, ask the operator to insert or
  remove it from the panel, then read `diag_screen_state` and
  `diag_screen_interlock` with `machine_read` and report them before rerunning
  the stage with `diag_screen_by_operator=true`. If the interlock is not OK,
  or the state doesn't match the request, stop and tell the operator.

- **Pump-laser shutter.** The tools close it first, and again after any step
  that opens it. If a tool fails in the middle of a step that had the pump
  open, call `close_pump_shutter` straight away. Never leave it open.
- **Operator steps.** When a result has `needs_operator: true`, relay its
  `reason` and `operator_steps` as they are, and wait. Don't work around them.
- **One stage at a time.** Each stage tool asks the operator before it runs.
  Say what the stage will do and what it needs before calling it.
- **Records.** Results carry a `record` path (a folder on S3DF with the
  numbers, traces and images). Quote it when you report.

## The stages

| # | Tool | Needs first | Done when | Escalates when |
|---|---|---|---|---|
| 1 | `gun_ramp` | Operator confirms the panel: AREQ at 0, modulator in TRIG, HV at full voltage (VoltSet 980 V). These aren't readable. | AREQ at target, both feedbacks Active | temperature run-away, feedback trip, AACT stops tracking AREQ |
| 2 | `schottky_scan` | Diagnostic screen inserted by hand (it has no PV); then call with `diag_screen_by_operator=true` | Emission phase found on the scope, PREQ = emission + 30 deg | no e-beam on the screen (only dark current), no emission window |
| 3 | `set_bunch_charge` | Operator confirms Cameron's UV feedback loop is **stopped** (it drives the same throttle); then `feedback_loop_off=true` | 10 fC (-1.7 mV on scope CH2); then the `handoff` steps | charge won't reach the target |
| 4 | `beam_on_screens` | Diagnostic screen extracted (by hand: `diag_screen_by_operator=true`); taught `yag` and `andor` positions | e-beam on the YAG cross (cross moved if it was near), beam on the Andor | no beam; e-beam far from the cross (an operator judges) |
| 5 | `align_collimator` | Stage 4 accepted | Collimator tuned near 90 mm (200 um hole) for the most Andor counts | no transmission (the beam misses the hole) |
| 5b | `plan_beam_optimization` | Stage 5 accepted | A VOCS for Badger (single objective with a constraint, or `multi_objective=true` as the proposal has it): see the ued-beam-optimization skill | the routine doesn't converge |
| 6 | `overlap_pump_laser` | `pump.hwp_min_energy_deg` from the laser team | e-beam and laser both on the cross; pump shutter closed | e-beam off the cross; laser not seen |
| 7 | `tune_sample_position` | Taught sample position (e.g. `bi`); `andor.through_hole_px` | Always escalates: the operator judges the pattern, then `save_position` | main beam not in the Andor through hole; saturation |
| 8 | `find_time_zero` | Stage 6 overlap still good; `pump.hwp_pump_probe_deg` (~2 uJ); the `time_zero` section of the setup file | t0 found, delay left there | overlap check fails; no drop in the window; BOED t0 uncertain or disagrees with the signal |

Notes per stage:

- **1.** The gun runs on the TS8 klystron (KY03). If AREQ was parked above
  0.05, the ramp's first step lowers it to 0.05. Tell the operator before starting.
  The ramp takes **about 20 min** (600 steps of 2 s, from `gun.ramp_n_steps`
  and `gun.ramp_dwell_s` in the setup file): it was slowed from 10 min for
  the reduced gun cooling-water flow. Don't pass `n_steps` or `dwell_s`
  unless the operator asks; say how long the ramp will take before starting.
  The gun body temperature window is 33-37 C (`gun.ramp_temp_min_C` /
  `ramp_temp_max_C`). The gun idles near 36.4 C with the RF off, so there is
  little headroom with the reduced flow: holds near 37 C are expected;
  report them. If the ramp aborts on temperature, tell the operator and
  don't restart it unasked.
- **2.** "Emission phase" here is the onset, where the scope charge first rises
  5 sigma above the trace noise, with the UV throttle at ~51. The operator may
  define it differently (half-max, peak); ask if the result looks off. The
  scope channel is a setting (`scope.channel`, CH2 by default, confirmed in
  the dry run; Fuhao's procedure text names CH0). If no pulse shows on a beam
  the screen camera sees, ask which channel is right. The scope's V/div PV
  reads UDF: the charge numbers trust it.
- **2, BSA option.** `schottky_scan(method='bsa')` replaces the fine scan
  with Sam Klein's amortized T0 posterior: four 10-point scans in a 70 deg
  window, each placed by the posterior so far. `onset_guess_deg` (the last
  known emission phase, within ~10 deg) skips the coarse scan too, so the
  stage takes 40 points instead of ~90. The model's T0 is where the charge
  starts to rise, about 1-2 deg before the grid method's threshold crossing
  (`bsa.check.threshold_crossing_deg` gives both). The stage stops for an
  operator, with PREQ put back, if the 98 % interval is wider than
  `bsa_max_width_deg` or the measured charge disagrees with the onset;
  then rerun with the default `method='grid'`. It hasn't been tried on a
  real UED scan yet: use `grid` unless the operator asks for BSA.
- **3.** After the fine tune, walk the operator through `handoff`: teach the
  loop at 10 fC ("set low charge") and 30 fC ("set high charge"), then
  "start feedback". From then on the loop owns the UV throttle: don't run
  `set_bunch_charge` again while it runs. Use `monitor_charge` (read-only) to
  watch the charge hold.
- **4, 6.** The e-beam check toggles the gun UV shutter to tell the beam from
  dark current. Within `cross.max_move_px` of the cross the tool moves the
  cross onto the beam; farther, the operator decides.
- **7.** There is no single objective for a good pattern. Report the total
  scattering intensity and, where a score exists, the pattern quality, and let
  the operator judge (sharp features, one clean domain). For a single
  crystal the symmetry is balanced with the sample pitch and yaw, which the
  tools don't move for now (stale IOC soft limits): ask the operator to set
  them by hand. Save the position only after the operator agrees.
- **8.** The signal is the Bi Delta I/I (%) at a ring, from Andor frames
  taken pump ON, OFF, OFF, ON at each delay (Fuhao's April 2026
  measurement). The default `method='grid'` zooms in on the drop around
  `center_mm` (or the current delay) and fits an erf step.
  `method='boed'` runs the April 2026 amortized BOED scan over
  `time_zero.boed_window_mm`: 10 grid points, then 70 drawn from the t0
  posterior, so about 35 min at ~26 s a point. t0 is the posterior median.
  The stage stops for an operator, with the delay put back, if the 98 %
  interval is wider than `boed_max_width_mm` or the signal disagrees.
  The models expect the baseline before t0 at 0 and a drop near April's
  ~4.4 %. `boed_y_shift` and `boed_y_scale` adjust for that, and
  `boed.check` suggests values from the first grid points. If its notes
  say they're off, tell the operator the suggested values before rerunning
  with `y_shift=` / `y_scale=`. Use `grid` unless the operator asks for
  BOED.
- **8, while it runs.** A scan takes 20-35 min. The tool sends a progress
  message per point (delay, Delta I/I, the t0 estimate so far). The first
  message names the record folder, which fills from the start:
  `live.jsonl`, one line per point, and `live.png`, the points so far with
  t0. Tell the operator the folder at the start so they can watch the
  plot. If the run is stopped, the points are still in `live.jsonl`.

## Camera views (sample chamber camera + chamber light)

| View | State | Exposure | Gain | Light |
|---|---|---|---|---|
| `full_view` | 1, sample chamber full view | 0.1 s | 0 | on |
| `ebeam` | 2, e-beam on the YAG | 1 s | 10 | off |
| `laser` | 3, pump laser on the YAG | 0.5 s | 5 | off |

These come from the setup file and may change with the pulse charge and the
pump wavelength. `set_camera_view` sets one.

## Reporting

After each stage, give one line on the outcome with its key numbers, then
what the operator must do next. Mention the backend whenever it matters
(`sim` numbers are a rehearsal, not the machine).
