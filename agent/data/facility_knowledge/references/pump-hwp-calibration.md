---
type: reference
title: "400 nm pump energy vs Harmonics HWP (2026-10-28)"
description: "The laser team's Run 7 calibration of pump energy against the Harmonics HWP angle, its cos^4 fit, the working points (8 deg for the YAG overlap, 22 deg for Bi time zero) and their notes."
timestamp: "2026-10-30"
tags: [ued, laser, pump, calibration]
---

# 400 nm pump energy vs Harmonics HWP

From the laser team's handover of 2026-10-28 (files in `bringup/pump_calibration/`).

**Fit:** E_PM1(HWP) = 0.41 + 16.60 cos^4(2 (HWP - 49.65 deg)) uJ, 0.036 uJ rms over 17 points. Maximum 17.0 uJ at 49.65 deg; minimum near 4.65 deg. There is no data below 23 deg, so the floor is model-dependent: read PM1 at 8, 16 and 20 deg to settle it. Valid only at pump throttle 16 deg.

At the sample = PM1 x 0.636 (measured transmission). Peak fluence: 1.71 mJ/cm^2 per uJ at the sample, for the 227 um FWHM spot.

| Use | HWP | PM1 | At sample | Peak fluence |
|---|---|---|---|---|
| YAG overlap (minimum energy) | 8 deg | 0.06-0.42 uJ | 0.04-0.27 uJ | 0.07-0.45 mJ/cm^2 |
| Bi time zero | 22 deg | 2.1-2.2 uJ | 1.34-1.37 uJ | 2.3 mJ/cm^2 |
| Bi first wide t0 scan | 25 deg | 3.4 uJ | 2.2 uJ | 3.7 mJ/cm^2 |
| Max | 49.65 deg | 17.0 uJ | 10.8 uJ | 18.5 mJ/cm^2 |

Round Bi fluences: 1 mJ/cm^2 at 17.0 deg, 2 at 21.0, 3 at 23.5, 4 at 25.5. The Run 6 Bi angle, 16.245 deg, now gives under 1 mJ/cm^2.

**Laser team's notes:**
- Pump long delay `UED:USR:MMN:03:04`: 0-300 mm; higher = more pump delay = negative pump-probe time. Coarse time zero near 200 mm, with a large error: start with a wide scan.
- The energy meter PM1 is viewable on the OPA laptop over VNC (UED home page, Laser tab).
- The pump lens X/Y were temporarily on the XPS-06 panel ("400 nm Lens X / Y").
- The yaw shifts the Z plane a lot: keep the yaw (and Z) where they are.
