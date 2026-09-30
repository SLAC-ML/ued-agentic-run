#!/bin/bash
# Run the UED GPT deck as a Slurm job on S3DF, then check the result.
#   sbatch [--cpus-per-task=N] gpt_job.sbatch <run_name> [deck_dir]
# Output goes to $AGENTIC_ROOT/runs/<run_name>/. For production runs on the UED
# allocation use e.g. --partition=milano --account=lcls:ued1016014 --qos=normal.
#SBATCH --job-name=gpt-ued
#SBATCH --partition=roma
#SBATCH --account=mli:default
#SBATCH --qos=preemptable
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=/sdf/group/mli/zhezhang/ued/agentic/runs/slurm-%x-%j.out
set -euo pipefail
source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh

RUN_NAME=${1:?usage: sbatch gpt_job.sbatch <run_name> [deck_dir]}
DECK_DIR=${2:-$AGENTIC_ROOT/UED_May2025}
RUN_DIR=$AGENTIC_ROOT/runs/$RUN_NAME

mkdir -p "$RUN_DIR"
cp "$DECK_DIR"/UED_beamline.in "$DECK_DIR"/*.gdf "$RUN_DIR"/
cd "$RUN_DIR"
echo "job=$SLURM_JOB_ID node=$SLURMD_NODENAME cpus=$SLURM_CPUS_PER_TASK deck=$DECK_DIR"

"$AGENTIC_ROOT"/scripts/run_gpt.sh "$SLURM_CPUS_PER_TASK" > gpt.log 2>&1
grep -E "^(real|user|sys)" gpt.log | head -3

python "$AGENTIC_ROOT"/scripts/check_run.py "$RUN_DIR"
