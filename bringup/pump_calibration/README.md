# 400 nm pump calibration (2026-10-28)

The laser team's handover for Run 7: the pump energy vs the Harmonics HWP, its fit, and the working points.

- `Energy_calibration_400nm_Ji_20261028.xlsx`: the measurement (energy meter PM1 vs HWP, 23–52°, pump throttle 16°).
- `Energy_calibration_400nm_Ji_20261028_fit.xlsx`: the fit, working points and a table for every degree, with live formulas (change the transmission or spot size and everything updates).
- `hwp_fit_400nm_20261028.png`: the plot; `plot_hwp_fit.py` redraws it.

## Fit

E_PM1(HWP) = 0.41 + 16.60 · cos⁴(2(HWP − 49.65°)) µJ

- Fits all 17 points to 0.036 µJ rms (max residual 0.08 µJ). cos⁴, not cos²: the HWP sits in front of the doubling crystal, and the 400 nm energy goes as the square of the fundamental along the crystal axis. A plain cos² (polariser) fit is 8x worse.
- Maximum 17.0 µJ at 49.65°; minimum at 4.65° (Patrick: 5–6°).
- **No data below 23°.** Down to ~20° the fit is solid. Lower, the floor isn't pinned down: a leakage model, A (cos² + 0.048)², fits equally well with a floor of 0.06 µJ instead of 0.41 µJ. Read PM1 at 8°, 16° and 20° to settle it (0.78 vs 0.58 µJ at 16°).

## Working points

At the sample (IP) = PM1 × 0.636 (measured transmission). Peak fluence = 4 ln2 / π · E_IP / FWHM², incident, for the 227 µm FWHM spot (knife edge on the sample card): 1.71 mJ/cm² per µJ at the IP.

| Use | HWP | PM1 | At sample | Peak fluence |
|---|---|---|---|---|
| YAG overlap (minimum energy) | 8° | 0.06–0.42 µJ* | 0.04–0.27 µJ | 0.07–0.45 mJ/cm² |
| **Bi time zero** | **22°** | **2.1–2.2 µJ** | **1.34–1.37 µJ** | **2.3 mJ/cm²** |
| Bi first wide t₀ scan (optional) | 25° | 3.4 µJ (measured) | 2.2 µJ | 3.7 mJ/cm² |
| Max | 49.65° | 17.0 µJ | 10.8 µJ | 18.5 mJ/cm² |

\*Model-dependent below 23°: read PM1 at 8°.

Round fluences for Bi: 1 mJ/cm² at 17.0°, 2 at 21.0°, 3 at 23.5°, 4 at 25.5°. `ued_setup.yaml` has `pump.hwp_min_energy_deg: 8.0` and `pump.hwp_pump_probe_deg: 22.0`. The Run 6 Bi angle, 16.245°, now gives under 1 mJ/cm².

The calibration holds only at pump throttle 16°.

## Laser team's notes (Patrick, 2026-10-28)

- The 400 nm pump is delivered to the IP (red marker 2) and characterized.
- **Pump long delay** (`UED:USR:MMN:03:04`): 0–300 mm. Higher number = more delay on the pump = negative pump-probe time. **Coarse time zero is expected near 200 mm**, with large error (first pump-probe after the chamber swap): start with a very wide scan. If the stage is double-pass, 1 mm ≈ 6.7 ps (to confirm).
- Transmission from the energy meter (PM1) spot to the IP: 63.6%. The energy meter is viewable remotely on the OPA laptop through VNC (link on the UED home page, Laser tab).
- The primary 400 nm energy control is the Harmonics HWP, on the SUED user panel.
- **The pump lens X/Y motors are temporarily on another controller:** the ones on the SUED user panel are wrong for now. Use the XPS-06 panel, "400 nm Lens X / Y", for pump steering. The tools' `pump_lens_h/v` (`MMN:08:05/06`) are the old motors until their XPS-06 PVs are read and mapped.
- Spot 227 µm FWHM by knife edge on the sample card, with the yaw set by eye to horizontal. **The yaw shifts the Z plane a lot: keep the yaw (and Z) where they are.**
