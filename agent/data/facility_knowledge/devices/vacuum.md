---
type: device
title: "Gate valves"
description: "The four gate valves on the e-beam path (240, 272, 280, 295) and the ePix-line valve 320."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Gate valves

Every beam stage of the bring-up tools stops unless 240, 272, 280 and 295 all read OPEN. 320 is reported for information only.

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `gv240` | `VVPG:AS01:240:POSITION` |  | CONFIRMED | no | not yet | Gate valve 240 (OPEN, CLOSED, MOVING, INCONSISTENT) |
| `gv272` | `VVPG:AS01:272:POSITION` |  | CONFIRMED | no | not yet | Gate valve 272 (OPEN, CLOSED, MOVING, INCONSISTENT) |
| `gv280` | `VVPG:AS01:280:POSITION` |  | CONFIRMED | no | not yet | Gate valve 280 (OPEN, CLOSED, MOVING, INCONSISTENT) |
| `gv295` | `VVPG:AS01:295:POSITION` |  | CONFIRMED | no | not yet | Gate valve 295 (OPEN, CLOSED, MOVING, INCONSISTENT) |
| `gv320` | `VVPG:AS01:320:POSITION` |  | LIKELY | no | not yet | Gate valve 320 (ePix line; monitored, not a gate for the Andor) |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
