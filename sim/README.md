# Bring-up simulations

GPT models of the UED beamline for simulating each bring-up stage, so procedures (and later agents) can be tried without the machine. Everything runs on S3DF (`iana` or Slurm), from the copy in `/sdf/group/mli/zhezhang/ued/agentic/sim/`.

- `ued_bringup.in`: the GPT deck. It's Fuhao's May 2025 `UED_beamline.in` plus steering correctors XC/YC00–05, a cathode-spot offset, the QD01/QF01 doublet, and screens at the schematic planes. With all kicks at zero it reproduces the May 2025 deck exactly at 0.80 m, and within 0.2 % downstream.
- `gptsim.py`: runs the deck. `run({...})` does one simulation and `scan([...])` runs many in parallel. Each returns per-screen centroid, angle, size, energy, charge and transmission.
- `virtual_gun.py`: a stand-in for the gun RF and body temperature, used to exercise the ramp-up procedure. Its constants are placeholders.
- `stages/`: one script per bring-up stage.

| Stage | Script | What it does |
|---|---|---|
| Gun ramp-up, procedure | `stages/gun_ramp_sim.py` | Runs `bringup/gun_ramp.py` against the virtual gun: a nominal ramp, a cooling-water fault, and a feedback trip |
| Gun ramp-up, beam | `stages/gun_amplitude_scan.py` | Beam energy, collimator transmission and spot size vs the amplitude setpoint (0.05 → 0.53) |
| Collimator alignment | `stages/collimator_alignment.py` | XC/YC00 steer the beam through the 100 µm collimator; XC/YC01 bring it back onto ANDOR1 |

```bash
ssh iana
source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh
cd /sdf/group/mli/zhezhang/ued/agentic/sim/stages
python collimator_alignment.py     # ~6 min, ~130 GPT runs in parallel
python gun_amplitude_scan.py       # ~2 min
python gun_ramp_sim.py             # ~1 s, no GPT
```

Results go to `/sdf/group/mli/zhezhang/ued/agentic/runs/sim/`.

## Positions

All positions are in metres from the cathode.

| Element | z (m) | Source |
|---|---|---|
| Gun (1.6 cell), field ends | 0.106 | `gun1Dmap.gdf` |
| Gun solenoid, peak | 0.196 | `gunSolenoid_v0_bucking.gdf`; the schematic agrees (≈ 0.21) |
| XC/YC00 | 0.33 | rough: just after the gun solenoid (sketch) |
| Faraday cup / Diag YAG screen | 0.50 | rough: before the collimator (sketch) |
| Collimator, 100 µm hole | 0.5575 | May 2025 deck |
| XC/YC01 | 0.65 | rough: just after the collimator (sketch) |
| Solenoid 2 | 1.005 | May 2025 deck |
| XC/YC02 | 1.10 | rough: after solenoid 2 |
| Cryo & Quantum Materials chamber (sample 1) | 1.499 | schematic, 59.025″ |
| XC/YC03 | 1.85 | rough: after sample 1 |
| QD01 / QF01 (off by default) | 2.03 / 2.10 | read off the schematic (orange) |
| Single-Shot & High Temperature chamber (sample 2) | 2.487 | schematic, 97.895″ |
| XC/YC04 | 2.85 | rough: after sample 2 |
| THz diagnostic chamber | 3.988 | schematic, 157.020″ |
| ANDOR1 diffraction detector | 4.631 | schematic, 182.332″ |
| XC/YC05 | 4.75 | rough: after ANDOR1 |

The May 2025 deck put its sample and detector screens 6–12 cm further downstream: 1.557, 2.580 and 4.752 m.

Corrector kicks are set as an angle in mrad at the nominal 3.098 MeV. At that energy, 1 mrad is 11.9 µT·m (1.19 × 10⁻⁴ kG·m). A positive kick steers the beam to +x or +y. Converting to the machine's `BCTRL` units needs each corrector's calibration.

## Known gaps

- **Gun amplitude calibration.** The amplitude scan assumes the field is linear in AREQ, with 0.53 ↔ 68 MV/m. The real AREQ → MV/m curve is needed. A spectrometer energy measurement at a few setpoints, fitted with this scan, would give it.
- **Gun RF and thermal model.** `virtual_gun.py` exercises the procedure logic only. Matching the real timing needs archived AREQ, AACT and gun temperature from past ramps, plus the RF pulse width, rep rate and cooling setpoint.
- **Corrector positions and calibrations.** Positions are rough, as Fuhao said they would have to be. The kick per unit of `BCTRL` is unknown.
- **Misalignment model.** The only error knob so far is a cathode-spot offset. Solenoid offsets and tilts would be the next ones to add.
