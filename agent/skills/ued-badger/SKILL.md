---
name: ued-badger
description: >
  Draft, check, run and read back Badger optimization routines for the UED
  with the ued_badger tools: the co-tuning after the collimator (stage 5:
  Sol1, Sol2, XC/YC00-04 against the Andor spot) and the sample position
  (stage 7: sample x/y against the Andor diffraction intensity). Use when the
  operator asks to set up or rehearse a Badger routine, to run an
  optimization on the simulator, to follow or stop a run, or to prepare a
  routine for the operator to run in Badger on ued-daq.
summary: Badger routines for UED with the ued_badger tools (sim runs, real-machine drafts)
---

# Badger routines for UED (ued_badger)

The `ued_badger` server turns a VOCS into a Badger routine, checks it in
Badger itself, and runs it headless with a budget. Two environments:

| Environment | What it is | Runnable here |
|---|---|---|
| `ued_sim` | the virtual UED (GPT); `sim_preset` stage5 (after the collimator, sample out) or stage7 (at the Bi sample, main beam in the Andor through hole, diffraction settings); its knobs persist between runs | yes |
| `ued` | the real machine through EPICS | **no**: read-only here. Draft and check; the operator runs it in Badger on ued-daq |

Knobs (logical names, units as `ued_tuning` reports them): stage 5 `sol1`,
`sol2`, `xc00`, `yc00`, `xc01`, `yc01`, `xc02`, `yc02`, `xc04`, `yc04`;
stage 7 `sample_x`, `sample_y`. A knob exists only where the setup file
gives it a safety range (`badger_info` lists them per environment).
Observables: `andor_spot_size_px`, `andor_total`,
`andor_offset_from_centre_px`, `andor_sigma_x_px`, `andor_sigma_y_px`,
`andor_saturated`, and `andor_frame_sum` (counts over the whole frame: the
diffracted intensity, with the main beam in the through hole).

Typical routines:
- **Stage 5b, spot size:** minimize `andor_spot_size_px` over the magnets,
  constraint `andor_total` GREATER_THAN ~0.8 x now (expected_improvement).
- **Stage 7, sample position:** maximize `andor_frame_sum` over `sample_x`,
  `sample_y` within ~0.15 mm of the taught position, constraint
  `andor_saturated` LESS_THAN 0.5. The main beam must be in the through hole
  first (`tune_sample_position` does that) and the Andor at its diffraction
  settings.

## Steps

1. `badger_info`: the knobs' safety ranges per environment, the generators,
   any active run. The safety ranges come from the setup files; a routine
   can't range outside them.
2. Decide the VOCS with the operator. `ued_tuning.plan_beam_optimization`
   gives a starting VOCS for the real machine (see the ued-beam-optimization
   skill). Pick the generator:
   - `expected_improvement`: the default; takes constraints; 4-10 knobs.
   - `neldermead`: 1-4 knobs, quick, local; **takes no constraints**.
   - `mobo`: two objectives (spot size down, counts up); needs
     `generator_params: {reference_point: {...}}`.
3. `draft_routine(name, variables, objectives, constraints, environment,
   generator, ...)`. Give `variables` as a list of knobs for automatic
   ranges (current +/- `span_fraction` of the safety range), or as
   `{knob: [lo, hi]}`. The reply has `ok`, `errors`, `warnings`, `current`
   (knob values now), `now` (one reading of the observables) and the final
   ranges. Fix every error and redraft; report the warnings. Nothing is set
   on any machine by drafting.
4. On `ued_sim`: `run_routine(name, max_evaluations, max_minutes,
   on_finish)`. It asks the operator first. About 12 s per evaluation; a
   30-evaluation run is ~6-10 min. `on_finish='start'` (default) puts the
   knobs back; `'best'` leaves them at the best feasible point.
5. `poll_run(run_id)` every minute or so: state, evaluations so far, best so
   far. `stop_run(run_id)` stops after the current evaluation, any time.
6. `run_result(run_id)`: why it stopped, start vs best, the change in
   percent, where the knobs were left, the archive file (the Badger GUI can
   open it).
7. For the real machine: `draft_routine(..., environment='ued')` against the
   live values. The reply's `next` has the operator's command; pass it on:
   on ued-daq, `/sdf/group/mli/zhezhang/ued/agentic/scripts/badger_ued.sh
   run <routine path>` opens the Badger GUI with the routine loaded. The
   operator checks the ranges against the current values and presses Run;
   `--dry-run` first logs the writes without sending them. Writes happen only
   there, to the knobs, inside the safety ranges, each logged to
   `badger/ued_writes.jsonl`. Never claim it ran; afterwards the run is in
   the Badger archive.

## Reading the results

- `stop_reason`: `evaluation budget reached` or `time budget reached` are
  normal; `the generator has converged` (Nelder-Mead) too. `no beam on the
  Andor for N evaluations in a row` means the ranges are too wide or a knob
  steered the beam off: narrow the ranges. `error: ...` comes with
  `runner.log` in the run folder.
- A NaN (null) spot size means no beam seen at that point; Bayesian
  generators learn to avoid it, Nelder-Mead does not.
- The improvement is in the simulator. It tells whether the VOCS and the
  generator are sensible, not what the real machine will do.
- After any real-machine optimization (by the operator) check the e-beam on
  the sample-YAG cross again (`beam_on_screens` or `check_overlap`).

## Failure modes

- `cannot read the knobs from ued`: the accelerator-side PVs don't answer.
  From S3DF they need the gateway prefix (`UED_ACCEL_PV_PREFIX`); on
  2026-10-28 the prefix route did not answer yet. Say so; don't retry in a
  loop.
- `a run is active`: one run at a time; poll it or stop it.
- `reset_sim` puts the simulator back to the state after stage 5 (forgets
  earlier runs' knob changes). It asks first.
