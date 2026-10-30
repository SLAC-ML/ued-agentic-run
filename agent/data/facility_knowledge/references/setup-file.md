---
type: reference
title: "The UED setup file (ued_setup.yaml)"
description: "The one editable YAML file with taught sample positions, camera views, Andor and pump settings, gun ramp and scope settings, and the safety ranges every write is checked against."
timestamp: "2026-10-30"
tags: [ued, setup, positions, safety]
---

# The UED setup file

The live copy is `/sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml`; the reviewed seed is `bringup/ued_setup.yaml` in the repo. Agent and operators share it: `save_position` (or `bringup/positions.py` for operators) writes one position line, keeps a `.bak`, and logs the change in `ued_setup.history.log`.

| Section | What it holds |
|---|---|
| `positions` | Taught sample-stage positions: `yag` (YAG screen with the e-beam cross), `andor` (sample out, beam to the far detector), `bi`, `si`. Each is `{x, y, z, pump_hwp_deg?, note}`. Moves close both shutters, set the camera to the `mid` view, apply the position's `pump_hwp_deg`, move x/y/z, then restore the gun UV. |
| `camera_views` | Sample-chamber camera presets: `full_view`, `ebeam`, `laser` (exposure, gain, chamber light), and `high` / `mid` / `low`. |
| `andor` | Andor exposure and gain for the beam check and for diffraction; the main-beam through hole's pixel position and radius. |
| `pump` | Pump HWP setpoints (`hwp_min_energy_deg` 8, `hwp_pump_probe_deg` 22: references/pump-hwp-calibration), power meter in/out, outcoupling mirror in/out. |
| `collimator` | Out (0 mm), nominal (90 mm, the 200 um hole), scan half-width. |
| `gun` | Ramp steps, dwell and temperature window; UV throttle for the scan (51) and operation (53); operating phase = emission + 30 deg; target charge 10 fC. |
| `scope` | Channel (CH2) and calibration (-0.17 mV per fC). |
| `cross` | How close counts as "on the cross", and how far the cross may be moved. |
| `limits` | Safety ranges: every write is checked against them before it is sent, and refused outside. Seeded from motor soft limits and magnet drive limits; `sample_x` / `sample_z` still null (no IOC limit on those motors). |

`null` entries are not taught yet; the tools report them as `setup_missing` and stop where a stage needs one.
