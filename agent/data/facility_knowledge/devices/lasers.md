---
type: device
title: "Drive and pump lasers"
description: "Gun UV drive (shutter, throttle) and the 400 nm pump (shutters, Harmonics HWP, ND wheel, power meter, coupling mirrors, steering lens)."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Drive and pump lasers

Shutters are Beckhoff analog outputs: 3 V open, 0 V closed; the tools use 1/0. Pump energy vs HWP: see references/pump-hwp-calibration. On 2026-10-28 the pump lens X/Y were temporarily on the XPS-06 panel ("400 nm Lens X / Y"); pump_lens_h/v below are the old motors until those are mapped.

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `gun_uv_shutter` | `UED:USR:BHC:AO1:4` | V | CONFIRMED | yes | yes | Gun UV shutter (1 open, 0 closed; on the PV 3 V open, 0 V closed) |
| `gun_uv_throttle` | `UED:USR:MMN:14:01` | deg | CONFIRMED | yes | yes | Drive UV throttle (max transmission at 21 deg; ~51 for the phase scan, ~53 for operation) |
| `pump_shutter` | `UED:USR:BHC:AO1:3` | V | CONFIRMED | yes | yes | Pump main shutter (1 open, 0 closed; on the PV 3 V open, 0 V closed) |
| `pump_extra_shutter` | `UED:USR:BHC:AO1:2` | V | CONFIRMED | yes | yes | Pump extra shutter (not used in the measurement loop; 3 V open) |
| `pump_hwp` | `UED:USR:MMN:05:02` | deg | CONFIRMED | yes | yes | Pump Harmonics HWP: sets the pump energy (max @ 51 deg). Its setpoints (minimum energy, ~2 uJ) are in ued_setup.yaml |
| `pump_nd_wheel` | `UED:USR:MMN:05:08` | deg | CONFIRMED | yes | yes | Pump ND wheel (max @ 310) |
| `pump_power_meter` | `UED:USR:MMN:05:06` | mm | CONFIRMED | yes | yes | Pump power meter (in @ 40 mm blocks the pump; out @ 0) |
| `pump_incoupling` | `UED:USR:MMN:04:03` | mm | CONFIRMED | no | yes | 1st chamber pump incoupling mirror (read-only here) |
| `pump_outcoupling` | `UED:USR:MMN:04:02` | mm | CONFIRMED | no | yes | 1st chamber pump outcoupling mirror (read-only here; IN blocks the pump) |
| `pump_lens_h` | `UED:USR:MMN:08:05` | mm | LIKELY | yes | yes | Pump steering H: moves the pump spot on the sample. Fuhao calls it "pump laser mirror H"; mapped to the run-7 list's pump lens H (UED:MCS:01:m7, "pump_beam_X", is the other candidate) |
| `pump_lens_v` | `UED:USR:MMN:08:06` | mm | LIKELY | yes | yes | Pump steering V (see pump_lens_h; UED:MCS:01:m8 is the other candidate) |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
