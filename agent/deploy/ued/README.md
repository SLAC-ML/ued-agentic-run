# Running the UED deployment on ued-daq

Unlike LCLS, nothing is staged, rewritten or pushed. `ued-daq` mounts `/sdf/group` and `/sdf/home` read-write at the same paths, so the build on S3DF runs there as is. It runs as `zhezhang`.

## Where the source lives

The source is `agent/` in the ued-agentic-run repo; edit and commit there. `/sdf/group/mli/zhezhang/OspreyDeployments/UED` is the deployed copy. It has to stay at that path, because the build bakes it in. The host-local files (`.env`, `.env.variant`) and the generated ones (`build/`, `var/`) exist only there, never in git. To push a change, run this from the repo root on your laptop, then rebuild:

```bash
rsync -av --exclude='/.env' --exclude='/.env.variant' --exclude='/build/' --exclude='/var/' \
    agent/ iana:/sdf/group/mli/zhezhang/OspreyDeployments/UED/
```

There's no `--delete`, so a file removed from `agent/` also has to be removed by hand on S3DF. Never add `--delete` without those four excludes: it would wipe the key file and the build.

## Build (on iana)

```bash
cd /sdf/group/mli/zhezhang/OspreyDeployments/UED
/sdf/group/mli/zhezhang/OspreyDeployments/.venv-osprey/bin/osprey build   # first time: creates build/.venv
build/.venv/bin/osprey build --skip-deps                                  # after edits to profile.yml
```

`.env.variant` selects `profiles/ued-daq.yml`. `.env` (mode 600) holds `SLAC_API_KEY` and the host settings from that file. Osprey loads `.env` at launch, not the profile's `env.defaults`, so when you change one, change the other.

## Launch (on ued-daq)

```bash
L=/sdf/group/mli/zhezhang/OspreyDeployments/UED/deploy/ued/launch_ued.sh
$L chat --print ping     # one round trip through the SLAC gateway
$L health
$L web                   # web terminal on 127.0.0.1:10100
```

From a laptop, open the web terminal through the existing `ued-daq` SSH alias. The banner's token URL goes in the browser, with port 10100 changed to 10102:

```bash
ssh -N -o ControlPath=none -o ExitOnForwardFailure=yes -L 127.0.0.1:10102:127.0.0.1:10100 ued-daq
```

Two of these options matter:

- `ExitOnForwardFailure=yes` makes `ssh` stop with "cannot listen to port" when the local port is already taken. A plain `-L` only warns, binds whatever it still can (often just IPv6 `[::1]`), and leaves `http://127.0.0.1:10102` pointing at whoever got there first. The page then spins forever.
- `ControlPath=none` gives the tunnel its own connection. Otherwise the forward is added to the shared `ued-daq` master connection, and it outlives the `ssh` you started.

**VS Code is the usual culprit.** A VS Code window with a Remote-SSH session (for example on iana) forwards any `localhost:PORT` it sees printed in its terminals. That's how it took `127.0.0.1:10102` on 2026-10-08. To get the port back, stop that forward in the Ports view. To stop it happening, set `"remote.autoForwardPortsSource": "process"` in VS Code (or turn off `remote.autoForwardPorts`). `lsof -nP -iTCP:10102 -sTCP:LISTEN` shows who holds the port.

The launcher unsets the `PYTHONPATH` that `ued-daq`'s DAQ `setup_env.sh` exports. It also pins the Claude Code bundled with this build, ahead of the self-updating one in the shared `~/.local/bin`.

## One-time: trust the workspace

Claude Code ignores the build's `permissions.allow` entries until `build/` is trusted. Until then, even the read-only `ued_snapshot` tool can't run unattended. Run `$L web` (or `$L chat`) interactively once and accept the trust dialog. The alternative is to set `projects["/sdf/group/mli/zhezhang/OspreyDeployments/UED/build"].hasTrustDialogAccepted: true` in `~/.claude.json`.

## Network

| Route | Used for |
|---|---|
| Direct | The SLAC AI gateway, `ai-api.slac.stanford.edu` (in `NO_PROXY`) |
| `psproxy:3128` | Anything outside SLAC. Claude Code's optional traffic is switched off, so in practice little or nothing |
| `lcls-prod03:3128` | Not usable: it refuses `ued-daq` with `403` |

## Write safety: five layers

The agent never writes PVs on `ued-daq`, which can reach every hutch IOC with write access.

1. `control_system.writes_enabled: false`, and the controls write tool denied.
2. Deny rules: `Bash(caput *)`, `Bash(pvput *)`, `Bash(*caput*)`, `Bash(*pvput*)`. The default persona also denies `Bash` outright.
3. `hooks/ued_write_guard.py`, a `PreToolUse` gate on shell commands, file writes and edits, and Python execution. It refuses any EPICS put it finds and fails closed.
4. `deploy/ued/guard-bin`: refusing `caput`/`pvput` shims, first on `PATH`.
5. `OSPREY_EXECUTION_MODE=readonly`: Osprey's deployment-wide read-only run.

## Tools

`mcp_servers/ued_beamline` has two tools: `ued_devices`, the device map, and `ued_snapshot`, a live read with `caget` only. Both reuse `bringup/` from the ued-agentic-run repo, deployed at `/sdf/group/mli/zhezhang/ued/agentic/bringup`.

Accelerator PVs (gun RF, magnets, correctors) answer from `ued-daq` with the address list `/cds/group/pcds/setup/ued_setup.sh` sets, `172.21.36.255:5064 172.27.99.255:5058` (since 2026-10-16). The profile gives the agent both entries for reads. The `.env` on S3DF carries the same `EPICS_CA_ADDR_LIST` line, so change it there too, then rebuild and restart the agent.
