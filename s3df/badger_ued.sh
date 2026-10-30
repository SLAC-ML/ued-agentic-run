#!/usr/bin/env bash
# =============================================================================
#  badger_ued.sh — Badger for UED operators, run on ued-daq.
#
#      badger_ued.sh                              # the Badger GUI
#      badger_ued.sh run ROUTINE.yaml             # the GUI with a routine loaded
#      badger_ued.sh --dry-run run ROUTINE.yaml   # writes logged, not sent
#      badger_ued.sh --read-only run ROUTINE.yaml # no writes at all
#      badger_ued.sh env                          # list the UED environments
#
#  ROUTINE.yaml is typically one the agent drafted:
#  /sdf/group/mli/zhezhang/ued/agentic/badger/routines/<name>.yaml.
#  The GUI opens with it loaded; check the variable ranges against the
#  current values, then press Run. Nothing starts by itself.
#
#  What it sets up:
#   - Badger: the fork in the AgenticOpt venv on S3DF (Badger 1.5.5.dev, Xopt
#     3.1.2, PyQt5), which runs on ued-daq as is (/sdf is mounted there).
#   - Its settings: badger/gui/badger_settings.yaml, created on first use.
#     Plugins: bringup/ued_badger/plugins (environments `ued` and `ued_sim`).
#     Templates: badger/routines, where the agent saves its routines.
#     Archive: badger/archive, shared with the agent's simulator runs.
#   - PVs: direct Channel Access on ued-daq. Anywhere else, the S3DF gateway,
#     and read-only.
#   - Writes: on ued-daq the `ued` environment writes its knobs (solenoids,
#     correctors, sample x/y) and nothing else, inside the safety ranges of
#     config/ued_setup.yaml, and logs every write to badger/ued_writes.jsonl.
#     The agent's own tools never set UED_BADGER_ALLOW_WRITES.
# =============================================================================
set -euo pipefail
A=/sdf/group/mli/zhezhang/ued/agentic
VENV=/sdf/group/mli/zhezhang/AgenticOpt/.venv
ROOT=$A/badger
SETTINGS=$ROOT/gui/badger_settings.yaml

mode=write
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) mode=dry; shift ;;
        --read-only) mode=read; shift ;;
        *) break ;;
    esac
done

unset PYTHONPATH                     # ued-daq's DAQ setup_env.sh exports one
# GPT and its licence, for the ued_sim environment
source "$A/scripts/env.sh" >/dev/null 2>&1 || true
export UED_BRINGUP_DIR=$A/bringup UED_BADGER_ROOT=$ROOT UED_SIM_DIR=$A/sim

if [[ "$(hostname -s)" == ued-daq ]]; then
    export EPICS_CA_ADDR_LIST="${EPICS_CA_ADDR_LIST:-172.21.36.255:5064 172.27.99.255:5058}"
    export EPICS_CA_AUTO_ADDR_LIST=NO
    unset UED_ACCEL_PV_PREFIX
else
    source "$A/scripts/epics_env.sh"
    if [[ $mode != read ]]; then
        echo "badger_ued: not on ued-daq ($(hostname -s)): read-only" >&2
        mode=read
    fi
fi
export EPICS_CA_MAX_ARRAY_BYTES="${EPICS_CA_MAX_ARRAY_BYTES:-50000000}"

case $mode in
    write) export UED_BADGER_ALLOW_WRITES=1; unset UED_BADGER_DRY_RUN
           echo "badger_ued: WRITES ENABLED for the ued environment's knobs" \
                "(logged to $ROOT/ued_writes.jsonl)" >&2 ;;
    dry)   export UED_BADGER_ALLOW_WRITES=1 UED_BADGER_DRY_RUN=1
           echo "badger_ued: dry run: writes logged to" \
                "$ROOT/ued_writes.jsonl, not sent" >&2 ;;
    read)  unset UED_BADGER_ALLOW_WRITES UED_BADGER_DRY_RUN
           echo "badger_ued: read-only: every write is refused" >&2 ;;
esac

mkdir -p "$ROOT/gui/db" "$ROOT/gui/logbook" "$ROOT/gui/logs" \
         "$ROOT/routines" "$ROOT/archive"
if [[ ! -f $SETTINGS ]]; then
    entry() {  # key value name
        printf '%s:\n  value: %s\n  is_path: true\n  display_name: %s\n  description: UED Badger %s\n' \
            "$1" "$2" "$3" "$3"
    }
    {
        entry BADGER_PLUGIN_ROOT "$A/bringup/ued_badger/plugins" "plugin root"
        entry BADGER_TEMPLATE_ROOT "$ROOT/routines" "template root"
        entry BADGER_ARCHIVE_ROOT "$ROOT/archive" "archive root"
        entry BADGER_DB_ROOT "$ROOT/gui/db" "db root"
        entry BADGER_LOGBOOK_ROOT "$ROOT/gui/logbook" "logbook root"
        entry BADGER_LOG_DIRECTORY "$ROOT/gui/logs" "log directory"
    } > "$SETTINGS"
fi

# This Badger reads its settings as ~/.config/config.yaml at import, before
# -cf applies, and the shared home's copy is the LCLS one. So it gets a home
# of its own whose config.yaml is the UED settings file (the X11 cookie stays
# the real one, so the GUI still opens on this display).
GUI_HOME=$ROOT/gui/home
mkdir -p "$GUI_HOME/.config"
ln -sfn "$SETTINGS" "$GUI_HOME/.config/config.yaml"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export HOME=$GUI_HOME

cd "$ROOT"
if [[ $# -eq 0 ]]; then
    exec "$VENV/bin/badger" -cf "$SETTINGS" -g
fi
exec "$VENV/bin/badger" -cf "$SETTINGS" "$@"
