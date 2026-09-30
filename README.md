# ued-agentic-run

This repo is for running UED beamline simulations with GPT (General Particle Tracer) on S3DF, and eventually letting agents drive them.

## What's in here

- `s3df/`: the scripts we use on S3DF. They set up the environment, run GPT (by hand or as a Slurm job), and sanity-check the output. [s3df/README.md](s3df/README.md) has the details.
- `assets/`: the raw files from collaborators: the GPT Linux build and license, the `UED_May2025` deck and field maps, and the analysis notebook. It's big and licensed, so it's not in git. The S3DF folder below has a copy of everything.

## The S3DF side

Everything lives in `/sdf/group/mli/zhezhang/ued/agentic` (reached via `ssh iana`):

```
sw/            GPT 3.43 (Linux build)
.venv/         Python env for analysis (numpy, pandas, matplotlib, jupyter)
scripts/       copy of s3df/ from this repo
UED_May2025/   the deck + field maps, left untouched
runs/          one folder per run, plus the Slurm logs
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

## Changing the scripts

Edit them in `s3df/` here, then push them over:

```bash
rsync -av s3df/ iana:/sdf/group/mli/zhezhang/ued/agentic/scripts/
```
