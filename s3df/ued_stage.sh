#!/usr/bin/env bash
# =============================================================================
#  ued_stage.sh — run a ued_tuning bring-up stage on ued-daq, for an operator.
#
#      ued_stage.sh find_time_zero method=boed                 # dry run
#      ued_stage.sh find_time_zero method=boed n_points=20     # shorter dry run
#      ued_stage.sh --write find_time_zero method=boed         # for real
#      ued_stage.sh --write find_time_zero method=grid center_mm=200
#      ued_stage.sh --write find_time_zero method=eig            # the fallback
#
#  The same stage code the agent's tools run (bringup/ued_tuning), with
#  bringup/run_stage.py as the backend:
#   - dry run (default): every write logged, none sent; reads are real;
#     waits cut to a tenth. Run it first: it shows every channel the stage
#     would write, in records/operator_writes.jsonl.
#   - --write (ued-daq only): writes only the channels this stage may write,
#     each inside the safety ranges of config/ued_setup.yaml, each logged.
#  Stage 8 (find_time_zero) is the stage it runs for now. Its record folder
#  (live.jsonl, live.png) is named in the first progress line.
# =============================================================================
set -euo pipefail
A=/sdf/group/mli/zhezhang/ued/agentic
PY=/sdf/group/mli/zhezhang/AgenticOpt/.venv/bin/python   # numpy, scipy, pyepics, torch

flag=()
if [[ "${1:-}" == --write ]]; then
    if [[ "$(hostname -s)" != ued-daq ]]; then
        echo "ued_stage: --write only on ued-daq (this is $(hostname -s))" >&2
        exit 2
    fi
    flag=(--write); shift
fi

unset PYTHONPATH                     # ued-daq's DAQ setup_env.sh exports one
if [[ "$(hostname -s)" == ued-daq ]]; then
    export EPICS_CA_ADDR_LIST="${EPICS_CA_ADDR_LIST:-172.21.36.255:5064 172.27.99.255:5058}"
    export EPICS_CA_AUTO_ADDR_LIST=NO
    unset UED_ACCEL_PV_PREFIX
else
    source "$A/scripts/epics_env.sh"
fi
export EPICS_CA_MAX_ARRAY_BYTES="${EPICS_CA_MAX_ARRAY_BYTES:-50000000}"
export UED_BRINGUP_DIR=$A/bringup UED_BOED_DIR=$A/boed

exec "$PY" "$A/bringup/run_stage.py" "${flag[@]}" "$@"
