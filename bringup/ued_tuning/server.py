"""FastMCP server ``ued_tuning`` — UED bring-up stages as tools.

One tool per stage (stages.py), the automation actions (taught positions,
camera views, the pump shutter; bringup/ued_automation.py), and reads. The
machine behind them is chosen by UED_TUNING_BACKEND:

  sim    sim/virtual_ued.py (UED_SIM_DIR): GPT + analytic stand-ins. Writes
         go to the virtual machine. For rehearsing on S3DF.
  epics  the real machine, READ-ONLY: every write is refused, so a stage
         stops at its first write. Reads work where a PV is mapped.

Positions, camera views, setpoints and safety ranges come from the setup
file ($UED_SETUP_FILE; see ued_automation.setup_path), read fresh on every
call. Records (traces, images, settings) go to $UED_RECORDS_DIR.

The deployed UED agent runs it with the epics backend, through the wrapper
agent/mcp_servers/ued_tuning_mcp (registered 2026-10-16).
Launched over stdio by ``python -m ued_tuning`` (PYTHONPATH = bringup/).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
import time

from fastmcp import FastMCP

from . import stages
from .channels import CHANNELS

auto = stages.auto
BACKEND = os.environ.get('UED_TUNING_BACKEND', 'sim')
_machine = None
OPERATOR_ERRORS = (auto.SetupError, auto.SafetyError,
                   stages.OperatorActionNeeded)


def machine():
    global _machine
    if _machine is None:
        with contextlib.redirect_stdout(sys.stderr):
            if BACKEND == 'sim':
                sys.path.insert(0, os.environ.get(
                    'UED_SIM_DIR', '/sdf/group/mli/zhezhang/ued/agentic/sim'))
                from virtual_ued import VirtualUED
                _machine = VirtualUED(seed=int(os.environ.get('UED_SIM_SEED',
                                                              '0')))
            elif BACKEND == 'epics':
                from .epics_backend import EpicsBackend
                _machine = EpicsBackend()
            else:
                raise RuntimeError(f'unknown UED_TUNING_BACKEND {BACKEND!r}')
    return _machine


def _call(name, fn, **kwargs):
    """Run fn(machine, setup, **kwargs); a refusal or a missing setup value
    comes back as the result's reason, never as a crash."""
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            out = fn(machine(), auto.load_setup(), **kwargs)
    except Exception as exc:        # a refused write lands here on epics
        out = {'stage': name, 'ok': False, 'accepted': False,
               'reason': f'{type(exc).__name__}: {exc}',
               'needs_operator': isinstance(exc, OPERATOR_ERRORS)}
    out['backend'] = BACKEND
    out['wall_s'] = round(time.time() - t0, 1)
    return json.dumps(stages._num(out))


def _action(name, body):
    """An automation action through a Recorder, so its writes are checked
    against the safety ranges and logged like a stage's."""
    def fn(m, setup):
        rec = stages.Recorder(m, setup)
        data = body(rec, setup) or {}
        return stages._result(name, rec, True, True, 'done', **data)
    return _call(name, fn)


mcp = FastMCP(
    'ued_tuning',
    instructions=(
        'UED beamline bring-up. Stages, in order: gun_ramp, schottky_scan '
        '(emission-phase scan on the scope), set_bunch_charge (then hand '
        "over to Cameron's UV feedback loop), beam_on_screens, "
        'align_collimator (then plan_beam_optimization for Badger), '
        'overlap_pump_laser, tune_sample_position, find_time_zero. Each '
        'returns ok/accepted/reason, needs_operator with the steps an '
        'operator must take, its measurements, and every write with the PV '
        'behind it. Rules the tools keep: beam stages stop unless all four '
        'gate valves are OPEN; the pump shutter is closed first and after '
        'any step that opens it; every write is checked against the safety '
        'ranges in the setup file; positions come from the setup file '
        '(list_positions, go_to_position, save_position). The backend is '
        "named in every result: 'sim' is a virtual machine for rehearsal; "
        "'epics' is the real machine and refuses all writes. "
        'tune_sample_position always needs an operator to judge the '
        'pattern.'),
)


# ------------------------------------------------------------------ reads
@mcp.tool()
async def ued_tuning_info() -> str:
    """Which backend this server drives, its stages and tools, the setup
    file in use, and what that file still lacks (positions, setpoints)."""
    setup = auto.load_setup()
    return json.dumps({'backend': BACKEND, 'stages': list(stages.STAGES),
                       'setup_file': str(auto.setup_path()),
                       'setup_missing': auto.missing(setup),
                       'setup_problems': auto.validate(setup)})


@mcp.tool()
async def machine_channels(group: str = '') -> str:
    """The logical channels the stages use, with the real PV behind each.

    Args:
        group: Optional filter: gun_rf, vacuum, laser, magnets, beamline,
            diagnostics, sample, pump_probe, camera, correctors.
    """
    rows = [{'name': c.name, 'group': c.group, 'units': c.units,
             'writable': c.writable, 'pv': c.pv, 'status': c.status,
             'pv_units': c.pv_units, 'desc': c.desc}
            for c in CHANNELS.values() if not group or c.group == group]
    return json.dumps(rows)


@mcp.tool()
async def machine_read(names: list[str]) -> str:
    """Read logical channels (no writes). Unknown or unmapped names report
    their error instead of a value.

    `units` gives the unit of each value as returned. On the real machine
    (epics) that is the raw PV's unit, which can differ from the channel's
    logical unit: a corrector reads its BCTRL setpoint, not a kick in mrad.
    """
    out, units = {}, {}
    m = machine()
    for n in names:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                v = m.get(n)
            out[n] = stages._num(v)
        except Exception as exc:
            out[n] = {'error': f'{type(exc).__name__}: {exc}'}
        ch = CHANNELS.get(n)
        if ch is not None:
            units[n] = (ch.pv_units or ch.units) if BACKEND == 'epics' \
                else ch.units
    return json.dumps({'backend': BACKEND, 'values': out, 'units': units})


@mcp.tool()
async def check_beam_prerequisites() -> str:
    """Read-only pre-data checklist: can the e-beam reach the screens (the
    four gate valves, all OPEN), plus the ePix valve, both shutters, the
    pump power meter (a warning if it is IN), the collimator, and the setup
    entries still missing. Relay every warning to the operator."""
    def fn(m, setup):
        r = auto.readiness(m, setup)
        ok = r['beam_allowed']
        return {'stage': 'beam prerequisites', 'ok': True, 'accepted': ok,
                'reason': 'all gate valves OPEN' if ok else
                'gate valves not all OPEN',
                **r, 'collimator_mm': m.get('collimator'),
                'setup_missing': auto.missing(setup),
                'setup_problems': auto.validate(setup)}
    return _call('beam prerequisites', fn)


@mcp.tool()
async def scope_charge(n: int = 3) -> str:
    """Read-only: the bunch charge on the scope (the channel in the setup
    file, CH2 by default): the dip below the trace baseline in mV (via the
    V/div setting) and in fC (-1.7 mV = 10 fC), averaged over n traces."""
    def fn(m, setup):
        q = stages.scope_charge(m, setup, n)
        q.pop('trace')
        return {'stage': 'scope charge', 'ok': True, **q}
    return _call('scope charge', fn)


@mcp.tool()
async def monitor_charge(samples: int = 10, interval_s: float = 1.0) -> str:
    """Read-only: scope charge and UV throttle over time, e.g. to watch
    Cameron's UV feedback loop hold the charge after set_bunch_charge."""
    return _call('monitor charge', stages.monitor_charge, samples=samples,
                 interval_s=interval_s)


@mcp.tool()
async def measure_andor_spot(n: int = 3) -> str:
    """Read-only: the beam spot on the Andor (size, counts, offset from the
    image centre), the objective of the beam optimization."""
    return _call('andor spot', stages.measure_andor_spot, n=n)


@mcp.tool()
async def plan_beam_optimization(span_fraction: float = 0.1,
                                 include_xc04: bool = True,
                                 min_total_fraction: float = 0.8,
                                 multi_objective: bool = False) -> str:
    """Read-only: an Xopt/Badger VOCS for the co-tuning after the
    collimator: minimize the Andor spot size with Sol1, Sol2, XC/YC00-02
    (XC/YC04 keep the beam near the Andor centre), keeping the transmitted
    counts above min_total_fraction of now; with multi_objective, maximize
    the counts as a second objective instead. For an operator to run in
    Badger; nothing is written."""
    return _call('beam optimization plan', stages.plan_beam_optimization,
                 span_fraction=span_fraction, include_xc04=include_xc04,
                 min_total_fraction=min_total_fraction,
                 multi_objective=multi_objective)


@mcp.tool()
async def list_positions() -> str:
    """Read-only: the taught sample-stage positions in the setup file, and
    where the stage is now."""
    def fn(m, setup):
        return {'stage': 'positions', 'ok': True,
                'positions': setup.get('positions') or {},
                'now': auto.current_position(m),
                'setup_file': str(auto.setup_path())}
    return _call('positions', fn)


# ------------------------------------------------------ automation actions
@mcp.tool()
async def go_to_position(name: str) -> str:
    """Move the sample stage to a taught position (yag, andor, bi, si, ...;
    "go2YAG" etc. of the old scripts): pump shutter closed first, every
    axis checked against its safety range, readback verified."""
    return _action(f'go to {name}',
                   lambda rec, setup: {'position': auto.go_to(rec, setup,
                                                               name)})


@mcp.tool()
async def save_position(name: str, note: str = '') -> str:
    """Teach a position: read the sample stage (x, y, z) and
    write it as positions.<name> in the setup file (backup kept, change
    logged). Ask an operator before overwriting a taught position."""
    def fn(m, setup):
        here = auto.current_position(m)
        path = auto.save_position(name, here, note=note)
        return {'stage': f'save {name}', 'ok': True, 'accepted': True,
                'reason': f'saved to {path}', 'position': here,
                'old': (setup.get('positions') or {}).get(name)}
    return _call(f'save {name}', fn)


@mcp.tool()
async def set_camera_view(view: str) -> str:
    """Sample chamber camera and chamber light: full_view (state 1:
    exposure 0.1, gain 0, light on), ebeam (state 2) or laser (state 3),
    as the setup file defines them."""
    return _action(f'view {view}',
                   lambda rec, setup: auto.set_view(rec, setup, view))


@mcp.tool()
async def close_pump_shutter() -> str:
    """Close the pump-laser shutter (the safe state)."""
    return _action('close pump shutter',
                   lambda rec, setup: auto.close_pump_shutter(rec))


@mcp.tool()
async def check_overlap(tolerance_px: float = 3.0) -> str:
    """The e-beam and the pump laser against the YAG cross, without
    steering (procedure 8, step 2). Opens the pump shutter at the
    minimum-energy setpoint, closes it again."""
    return _call('overlap check', stages.check_overlap,
                 tolerance_px=tolerance_px)


# ----------------------------------------------------------------- stages
@mcp.tool()
async def gun_ramp(target: float = 0.53, n_steps: int | None = None,
                   dwell_s: float | None = None) -> str:
    """Stage 1: ramp the gun amplitude setpoint AREQ (KY03, TS8) from 0.05 to
    target, holding while the gun body temperature is outside its window
    (gun.ramp_temp_min_C..ramp_temp_max_C in the setup file, 33-36 C) and
    aborting to AREQ = 0 on a temperature run-away, a feedback trip, or an
    amplitude readback that stops tracking. Leave n_steps and dwell_s unset:
    they come from gun.ramp_n_steps / gun.ramp_dwell_s in the setup file
    (600 x 2 s = 20 min, for the reduced cooling-water flow). Pass them only
    if the operator asks for a different ramp."""
    return _call('gun_ramp', stages.gun_ramp, target=target, n_steps=n_steps,
                 dwell_s=dwell_s)


@mcp.tool()
async def schottky_scan(coarse_step_deg: float = 5.0,
                        fine_step_deg: float = 0.5,
                        phase_offset_deg: float | None = None,
                        throttle_deg: float | None = None,
                        diag_screen_by_operator: bool = False) -> str:
    """Stage 2: diagnostic screen in (collimator at zero), e-beam check on
    its camera with the gun UV toggled, then the emission-phase scan on the
    scope with the UV throttle at ~51: PREQ = emission + 30 deg. Saves
    throttle, phase, screen image and trace as a record.

    Args:
        diag_screen_by_operator: the diagnostic screen has no PV; set true
            once an operator has inserted it.
    """
    return _call('schottky_scan', stages.schottky_scan,
                 coarse_step=coarse_step_deg, fine_step=fine_step_deg,
                 phase_offset=phase_offset_deg, throttle=throttle_deg,
                 diag_screen_by_operator=diag_screen_by_operator)


@mcp.tool()
async def set_bunch_charge(feedback_loop_off: bool = False,
                           target_fC: float | None = None,
                           tolerance: float = 0.1,
                           fine_tune: bool = True,
                           diag_screen_by_operator: bool = False) -> str:
    """Stage 3: UV throttle to ~53, fine-tune onto the target charge on the
    scope (10 fC = -1.7 mV), record, then hand over to Cameron's UV
    feedback loop (steps in `handoff`).

    Args:
        feedback_loop_off: an operator confirms Cameron's loop is stopped.
            It drives the same throttle, so without this nothing is written.
    """
    return _call('set_bunch_charge', stages.set_bunch_charge,
                 feedback_loop_off=feedback_loop_off, target_fC=target_fC,
                 tolerance=tolerance, fine_tune=fine_tune,
                 diag_screen_by_operator=diag_screen_by_operator)


@mcp.tool()
async def beam_on_screens(diag_screen_by_operator: bool = False) -> str:
    """Stage 4: diagnostic screen out; go to the YAG, light off, e-beam
    view, gun UV toggled; move the cross onto the beam if it is near
    (escalate if far); full view. Then go to the Andor position, Andor
    exposure 1 s, gain 2, and check the beam (escalate if not seen)."""
    return _call('beam_on_screens', stages.beam_on_screens,
                 diag_screen_by_operator=diag_screen_by_operator)


@mcp.tool()
async def align_collimator(step_mm: float = 0.1,
                           fine_step_mm: float = 0.02) -> str:
    """Stage 5: with the beam on the Andor, insert the collimator to its
    nominal 90 mm (200 um hole) and tune its motor for the most counts.
    The beam optimization that follows is plan_beam_optimization."""
    return _call('align_collimator', stages.align_collimator,
                 step_mm=step_mm, fine_step_mm=fine_step_mm)


@mcp.tool()
async def overlap_pump_laser(step_mm: float = 0.2,
                             tolerance_px: float = 3.0) -> str:
    """Stage 6: the e-beam on the YAG cross as in stage 4, then the pump
    laser (laser view, minimum-energy HWP setpoint, power meter out) steered
    with the pump mirror/lens H and V onto the cross. The pump shutter is
    closed at the end; full view."""
    return _call('overlap_pump_laser', stages.overlap_pump_laser,
                 step_mm=step_mm, tolerance_px=tolerance_px)


@mcp.tool()
async def tune_sample_position(sample: str = 'bi', span_mm: float = 0.15,
                               points: int = 7,
                               single_crystal: bool = False) -> str:
    """Stage 7: full view, go to the sample, steer XC/YC04 so the main beam
    goes through the Andor through hole, Andor exposure 2 s / gain 1000,
    raster x, y (pitch and yaw are set by hand) for the pattern, save
    a record with the images and settings. Always needs an operator to
    judge the pattern and save the position."""
    return _call('tune_sample_position', stages.tune_sample_position,
                 sample=sample, span_mm=span_mm, points=points,
                 single_crystal=single_crystal)


@mcp.tool()
async def find_time_zero(sample: str = 'bi', center_mm: float | None = None,
                         coarse_span_mm: float = 3.0,
                         fine_span_mm: float = 0.3) -> str:
    """Stage 8: verify the overlap on the YAG, go to the sample, pump HWP
    to its ~2 uJ setpoint, open the pump shutter, scan the delay and fit
    the Bragg-peak drop (a stand-in for the LCLS DAQ / BOED scan), close
    the shutter."""
    return _call('find_time_zero', stages.find_time_zero, sample=sample,
                 center_mm=center_mm, coarse_span_mm=coarse_span_mm,
                 fine_span_mm=fine_span_mm)


if BACKEND == 'sim':
    @mcp.tool()
    async def sim_truth() -> str:
        """SIM ONLY: the virtual machine's hidden truth and how far the
        current state is from ideal. Not available on the real machine."""
        with contextlib.redirect_stdout(sys.stderr):
            return json.dumps(stages._num(machine().report_truth()))
