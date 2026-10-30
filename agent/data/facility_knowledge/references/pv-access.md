---
type: reference
title: "Reading UED PVs from S3DF and from ued-daq"
description: "The S3DF EPICS gateway and its UED:USER: prefix for accelerator-side PVs, which PVs it serves, how to caget from iana, and direct Channel Access from ued-daq."
timestamp: "2026-10-30"
tags: [ued, epics, pv, s3df]
---

# Reading UED PVs from S3DF and from ued-daq

## From S3DF (iana): the EPICS gateway

```bash
source /sdf/group/mli/zhezhang/ued/agentic/scripts/epics_env.sh
caget UED:USR:MMN:14:07                    # hutch PV: its own name
caget UED:USER:SIOC:AS01:KY03:0:AREQ       # accelerator PV: UED:USER: prefix
uedget SIOC:AS01:KY03:0:AREQ UED:USR:MMN:14:07   # adds the prefix where needed
```

- Gateway: `EPICS_CA_ADDR_LIST=172.24.3.10:5110`, `EPICS_CA_AUTO_ADDR_LIST=NO` (server `pscag01`). Access is read, no write.
- **Hutch PVs** (`UED:*`) answer under their own names, camera images included.
- **Accelerator-side PVs** answer only as `UED:USER:<PV>`. Live on 2026-10-29: gun RF (AREQ, PREQ, AACT, PACT), gun temperature, solenoids (BCTRL, BACT), quads, corrector setpoints (BCTRL).
- **Not on the gateway yet** (2026-10-29): gate valves (`VVPG:AS01:*:POSITION`), gun feedback enables and states (`PFBENB`, `AFBENB`, `PFBST`, `AFBST`), diagnostic screen (`YAGS:AS01:270`), scope (`SCOP:AS01:SC01`), chamber light (`ACSW:AS01:NW03`), corrector readbacks (`BACT`). Beam stages stop at the gate-valve check from S3DF.
- The tools add the prefix themselves when `UED_ACCEL_PV_PREFIX=UED:USER:` is set. A prefixed record whose timestamp is the EPICS epoch (1990-01-01, never processed) is a placeholder, not the machine's value; the tools report it as unavailable.

## From ued-daq: direct Channel Access

`EPICS_CA_ADDR_LIST="172.21.36.255:5064 172.27.99.255:5058"` (from `/cds/group/pcds/setup/ued_setup.sh`; `~/.bashrc` sets it on `ued-*` hosts). The first entry reaches the hutch IOCs, the second the accelerator side. Every mapped PV answered on 2026-10-29, with no prefix. ued-daq can write to the hutch IOCs, so the agent there relies on its own write guards.

## Device pages

The PV of every device the tools use, with its status from S3DF, is in devices/.
