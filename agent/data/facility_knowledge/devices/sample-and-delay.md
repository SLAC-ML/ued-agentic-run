---
type: device
title: "Sample stage and pump delay"
description: "The 1st (SUED) chamber sample stage and the pump long delay stage."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Sample stage and pump delay

Motor reads take <PV>.RBV, the actual position. Pitch and yaw are set by hand: the yaw shifts the Z plane a lot, so keep yaw and Z where they are. Taught positions live in the setup file (references/setup-file). Pump delay: 0-300 mm, higher = more pump delay = negative pump-probe time; coarse time zero near 200 mm (2026-10-28).

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `sample_x` | `UED:UM1:MMS:02` | mm | CONFIRMED | yes | yes | SUED sample stage X |
| `sample_y` | `UED:USR:MMN:04:01` | mm | CONFIRMED | yes | yes | SUED sample stage Y |
| `sample_z` | `UED:UM1:MMS:01` | mm | CONFIRMED | yes | yes | SUED sample stage Z |
| `sample_pitch` | `UED:USR:MMN:04:04` | deg | CONFIRMED | no | yes | SUED sample stage pitch (read-only here; set by hand) |
| `sample_yaw` | `UED:UM1:MMS:03` | deg | CONFIRMED | no | yes | SUED sample stage yaw (read-only here; set by hand) |
| `pattern_quality` | — |  | SIM_ONLY | no | - | Diffraction pattern quality score (0..1). On the real machine, a score of the far-detector image (readable: cam_far_andor image); the scoring function does not exist yet |
| `delay` | `UED:USR:MMN:03:04` | mm | CONFIRMED | yes | yes | Pump long delay stage |
| `diffraction_signal` | — |  | SIM_ONLY | no | - | Bragg-peak intensity, normalised to pump-off. On the real machine, the LCLS DAQ or the Run 6 BOED script |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
