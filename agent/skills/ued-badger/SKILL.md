---
name: ued-badger
description: >
  Draft, check, run and read back Badger optimization routines for the UED
  (Sol1, Sol2, XC/YC00-02, XC/YC04 against the Andor spot) with the
  ued_badger tools. Use when the operator asks to set up or rehearse a
  Badger routine, to run an optimization on the simulator, to follow or stop
  a run, or to prepare a routine for the real machine.
summary: Badger routines for UED with the ued_badger tools (sim runs, real-machine drafts)
---

# Badger routines for UED (ued_badger)

The `ued_badger` server turns a VOCS into a Badger routine, checks it in
Badger itself, and runs it headless with a budget. Two environments:

| Environment | What it is | Runnable here |
|---|---|---|
| `ued_sim` | the virtual UED (GPT), starting from the state after stage 5; its knobs persist between runs | yes |
| `ued` | the real machine, through EPICS (with the gateway prefix from S3DF) | **no**: read-only. Draft and check only; an operator runs the routine in Badger |

Knobs (logical names, units as `ued_tuning` reports them): `sol1`, `sol2`,
`xc00`, `yc00`, `xc01`, `yc01`, `xc02`, `yc02`, `xc04`, `yc04`. Observables:
`andor_spot_size_px`, `andor_total`, `andor_offset_from_centre_px`,
`andor_sigma_x_px`, `andor_sigma_y_px`, `andor_saturated`.

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
   live values, then give the operator the routine path to load in Badger.
   Never claim it ran.

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
