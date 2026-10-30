---
type: concept
title: "Emission phase and the Schottky scan"
description: "What the emission phase is, how stage 2 finds it on the scope (grid scan, threshold crossing), and the BSA option with an amortized T0 posterior."
timestamp: "2026-10-30"
tags: [ued, physics, gun, schottky, boed]
---

# Emission phase and the Schottky scan

The photocathode emits only while the RF field at the cathode pulls electrons out. Scanning the gun phase (PREQ) with the UV on, the charge on the scope is zero over part of the cycle and rises where emission starts. That onset is the **emission phase**; the gun is then run at **PREQ = emission + 30 deg** (`gun.phase_from_emission_deg`). The UV throttle is at ~51 deg for the scan (more UV, a clearer edge) and ~53 deg in operation.

**Grid method** (default): a coarse scan over -180..180 deg in 5 deg steps finds the window where the charge stays above 5 sigma of the trace noise. A 0.5 deg fine scan around its rising edge then interpolates the threshold crossing. About 90 points.

**BSA method** (`method='bsa'`, Sam Klein's amortized posterior, `boed/` in the repo): a network trained on simulated scans gives the posterior of T0, the onset, from the points measured so far. Four 10-point scans are each placed by the posterior after the ones before: 40 points, or 40 plus the coarse scan. T0 marks where the rise starts, about 1-3 deg before the grid method's threshold crossing. The stage stops for an operator if the 98 % interval is wider than 4 deg, or if the measured charge disagrees with the onset. Tested on the simulator only (2026-10-29); not yet on a real UED scan.

Which definition the operators mean (onset, half maximum, or peak), and the direction of the 30 deg offset, are open questions in the bring-up README.
