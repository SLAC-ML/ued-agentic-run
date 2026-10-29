#!/usr/bin/env bash
# =============================================================================
#  launch_ued.sh — run the UED OSPREY assistant on ued-daq or on S3DF (iana),
#  in place from S3DF.
#
#      launch_ued.sh                     # osprey web  (127.0.0.1:10100 by default)
#      launch_ued.sh chat --print ping   # one round trip through the SLAC gateway
#      launch_ued.sh health
#
#  Nothing is copied to ued-daq: it mounts /sdf read-write at the same paths,
#  so the build on S3DF runs as is. Build on iana (`osprey build`), launch here.
#  From a laptop, reach the web terminal with (see deploy/ued/README.md for why
#  the options matter: a plain -L can lose 127.0.0.1:10102 to VS Code silently)
#      ssh -N -o ControlPath=none -o ExitOnForwardFailure=yes \
#          -L 127.0.0.1:10102:127.0.0.1:10100 ued-daq   # then open the token URL on :10102
#
#  What the wrapper fixes (same lessons as LCLS/deploy/acr/launch_lcls.sh):
#   - ued-daq's DAQ environment (setup_env.sh) exports PYTHONPATH, which Python
#     puts ahead of the build venv's own packages. Unset.
#   - osprey's child environment prepends user-local bin dirs it finds off PATH
#     (~/.local/bin, ~/.cargo/bin, /usr/local/bin). The home here is the shared
#     S3DF home, so whatever claude lives in ~/.local/bin would shadow the one
#     this build bundles. They go at the TAIL, so osprey sees them "already on
#     PATH" and prepends nothing; the build venv goes first.
#   - deploy/ued/guard-bin goes before everything: refusing caput/pvput shims,
#     one of the four write-safety layers (see profile.yml).
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unset PYTHONPATH
cd "$ROOT"

[[ -x build/.venv/bin/osprey ]] || { echo "no build at $ROOT/build — run \`osprey build\` on iana first" >&2; exit 1; }
if ! grep -q '^SLAC_API_KEY=..*' .env 2>/dev/null; then
  echo "SLAC_API_KEY is missing or blank in $ROOT/.env — fill it (mode 600) first" >&2; exit 1
fi
# The host profile must match the host: ued-daq (direct CA on the hutch
# network) or s3df (the EPICS gateway, since 2026-10-28).
variant="$(sed -n 's/^OSPREY_PROFILE_VARIANT=//p' .env.variant 2>/dev/null)"
case "$(hostname -s):$variant" in
  ued-daq:ued-daq | *:s3df) ;;
  ued-daq:*) echo "warning: on ued-daq, but .env.variant selects '${variant:-nothing}', not ued-daq" >&2 ;;
  *) echo "warning: on $(hostname -s), .env.variant selects '${variant:-nothing}': here the UED PVs answer only through the S3DF gateway (variant s3df)" >&2 ;;
esac

# The Claude Code CLI this build bundles (the one `osprey chat` and the subagents use).
CLAUDE_BIN="$ROOT/build/.venv/bin/claude"
if [[ ! -x "$CLAUDE_BIN" ]]; then
  CLAUDE_BIN=$(ls "$ROOT"/build/.venv/lib/python3*/site-packages/claude_agent_sdk/_bundled/claude 2>/dev/null | head -1)
fi

# The bundled CLI's own directory goes right after the shims: this build has no
# build/.venv/bin/claude, and the shared home's ~/.local/bin holds a personal,
# self-updating Claude Code that `osprey chat` would otherwise find.
CLAUDE_DIR=""; [[ -n "$CLAUDE_BIN" ]] && CLAUDE_DIR="$(dirname "$CLAUDE_BIN"):"
export PATH="$ROOT/deploy/ued/guard-bin:$CLAUDE_DIR$ROOT/build/.venv/bin:$PATH:$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin"

cmd=("${@:-web}")
# The web terminal spawns whatever `claude` osprey's shell resolver finds; pin it to
# the bundled CLI. An explicit --shell wins.
if [[ "${cmd[0]}" == "web" && -n "$CLAUDE_BIN" ]] && [[ " ${cmd[*]} " != *" --shell "* ]]; then
  cmd+=(--shell "$CLAUDE_BIN")
fi
exec build/.venv/bin/osprey "${cmd[@]}"
