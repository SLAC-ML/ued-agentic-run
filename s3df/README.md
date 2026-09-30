# GPT on S3DF

Scripts for running the UED beamline deck with GPT 3.43 (Linux build) on S3DF.
They are deployed to `/sdf/group/mli/zhezhang/ued/agentic/scripts/`
(`~/group/ued/agentic/scripts/` on `ssh iana`):

    rsync -av s3df/ iana:/sdf/group/mli/zhezhang/ued/agentic/scripts/

## Layout on S3DF

```
~/group/ued/agentic/
  sw/gpt343-CentOS7-devtoolset8-1-apr-2021-avx2/   GPT install (bin/, UserManual.pdf, tutorial/)
  .venv/          Python 3.11 + numpy/pandas/scipy/matplotlib/jupyter (uv)
  scripts/        this folder
  UED_May2025/    deck, field maps, parse_gdf.py, notebook (unmodified inputs)
  runs/<name>/    one folder per run; Slurm logs in runs/slurm-*.out
```

## Running

Environment (GPT on `PATH`, `GPTLICENSE`, Python env):

    source ~/group/ued/agentic/scripts/env.sh

Batch job (preferred; copies the deck into `runs/<name>/`, runs GPT + gdfa,
then `check_run.py`):

    sbatch ~/group/ued/agentic/scripts/gpt_job.sbatch my_run
    sbatch --cpus-per-task=32 ~/group/ued/agentic/scripts/gpt_job.sbatch my_run_j32

The defaults are `roma` / `mli:default` / `preemptable`. To use the UED
allocation instead, add `--partition=milano --account=lcls:ued1016014 --qos=normal`.

Interactively, from a folder holding the deck and field maps:

    ~/group/ued/agentic/scripts/run_gpt.sh 16     # = gpt -j 16 ..., then gdfa

`-j N` sets the number of GPT threads exactly as on Windows. Without it,
GPT uses every core on the node.

## Checking a run

    python ~/group/ued/agentic/scripts/check_run.py runs/my_run [--compare runs/other]

This prints the notebook's beam properties at z = 1.56 m next to the colleague's
Windows reference numbers, and gives PASS or FAIL against the tolerances in the
script. `--compare` diffs the full z-evolution of two runs. For the plots,
copy `check_single_run_1p6cell_10fC.ipynb` and `parse_gdf.py` into the run
folder and run:

    jupyter nbconvert --to notebook --execute --output checked.ipynb check_single_run_1p6cell_10fC.ipynb

## Notes

- The per-particle output (`UED_10fC_1p6cell_3p1MeV.gdf`) is about 600 MB per
  run, from 470 screens at 1 cm spacing.
- Screens between the collimator (z = 0.5575 m) and the end of that GPT time
  step still show all 62.5k particles, because removal is applied at the end of
  the step. So the emittance/size drop appears a few cm downstream of the iris,
  and exactly where depends on the step size (about 0.60 m here and about
  0.66 m in the Windows reference). Screens further downstream are unaffected.
