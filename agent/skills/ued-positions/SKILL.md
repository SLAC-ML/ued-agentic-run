---
name: ued-positions
description: >
  Work with UED sample-stage positions and the shared setup file
  (ued_setup.yaml): list the taught positions, move to one (YAG, Andor, Bi,
  Si), teach or save a position, set a camera view, explain the motor safety
  ranges or the camera and laser setpoints. Use when the operator asks to go
  to or save a position, to change a camera view, or about safety ranges and
  setpoints.
summary: Taught positions, camera views and safety ranges in ued_setup.yaml
---

# UED positions and the setup file

## The file

One YAML file holds what the operators and the agent share: taught
sample-stage positions, the camera views, the pump and collimator setpoints,
and the safety ranges every write is checked against.

- The live copy: `/sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml`.
  `ued_tuning_info` names the file in use.
- The reviewed seed is `bringup/ued_setup.yaml` in the ued-agentic-run repo.
- `null` means not known yet. `ued_tuning_info` lists those under
  `setup_missing`.

## Tools

| Want | Tool | Note |
|---|---|---|
| See the taught positions and where the stage is | `list_positions` | read-only |
| Go to a position ("go2YAG", "go2Andor", "go2Bi") | `go_to_position(name)` | pump shutter closed first; every axis checked against its safety range before the first move; readback verified |
| Teach a position | `save_position(name, note)` | reads x, y, z, pitch, yaw now and writes that one line |
| Camera view | `set_camera_view(view)` | `full_view`, `ebeam` or `laser` |

The old run-4 scripts map like this: `goToYAG` is `go_to_position('yag')`,
`goToAndor1`/`StageOut` is `go_to_position('andor')`, `goToBi` is
`go_to_position('bi')`, and `saveYAG` is `save_position('yag')`. Their
coordinates were on the old PI stage and don't carry over.

## Teaching a position

1. The operator moves the stage. For `yag`, put the YAG screen at the beam
   cross. For `andor`, move the sample card out of the beam, leaving the cross
   in free space on the camera. For a sample, put it at the cross.
2. Confirm with the operator, then call `save_position(name, note)`. Put who
   and why in the note.
3. If the name is already taught, show the old and new coordinates and ask
   before overwriting.

`save_position` keeps the rest of the file as it is (comments included). It
keeps the previous file as `ued_setup.yaml.bak` and appends the change to
`ued_setup.history.log` beside it.

## Everything else in the file

Laser setpoints (`pump.hwp_min_energy_deg`, `pump.hwp_pump_probe_deg`), the
Andor through hole, camera views and safety ranges are the operators' to set.
Don't edit them yourself. Show the operator the exact key and the line to
change, and let them edit the file.

- **Safety ranges** (`limits`) were seeded on 2026-10-21 from the motors' soft
  limits and the magnets' drive limits. The pump HWP and UV throttle ranges
  are placeholders until confirmed. A write outside a range is refused with
  `SafetyError` before it is made: report it and don't look for a way round
  it.
- **Units** are the machine's: mm and deg for motors. On the real machine,
  correctors and solenoids are in BCTRL units (kG-m, or A for SOL2 and
  XC/YC04).
