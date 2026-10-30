# EPICS Channel Access to the UED PVs from S3DF (iana), read-only.
#   source /sdf/group/mli/zhezhang/ued/agentic/scripts/epics_env.sh
#
# Puts S3DF's EPICS base (caget, cainfo, camonitor) on PATH and points
# Channel Access at the UED EPICS gateway. Hutch PVs (UED:*) answer under
# their own names; accelerator-side PVs (gun RF, magnets, ...) only under the
# UED:USER: prefix. `uedget` adds it for you:
#   caget  UED:USR:MMN:14:07                  # hutch: as is
#   caget  UED:USER:SIOC:AS01:KY03:0:AREQ     # accelerator: prefixed
#   uedget SIOC:AS01:KY03:0:AREQ UED:USR:MMN:14:07   # adds the prefix where needed
# The gateway grants read access only; never caput/pvput to UED PVs.

_EPICS_BASE=/sdf/sw/epics/base/7.0.3.1-1.0
_EPICS_ARCH="rhel$(. /etc/os-release; echo "${VERSION_ID%%.*}")-x86_64"
case ":$PATH:" in
    *":$_EPICS_BASE/bin/$_EPICS_ARCH:"*) ;;
    *) export PATH="$_EPICS_BASE/bin/$_EPICS_ARCH:$PATH" ;;
esac
unset _EPICS_BASE _EPICS_ARCH

export EPICS_CA_ADDR_LIST=172.24.3.10:5110
export EPICS_CA_AUTO_ADDR_LIST=NO
# Camera images are big arrays (GigE RGB: 3 x 2048 x 2048)
export EPICS_CA_MAX_ARRAY_BYTES=50000000
# The same prefix for the UED tools (bringup/pv_access.py)
export UED_ACCEL_PV_PREFIX=UED:USER:

# caget with UED:USER: added to every PV name that doesn't start with UED:
uedget() {
    local a=() x
    for x in "$@"; do
        if [[ "$x" == *:* && "$x" != UED:* && "$x" != -* ]]; then
            a+=("${UED_ACCEL_PV_PREFIX}$x")
        else
            a+=("$x")
        fi
    done
    caget "${a[@]}"
}
