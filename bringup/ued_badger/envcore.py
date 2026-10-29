"""What the two UED Badger environments do with the machine.

The plugins (plugins/environments/{ued_sim,ued}) are thin: Badger asks them
for knob values, sets knobs and reads observables, and they hand the call to
the functions here, which work on a ued_tuning backend (get/put/sleep):

  ued_sim  sim/virtual_ued.py, put in the state after stage 5 (gun at
           0.53, on crest, collimator in, sample out, Andor at its check
           settings). Its knobs persist between runs in SIM_STATE, as a
           real machine's would; reset_sim_state() forgets them.
  ued      ued_tuning's EpicsBackend: reads through the CA settings and the
           PV prefix (pv_access), and refuses every write.

Every knob write is checked against the setup file's safety ranges first.
"""
from __future__ import annotations

import json
import math
import os
import sys

from . import common

sys.path.insert(0, str(common.BRINGUP))
import ued_automation as auto  # noqa: E402

# The mock-up's state after stage 5 (sim/stages/mcp_mockup.py, 2026-10-21)
SIM_PRESET = {'pfb_enable': 1, 'afb_enable': 1, 'areq': 0.53,
              'preq': 151.81, 'gun_uv_throttle': 54.0, 'gun_uv_shutter': 1,
              'collimator': 90.29, 'cam_far_andor.exposure': 1.0,
              'cam_far_andor.gain': 2.0}
STATE_CHANNELS = ('areq', 'aact', 'preq', 'gun_uv_throttle',
                  'gun_uv_shutter', 'collimator', 'diag_screen_state',
                  'cam_far_andor.exposure', 'cam_far_andor.gain')

_machines = {}


def machine(env_name, seed=0):
    """The backend behind an environment, made once per process."""
    if env_name not in _machines:
        if env_name == 'ued_sim':
            sim_dir = os.environ.get('UED_SIM_DIR', str(common.REPO_SIM))
            sys.path.insert(0, sim_dir)
            from virtual_ued import VirtualUED
            m = VirtualUED(seed=seed)        # diag holder and sample out
            for name, value in SIM_PRESET.items():
                m.put(name, value)
            m.sleep(5.0)                     # AACT settles on AREQ
            for name, value in load_sim_state().items():
                m.put(name, value)
        elif env_name == 'ued':
            from ued_tuning.epics_backend import EpicsBackend
            m = EpicsBackend()
        else:
            raise ValueError(f'unknown environment {env_name!r}')
        _machines[env_name] = m
    return _machines[env_name]


def load_sim_state() -> dict:
    try:
        state = json.loads(common.SIM_STATE.read_text())
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in state.items() if k in common.KNOBS}


def save_sim_state(m):
    common.SIM_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = common.SIM_STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(get_knobs(m, common.KNOBS), indent=1))
    os.replace(tmp, common.SIM_STATE)


def reset_sim_state() -> bool:
    try:
        common.SIM_STATE.unlink()
        return True
    except FileNotFoundError:
        return False


def get_knobs(m, names) -> dict:
    return {n: float(m.get(n)) for n in names}


def set_knobs(m, env_name, values, settle_s=1.0):
    """Check every value against its safety range, then write them all and
    wait for the beam to settle."""
    setup = common.setup_for(env_name)
    for n, v in values.items():
        if n not in common.KNOBS:
            raise KeyError(f'{n} is not a knob of {env_name}')
        auto.check_limits(setup, n, v)
    for n, v in values.items():
        m.put(n, float(v))
    m.sleep(settle_s)


def observe(m, names, n_avg=3) -> dict:
    """The Andor observables (NaN size and offset when no beam is seen)."""
    from ued_tuning import stages
    s = stages.measure_andor_spot(m, None, n=n_avg)
    a = s['andor']

    def f(v):
        return float('nan') if v is None else float(v)
    full = {'andor_spot_size_px': f(s['spot_size_px']),
            'andor_total': f(s['total']),
            'andor_offset_from_centre_px': f(s['offset_from_centre_px']),
            'andor_sigma_x_px': f(a['sigma_x']),
            'andor_sigma_y_px': f(a['sigma_y']),
            'andor_saturated': float(bool(a['saturated']))}
    return {n: full[n] for n in names}


def states(m) -> dict:
    """The settings around the knobs, archived with each run."""
    out = {}
    for n in STATE_CHANNELS:
        try:
            v = m.get(n)
            out[n] = v if isinstance(v, str) else round(float(v), 4)
        except Exception as exc:                  # unreadable: say so
            out[n] = f'unreadable: {exc}'
    return out


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)
