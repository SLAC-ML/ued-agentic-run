---
type: procedure
title: "Beam optimization after the collimator (Badger)"
description: "Minimizing the e-beam spot on the Andor with Sol1, Sol2 and correctors XC/YC00-04 as a Badger routine, drafted and rehearsed by the agent and run by an operator."
timestamp: "2026-10-30"
tags: [ued, procedure, optimization, badger]
---

# Beam optimization after the collimator

After stage 5 the beam is through the collimator and on the Andor. The usual optimization minimizes the spot size on the Andor while the transmitted charge stays above a level.

| Knobs | Role |
|---|---|
| Sol1, Sol2 | the focus: the spot size on the Andor |
| XC/YC00 | keep the beam aligned through the collimator |
| XC/YC01, XC/YC02 | keep the beam pointing the same on the sample-chamber YAG |
| XC/YC04 | keep the beam near the Andor centre (lens aberration spoils the size far off it) |

**Objective:** `andor_spot_size_px` = sqrt(sigma_x sigma_y) on the Andor, minimized.
**Constraint:** Andor counts above a fraction (0.8) of the start, a proxy for the transmitted charge; offset from the Andor centre under 100 px with XC/YC04. The multi-objective form makes the counts a second objective.

**How the agent does it** (`ued_badger` tools):
1. `plan_beam_optimization` (ued_tuning) gives a VOCS: ranges are the current value +/- 10 % of the safety range.
2. `draft_routine` builds a Badger routine and has Badger validate it against the knobs, the safety ranges and the generator. On the real machine (`ued`) it only reads.
3. The routine is rehearsed on the simulator (`ued_sim`, `run_routine`, ~12 s per evaluation). An operator runs the real-machine routine in Badger.
4. Afterwards, check the e-beam is still on the sample-YAG cross.

Generators: `expected_improvement` (default; takes constraints), `neldermead` (1-4 knobs; no constraints), `mobo` (two objectives). Units on the real machine are BCTRL units: kG-m, or A for Sol2 and XC/YC04.
