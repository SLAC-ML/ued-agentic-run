---
type: procedure
title: "Gun RF ramp-up"
description: "How the gun RF is ramped from AREQ 0.05 to 0.53 (stage 1), the checks on the way, and how the bring-up tool differs from the original ramp_rf.py."
timestamp: "2026-10-30"
tags: [ued, procedure, gun, rf]
---

# Gun RF ramp-up

**Before the ramp**, the operator confirms on the panel: AREQ is 0, the modulator is in TRIG, the HV is at full voltage (VoltSet = 980 V), and the readbacks match the 0.05 setpoint. These can't be read yet.

**The ramp** (stage 1, `gun_ramp`; code `bringup/gun_ramp.py`, from `ramp_rf.py` by C. England):

1. Set AREQ (`SIOC:AS01:KY03:0:AREQ`) to 0.05. If it was parked higher, lower it to 0.05 first.
2. Enable the phase and amplitude feedbacks (`PFBENB`, `AFBENB`).
3. Step AREQ to the target, 0.53, in `gun.ramp_n_steps` steps of `gun.ramp_dwell_s`: 600 x 2 s = 20 min since 2026-10-28, for the reduced cooling-water flow.
4. Before each step, wait until the gun body temperature (`APC:AS01:TM01:M2_CH2_SPARE`) is within `gun.ramp_temp_min_C`-`ramp_temp_max_C` (33-37 C). The gun idles at ~36.4 C with RF off. After 10 out-of-range readings in a row, set AREQ to 0 and stop.

**Added on top of the original:**
- Both feedbacks must report Active (`PFBST`, `AFBST`) before the ramp and at every step.
- The amplitude readback must track the setpoint. AACT reads in kV and AREQ is dimensionless, so the tool calibrates their ratio over the first steps and holds it within a tolerance.

The original script is at `/sdf/group/mli/zhezhang/ued/agentic/assets/gun_ramp_up/ramp_rf.py`. From S3DF the feedback PVs aren't on the gateway yet (references/pv-access), so a ramp watched from S3DF can't confirm them.
