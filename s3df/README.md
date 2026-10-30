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

## Reading UED PVs (caget)

`epics_env.sh` puts S3DF's EPICS base (`caget`, `cainfo`, `camonitor`) on `PATH`. It also points Channel Access at the UED gateway, `172.24.3.10:5110`. Hutch PVs (`UED:*`) answer under their own names, accelerator-side ones only under the `UED:USER:` prefix, and `uedget` adds that prefix where it's needed. The gateway allows reads only.

    source ~/group/ued/agentic/scripts/epics_env.sh
    caget UED:USR:MMN:14:07                       # collimator
    caget UED:USER:SIOC:AS01:KY03:0:AREQ          # gun amplitude setpoint
    uedget SIOC:AS01:KY03:0:AREQ SOLN:AS01:121:BCTRL UED:USR:MMN:14:07

## Badger for operators on ued-daq

`badger_ued.sh` starts Badger, the fork in the AgenticOpt venv on S3DF, which runs on ued-daq as is. It uses the UED environments (`bringup/ued_badger/plugins`: `ued` for the real machine, `ued_sim` for the simulator), the agent's routines as templates (`badger/routines`), and the shared archive (`badger/archive`).

    S=/sdf/group/mli/zhezhang/ued/agentic/scripts
    $S/badger_ued.sh run /sdf/group/mli/zhezhang/ued/agentic/badger/routines/<name>.yaml
    $S/badger_ued.sh --dry-run run <routine>    # writes logged, not sent
    $S/badger_ued.sh --read-only                # GUI, no writes
    $S/badger_ued.sh env ued                    # knobs, ranges, observables

On ued-daq the `ued` environment writes its knobs (solenoids, correctors, sample x/y) and nothing else, inside the safety ranges of `config/ued_setup.yaml`. It logs every write to `badger/ued_writes.jsonl`. Anywhere else it is read-only. Badger reads its settings from `~/.config/config.yaml`, and the shared home's copy points at the LCLS plugins, so the launcher gives Badger a home of its own (`badger/gui/home`) with the UED settings.

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
