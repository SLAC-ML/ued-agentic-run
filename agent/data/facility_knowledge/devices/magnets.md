---
type: device
title: "Solenoids, quads and correctors"
description: "Gun solenoid (Sol1), second solenoid (Sol2), the quad doublet and the XC/YC00-05 steering correctors, with their setpoint (BCTRL) and readback (BACT) PVs."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Solenoids, quads and correctors

Units are BCTRL units: kG-m, or A for Sol2 and XC/YC04; their calibration to field or kick is not known yet. The quad doublet is off by default and no tool drives it. XC/YC05 have no PV yet.

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `sol1` | `SOLN:AS01:121:BCTRL` | kG-m | CONFIRMED | yes | prefix | Gun solenoid strength |
| `sol2` | `SOLN:AS01:311:BCTRL` | A | CONFIRMED | yes | prefix | 2nd solenoid strength |
| `sol1_rb` | `SOLN:AS01:121:BACT` | kG-m | CONFIRMED | no | prefix | Gun solenoid readback (BACT) |
| `sol2_rb` | `SOLN:AS01:311:BACT` | A | CONFIRMED | no | prefix | 2nd solenoid readback (BACT) |
| `quad1` | `QUAD:AS01:361:BCTRL` |  | CONFIRMED | no | prefix | Quad doublet 1st quad setpoint (BCTRL; not driven by the tools) |
| `quad2` | `QUAD:AS01:371:BCTRL` |  | CONFIRMED | no | prefix | Quad doublet 2nd quad setpoint (BCTRL; not driven by the tools) |
| `quad1_rb` | `QUAD:AS01:361:BACT` |  | CONFIRMED | no | prefix | Quad doublet 1st quad readback |
| `quad2_rb` | `QUAD:AS01:371:BACT` |  | CONFIRMED | no | prefix | Quad doublet 2nd quad readback |
| `xc00` | `XCOR:AS01:121:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | XC00 steering kick |
| `xc00_rb` | `XCOR:AS01:121:BACT` | kG-m | CONFIRMED | no | not yet | XC00 readback (BACT) |
| `yc00` | `YCOR:AS01:122:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | YC00 steering kick |
| `yc00_rb` | `YCOR:AS01:122:BACT` | kG-m | CONFIRMED | no | not yet | YC00 readback (BACT) |
| `xc01` | `XCOR:AS01:221:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | XC01 steering kick |
| `xc01_rb` | `XCOR:AS01:221:BACT` | kG-m | CONFIRMED | no | not yet | XC01 readback (BACT) |
| `yc01` | `YCOR:AS01:222:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | YC01 steering kick |
| `yc01_rb` | `YCOR:AS01:222:BACT` | kG-m | CONFIRMED | no | not yet | YC01 readback (BACT) |
| `xc02` | `XCOR:AS01:321:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | XC02 steering kick |
| `xc02_rb` | `XCOR:AS01:321:BACT` | kG-m | CONFIRMED | no | not yet | XC02 readback (BACT) |
| `yc02` | `YCOR:AS01:322:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | YC02 steering kick |
| `yc02_rb` | `YCOR:AS01:322:BACT` | kG-m | CONFIRMED | no | not yet | YC02 readback (BACT) |
| `xc03` | `XCOR:AS01:341:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | XC03 steering kick |
| `xc03_rb` | `XCOR:AS01:341:BACT` | kG-m | CONFIRMED | no | not yet | XC03 readback (BACT) |
| `yc03` | `YCOR:AS01:342:BCTRL` | BCTRL, EGU kG-m (unconfirmed) | CONFIRMED | yes | prefix | YC03 steering kick |
| `yc03_rb` | `YCOR:AS01:342:BACT` | kG-m | CONFIRMED | no | not yet | YC03 readback (BACT) |
| `xc04` | `XCOR:AS01:381:BCTRL` | BCTRL, EGU A (unconfirmed) | CONFIRMED | yes | prefix | XC04 steering kick |
| `xc04_rb` | `XCOR:AS01:381:BACT` | A | CONFIRMED | no | not yet | XC04 readback (BACT) |
| `yc04` | `YCOR:AS01:382:BCTRL` | BCTRL, EGU A (unconfirmed) | CONFIRMED | yes | prefix | YC04 steering kick |
| `yc04_rb` | `YCOR:AS01:382:BACT` | A | CONFIRMED | no | not yet | YC04 readback (BACT) |
| `xc05` | — | mrad | UNMAPPED | yes | - | XC05 steering kick |
| `yc05` | — | mrad | UNMAPPED | yes | - | YC05 steering kick |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
