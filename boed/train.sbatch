#!/bin/bash
# Train the amortized T0 posteriors on an S3DF GPU node.
#   cd boed && sbatch train.sbatch bsa       runs/bsa_full_v2
#   cd boed && sbatch train.sbatch vanilla   runs/two_bunch_full
# Both use 1M simulated trajectories; the original runs took ~6 h (bsa) and ~4 h (vanilla)
# on one turing GPU.
#SBATCH --job-name=ued-boed
#SBATCH --partition=turing
#SBATCH --account=mli:bax
#SBATCH --gpus=1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=30G
#SBATCH --time=24:00:00
#SBATCH --output=slurm-%x-%j.out
set -euo pipefail
source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh

VARIANT=${1:?usage: sbatch train.sbatch <bsa|vanilla> <out_dir>}
OUT_DIR=${2:?usage: sbatch train.sbatch <bsa|vanilla> <out_dir>}
cd "$SLURM_SUBMIT_DIR"   # boed/, so the scripts find their sibling modules
python "train_${VARIANT}.py" --out_dir "$OUT_DIR"
