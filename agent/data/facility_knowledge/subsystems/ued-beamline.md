---
type: facility_overview
title: "SLAC MeV-UED beamline (Run 7)"
description: "What the UED beamline is, its layout from the photocathode gun to the far detector, how the agent reaches it, and where the rest of this knowledge base goes into detail."
timestamp: "2026-10-30"
tags: [ued, overview]
---

# SLAC MeV-UED beamline (Run 7)

The MeV ultrafast electron diffraction (UED) beamline makes femtosecond electron bunches, a few to tens of fC, in an RF photocathode gun. It sends them through a sample that a 400 nm pump laser excites, and records the diffraction pattern on a far detector.

## Main elements, roughly upstream to downstream

- **Photocathode gun.** A UV drive laser hits the cathode; its spot is on the virtual cathode camera (`UED:GIGE:06`). The UV shutter and throttle set the charge. The RF comes from klystron KY03 (TS8) since 2026-10-28. See devices/gun-rf and devices/lasers.
- **Gun solenoid (Sol1)**, with steering correctors XC/YC00.
- **Diagnostic screen** `YAGS:AS01:270` (z ~ 0.5 m), with its camera `UED:GIGE:09`. An operator inserts it for the emission-phase scan, while the oscilloscope reads the charge.
- **Collimator** (`UED:USR:MMN:14:07`): out at 0 mm, the 200 um hole near 90 mm.
- **Second solenoid (Sol2)**, a quad doublet (off by default) and correctors XC/YC01-04. Their roles in the optimization are in procedures/beam-optimization.
- **Sample chamber** (1st, SUED chamber): the sample stage (devices/sample-and-delay), a YAG screen with an e-beam cross on the sample-chamber camera `UED:GIGE:02`, and the pump laser through the coupling mirrors.
- **Far detector:** the Andor EMCCD `UED:ANDOR:CAM:03`, where the beam spot and the diffraction pattern are measured. A through hole passes the main beam.

Gate valves 240, 272, 280 and 295 sit on the e-beam path; all four must read OPEN for beam (devices/vacuum).

## Bring-up

The Run 7 bring-up has eight stages, from the gun ramp to time zero: see procedures/bringup-stages. Procedures 1-8 are the operators' (Fuhao Ji); the agent's tools follow them.

## How the agent reaches the machine

- **Read-only.** The agent never writes a PV. Five separate guards refuse writes, and the S3DF EPICS gateway itself grants read access only.
- **Two deployments.** From S3DF (iana), the PVs come through the EPICS gateway; accelerator-side PVs need the `UED:USER:` prefix, and some aren't served yet. From ued-daq there is direct Channel Access to every PV. See references/pv-access.
- **Setup file.** Taught positions, camera views, setpoints and safety ranges live in one YAML file: references/setup-file.
