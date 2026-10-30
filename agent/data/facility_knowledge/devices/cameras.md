---
type: device
title: "Cameras"
description: "The four cameras the bring-up tools read (virtual cathode, diagnostic screen, sample chamber, far-detector Andor), their image PVs and settings."
timestamp: "2026-10-30"
tags: [ued, devices, cameras, pv]
---

# Cameras

All cameras are hutch IOCs (`UED:*`), so they answer from S3DF under their own names. The tools compute beam stats (centroid, rms size, total, saturation) from the image PV itself: the GigE cameras' Stats plugins are switched off (their centroids read 0.0, which looks real), and the Andor's Stats1 runs on a small ROI.

| Camera | PV prefix | Image | Map status | What it is |
|---|---|---|---|---|
| `cam_vcc` | `UED:GIGE:06` | `UED:GIGE:06:IMAGE1:ArrayData` | CONFIRMED | Virtual cathode camera (gun UV spot) |
| `cam_diag_yag` | `UED:GIGE:09` | `UED:GIGE:09:IMAGE1:ArrayData` | CONFIRMED | Diagnostic screen camera (z ~0.5 m) |
| `cam_sample_yag` | `UED:GIGE:02` | `UED:GIGE:02:IMAGE1:ArrayData` | LIKELY | Sample chamber camera (RGB) |
| `cam_far_andor` | `UED:ANDOR:CAM:03` | `UED:ANDOR:CAM:03:IMAGE2:ArrayData` | CONFIRMED | Far-detector Andor EMCCD |

## Settings the tools read or set

| Tool name | PV | Units | Map status | Tools may write | From S3DF | What it is |
|---|---|---|---|---|---|---|
| `cam_vcc.exposure` | `UED:GIGE:06:AcquireTime` | s | CONFIRMED | yes | yes | Virtual cathode camera (gun UV spot): exposure |
| `cam_vcc.gain` | `UED:GIGE:06:Gain` |  | CONFIRMED | yes | yes | Virtual cathode camera (gun UV spot): gain |
| `cam_diag_yag.exposure` | `UED:GIGE:09:AcquireTime` | s | CONFIRMED | yes | yes | Diagnostic screen camera (z ~0.5 m): exposure |
| `cam_diag_yag.gain` | `UED:GIGE:09:Gain` |  | CONFIRMED | yes | yes | Diagnostic screen camera (z ~0.5 m): gain |
| `cam_sample_yag.exposure` | `UED:GIGE:02:AcquireTime` | s | LIKELY | yes | yes | Sample chamber camera (RGB): exposure |
| `cam_sample_yag.gain` | `UED:GIGE:02:Gain` |  | LIKELY | yes | yes | Sample chamber camera (RGB): gain |
| `cam_far_andor.exposure` | `UED:ANDOR:CAM:03:AcquireTime` | s | CONFIRMED | yes | yes | Far-detector Andor EMCCD: exposure |
| `cam_far_andor.gain` | `UED:ANDOR:CAM:03:AndorEMGain` |  | CONFIRMED | yes | yes | Far-detector Andor EMCCD: gain |
| `cam_sample_yag.cross_x` | `UED:GIGE:02:Cross2X` | px | LIKELY | yes | yes | Sample chamber camera: e-beam cross x |
| `cam_sample_yag.cross_y` | `UED:GIGE:02:Cross2Y` | px | LIKELY | yes | yes | Sample chamber camera: e-beam cross y |
| `cam_far_andor.acquire` | `UED:ANDOR:CAM:03:Acquire` |  | CONFIRMED | yes | yes | Andor acquisition: write 1 to start, 0 to stop; reads Acquire or Done |

Camera views (exposure, gain, light) and the Andor settings for each step are in the setup file (references/setup-file).

*Map status*: CONFIRMED (read and checked), LIKELY (read, meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator only). *Tools may write*: the tools would write it on a write-enabled deployment; the deployed agent refuses every PV write. *From S3DF*: yes = answers through the gateway under its own name; prefix = answers as `UED:USER:<PV>`; not yet = not served by the gateway on 2026-10-29 (read it from ued-daq). Generated from bringup/ued_tuning/channels.py by bringup/okf_devices.py.
