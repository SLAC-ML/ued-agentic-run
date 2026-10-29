# UED bring-up tools

This folder starts from Fuhao Ji's `ued_run4` scripts (GUED run 4, Nov–Dec 2023, `~/Projects/ued_run4`). It keeps what's still useful from them, mapped to today's PVs. Everything here is **read-only**: it uses `caget` and never `caput`.

- `ued_pvs.py`: the PV map. Each run-4 PV is paired with its current PV, with a status: CONFIRMED, LIKELY, CANDIDATE, UNMAPPED or NO_ACCESS. Since 2026-10-16 it follows Fuhao's run-7 list where that has the device, and no PV is NO_ACCESS any more.
- `snapshot.py`: a read-only beamline snapshot built on that map. It replaces `PVtest_run4.py`; `--json` gives machine-readable output.
- `gun_ramp.py`: the gun RF ramp-up procedure, ported from `ramp_rf.py`. It has two extra checks: the feedbacks must stay Active, and the amplitude readback must track the setpoint. On the real machine AACT is in kV and AREQ is dimensionless, so the check holds their ratio steady after calibrating it over the first steps. It drives a backend: the simulator in [`sim/virtual_gun.py`](../sim/README.md), or the read-only EPICS backend, which refuses the first write.
- `ued_automation.py`: the updated version of the run-4 automation scripts (`goToYAG`, `goToBi`, `saveYAG`, ...), reworked per Fuhao's 2026-10 notes. It names no PV: it drives a backend through the logical channels. It reads one editable setup file, closes the pump shutter before any move, and checks every write against the safety ranges. The `ued_tuning` stages move the stage through it.
- `ued_setup.yaml`: the seed of that setup file: taught positions, the three camera views, Andor settings, pump and collimator setpoints, and safety ranges. The tools read the live copy, `/sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml` (or `$UED_SETUP_FILE`). `save_position` writes one position line there, keeps a `.bak`, and logs the change. Positions and the laser setpoints are still `null`, to be taught. The safety ranges were seeded on 2026-10-21 from the motors' soft limits and the magnets' drive limits.
- `ued_tuning/`: an MCP server with one tool per bring-up stage, all eight from the Run 7 proposal (gun ramp-up through time zero). It also has the automation actions (`go_to_position`, `save_position`, `set_camera_view`, `close_pump_shutter`), read-only checks (`check_beam_prerequisites`, `scope_charge`, `monitor_charge`, `measure_andor_spot`, `list_positions`) and `plan_beam_optimization`, an Xopt/Badger VOCS. The stage procedures follow the operators' 2026-10 notes: the dry-run notes for stages 1–3 and Fuhao's procedures for 4–8 (see `stages.py`). Beam stages stop unless all four gate valves read OPEN. `UED_TUNING_BACKEND` picks the machine behind it. `sim` is the virtual UED in [`sim/virtual_ued.py`](../sim/README.md). `epics` is the real machine, read-only: it reads through the channel map in `channels.py` and refuses every write, so a stage stops at its first write. It computes camera stats (centroid, size, total) from the image itself, because most of the cameras' Stats plugins are switched off. The deployed agent runs it with the `epics` backend (since 2026-10-16); see [agent/deploy/ued/README.md](../agent/deploy/ued/README.md). [reports/ued-bringup-mockup.html](../reports/ued-bringup-mockup.html) has the mock-up and the real-machine check (refreshed 2026-10-21; rebuild with `reports/src/ued-bringup-mockup/build.py`). [reports/ued-bringup-steps.html](../reports/ued-bringup-steps.html) lists every step of every stage for an expert to review.
- `mcp_readonly_check.py`: runs the `ued_tuning` server against the real machine with the `epics` backend. It reads every channel, runs the read-only checks, and calls every stage tool, and each tool stops at or before its first write. Results go to `runs/epics/` on S3DF.

Run it on `ued-daq`. S3DF is mounted there, so nothing has to be copied over:

```bash
source /cds/group/pcds/dist/pds/ued/scripts/setup_env.sh
python /sdf/group/mli/zhezhang/ued/agentic/bringup/snapshot.py          # table
python /sdf/group/mli/zhezhang/ued/agentic/bringup/snapshot.py --json   # for agents
```

To change it, edit here and push with `rsync -a bringup/ iana:/sdf/group/mli/zhezhang/ued/agentic/bringup/`.

## What the run-4 scripts did

The scripts have three layers:

1. **Primitive actions** (`run4_basics.py`): open/close the gun UV and pump shutters, move the sample stage to a saved position, set the pump to its lowest energy, set the UV throttle for low or high charge, switch the chamber light, and insert the far-detector phosphor.
2. **Named sample positions** (`pos_*.txt`, `settings_*.txt`): YAG, Bi, Si, flow cell, slit jet. The coordinates belong to the old PI stage and don't carry over. The idea does carry over: a named position plus a pump setting per sample.
3. **Operator procedures** (`run4_utilities.py`): these pause for the operator to press Enter.

### Procedures worth keeping

**Spatial overlap** (`spatialOverlap`):

1. Close the pump shutter and set the pump to its lowest energy.
2. Move the YAG in and switch the chamber light off.
3. Set the sample camera to gain 30 and exposure 2 s, then open the gun UV shutter.
4. *Operator marks the e-beam position on the camera.*
5. Set the sample camera to gain 0 and exposure 0.1 s, then open the pump shutter.
6. *Operator steers the laser onto the mark.*
7. Close the pump shutter and switch the chamber light on.

The other procedures reuse those steps:

- `checkEbeam` is steps 1–4, then the camera goes back to gain 0 / 0.1 s and the light comes on.
- `checkPumpLaser` is steps 1–2 and 5–7.
- `checkAndorEbeam`: move the stage out and insert the phosphor, set the Andor to gain 10 and exposure 0.1 s, and open the gun UV shutter. Then insert the collimator to 93 mm and tune the steering and collimator.

The operator steps can become camera checks for an agent. Every current camera has areaDetector Stats plugins (`<prefix>:Stats1..5`) that give the beam centroid and size.

## Setpoints from run 4

All positions are in old controller units. Positions need re-teaching on the new stages, and the charge settings need a Faraday-cup recalibration.

| What | Run-4 value | Note |
|---|---|---|
| Low charge, 10 fC | UV throttle 48.4 | `UED:USR:MMN:14:01` read 48.0 on 10-01 and 50.0 on 10-16 |
| High charge, 50 fC | UV throttle 28.4 | the new throttle is at maximum at 21° |
| Pump at lowest energy | HWP 70 | an ND wheel −150 line was commented out |
| Stage out (to reach the Andor) | rel X 5, X 9 | GUED stage (gas phase); not applicable to SUED |
| Collimator inserted | 93 mm | |
| E-beam on the YAG camera | gain 30, 2 s | |
| Laser on the YAG camera | gain 0, 0.1 s | |
| Andor, e-beam check | gain 10, 0.1 s | set by the operator |
| Saved samples, GUED stage (rel X, X, Y, Z / HWP); not applicable to SUED | YAG 10, 22.45, 41, 0 / 70 · Bi 9.95, 14, 45.1, 0 / 76.7 · Si 14.05, 13.9, 39.75, 0 / −130 · FC 10, 14.05, 10.85, 0 / 70 · SJ 0, 14.65, 10.9, 0 / 70 | |

## Controls environment on ued-daq

- `setup_env.sh` provides `caget`, `cainfo` and pyepics (EPICS 7). It sets the CA address list from `/cds/group/pcds/setup/ued_setup.sh`: `172.21.36.255:5064 172.27.99.255:5058`. Since 2026-10-16, `~/.bashrc` on `ued-*` hosts sources the same file.
- With that list, both sides answer from `ued-daq` (checked 2026-10-16):
  - The hutch PVs (`UED:*`) answer on the first entry.
  - The accelerator PVs (`*:AS01:*`: gun RF, solenoids, quads, correctors, rep rate) answer on the second, `172.27.99.255:5058`. On 2026-10-01 they didn't, with what looked like the same list.
  - The deployed agent's profile still lists only the first entry. [agent/deploy/ued/README.md](../agent/deploy/ued/README.md) says what to change.
- Fuhao's run-7 list is in `/sdf/home/f/fuhaoji/UEDagentic/codes/`. `PVnamelist_SUED_agentic.py` holds the PVs and `PVtest_run7.py` cagets them all. The test appends to `results_PVtest_run7.txt` in the current folder, so run a copy from your own folder. Our run of it is in `pv_survey/run7_20261016/` on S3DF: all 109 PVs answered, in 3 s.
- Camera stats plugins: on the GigE cameras (`UED:GIGE:03/09/12/13`) the Stats plugins are disabled, so their `Stats*:Centroid*` read 0.0. On the Andor, Stats1 runs on a 163×163 ROI. The tools compute stats from the image PV instead. The images are `UED:GIGE:02:IMAGE1:ArrayData` (the sample chamber camera since 2026-10-28; `GIGE:03`, used before, is another camera with the same parameters, RGB 3×2048×2048), `UED:GIGE:09:IMAGE1` and `UED:ANDOR:CAM:03:IMAGE2` (1024×1024, 16-bit).
- Current PV names can be found in five places:
  - Fuhao's run-7 list, above.
  - `/cds/group/pcds/pyps/config/ued/iocmanager.cfg`, the IOCs with readable aliases.
  - `/cds/data/iocData/<ioc>/iocInfo/IOC.pvlist`, the full PV list of each IOC.
  - `/cds/group/pcds/dist/pds/ued/misc/epicsArch*.txt`, the PVs the DAQ records, with descriptions.
  - The `.DESC` field of the XPS (`UED:USR:MMN:xx:yy`) and SmarAct motors names what each axis drives. Some are stale: see question 3.

## Open questions

Fuhao's layout sketch and the gun ramp script (`assets/layout/`, `assets/gun_ramp_up/`) answered part of the original list. His run-7 PV list and the 2026-10 procedure notes answered more.

1. **Write route:** still open. The tools are read-only on the real machine. Should stage writes go through Badger routines an operator approves, or the MCP tools with approval and the safety ranges? And for the accelerator side, from `ued-daq` or through `uedopr` on `testfac-srv01`?
2. **Taught positions and setpoints:** to fill in `ued_setup.yaml`. They are `null` there until then:
   - the sample-stage positions `yag`, `andor`, `bi`, `si`;
   - the pump HWP angles: seeded with Xinxin's Run 6 values (YAG overlap 12.0°, Bi t₀ 16.245°); confirm with the laser team;
   - the Andor through hole's pixel position and radius.
3. **Safety ranges:** confirm the seeded ones, especially the placeholders for the pump HWP (`0–180`) and the UV throttle (`45–60`). Their IOC limits are ±1e6 and ±180.
4. **Sample stage:** answered (Fuhao, 2026-10-28). The SUED sample stage is XPS-11: `11:03/04/05` (X/Y/Z), `11:01` (pitch) and `11:08` (yaw). Their DESCs ("Incoupling X", "Incoupling Y", "Outcoupling in@24.9", "Capillary Y", "Catcher Y") are stale. Run 4 was a gas-phase run on the GUED chamber, so its PI X/Y/Z and SmarAct relative X don't carry over; relative X is retired, and pitch and yaw take its place. Still open: the list's "2nd SUED sample stage" block gives `03:04` as Z, but `03:04` is also its pump long delay. Is that block stale?
5. **Pump steering:** Fuhao's procedure says "pump laser mirror H and V". The tools map that to the run-7 list's pump lens H/V (`MMN:08:05/06`). Or is it the SmarAct `UED:MCS:01:m7/m8` ("pump_beam_X/Y")?
6. **Emission phase (stage 2):** the tools take the onset, where the scope charge first rises 5σ above the trace noise. Is it the onset, the half-maximum or the peak, and is the 30° offset added in the direction PREQ grows?
7. **Scope:** `MBBO_CH2_SCL` (V/div) reads UDF, so the charge numbers trust a record that was never processed. Is there a readback, and is −1.7 mV = 10 fC for a particular termination? The procedure text says `WF_CH0_TRACE`; CH2 is the confirmed one.
8. **Cameron's UV feedback loop (stage 3):** where does it live, and is it PV-backed? Its "continuously tune the UV throttle to keep ..." is cut off. The tool fine-tunes only with the operator's confirmation that the loop is stopped, then hands over.
9. **Diagnostic screen and Faraday cup:** still no PV for the inserter, so inserting and extracting it is an operator step (`diag_screen_by_operator=true`). Does the scope read the Faraday cup on that holder? The simulator assumes the pulse shows only while the holder is in.
10. **E-beam view gain:** procedure (4) says gain 30, the state list says 10. The setup file uses 10.
11. **Shutter voltage levels:** answered from Xinxin's Run 6 code: 3 V open, 0 V closed, read as open when > 0. The tools keep 1/0 and translate at the machine boundary (`channels.to_pv` / `from_pv`).
12. **Gun ramp:** the AREQ → MV/m calibration; archived ramps for the virtual gun; the modulator mode and HV PVs, so the preconditions can be read instead of asked. If AREQ is parked above 0.05, a ramp starts by lowering it to 0.05. The gun is on TS8 (KY03) since 2026-10-28; TS1 (KY01) is offline.
13. **Correctors:** which PV sets the kick, `BCTRL` (reads −145.6, EGU "kG-m", limits ±521) or `BDES` (reads 0)? What is the kick per unit? XC/YC04 are in A. XC/YC05 is in neither list.
14. **Far-detector phosphor:** the old `ASTA:BO:2114-9:BIT2` is commented out in the run-7 list and doesn't answer. Is it still needed?

## Reference: Xinxin's Run 5/6 hutch-python code

`UED_agentic_beamtime/xxCodes.py` (Run 6, liquid jet, 2026-06; Run 5 solid
phase in its commented parts). Adopted into the tools: the shutter levels
(3 V / 0 V), both shutters closed before every stage move and the gun UV
restored after, the sample-camera "mid" view on moves and the high / mid /
low presets, a per-position `pump_hwp_deg`, the Run 6 pump HWP angles as
seeds, the readiness checklist (power meter IN, ePix valve), the side camera
`UED:GIGE:03`, and serpentine rasters.

Kept for reference only (the run-7 PVs above are the current ones):

| What | Run 5/6 PV or device | Note |
|---|---|---|
| SC1 front LED | `APC:AS01:TM04:2114_02:CH02` ("On"/"Off") | Run 6 sample-chamber light; the tools use `ACSW:AS01:NW03:2POWER…` |
| SC1 back LED | `ACSW:AS01:NW03:5POWERON` / `5POWEROFF` | outlet 5 |
| Pump outcoupling mirror | `pump_sc1_outcouplingMirror` (ued.db) | IN ≈ 24 (Run 6), 18 (Run 5); blocks the pump when IN. Run 6 XPS-11 DESC "Outcoupling in@24.9" |
| SC1 aperture | `aperture_x/y/z` (ued.db) | Run 5: retract (z → 0) before moving the sample; not allowed at `sc1_x ≥ 32.5` |
| Laser trigger rate | `TPR:AS01:TS02:0:CH07_SEQNUM` / `_SEQBIT` | 360 Hz: 5 / 7; 30 Hz: 7 / 4 |
| Pump Uniblitz polarity | `UED:DDG:01:abOutputPolarityBO` | 0 always open, 1 TTL |
| Drive UV Lambda shutter TTL | `ASTA:LSC01:TTL:IN:DISABLE` / `:HIGH` | manual vs TTL |
| Cold trap, HPLC | `APC:AS01:TM03:3314_02:CH02`, `UED:SDS:LC20:02:*` | liquid jet only |

Device names (`pump_hwp_angle`, `catcher_x`, `sample_x`, …) come from the
hutch-python `ued.db`; its happi database maps each to a PV.
