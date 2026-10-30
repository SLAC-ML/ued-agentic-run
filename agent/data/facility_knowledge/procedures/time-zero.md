---
type: procedure
title: "Pump-probe time zero (stage 8)"
description: "Finding pump-probe time zero on the Bi sample: the Delta I/I signal at a Bi ring from Andor frames, the grid, amortized BOED and non-amortized BOED delay scans, the setup values they use, and what must be in place first."
timestamp: "2026-10-30"
tags: [ued, procedure, time-zero, boed]
---

# Pump-probe time zero (stage 8)

Time zero (t0) is the pump delay at which the 400 nm pump and the electron bunch arrive at the sample together. Past it, the pump heats the Bi lattice and the Bragg intensity drops. The tool (`find_time_zero`) finds the delay where that drop starts.

**First, in place:**
- Spatial overlap from stage 6, still good: the tool re-checks the e-beam and the pump laser on the sample-YAG cross.
- Taught positions `yag` and `bi`; the main beam in the Andor through hole (stage 7).
- Pump HWP setpoint for pump-probe, 22 deg (~2.2 uJ at PM1): references/pump-hwp-calibration.
- Pump power meter out (0 mm).

**The signal:** at each delay, Andor frames with the pump ON, OFF, OFF, ON. The tool removes each frame's corner background, masks the through hole (`time_zero.hole_mask_px`), and takes the radial profile about the ring centre. Delta I/I (%) is ON vs OFF at the Bi ring s = 7.30 1/A +/- 8 bins (s calibration 0.01924 1/A per px). The ring centre is found from 5 pump-off frames at the start, unless `time_zero.ring_center_px` is set. This is Fuhao Ji's `bi_pp_signal_2026.py` (April 2026), ported to `bringup/ued_tuning/diffraction.py`.

**Three methods:**
- `method='grid'` (default): scans that zoom in on the drop around `center_mm` (or the current delay), fitted with an erf step.
- `method='boed'`: the April 2026 amortized BOED scan (Sam Klein's posterior-sampling models, `boed/models/delay_t0_2026-04`). It starts with 10 grid points over `time_zero.boed_window_mm` (170-210 mm), then 70 points, each drawn from the t0 posterior so far; t0 is the posterior median. About 35 min at ~26 s a point. It stops for an operator, with the delay put back, if the 98 % interval is wider than `boed_max_width_mm` (0.5 mm) or the signal disagrees with t0.
- `method='eig'`: the April 2026 non-amortized BOED (Ryan Roussel's pyro generator, `boed/delay_eig.py`, now an Xopt generator). It starts with 10 grid points over `time_zero.eig_window_mm` (170-210 mm), then 20 points, each where the expected information gain is highest under a posterior refit from the priors (`time_zero.eig_priors`, t0 190 +/- 10 mm) at every point. About 20 min: ~15 s of computing plus ~26 s of measuring a point. No `y_shift`/`y_scale`: the model fits its own baseline, drop and noise. It is accepted and refused as `boed` (`eig_max_width_mm`, 0.5 mm). Two changes from April: the data counted once (April re-used each posterior as the next prior) and the noise learned (April pinned it at 0.135 %). The next point is picked among delays near t0 (`eig_margin_mm`), a heuristic: the gain is about all seven model parameters, and over the whole window it goes for the decay tail. Its 98 % intervals are narrow (a mean-field posterior) and are not accuracies. It needs pyro-ppl and xopt in the helper Python (`UED_BOED_PYTHON`); the stage checks before it moves anything.

**The models' expectations:** the baseline before t0 at 0 and a drop near April's ~4.4 %. `boed_y_shift` (added, 3.0 in April) and `boed_y_scale` (multiplied in) adjust for that, and the result's `boed.check` suggests values from the first grid points. In simulation the models went wrong on drops of 8 % and more unless `y_scale` brought them near 4.4 %.

**Where t0 is:** in April it was near 189 mm on the pump long delay (`UED:USR:MMN:03:04`), and the signal dropped toward lower delay (`time_zero.signal_drops_toward: lower`). After the 2026-10 chamber swap the laser team expects it near 200 mm, with a large error.

**While it runs:** the record folder fills from the start: `live.jsonl` (one line per point: delay, Delta I/I, the t0 estimate so far) and `live.png` (the plot). A stopped run keeps its points.

**Running it on the machine:** on ued-daq, `/sdf/group/mli/zhezhang/ued/agentic/scripts/ued_stage.sh find_time_zero method=boed` is a dry run (every write logged to `records/operator_writes.jsonl`, none sent). `--write` runs it for real, writing only stage 8's channels, inside the safety ranges. `method=eig` runs the same way.
