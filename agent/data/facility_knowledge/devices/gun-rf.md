---
type: device
title: "Gun RF"
description: "Gun RF on klystron KY03 (TS8): amplitude and phase setpoints and readbacks, the two feedbacks, and the gun body temperature."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Gun RF

The gun is on TS8 (KY03) since 2026-10-28; TS1 (KY01) is offline. AREQ is dimensionless (0..0.53); AACT reads in kV, so the ramp checks their ratio. Ramp-up: see procedures/gun-ramp.

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `areq` | `SIOC:AS01:KY03:0:AREQ` | unconfirmed (EGU "degrees") | CONFIRMED | yes | prefix | Gun amplitude setpoint (0..0.53) |
| `preq` | `SIOC:AS01:KY03:0:PREQ` | deg | CONFIRMED | yes | prefix | Gun phase setpoint (-180..180) |
| `aact` | `SIOC:AS01:KY03:0:AACT_AVGNT` | kV | CONFIRMED | no | prefix | Gun amplitude readback (averaged) |
| `pact` | `SIOC:AS01:KY03:0:PACT_AVGNT` | deg | CONFIRMED | no | prefix | Gun phase readback (averaged) |
| `pfb_enable` | `SIOC:AS01:KY03:0:PFBENB` |  | CONFIRMED | yes | not yet | Phase feedback enable |
| `afb_enable` | `SIOC:AS01:KY03:0:AFBENB` |  | CONFIRMED | yes | not yet | Amplitude feedback enable |
| `pfb_status` | `SIOC:AS01:KY03:0:PFBST` |  | CONFIRMED | no | not yet | Phase feedback status (Disable, Pause, Feedforward, Active) |
| `afb_status` | `SIOC:AS01:KY03:0:AFBST` |  | CONFIRMED | no | not yet | Amplitude feedback status (Disable, Pause, Feedforward, Active) |
| `gun_temp` | `APC:AS01:TM01:M2_CH2_SPARE` | C | CONFIRMED | no | prefix | Gun body temperature (a Beckhoff thermocouple, not klystron-scoped) |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
