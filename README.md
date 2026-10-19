# ued-agentic-run

This repo has two parts: running UED beamline simulations with GPT (General Particle Tracer) on S3DF, and building tools for bringing up the real UED beamline. Eventually agents will drive both.

## What's in here

- `s3df/`: the scripts we use on S3DF. They set up the environment, run GPT (by hand or as a Slurm job), and sanity-check the output. [s3df/README.md](s3df/README.md) has the details.
- `bringup/`: tools for the real beamline, starting from Fuhao's 2023 run-4 automation scripts. So far there's a map from the old PVs to today's PVs, a read-only snapshot of the beamline state, the gun ramp-up procedure, and `ued_tuning`, an MCP server with a tool for each of the eight bring-up stages. On the real machine those tools only read for now. [bringup/README.md](bringup/README.md) has the details and the open questions.
- `sim/`: GPT simulations of the bring-up stages. There's a beamline deck with all the steering kickers, a Python runner for scans, one script per stage, and a virtual UED that the `ued_tuning` tools can be rehearsed against. [sim/README.md](sim/README.md) has the details.
- `agent/`: the source of the Osprey agent that runs on `ued-daq`. It holds the profile, the read-only beamline and tuning tools, the write guard and the launcher. Keys and build output stay out of git. [agent/deploy/ued/README.md](agent/deploy/ued/README.md) has the details.
- `assets/`: the raw files from collaborators: the GPT Linux build and license, the `UED_May2025` deck and field maps, and the analysis notebook. It's big and licensed, so it's not in git. The S3DF folder below has a copy of everything.

## The S3DF side

Everything lives in `/sdf/group/mli/zhezhang/ued/agentic` (reached via `ssh iana`):

```
sw/            GPT 3.43 (Linux build)
.venv/         Python env for analysis (numpy, pandas, matplotlib, jupyter)
scripts/       copy of s3df/ from this repo
bringup/       copy of bringup/ from this repo
sim/           copy of sim/ from this repo
UED_May2025/   the deck + field maps, left untouched
runs/          one folder per run, plus the Slurm logs
pv_survey/     raw PV survey dumps from ued-daq
```

## Quick start

```bash
ssh iana
A=/sdf/group/mli/zhezhang/ued/agentic
source $A/scripts/env.sh                        # gpt, gdfa, python on your PATH
sbatch $A/scripts/gpt_job.sbatch my_first_run   # takes a few minutes
cat $A/runs/slurm-gpt-ued-*.out                 # quick check at the end
```

Results land in `$A/runs/my_first_run/`. For the plots, run the notebook in that folder. [s3df/README.md](s3df/README.md) explains how.

## The machine side (ued-daq)

`ued-daq` is the UED production machine, and the S3DF folder above is mounted there. **Only read from it: `caget` is fine, but never `caput`.** Do any file writing on S3DF, and ask before changing anything on `ued-daq`.

To see what the beamline is doing right now:

```bash
ssh ued-daq
source /cds/group/pcds/dist/pds/ued/scripts/setup_env.sh
python /sdf/group/mli/zhezhang/ued/agentic/bringup/snapshot.py          # table
python /sdf/group/mli/zhezhang/ued/agentic/bringup/snapshot.py --json   # for agents
```

Both the hutch PVs (`UED:*`) and the accelerator PVs (gun RF, magnets, correctors) read from there. `setup_env.sh` sets the CA address list that reaches both, and so does `~/.bashrc` on `ued-*` hosts. Fuhao's run-7 PV list and its test script are in `/sdf/home/f/fuhaoji/UEDagentic/codes/`.

### The agent on ued-daq

The Osprey agent's source is `agent/` in this repo. The deployed copy is at `/sdf/group/mli/zhezhang/OspreyDeployments/UED`. It's built on S3DF and runs on `ued-daq` straight from there, with nothing copied over. It talks to the SLAC AI gateway directly and is read-only on the machine, with five separate guards against PV writes.

```bash
ssh ued-daq   # no setup_env.sh needed; the launcher sets up its own environment
L=/sdf/group/mli/zhezhang/OspreyDeployments/UED/deploy/ued/launch_ued.sh
$L chat --print ping   # quick check
$L web                 # web terminal on ued-daq's 127.0.0.1:10100
```

From your laptop, open the tunnel and then the banner's token URL with port 10102:

```bash
ssh -N -o ControlPath=none -o ExitOnForwardFailure=yes -L 127.0.0.1:10102:127.0.0.1:10100 ued-daq
```

Without `ExitOnForwardFailure`, a taken local port only gives a warning, and the page loads forever. VS Code's automatic port forwarding is the usual cause.

[agent/deploy/ued/README.md](agent/deploy/ued/README.md) covers syncing, building, the one-time workspace trust, the network routes and the write guards.

## Changing the scripts

Edit them here, then push them over:

```bash
rsync -av s3df/ iana:/sdf/group/mli/zhezhang/ued/agentic/scripts/
rsync -av bringup/ iana:/sdf/group/mli/zhezhang/ued/agentic/bringup/
rsync -av sim/ iana:/sdf/group/mli/zhezhang/ued/agentic/sim/
```

The agent goes to its own deployed copy. The excludes protect its key file and build, which exist only on S3DF. Rebuild afterwards:

```bash
rsync -av --exclude='/.env' --exclude='/.env.variant' --exclude='/build/' --exclude='/var/' \
    agent/ iana:/sdf/group/mli/zhezhang/OspreyDeployments/UED/
ssh iana 'cd /sdf/group/mli/zhezhang/OspreyDeployments/UED && build/.venv/bin/osprey build --skip-deps'
```
