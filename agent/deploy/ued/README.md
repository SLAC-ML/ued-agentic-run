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

`.env.variant` picks the host profile: `profiles/ued-daq.yml` (direct Channel Access on the hutch network) or `profiles/s3df.yml` (the S3DF EPICS gateway). Since 2026-10-29 the deployment selects `s3df`: see "Running on S3DF" below.

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

## Running on S3DF

Since 2026-10-28 the experiment is meant to run from S3DF, not `ued-daq`. There the PVs come through the EPICS gateway `172.24.3.10:5110`. The accelerator-side PVs (gun RF, magnets, correctors, gate valves, diagnostic screen, scope) are served only under a prefix such as `UED:USER:`. The servers add it themselves when `UED_ACCEL_PV_PREFIX` is set (`bringup/pv_access.py`). On 2026-10-28 the hutch PVs answered from iana but the prefixed accelerator PVs didn't yet. See [bringup/README.md](../../../bringup/README.md#controls-environment-on-s3df).

The deployment was switched on 2026-10-29. The `ued-daq` versions of `.env` and `.env.variant` are kept beside them as `*.bak-20261029-ued-daq`. To switch either way (on iana, in the deployed copy):

1. Back up `.env` and `.env.variant`.
2. `echo OSPREY_PROFILE_VARIANT=s3df > .env.variant` (or `ued-daq`).
3. In `.env`, under the "Declared by this profile" banner, match the host profile's `env.defaults`. For S3DF that means `EPICS_CA_ADDR_LIST=172.24.3.10:5110` and `UED_ACCEL_PV_PREFIX=UED:USER:`, and no `HTTPS_PROXY`/`HTTP_PROXY`: `psproxy` isn't reachable from S3DF, and iana reaches the internet directly. Keep mode 600.
4. `build/.venv/bin/osprey build --skip-deps`.

Launch on iana the same way as on `ued-daq`, and tunnel to iana instead:

```bash
ssh iana
/sdf/group/mli/zhezhang/OspreyDeployments/UED/deploy/ued/launch_ued.sh web
# on the laptop:
ssh -N -o ControlPath=none -o ExitOnForwardFailure=yes -L 127.0.0.1:10102:127.0.0.1:10100 iana
```

The `iana` alias is one node, `sdfiana016`; the tunnel has to reach the node the agent runs on. That node is shared, so anyone logged in there can reach its `127.0.0.1:10100`: only the banner's token keeps them out, so don't paste the token URL anywhere.

## Models

The SLAC gateway's tiers (`api.providers.slac.models` in `profile.yml`) are Haiku 4.5, Sonnet 5, Opus 5.5 (since 2026-10-29; Opus 5 before) and Fable 5.1. The gateway reports a 1M-token input window for all of them except Haiku 4.5 (200k). Claude Code doesn't recognise the gateway's `us.anthropic.*` names and assumes 200k for them. So `claude_code.models` gives Claude Code the same names with `[1m]` appended. That suffix sets the 1M window, and Claude Code strips it before each request. Checked on 2026-10-29: an Opus subagent reported `us.anthropic.claude-opus-5-5[1m]` and answered through the gateway. The default model (`model:` in `profile.yml`) is still Haiku.

## Write safety: five layers

The agent never writes PVs, on `ued-daq` (which can reach every hutch IOC with write access) or through the S3DF gateway.

1. `control_system.writes_enabled: false`, and the controls write tool denied.
2. Deny rules: `Bash(caput *)`, `Bash(pvput *)`, `Bash(*caput*)`, `Bash(*pvput*)`. The default persona also denies `Bash` outright.
3. `hooks/ued_write_guard.py`, a `PreToolUse` gate on shell commands, file writes and edits, and Python execution. It refuses any EPICS put it finds and fails closed.
4. `deploy/ued/guard-bin`: refusing `caput`/`pvput` shims, first on `PATH`.
5. `OSPREY_EXECUTION_MODE=readonly`: Osprey's deployment-wide read-only run.

## Tools

Three MCP servers, all reusing `bringup/` from the ued-agentic-run repo, deployed at `/sdf/group/mli/zhezhang/ued/agentic/bringup`:

- `ued_beamline` (`mcp_servers/ued_beamline`) has two tools: `ued_devices`, the device map, and `ued_snapshot`, a live read with `caget` only.
- `ued_tuning` (`mcp_servers/ued_tuning_mcp`, a wrapper around `bringup/ued_tuning`) has the bring-up tools:
  - one per stage of the Run 7 proposal;
  - automation actions: positions, camera views, the pump shutter;
  - read-only checks and `plan_beam_optimization`.

  The wrapper forces the `epics` backend, which reads with `caget` and refuses every write before any EPICS call, so each tool that writes stops at its first write. Read-only tools run unprompted; every tool that writes asks first. The positions, setpoints and safety ranges come from `/sdf/group/mli/zhezhang/ued/agentic/config/ued_setup.yaml`. The simulator backend isn't offered here: rehearsals run on S3DF (`sim/stages/mcp_mockup.py`), not on the DAQ machine.
- `ued_badger` (`mcp_servers/ued_badger_mcp`, a wrapper around `bringup/ued_badger`) has the Badger routines for the optimization after the collimator. Its tools are `badger_info`, `draft_routine`, `list_routines`, `run_routine`, `poll_run`, `stop_run`, `run_result`, `list_runs` and `reset_sim`. Drafting validates a routine in Badger itself and reads where the machine is now. Runs are headless and budgeted, and only on the simulator (`ued_sim`). Routines for the real machine (`ued`) are checked read-only, and an operator runs them in Badger. The server never imports Badger: it calls the AgenticOpt venv (`UED_BADGER_PYTHON`) as subprocesses. `run_routine` and `reset_sim` ask; the rest run unprompted.

## Skills

`skills/` holds the UED skills; the build copies them into `build/.claude/skills/`:

- `ued-bringup`: the campaign, stage by stage, with the rules the tools keep and when to stop for an operator.
- `ued-positions`: taught positions, camera views and safety ranges in the setup file.
- `ued-beam-optimization`: the Badger/Xopt plan for the optimization after the collimator.
- `ued-badger`: drafting, rehearsing and reading back Badger routines with the `ued_badger` tools.

On `ued-daq`, the accelerator PVs (gun RF, magnets, correctors) answered with the address list `/cds/group/pcds/setup/ued_setup.sh` sets, `172.21.36.255:5064 172.27.99.255:5058`, from 2026-10-16. By 2026-10-28 the KY01 gun PVs no longer answered there. The `ued-daq` profile gives the agent both entries for reads. The `.env` on S3DF carries the same `EPICS_CA_ADDR_LIST` line, so change it there too, then rebuild and restart the agent.
