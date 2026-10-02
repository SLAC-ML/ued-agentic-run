# UED bring-up tools

This folder starts from Fuhao Ji's `ued_run4` scripts (GUED run 4, Nov–Dec 2023, `~/Projects/ued_run4`). It keeps what's still useful from them, mapped to today's PVs. Everything here is **read-only**: it uses `caget` and never `caput`.

- `ued_pvs.py`: the PV map. Each run-4 PV is paired with its current PV, with a status: CONFIRMED, LIKELY, CANDIDATE, UNMAPPED or NO_ACCESS.
- `snapshot.py`: a read-only beamline snapshot built on that map. It replaces `PVtest_run4.py`; `--json` gives machine-readable output.

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
| Low charge, 10 fC | UV throttle 48.4 | `UED:USR:MMN:14:01` reads 48.0 today |
| High charge, 50 fC | UV throttle 28.4 | the new throttle is at maximum at 21° |
| Pump at lowest energy | HWP 70 | an ND wheel −150 line was commented out |
| Stage out (to reach the Andor) | rel X 5, X 9 | |
| Collimator inserted | 93 mm | |
| E-beam on the YAG camera | gain 30, 2 s | |
| Laser on the YAG camera | gain 0, 0.1 s | |
| Andor, e-beam check | gain 10, 0.1 s | set by the operator |
| Saved samples (rel X, X, Y, Z / HWP) | YAG 10, 22.45, 41, 0 / 70 · Bi 9.95, 14, 45.1, 0 / 76.7 · Si 14.05, 13.9, 39.75, 0 / −130 · FC 10, 14.05, 10.85, 0 / 70 · SJ 0, 14.65, 10.9, 0 / 70 | |

## Controls environment on ued-daq

- `setup_env.sh` provides `caget`, `cainfo` and pyepics (EPICS 7). With the default settings, hutch PVs (`UED:*`) respond.
- Accelerator PVs (`*:AS01:*`: gun RF, solenoids, quads, correctors, rep rate) don't respond from `ued-daq`. I tried the default setup, the address list in `/cds/group/pcds/setup/ued_setup.sh` (`172.21.36.255:5064 172.27.99.255:5058`), and PV Access. This includes PVs the current DAQ still lists.
- Current PV names can be found in three places:
  - `/cds/group/pcds/pyps/config/ued/iocmanager.cfg`, the IOCs with readable aliases.
  - `/cds/data/iocData/<ioc>/iocInfo/IOC.pvlist`, the full PV list of each IOC.
  - `/cds/group/pcds/dist/pds/ued/misc/epicsArch*.txt`, the PVs the DAQ records, with descriptions.
  - The `.DESC` field of the XPS (`UED:USR:MMN:xx:yy`) and SmarAct motors names what each axis drives.

## Open questions

1. How should accelerator PVs (`AS01`) be reached now? Through a different host or a gateway?
2. Which axis is the pump energy control: `MMN:05:03` (527 nm HWP), `MMN:05:02` (harmonics HWP), or the new pump throttle `MMN:08:01`?
3. Is XPS-04 the sample stage? Which "Sample Y" is right, `MMN:04:07` or `MMN:04:01`? Is `UED:MCS2:03:m1` the relative X? Its description says "Charge Guard".
4. Which camera views the sample-plane YAG: `UED:GIGE:09` (DIAG YAG), `:12` (THz Sample) or `:13` (Beamline Viewing)?
5. What voltages do the Beckhoff shutter outputs use for open and closed? All read 0 V now.
6. Which PVs control the far-detector phosphor and the chamber light? And what do the PLC axes `UED:UM1:MMS:01–08` drive? They have no descriptions.
