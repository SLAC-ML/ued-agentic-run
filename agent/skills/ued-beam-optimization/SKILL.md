---
name: ued-beam-optimization
description: >
  Plan the UED beam optimization that follows the collimator alignment:
  minimize the beam spot size on the Andor with Sol1, Sol2 and XC/YC00-02
  (XC/YC04 to keep it centred) while the transmitted charge stays above a
  level, as a Badger routine (rehearsed on the simulator, run on the real
  machine by an operator). Use when the operator asks to optimize the focus
  or spot size on the Andor, to set up a Badger routine, or what the
  steering magnets are for.
summary: Badger/Xopt plan for the post-collimator beam optimization
---

# UED beam optimization (after the collimator)

Once the beam shows on the sample YAG and the Andor (stage 4) and the
collimator is tuned (stage 5), the beam is at a good starting point. The usual
optimization then minimizes the spot size on the Andor while the transmitted
pulse charge stays above a level. It runs in Xopt/Badger with an operator:
the agent prepares the plan and never writes the magnets itself.

## Steps

1. Check that stage 5 (`align_collimator`) was accepted. Without the beam
   through the collimator the objective means nothing.
2. `measure_andor_spot` (read-only): the starting spot size, counts and
   offset from the Andor centre. Report them.
3. `plan_beam_optimization` (read-only): a VOCS with variables, objective and
   constraints, ranges built from the current values and the safety ranges.
4. Turn it into a Badger routine with the `ued_badger` tools (see the
   ued-badger skill): rehearse it on the simulator (`draft_routine` with
   `environment='ued_sim'`, then `run_routine`) to check the VOCS and the
   generator, then draft it for the real machine (`environment='ued'`),
   which checks it against the live values without writing anything.
5. The operator runs the real-machine routine in Badger. Afterwards, check
   that the e-beam is still on the sample-YAG cross (`beam_on_screens`, or
   `check_overlap` if the laser overlap was already done) and near the Andor
   centre.

## What each magnet is for

| Magnets | Role |
|---|---|
| Sol1, Sol2 | the focus: they set the spot size on the Andor |
| XC/YC00 | keep the beam aligned through the collimator |
| XC/YC01, XC/YC02 | keep the beam pointing the same on the sample-chamber YAG |
| XC/YC04 | keep the beam roughly at the Andor centre. Optional, but far off-centre the lens aberration spoils the size measurement |

## The plan

- **Objective:** `andor_spot_size_px`, minimize. This is sqrt(sigma_x
  sigma_y) of the beam on the Andor, from the image.
- **Constraints:** Andor counts above a fraction (default 0.8) of now, a proxy
  for the transmitted charge. With XC/YC04 included, the offset from the
  Andor centre stays under 100 px.
- **Multi-objective** (`multi_objective=true`): the proposal's form. The
  counts become a second objective (maximize) instead of a constraint, and
  the routine gives the trade-off front between spot size and charge.
- **Escalation:** the proposal has the routine escalate only if it doesn't
  converge. The plan's `escalate_if` says when: no 10 % cut in spot size
  within 50 evaluations, or the counts below the constraint at the best
  point. Then stop and hand it to the operator.
- **Ranges:** current value +/- 10 % of the safety range, clipped to it.
  Widen or narrow them with the operator.
- **Generator:** Bayesian optimization (expected improvement) for the full
  set; Nelder-Mead for a quick local search on a few variables; multi-
  objective Bayesian optimization (expected hypervolume) with
  `multi_objective=true`.

Units: on the real machine solenoids and correctors are in BCTRL units (kG-m,
or A for SOL2 and XC/YC04), and their calibration to field or kick isn't
known yet. Quote ranges in those units. In the simulator they are deck scale
factors and mrad.
