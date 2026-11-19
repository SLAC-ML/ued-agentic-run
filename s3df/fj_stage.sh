#!/usr/bin/env bash
# =============================================================================
#  fj_stage.sh — run any ued_tuning bring-up stage on ued-daq from your own
#  clone, with your own setup file and records folder (nothing is written to
#  /sdf/group/mli/zhezhang).
#
#      fj_stage.sh snapshot                      # read-only beamline table, saved too
#      fj_stage.sh diff                          # what changed between the last two snapshots
#      fj_stage.sh edit                          # open the setup file
#      fj_stage.sh gun_ramp                      # dry run (default)
#      fj_stage.sh --write gun_ramp              # for real: ued-daq only, asks first
#      fj_stage.sh schottky_scan diag_screen_by_operator=true
#      fj_stage.sh last                          # newest run folders (result.json, plot.png)
#      fj_stage.sh plot RUN_FOLDER               # redraw plot.png
#
#  Paths (override by exporting them first):
#    UED_WORK   config/ and records/ live here
#               default /sdf/home/f/fuhaoji/UEDagentic/agentic_run
#    UED_PY     Python with numpy, scipy, pyyaml, pyepics
#               default: the AgenticOpt venv (read access is enough)
# =============================================================================
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${UED_WORK:-/sdf/home/f/fuhaoji/UEDagentic/agentic_run}"
PY="${UED_PY:-/sdf/group/mli/zhezhang/AgenticOpt/.venv/bin/python}"

export UED_SETUP_FILE="$WORK/config/ued_setup.yaml"
export UED_RECORDS_DIR="$WORK/records"
export UED_BRINGUP_DIR="$REPO/bringup" UED_BOED_DIR="$REPO/boed"
[[ -f "$UED_SETUP_FILE" ]] || {
    echo "fj_stage: no setup file at $UED_SETUP_FILE" >&2
    echo "  cp /sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml $WORK/config/" >&2
    exit 1; }
mkdir -p "$UED_RECORDS_DIR"
SNAPS="$WORK/snapshots"
[[ -x "$PY" ]] || { echo "fj_stage: no Python at $PY (set UED_PY)" >&2; exit 1; }

unset PYTHONPATH                     # ued-daq's DAQ setup_env.sh exports one
if [[ "$(hostname -s)" == ued-daq ]]; then
    export EPICS_CA_ADDR_LIST="${EPICS_CA_ADDR_LIST:-172.21.36.255:5064 172.27.99.255:5058}"
    export EPICS_CA_AUTO_ADDR_LIST=NO
    unset UED_ACCEL_PV_PREFIX
else
    echo "fj_stage: not on ued-daq ($(hostname -s)): gateway, read-only" >&2
    source "$REPO/s3df/epics_env.sh"
fi
export EPICS_CA_MAX_ARRAY_BYTES="${EPICS_CA_MAX_ARRAY_BYTES:-50000000}"

echo "setup   $UED_SETUP_FILE"
echo "records $UED_RECORDS_DIR"
case "${1:-}" in
    snapshot)  shift; mkdir -p "$SNAPS"       # printed and saved
               out="$SNAPS/$(date +%Y%m%d_%H%M%S).txt"
               "$PY" "$REPO/bringup/snapshot.py" "$@" | tee "$out"
               echo "saved   $out"
               "$PY" "$REPO/bringup/fj_snapshot_images.py" "${out%.txt}" \
                   || echo "  (camera images not saved)"
               exit 0 ;;
    diff)      new=$(ls -t "$SNAPS"/*.txt 2>/dev/null | sed -n 1p || true)
               old=$(ls -t "$SNAPS"/*.txt 2>/dev/null | sed -n 2p || true)
               [[ -n "$old" ]] || { echo "fj_stage: need two saved snapshots in $SNAPS" >&2; exit 1; }
               echo "< $(basename "$old")   > $(basename "$new")"
               diff <(grep -v '^UED snapshot' "$old") <(grep -v '^UED snapshot' "$new") \
                   && echo "no change"; exit 0 ;;
    edit)      exec "${EDITOR:-vi}" "$UED_SETUP_FILE" ;;
    positions) shift; exec "$PY" "$REPO/bringup/positions.py" "$@" ;;
    plot)      shift; exec "$PY" "$REPO/bringup/fj_plot.py" "$@" ;;   # redraw a run folder
    last)      ls -dt "$UED_RECORDS_DIR"/*/ | head -"${2:-5}"; exit 0 ;;
    "") sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
esac
cd "$REPO/bringup"
exec "$PY" "$REPO/bringup/fj_run_stage.py" "$@"
