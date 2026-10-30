"""What the two UED Badger environments do with the machine.

The plugins (plugins/environments/{ued_sim,ued}) are thin: Badger asks them
for knob values, sets knobs and reads observables, and they hand the call to
the functions here, which work on a ued_tuning backend (get/put/sleep):

  ued_sim  sim/virtual_ued.py, in one of two presets:
           stage5  after stage 5: gun at 0.53, on crest, collimator in,
                   sample out, Andor at its check settings;
           stage7  then at the Bi sample, the main beam steered into the
                   Andor through hole, the Andor at its diffraction settings.
           Its knobs persist between runs (one state file per preset), as a
           real machine's would; reset_sim_state() forgets them.
  ued      the real machine through EPICS. For the agent, ued_tuning's
           EpicsBackend: it reads through the CA settings and the PV prefix
           (pv_access) and refuses every write. In an operator's Badger
           started by scripts/badger_ued.sh (UED_BADGER_ALLOW_WRITES=1),
           live.LiveEpicsBackend, which writes the knobs and nothing else.

Every knob write is checked against the setup file's safety ranges first.
"""
from __future__ import annotations

import json
import math
import os
import sys

import numpy as np

from . import common

sys.path.insert(0, str(common.BRINGUP))
import ued_automation as auto  # noqa: E402

# The mock-up's state after stage 5 (sim/stages/mcp_mockup.py, 2026-10-21)
SIM_PRESET = {'pfb_enable': 1, 'afb_enable': 1, 'areq': 0.53,
              'preq': 151.81, 'gun_uv_throttle': 54.0, 'gun_uv_shutter': 1,
              'collimator': 90.29, 'cam_far_andor.exposure': 1.0,
              'cam_far_andor.gain': 2.0}
SIM_PRESETS = ('stage5', 'stage7')
STATE_CHANNELS = ('areq', 'aact', 'preq', 'gun_uv_throttle',
                  'gun_uv_shutter', 'collimator', 'diag_screen_state',
                  'sample_x', 'sample_y', 'cam_far_andor.exposure',
                  'cam_far_andor.gain')

_machines = {}


def machine(env_name, seed=0, preset='stage5'):
    """The backend behind an environment, made once per process."""
    key = (env_name, preset if env_name == 'ued_sim' else None)
    if key not in _machines:
        if env_name == 'ued_sim':
            m = _sim_machine(seed, preset)
        elif env_name == 'ued':
            if os.environ.get(common.ALLOW_WRITES_ENV) == '1':
                from .live import LiveEpicsBackend
                m = LiveEpicsBackend()
            else:
                from ued_tuning.epics_backend import EpicsBackend
                m = EpicsBackend()
        else:
            raise ValueError(f'unknown environment {env_name!r}')
        _machines[key] = m
    return _machines[key]


def _sim_machine(seed, preset):
    if preset not in SIM_PRESETS:
        raise ValueError(f'preset is one of {SIM_PRESETS}, not {preset!r}')
    sim_dir = os.environ.get('UED_SIM_DIR', str(common.REPO_SIM))
    sys.path.insert(0, sim_dir)
    from virtual_ued import VirtualUED
    m = VirtualUED(seed=seed)            # diag holder and sample out
    for name, value in SIM_PRESET.items():
        m.put(name, value)
    m.sleep(5.0)                         # AACT settles on AREQ
    if preset == 'stage7':
        from ued_tuning import stages
        setup = common.setup_for('ued_sim')
        rec = stages.Recorder(m, setup)
        auto.go_to(rec, setup, 'bi')
        hole = stages._into_through_hole(rec, setup)
        if not hole['in_hole']:
            raise RuntimeError('stage7 preset: main beam not in the Andor '
                               'through hole: ' + hole['why'])
        d = auto.need(setup, 'andor', 'diffraction')
        auto.andor_settings(rec, d['exposure'], d['gain'])
    for name, value in load_sim_state(preset).items():
        m.put(name, value)
    return m


def _state_file(preset='stage5'):
    if preset == 'stage5':
        return common.SIM_STATE
    return common.SIM_STATE.with_name(f'ued_sim_state_{preset}.json')


def load_sim_state(preset='stage5') -> dict:
    try:
        state = json.loads(_state_file(preset).read_text())
    except (OSError, ValueError):
        return {}
    return {k: float(v) for k, v in state.items() if k in common.KNOBS}


def save_sim_state(m, preset='stage5'):
    path = _state_file(preset)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(get_knobs(m, common.KNOBS), indent=1))
    os.replace(tmp, path)


def reset_sim_state() -> list:
    """Forget every preset's saved knobs; returns the files removed."""
    gone = []
    for preset in SIM_PRESETS:
        try:
            _state_file(preset).unlink()
            gone.append(preset)
        except FileNotFoundError:
            pass
    return gone


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


def frame_sum(m, nsigma=3.0) -> float:
    """Background-subtracted counts over the whole Andor frame, above
    nsigma robust sigmas of the background: the diffracted intensity when
    the main beam is in the through hole (procedure 7)."""
    if getattr(m, 'kind', '') == 'sim':
        b = 8                            # VirtualUED.image() bins 8 x 8
        img = np.asarray(m.image('cam_far_andor', binning=b), float) * b * b
    else:
        img = np.asarray(m.image('cam_far_andor'), float)
    bkg = float(np.median(img))
    noise = 1.4826 * float(np.median(np.abs(img - bkg))) or 1.0
    sig = img - bkg
    return float(sig[sig > nsigma * noise].sum())


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
    if 'andor_frame_sum' in names:
        full['andor_frame_sum'] = frame_sum(m)
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
