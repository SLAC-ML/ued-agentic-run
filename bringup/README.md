# UED bring-up tools

This folder starts from Fuhao Ji's `ued_run4` scripts (GUED run 4, Nov–Dec 2023, `~/Projects/ued_run4`). It keeps what's still useful from them, mapped to today's PVs. Everything here is **read-only**: it uses `caget` and never `caput`.

- `ued_pvs.py`: the PV map. Each run-4 PV is paired with its current PV, with a status: CONFIRMED, LIKELY, CANDIDATE, UNMAPPED or NO_ACCESS. Since 2026-10-16 it follows Fuhao's run-7 list where that has the device, and no PV is NO_ACCESS any more.
- `snapshot.py`: a read-only beamline snapshot built on that map. It replaces `PVtest_run4.py`; `--json` gives machine-readable output.
- `gun_ramp.py`: the gun RF ramp-up procedure, ported from `ramp_rf.py`. It has two extra checks: the feedbacks must stay Active, and the amplitude readback must track the setpoint. On the real machine AACT is in kV and AREQ is dimensionless, so the check holds their ratio steady after calibrating it over the first steps. It drives a backend: the simulator in [`sim/virtual_gun.py`](../sim/README.md), or the read-only EPICS backend, which refuses the first write.
- `ued_automation.py`: the updated version of the run-4 automation scripts (`goToYAG`, `goToBi`, `saveYAG`, ...), reworked per Fuhao's 2026-10 notes. It names no PV: it drives a backend through the logical channels. It reads one editable setup file, closes the pump shutter before any move, and checks every write against the safety ranges. The `ued_tuning` stages move the stage through it.
- `ued_setup.yaml`: the seed of that setup file: taught positions, the three camera views, Andor settings, pump and collimator setpoints, and safety ranges. The tools read the live copy, `/sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml` (or `$UED_SETUP_FILE`). `save_position` writes one position line there, keeps a `.bak`, and logs the change. Positions and the laser setpoints are still `null`, to be taught. The safety ranges were seeded on 2026-10-21 from the motors' soft limits and the magnets' drive limits.
- `ued_tuning/`: an MCP server with one tool per bring-up stage, all eight from the Run 7 proposal (gun ramp-up through time zero). It also has the automation actions (`go_to_position`, `save_position`, `set_camera_view`, `close_pump_shutter`), read-only checks (`check_beam_prerequisites`, `scope_charge`, `monitor_charge`, `measure_andor_spot`, `list_positions`) and `plan_beam_optimization`, an Xopt/Badger VOCS. The stage procedures follow the operators' 2026-10 notes: the dry-run notes for stages 1–3 and Fuhao's procedures for 4–8 (see `stages.py`). Beam stages stop unless all four gate valves read OPEN. Stage 2 has a second method, `method='bsa'`: Sam Klein's amortized T0 posterior ([boed/](../boed/README.md)) places four 10-point scans instead of the fine grid, and with `onset_guess_deg` it skips the coarse scan too. Stage 8 (time zero) measures the Bi pump-probe ΔI/I from Andor frames (`diffraction.py`, ported from Fuhao's April 2026 code) and has `method='boed'`: the April 2026 amortized BOED delay scan, with its models in `boed/models/delay_t0_2026-04` ([boed/](../boed/README.md#pump-probe-time-zero-on-the-delay-stage-stage-8)). A third method, `method='eig'`, is the April non-amortized BOED (`boed/delay_eig.py`, an Xopt generator; fixed to count the data once and learn the noise). Its hand-set values are in the setup file's `time_zero` section. While stage 8 runs it sends a progress message per point and writes a live log (`live.jsonl`, `live.png`) into its record folder from the start. `UED_TUNING_BACKEND` picks the machine behind it. `sim` is the virtual UED in [`sim/virtual_ued.py`](../sim/README.md). `epics` is the real machine, read-only: it reads through the channel map in `channels.py` and refuses every write, so a stage stops at its first write. It computes camera stats (centroid, size, total) from the image itself, because most of the cameras' Stats plugins are switched off. The deployed agent runs it with the `epics` backend (since 2026-10-16); see [agent/deploy/ued/README.md](../agent/deploy/ued/README.md). [reports/ued-bringup-mockup.html](../reports/ued-bringup-mockup.html) has the mock-up and the real-machine check (refreshed 2026-10-21; rebuild with `reports/src/ued-bringup-mockup/build.py`). [reports/ued-bringup-steps.html](../reports/ued-bringup-steps.html) lists every step of every stage for an expert to review.
- `mcp_readonly_check.py`: runs the `ued_tuning` server against the real machine with the `epics` backend. It reads every channel, runs the read-only checks, and calls every stage tool, and each tool stops at or before its first write. Results go to `runs/epics/` on S3DF.
- `run_stage.py`: runs a `ued_tuning` stage on ued-daq for an operator, through `scripts/ued_stage.sh` (`s3df/ued_stage.sh`). The deployed agent is read-only and its tools can't run on ued-daq; this runs the same stage code there. The default is a dry run, which logs every write and sends none. `--write` sends only the writes that stage may make (stage 8 for now), inside the safety ranges, each logged to `records/operator_writes.jsonl`. On 2026-10-30 a stage-8 dry run on ued-daq went through the moves and views to the overlap check. It stopped there, correctly: no pump laser on the YAG. Nothing on the machine changed.
- `pv_access.py`: how the tools name PVs on the wire. From S3DF the EPICS gateway serves the accelerator-side PVs only under a prefix, so every read goes through `wire_name()`: with `UED_ACCEL_PV_PREFIX` set (e.g. `UED:USER:`), every PV not starting with `UED:` gets the prefix. The maps keep the PVs' own names. Unset (on `ued-daq`), names go out as they are.
- `ued_badger/`: an agent-friendly Badger for the co-tuning after the collimator (Sol1, Sol2, XC/YC00-02, XC/YC04 against the Andor spot), on the model of the LCLS deployment's Badger tools. An MCP server (`python -m ued_badger`) drafts a routine from a VOCS, has Badger validate it against its environment (knobs, observables, safety ranges, generator), and runs it headless with a budget, a stop file, a live log and a beam-loss abort. At the end it puts the knobs back (or at the best point) and archives the run where the Badger GUI finds it. Two Badger environment plugins (`ued_badger/plugins/environments/`): `ued_sim`, the virtual UED after stage 5, which is runnable; and `ued`, the real machine through the EPICS backend, which reads only, so its routines are checked against the live values and run by an operator. The server runs in the agent's Python and calls the AgenticOpt venv (`UED_BADGER_PYTHON`, Badger fork + Xopt 3.1) as subprocesses. Routines, runs, archive and the simulator's knob state live in `/sdf/group/mli/zhezhang/ued/agentic/badger/` (`UED_BADGER_ROOT`). Tested on iana on 2026-10-28: Nelder-Mead on Sol1/XC00 cut the simulated spot 6.8 → 2.0 px in 10 evaluations; expected improvement on four knobs with a counts constraint, 6.8 → 2.3 px in 8 (~12-17 s per evaluation). Since 2026-10-30 it also covers stage 7: the knobs `sample_x`/`sample_y` and the observable `andor_frame_sum` (the diffracted intensity over the whole frame, with the main beam in the through hole). The simulator has a `stage7` preset at the Bi sample; a rehearsal there raised the intensity by 32 % in 8 evaluations. Operators run the agent's real-machine routines in Badger on ued-daq with `scripts/badger_ued.sh run <routine>` (`s3df/badger_ued.sh`). Only there does the `ued` environment write (`ued_badger/live.py`): its knobs only, inside the setup file's safety ranges, each write logged; `--dry-run` logs without sending. On 2026-10-30 on ued-daq it read the real knobs and Andor, refused writes when read-only, and in a dry run logged writes it never sent.

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

## Controls environment on S3DF

Since 2026-10-28 the experiment runs from S3DF rather than `ued-daq`. The PVs come through the EPICS gateway: `export EPICS_CA_ADDR_LIST=172.24.3.10:5110 EPICS_CA_AUTO_ADDR_LIST=NO`. The agent's S3DF host profile is `agent/profiles/s3df.yml`.

- **Hutch PVs** (`UED:*`) answer through the gateway under their own names, Andor images included (checked from iana on 2026-10-28). The exception is `UED:GIGE:03:Cross2X/Y` (the sample-YAG cross overlay), which answers from `ued-daq` but not through the gateway.
- **Accelerator-side PVs** (gun RF `SIOC:AS01:KY03` since 2026-10-28, `KY01` before; solenoids, correctors, gate valves `VVPG:AS01:*`, diagnostic screen `YAGS:AS01:270`, scope `SCOP:AS01:SC01`, chamber light `ACSW:AS01:NW03`, gun temperature) are served only under a prefix, e.g. `UED:USER:SIOC:AS01:KY03:0:AREQ`. On 2026-10-28 none of them answered (KY01 and KY03 tried), raw or with the prefixes `UED:USER:`, `UED:USER`, `UED:USR:`, from iana or from `ued-daq`. The gateway port (TCP 5110) is open. Either the prefix route isn't live yet or its names are different: to confirm with the controls group.
- **Placeholders (2026-10-29).** A day later the gateway (`pscag01`) answered many of the prefixed names: `UED:USER:SIOC:AS01:KY03:0:AREQ`/`PREQ`/`AACT_AVGNT`, the solenoid and corrector `BCTRL`s, the quads, the gun temperature. But every one read 0.0, with status UDF and the EPICS-epoch timestamp (1990-01-01): records nothing has ever written, not the machine. The gate valves, feedback states, diagnostic screen, scope, chamber light and corrector readbacks still didn't answer. So the readers treat a prefixed PV whose timestamp is the epoch as unavailable (`pv_access.never_processed`; the EPICS backend says "a gateway placeholder", the snapshot shows it as not connected). By 11:00 the same day they were live: KY03 `AREQ`/`PREQ`/`AACT_AVGNT`, the solenoid `BCTRL`/`BACT`, the corrector and quad `BCTRL` and the gun temperature read real values with current timestamps (`cainfo`: "read, no write"). Still missing: the gate valves, the gun feedback enables and states, the diagnostic screen, the scope, the chamber light and the corrector `BACT`. The guard stays, in case a name is published again before it is live.
- **`caget` from iana:** `source /sdf/group/mli/zhezhang/ued/agentic/scripts/epics_env.sh` (repo `s3df/epics_env.sh`). It sets the gateway and `UED_ACCEL_PV_PREFIX`, puts `caget` on `PATH`, and adds `uedget`, which prefixes accelerator names itself.
- Set `UED_ACCEL_PV_PREFIX=UED:USER:` and the tools add it themselves (`pv_access.py`). `ued_tuning_info`, `check_beam_prerequisites` and `machine_channels` (`wire_pv`) show what goes on the wire.
- The read-only check from iana with the prefix set (`runs/epics/readonly_check_s3df_20261028.json`): 60 of the 94 mapped channels answer, all of them hutch-side. On 2026-10-29 (`readonly_check_s3df_20261029.json`, before the placeholder guard) 86 of 119 "answered", the extra ones being the placeholders above. Every beam stage stops before its first write, because the gate valves read UNREADABLE. The Andor spot measurement works.

## Controls environment on ued-daq

- `setup_env.sh` provides `caget`, `cainfo` and pyepics (EPICS 7). It sets the CA address list from `/cds/group/pcds/setup/ued_setup.sh`: `172.21.36.255:5064 172.27.99.255:5058`. Since 2026-10-16, `~/.bashrc` on `ued-*` hosts sources the same file.
- With that list, both sides answer from `ued-daq` (checked 2026-10-16):
  - The hutch PVs (`UED:*`) answer on the first entry.
  - The accelerator PVs (`*:AS01:*`: gun RF, solenoids, quads, correctors, rep rate) answer on the second, `172.27.99.255:5058`. On 2026-10-01 they didn't, with what looked like the same list.
  - On 2026-10-28 the KY01 gun PVs no longer answered on `172.27.99.255:5058` from `ued-daq`: the accelerator side may have moved behind the S3DF gateway.
- Fuhao's run-7 list is in `/sdf/home/f/fuhaoji/UEDagentic/codes/`. `PVnamelist_SUED_agentic.py` holds the PVs and `PVtest_run7.py` cagets them all. The test appends to `results_PVtest_run7.txt` in the current folder, so run a copy from your own folder. Our run of it is in `pv_survey/run7_20261016/` on S3DF: all 109 PVs answered, in 3 s.
- Camera stats plugins: on the GigE cameras (`UED:GIGE:03/09/12/13`) the Stats plugins are disabled, so their `Stats*:Centroid*` read 0.0. On the Andor, Stats1 runs on a 163×163 ROI. The tools compute stats from the image PV instead. The images are `UED:GIGE:02:IMAGE1:ArrayData` (the sample chamber camera since 2026-10-28; `GIGE:03`, used before, is another camera with the same parameters, RGB 3×2048×2048), `UED:GIGE:09:IMAGE1` and `UED:ANDOR:CAM:03:IMAGE2` (1024×1024, 16-bit).
- Current PV names can be found in five places:
  - Fuhao's run-7 list, above.
  - `/cds/group/pcds/pyps/config/ued/iocmanager.cfg`, the IOCs with readable aliases.
  - `/cds/data/iocData/<ioc>/iocInfo/IOC.pvlist`, the full PV list of each IOC.
  - `/cds/group/pcds/dist/pds/ued/misc/epicsArch*.txt`, the PVs the DAQ records, with descriptions.
  - The `.DESC` field of the XPS (`UED:USR:MMN:xx:yy`) and SmarAct motors names what each axis drives. Some are stale: see question 5.

## Open questions

Fuhao's layout sketch and the gun ramp script (`assets/layout/`, `assets/gun_ramp_up/`) answered part of the original list. His run-7 PV list and the 2026-10 procedure notes answered more.

1. **Write route:** still open. The tools are read-only on the real machine. Should stage writes go through Badger routines an operator approves (the agent can now draft and check them, `ued_badger`), or the MCP tools with approval and the safety ranges? And now that the experiment runs from S3DF, does the gateway take writes at all?
2. **Gateway prefix:** since 2026-10-29 `UED:USER:<PV>` carries live values for the gun RF, magnets and gun temperature. Will the gate valves (`VVPG:AS01:*:POSITION`), gun feedback states, diagnostic screen (`YAGS:AS01:270`), scope (`SCOP:AS01:SC01`), chamber light and corrector readbacks (`BACT`) be added? And can `UED:GIGE:03:Cross2X/Y` be added?
3. **Taught positions and setpoints:** to fill in `ued_setup.yaml`. They are `null` there until then:
   - the sample-stage positions `yag`, `andor`, `bi`, `si`;
   - the pump HWP angles: set from the laser team's 400 nm calibration of 2026-10-28 (8° for the YAG overlap, 22° for Bi time zero; see `pump_calibration/README.md`);
   - the Andor through hole's pixel position and radius.
4. **Safety ranges:** confirm the seeded ones, especially the placeholders for the pump HWP (`0–180`) and the UV throttle (`45–60`). Their IOC limits are ±1e6 and ±180.
5. **Sample stage:** answered (Fuhao, 2026-10-28). 1st (SUED) chamber: X `UED:UM1:MMS:02`, Y `UED:USR:MMN:04:01`, Z `UED:UM1:MMS:01`, pitch `UED:USR:MMN:04:04`, yaw `UED:UM1:MMS:03` (pitch and yaw read-only for the tools). 2nd chamber (XPS-13): X `13:01`, Y `13:06`, Z `13:03`, pitch `13:04`, yaw `13:05`. Pump coupling mirrors: 1st chamber incoupling `MMN:04:03`, outcoupling `MMN:04:02`; 2nd chamber incoupling `MMN:13:02`, outcoupling `MMN:13:07`. XPS-11, mapped as the sample stage until then, is the Run 6 jet hardware (its DESCs, Incoupling X/Y, Outcoupling, Capillary Y, Catcher Y, were right) and is no longer mapped. The run-7 list's "2nd SUED stage" (XPS-03) and THz motors on XPS-13 were stale; `MMN:03:04` is only the pump long delay. Read on 2026-10-28: Y has IOC soft limits 0–25 (seeded as `limits.sample_y`); the IMS motors X, Z and yaw have none (LLM = HLM = 0). Still to do: `limits.sample_x` and `limits.sample_z` from the holder's travel (their only software limit), and the outcoupling mirror's IN/OUT positions (`pump.outcoupling_*_mm`); all `null` in `ued_setup.yaml` until then.
6. **Pump steering:** Fuhao's procedure says "pump laser mirror H and V". The tools map that to the run-7 list's pump lens H/V (`MMN:08:05/06`). Or is it the SmarAct `UED:MCS:01:m7/m8` ("pump_beam_X/Y")?
7. **Emission phase (stage 2):** the tools take the onset, where the scope charge first rises 5σ above the trace noise. Is it the onset, the half-maximum or the peak, and is the 30° offset added in the direction PREQ grows?
8. **Scope:** `MBBO_CH2_SCL` (V/div) reads UDF, so the charge numbers trust a record that was never processed. Is there a readback, and is −1.7 mV = 10 fC for a particular termination? The procedure text says `WF_CH0_TRACE`; CH2 is the confirmed one.
9. **Cameron's UV feedback loop (stage 3):** where does it live, and is it PV-backed? Its "continuously tune the UV throttle to keep ..." is cut off. The tool fine-tunes only with the operator's confirmation that the loop is stopped, then hands over.
10. **Diagnostic screen and Faraday cup:** the inserter is moved by command PVs (`YAGS:AS01:270:OPENCMD`/`CLOSECMD`) the tools never write, so inserting and extracting it is an operator step (`diag_screen_by_operator=true`); the tools read its state (`OPENSOLENOID`) and interlock (`INTLKSUM`), which from S3DF need the gateway prefix. Does the scope read the Faraday cup on that holder? The simulator assumes the pulse shows only while the holder is in.
11. **E-beam view gain:** procedure (4) says gain 30, the state list says 10. The setup file uses 10.
12. **Shutter voltage levels:** answered from Xinxin's Run 6 code: 3 V open, 0 V closed, read as open when > 0. The tools keep 1/0 and translate at the machine boundary (`channels.to_pv` / `from_pv`).
13. **Gun ramp:** the AREQ → MV/m calibration; archived ramps for the virtual gun; the modulator mode and HV PVs, so the preconditions can be read instead of asked. If AREQ is parked above 0.05, a ramp starts by lowering it to 0.05. The gun is on TS8 (KY03) since 2026-10-28; TS1 (KY01) is offline.
14. **Correctors:** which PV sets the kick, `BCTRL` (reads −145.6, EGU "kG-m", limits ±521) or `BDES` (reads 0)? What is the kick per unit? XC/YC04 are in A. XC/YC05 is in neither list.
15. **Far-detector phosphor:** the old `ASTA:BO:2114-9:BIT2` is commented out in the run-7 list and doesn't answer. Is it still needed?

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
| Pump outcoupling mirror | `pump_sc1_outcouplingMirror` (ued.db) | IN ≈ 24 (Run 6), 18 (Run 5); blocks the pump when IN. This run: `UED:USR:MMN:04:02` (1st chamber), checked by the readiness check |
| SC1 aperture | `aperture_x/y/z` (ued.db) | Run 5: retract (z → 0) before moving the sample; not allowed at `sc1_x ≥ 32.5` |
| Laser trigger rate | `TPR:AS01:TS02:0:CH07_SEQNUM` / `_SEQBIT` | 360 Hz: 5 / 7; 30 Hz: 7 / 4 |
| Pump Uniblitz polarity | `UED:DDG:01:abOutputPolarityBO` | 0 always open, 1 TTL |
| Drive UV Lambda shutter TTL | `ASTA:LSC01:TTL:IN:DISABLE` / `:HIGH` | manual vs TTL |
| Cold trap, HPLC | `APC:AS01:TM03:3314_02:CH02`, `UED:SDS:LC20:02:*` | liquid jet only |

Device names (`pump_hwp_angle`, `catcher_x`, `sample_x`, …) come from the
hutch-python `ued.db`; its happi database maps each to a PV.
