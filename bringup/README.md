# UED bring-up tools

This folder starts from Fuhao Ji's `ued_run4` scripts (GUED run 4, Nov–Dec 2023, `~/Projects/ued_run4`). It keeps what's still useful from them, mapped to today's PVs. Everything here is **read-only**: it uses `caget` and never `caput`.

- `ued_pvs.py`: the PV map. Each run-4 PV is paired with its current PV, with a status: CONFIRMED, LIKELY, CANDIDATE, UNMAPPED or NO_ACCESS. Since 2026-10-16 it follows Fuhao's run-7 list where that has the device, and no PV is NO_ACCESS any more.
- `snapshot.py`: a read-only beamline snapshot built on that map. It replaces `PVtest_run4.py`; `--json` gives machine-readable output.
- `gun_ramp.py`: the gun RF ramp-up procedure, ported from `ramp_rf.py`. It has two extra checks: the feedbacks must stay Active, and the amplitude readback must track the setpoint. It drives a backend, which for now is only the simulator in [`sim/virtual_gun.py`](../sim/README.md). There is no machine backend.
- `ued_tuning/`: an MCP server with one tool per bring-up stage, all eight from the Run 7 proposal (gun ramp-up through time zero). `UED_TUNING_BACKEND` picks the machine behind it. `sim` is the virtual UED in [`sim/virtual_ued.py`](../sim/README.md). `epics` is the real machine, read-only: it reads through the channel map in `channels.py` and refuses every write, so a stage stops at its first write. It computes camera stats (centroid, size, total) from the image itself, because most of the cameras' Stats plugins are switched off. It isn't registered in the deployed agent yet. [reports/ued-bringup-mockup.html](../reports/ued-bringup-mockup.html) has the mock-up run and what blocks each stage on the real machine.
- `mcp_readonly_check.py`: runs the `ued_tuning` server against the real machine with the `epics` backend. It reads every channel and calls every stage tool, and each tool stops at its first write. Results go to `runs/epics/` on S3DF.

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
| Stage out (to reach the Andor) | rel X 5, X 9 | |
| Collimator inserted | 93 mm | |
| E-beam on the YAG camera | gain 30, 2 s | |
| Laser on the YAG camera | gain 0, 0.1 s | |
| Andor, e-beam check | gain 10, 0.1 s | set by the operator |
| Saved samples (rel X, X, Y, Z / HWP) | YAG 10, 22.45, 41, 0 / 70 · Bi 9.95, 14, 45.1, 0 / 76.7 · Si 14.05, 13.9, 39.75, 0 / −130 · FC 10, 14.05, 10.85, 0 / 70 · SJ 0, 14.65, 10.9, 0 / 70 | |

## Controls environment on ued-daq

- `setup_env.sh` provides `caget`, `cainfo` and pyepics (EPICS 7). It sets the CA address list from `/cds/group/pcds/setup/ued_setup.sh`: `172.21.36.255:5064 172.27.99.255:5058`. Since 2026-10-16, `~/.bashrc` on `ued-*` hosts sources the same file.
- With that list, both sides answer from `ued-daq` (checked 2026-10-16):
  - The hutch PVs (`UED:*`) answer on the first entry.
  - The accelerator PVs (`*:AS01:*`: gun RF, solenoids, quads, correctors, rep rate) answer on the second, `172.27.99.255:5058`. On 2026-10-01 they didn't, with what looked like the same list.
  - The deployed agent's profile still lists only the first entry. [agent/deploy/ued/README.md](../agent/deploy/ued/README.md) says what to change.
- Fuhao's run-7 list is in `/sdf/home/f/fuhaoji/UEDagentic/codes/`. `PVnamelist_SUED_agentic.py` holds the PVs and `PVtest_run7.py` cagets them all. The test appends to `results_PVtest_run7.txt` in the current folder, so run a copy from your own folder. Our run of it is in `pv_survey/run7_20261016/` on S3DF: all 109 PVs answered, in 3 s.
- Camera stats plugins: on the GigE cameras (`UED:GIGE:03/09/12/13`) the Stats plugins are disabled, so their `Stats*:Centroid*` read 0.0. On the Andor, Stats1 runs on a 163×163 ROI. The tools compute stats from the image PV instead. The images are `UED:GIGE:03:IMAGE1:ArrayData` (RGB, 3×2048×2048), `UED:GIGE:09:IMAGE1` and `UED:ANDOR:CAM:03:IMAGE2` (1024×1024, 16-bit).
- Current PV names can be found in five places:
  - Fuhao's run-7 list, above.
  - `/cds/group/pcds/pyps/config/ued/iocmanager.cfg`, the IOCs with readable aliases.
  - `/cds/data/iocData/<ioc>/iocInfo/IOC.pvlist`, the full PV list of each IOC.
  - `/cds/group/pcds/dist/pds/ued/misc/epicsArch*.txt`, the PVs the DAQ records, with descriptions.
  - The `.DESC` field of the XPS (`UED:USR:MMN:xx:yy`) and SmarAct motors names what each axis drives. Some are stale: see question 3.

## Open questions

Fuhao's layout sketch and the gun ramp script (`assets/layout/`, `assets/gun_ramp_up/`) answered part of the original list, and his run-7 PV list answered more.

1. **Accelerator PVs (`AS01`):** answered for reads. They answer from `ued-daq` now. Still open: the write route, for when stages may write (`uedopr` / `testfac-srv01`, or approved writes from `ued-daq`).
2. **Pump energy control:** mostly answered. The run-7 list sets the pump with the Harmonics HWP `MMN:05:02` (DESC "max @ 51", the list says 50) and the ND wheel `MMN:05:08` (max @ 310). It calls `MMN:08:01` the THz throttle, though its DESC says "Pump Throttle (max @ 44.5)". To confirm: is 08:01 unused for SUED pump-probe?
3. **Sample stage:** partly answered. The run-7 list puts the SUED sample stage on XPS-11: `11:03/04/05` (X/Y/Z), `11:01` (pitch) and `11:08` (yaw). Their DESCs say "Incoupling X", "Incoupling Y", "Outcoupling in@24.9", "Capillary Y" and "Catcher Y". Are those left over from a jet setup? The list's "2nd SUED sample stage" block gives `03:04` as Z, but `03:04` is also its pump long delay (DESC "Pump Long Delay"). Is that block stale? On XPS-04, `04:04` is "1st Pitch", not Sample X as the 10-01 survey guessed.
4. **Sample-plane camera:** answered. `UED:GIGE:03` is the sample chamber camera. Its e-beam marker is the cross overlay `Cross2X/Y` (1080, 1034).
5. **Shutter voltage levels:** still open. What voltages do the Beckhoff shutter outputs use for open and closed? All read 0 V.
6. **Phosphor, chamber light, Faraday cup:** partly answered.
   - Chamber light: `ACSW:AS01:NW03:2POWERON` / `:2POWEROFF`, with the state in `:2POWERSTATE`.
   - Far-detector phosphor: still open. The old `ASTA:BO:2114-9:BIT2` is commented out in the run-7 list and doesn't answer.
   - Faraday cup and its holder with the Diag YAG: still no PV for the charge or the inserter.
7. **Gun ramp details:** partly open.
   - The feedback enums read "Disable" with the gun off. `ramp_rf.py` waits for "Active".
   - `AREQ`'s EGU says "degrees" and `AACT_AVGNT`'s says kV. The AREQ → MV/m calibration is still needed.
   - Still needed: archived ramps for the virtual gun, and the modulator mode/HV PVs.
8. **Correctors:** partly answered. `X/YCOR:AS01:121…382` exist and read. What's open:
   - Their `BCTRL` EGU says kG-m, but `BCTRL` reads −145.6 (limits ±521) where `BDES` reads 0. Which one sets the kick, and what's the kick per unit?
   - XC/YC05 is in neither list.
   - On 10-16 the magnets were "Turned Off", and solenoid 2 read "PS Tripped".
9. **Pump power meter (new):** `MMN:05:06` read 40 (in, blocking the pump) on 10-16. Stages 6 and 8 take it out first; that's one more write to approve.
