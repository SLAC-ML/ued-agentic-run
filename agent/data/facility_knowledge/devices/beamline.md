---
type: device
title: "Collimator, diagnostic screen, scope, chamber light"
description: "The collimator, the diagnostic screen (YAGS:AS01:270) and its interlock, the oscilloscope that reads the bunch charge, and the sample-chamber light."
timestamp: "2026-10-30"
tags: [ued, devices, pv]
---

# Collimator, diagnostic screen, scope, chamber light

The diagnostic screen is moved by command PVs (OPENCMD inserts, CLOSECMD removes) that the agent never writes: an operator moves it and the tools read its state. Scope: 10 fC = -1.7 mV on CH2; the V/div records read UDF, so check the front panel.

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `diag_holder` | — |  | UNMAPPED | yes | - | Diagnostic screen inserter (0 out, 1 YAG; 2 FC in the simulator only). On the real machine an operator step: insert with YAGS:AS01:270:OPENCMD, remove with :CLOSECMD (from the panel); check with diag_screen_state |
| `diag_screen_state` | `YAGS:AS01:270:OPENSOLENOID` |  | LIKELY | no | not yet | Diagnostic screen state (OPENSOLENOID; open = screen inserted, to confirm on the machine). Accelerator-side: from S3DF it needs the gateway prefix |
| `diag_screen_interlock` | `YAGS:AS01:270:INTLKSUM` |  | LIKELY | no | not yet | Diagnostic screen interlock summary |
| `collimator` | `UED:USR:MMN:14:07` | mm | CONFIRMED | yes | yes | Collimator motor (0 out; nominal 90 mm = the 200 um hole) |
| `chamber_light` | `ACSW:AS01:NW03:2POWERSTATE` |  | CONFIRMED | yes | not yet | Sample chamber light (1 on, 0 off). Reads the state; switched by writing ACSW:AS01:NW03:2POWERON or :2POWEROFF |
| `scope_ch2_trace` | `SCOP:AS01:SC01:WF_CH2_TRACE` | div | CONFIRMED | no | not yet | Oscilloscope CH2 trace, 500 samples in divisions (baseline near +3.4 div); the e-beam pulse is negative-going |
| `scope_ch2_vdiv` | `SCOP:AS01:SC01:MBBO_CH2_SCL` |  | CONFIRMED | no | not yet | Oscilloscope CH2 volts/div (an output record that reads UDF: check the front panel) |
| `scope_ch0_trace` | `SCOP:AS01:SC01:WF_CH0_TRACE` | div | CONFIRMED | no | not yet | Oscilloscope CH0 trace, 500 samples in divisions (baseline near -2.4 div); the e-beam pulse is negative-going |
| `scope_ch0_vdiv` | `SCOP:AS01:SC01:MBBO_CH0_SCL` |  | CONFIRMED | no | not yet | Oscilloscope CH0 volts/div (an output record that reads UDF: check the front panel) |

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
