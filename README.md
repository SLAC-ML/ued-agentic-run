# ued-agentic-run

This repo has two parts: running UED beamline simulations with GPT (General Particle Tracer) on S3DF, and building tools for bringing up the real UED beamline. Eventually agents will drive both.

## What's in here

- `s3df/`: the scripts we use on S3DF. They set up the environment, run GPT (by hand or as a Slurm job), and sanity-check the output. [s3df/README.md](s3df/README.md) has the details.
- `bringup/`: tools for the real beamline, starting from Fuhao's 2023 run-4 automation scripts. So far there's a map from the old PVs to today's PVs, and a read-only snapshot of the beamline state. [bringup/README.md](bringup/README.md) has the details and the open questions.
- `assets/`: the raw files from collaborators: the GPT Linux build and license, the `UED_May2025` deck and field maps, and the analysis notebook. It's big and licensed, so it's not in git. The S3DF folder below has a copy of everything.

## The S3DF side

Everything lives in `/sdf/group/mli/zhezhang/ued/agentic` (reached via `ssh iana`):

```
sw/            GPT 3.43 (Linux build)
.venv/         Python env for analysis (numpy, pandas, matplotlib, jupyter)
scripts/       copy of s3df/ from this repo
bringup/       copy of bringup/ from this repo
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

The hutch PVs (`UED:*`) read fine from there. The accelerator PVs (gun RF, magnets) don't answer from `ued-daq` yet.

## Changing the scripts

Edit them here, then push them over:

```bash
rsync -av s3df/ iana:/sdf/group/mli/zhezhang/ued/agentic/scripts/
rsync -av bringup/ iana:/sdf/group/mli/zhezhang/ued/agentic/bringup/
```
