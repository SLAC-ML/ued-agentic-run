"""FastMCP server ``ued_tuning`` — UED bring-up stages as tools.

One tool per stage (stages.py), plus reads. The machine behind them is
chosen by UED_TUNING_BACKEND:

  sim    sim/virtual_ued.py (UED_SIM_DIR): GPT + analytic stand-ins. Writes
         go to the virtual machine. For rehearsing on S3DF.
  epics  the real machine, READ-ONLY: every write is refused, so a stage
         stops at its first write. Reads work where a PV is mapped.

Not registered in the deployed agent yet; see the mock-up report.
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

BACKEND = os.environ.get('UED_TUNING_BACKEND', 'sim')
_machine = None


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


def _run(name, **kwargs):
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            out = stages.STAGES[name](machine(), **kwargs)
    except Exception as exc:        # a refused write lands here on epics
        out = {'stage': name, 'ok': False, 'accepted': False,
               'reason': f'{type(exc).__name__}: {exc}'}
    out['backend'] = BACKEND
    out['wall_s'] = round(time.time() - t0, 1)
    return json.dumps(stages._num(out))


mcp = FastMCP(
    'ued_tuning',
    instructions=(
        'UED beamline bring-up, one tool per stage, in this order: gun_ramp, '
        'schottky_scan, set_bunch_charge, beam_on_screens, align_collimator, '
        'overlap_pump_laser, tune_sample_position, find_time_zero. Each '
        'returns ok/accepted/reason, its measurements, and every write it '
        'made with the PV behind it. The backend is named in every result: '
        "'sim' is a virtual machine for rehearsal; 'epics' is the real "
        'machine and refuses all writes. tune_sample_position always needs '
        'an operator to confirm the pattern.'),
)


@mcp.tool()
async def ued_tuning_info() -> str:
    """Which backend this server drives, and the stages it offers."""
    return json.dumps({'backend': BACKEND, 'stages': list(stages.STAGES)})


@mcp.tool()
async def machine_channels(group: str = '') -> str:
    """The logical channels the stages use, with the real PV behind each.

    Args:
        group: Optional filter: gun_rf, laser, magnets, beamline,
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
    their error instead of a value."""
    out = {}
    m = machine()
    for n in names:
        try:
            with contextlib.redirect_stdout(sys.stderr):
                v = m.get(n)
            out[n] = stages._num(v)
        except Exception as exc:
            out[n] = {'error': f'{type(exc).__name__}: {exc}'}
    return json.dumps({'backend': BACKEND, 'values': out})


@mcp.tool()
async def gun_ramp(target: float = 0.53, n_steps: int = 300,
                   dwell_s: float = 2.0) -> str:
    """Stage 1: ramp the gun amplitude setpoint AREQ from 0.05 to target,
    holding while the gun body temperature is outside 33-37 C and aborting
    to AREQ = 0 on a temperature run-away or a feedback trip."""
    return _run('gun_ramp', target=target, n_steps=n_steps, dwell_s=dwell_s)


@mcp.tool()
async def schottky_scan(coarse_step_deg: float = 10.0,
                        fine_step_deg: float = 1.0,
                        operating_offset_deg: float = 37.0) -> str:
    """Stage 2: scan the gun phase, find the zero crossing from the Faraday-
    cup charge, and set the phase to zero crossing + operating_offset_deg."""
    return _run('schottky_scan', coarse_step=coarse_step_deg,
                fine_step=fine_step_deg,
                operating_offset=operating_offset_deg)


@mcp.tool()
async def set_bunch_charge(target_fC: float = 10.0,
                           tolerance: float = 0.05) -> str:
    """Stage 3: steer the UV throttle until the Faraday-cup charge is within
    tolerance (fraction) of target_fC."""
    return _run('set_bunch_charge', target_fC=target_fC, tolerance=tolerance)


@mcp.tool()
async def beam_on_screens() -> str:
    """Stage 4: put the beam on the Diag YAG, then on the far detector
    (collimator out, then in); report position, size and saturation."""
    return _run('beam_on_screens')


@mcp.tool()
async def align_collimator(span_mrad: float = 1.5, points: int = 11,
                           sweeps: int = 2) -> str:
    """Stage 5: scan XC00/YC00 for the most charge through the collimator,
    then steer XC01/YC01 so the beam lands on the far-detector centre."""
    return _run('align_collimator', span=span_mrad, points=points,
                sweeps=sweeps)


@mcp.tool()
async def overlap_pump_laser(step_mm: float = 0.2,
                             tolerance_px: float = 3.0) -> str:
    """Stage 6: mark the e-beam on the sample YAG (and on the camera's
    cross overlay), then steer the pump lens (pump at lowest energy, power
    meter out, chamber light off) until the laser sits on the mark."""
    return _run('overlap_pump_laser', step_mm=step_mm,
                tolerance_px=tolerance_px)


@mcp.tool()
async def tune_sample_position(sample: str = 'bi', span_mm: float = 0.15,
                               points: int = 7) -> str:
    """Stage 7: raster the sample stage around its taught position for the
    best diffraction pattern. Always needs an operator to confirm."""
    return _run('tune_sample_position', sample=sample, span_mm=span_mm,
                points=points)


@mcp.tool()
async def find_time_zero(center_mm: float | None = None,
                         coarse_span_mm: float = 3.0,
                         fine_span_mm: float = 0.3) -> str:
    """Stage 8: scan the pump delay, fit the Bragg-peak drop, set t0."""
    return _run('find_time_zero', center_mm=center_mm,
                coarse_span_mm=coarse_span_mm, fine_span_mm=fine_span_mm)


if BACKEND == 'sim':
    @mcp.tool()
    async def sim_truth() -> str:
        """SIM ONLY: the virtual machine's hidden truth and how far the
        current state is from ideal. Not available on the real machine."""
        with contextlib.redirect_stdout(sys.stderr):
            return json.dumps(stages._num(machine().report_truth()))
