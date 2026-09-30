#!/bin/bash
# Linux port of UED_May2025/run_gpt.bat (10 fC, 1.6-cell gun, 3.1 MeV).
# Run from a directory holding UED_beamline.in + its field maps:
#   run_gpt.sh [NCPU]        NCPU defaults to $SLURM_CPUS_PER_TASK, else 16
set -euo pipefail
NCPU=${1:-${SLURM_CPUS_PER_TASK:-16}}
source /sdf/group/mli/zhezhang/ued/agentic/scripts/env.sh

echo "host=$(hostname)  ncpu=$NCPU  gpt=$(command -v gpt)  cwd=$PWD"
time gpt -v -j "$NCPU" -o UED_10fC_1p6cell_3p1MeV.gdf UED_beamline.in

time gdfa -o UED_stat_10fC_1p6cell_3p1MeV.gdf UED_10fC_1p6cell_3p1MeV.gdf position \
    dt_50 stdx stdy stdz stdt avgt avgG avgz nemirrms stdG Q

# gdftrans -o traj.gdf UED_beamline_result.gdf time x y z Bx By Bz
