"""UED automation: taught positions, camera views, laser safety, safety ranges.

The updated version of Fuhao Ji's run-4 automation scripts (run4_basics.py
and run4_utilities.py: goToYAG, goToBi, goToAndor1, saveYAG, checkEbeam,
spatialOverlap, ...), reworked per his notes of 2026-10:

  a. PVs follow the run-7 list. This module names no PV: it talks to a
     backend (get/put/sleep) through the logical channels of
     ued_tuning/channels.py, so it drives the virtual UED and, read-only,
     the real machine.
  b. Positions, camera views, setpoints and safety ranges live in one
     editable YAML file, ued_setup.yaml, shared by the agent and operators.
  c. The ued_tuning stages move the sample stage through go_to(), never by
     writing the motor channels themselves.
  d. Every write is checked against the safety ranges first
     (check_limits; ued_tuning's Recorder calls it on every put).

And as in run 4, the pump-laser shutter is closed before any move: an
unplanned shot at high energy (after an energy measurement, or a
pump-probe run at high fluence) can damage the sample.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
SEED = HERE / 'ued_setup.yaml'
LIVE_DEFAULT = Path('/sdf/group/mli/zhezhang/ued/agentic/config/'
                    'ued_setup.yaml')
RECORDS_DEFAULT = Path('/sdf/group/mli/zhezhang/ued/agentic/records')
AXES = ('x', 'y', 'z', 'pitch', 'yaw')
GATE_VALVES = ('gv240', 'gv272', 'gv280', 'gv295')
PUMP_LEVELS = {'min_energy': 'hwp_min_energy_deg',
               'pump_probe': 'hwp_pump_probe_deg'}


class SetupError(RuntimeError):
    """The setup file lacks a value this step needs (not taught yet)."""


class SafetyError(RuntimeError):
    """A write outside its safety range; refused before it is made."""


# ------------------------------------------------------------- the file
def setup_path() -> Path:
    """$UED_SETUP_FILE, else the live copy on S3DF, else the repo seed."""
    p = os.environ.get('UED_SETUP_FILE')
    if p:
        return Path(p)
    return LIVE_DEFAULT if LIVE_DEFAULT.exists() else SEED


def load_setup(path=None) -> dict:
    with open(path or setup_path()) as f:
        return yaml.safe_load(f) or {}


def need(setup, *keys):
    """setup[k1][k2]..., or SetupError naming the missing key."""
    v = setup
    for k in keys:
        v = v.get(k) if isinstance(v, dict) else None
        if v is None:
            raise SetupError(
                f"{'.'.join(keys)} is not set in {setup_path()}. Teach it "
                '(save_position for a stage position) or ask an operator '
                'for the value.')
    return v


def check_limits(setup, name, value):
    """Refuse a value outside the channel's safety range, if it has one."""
    lim = (setup.get('limits') or {}).get(name)
    if lim is None or isinstance(value, str):
        return
    lo, hi = float(lim[0]), float(lim[1])
    if not lo <= float(value) <= hi:
        raise SafetyError(f'{name} = {value} is outside its safety range '
                          f'[{lo:g}, {hi:g}] in {setup_path()}')


def missing(setup) -> list:
    """The setup entries that are still null (positions, setpoints)."""
    out = [f'positions.{k}' for k, v in (setup.get('positions') or {}).items()
           if v is None]
    for sect in ('andor', 'pump'):
        out += [f'{sect}.{k}' for k, v in (setup.get(sect) or {}).items()
                if v is None]
    return out


def save_position(name, coords, note='', path=None) -> Path:
    """Write positions.<name> as one line, keeping the rest of the file
    (comments included) as it is. Keeps the previous file as .bak and
    appends the change to ued_setup.history.log beside it."""
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError(f'position names are lower_case words, not {name!r}')
    path = Path(path or setup_path())
    if path == SEED:            # never edit the reviewed seed in place
        LIVE_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SEED, LIVE_DEFAULT)
        path = LIVE_DEFAULT
    old = load_setup(path)
    for a, v in coords.items():
        check_limits(old, f'sample_{a}', v)
    value = '{' + ', '.join(f'{a}: {round(float(coords[a]), 4)}'
                            for a in AXES if a in coords) + '}'
    lines = path.read_text().splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines)
                 if re.match(r'positions:\s*(#.*)?$', ln))
    end, hit = start + 1, None
    while end < len(lines) and (lines[end].startswith((' ', '\t'))
                                or not lines[end].strip()):
        m = re.match(rf'(\s+){name}:\s*(\{{.*?\}}|null)?(\s*#.*)?\n?$',
                     lines[end])
        if m:
            hit = end
        end += 1
    if hit is not None:
        m = re.match(rf'(\s+){name}:\s*(\{{.*?\}}|null)?(\s*#.*)?\n?$',
                     lines[hit])
        lines[hit] = f'{m.group(1)}{name}: {value}{m.group(3) or ""}\n'
    else:
        last = max(i for i in range(start + 1, end) if lines[i].strip()) \
            if end > start + 1 else start
        lines.insert(last + 1, f'  {name}: {value}\n')
    text = ''.join(lines)
    new = yaml.safe_load(text)
    if {a: new['positions'][name][a] for a in coords} != \
            {a: round(float(v), 4) for a, v in coords.items()}:
        raise RuntimeError('position did not round-trip; file left as it was')
    shutil.copy2(path, path.with_suffix('.yaml.bak'))
    tmp = path.with_suffix('.yaml.tmp')
    tmp.write_text(text)
    os.replace(tmp, path)
    with open(path.with_name('ued_setup.history.log'), 'a') as log:
        log.write(json.dumps({
            'time': datetime.datetime.now().isoformat(timespec='seconds'),
            'position': name,
            'old': (old.get('positions') or {}).get(name),
            'new': new['positions'][name], 'note': note}) + '\n')
    return path


def save_record(kind, data, arrays=None) -> str:
    """A record folder under $UED_RECORDS_DIR: record.json plus arrays.npz
    (camera images, scope traces). Returns the folder path."""
    root = Path(os.environ.get('UED_RECORDS_DIR', RECORDS_DEFAULT))
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
    folder = root / f'{stamp}_{kind}'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'record.json').write_text(json.dumps(data, indent=1,
                                                   default=str))
    if arrays:
        import numpy as np
        np.savez_compressed(folder / 'arrays.npz', **{
            k: np.asarray(v) for k, v in arrays.items() if v is not None})
    return str(folder)


# ------------------------------------------------- actions on a backend
def close_pump_shutter(m):
    """Always first (run 4's pumpLaserOff before every action)."""
    m.put('pump_shutter', 0)


def gate_valves(m) -> dict:
    return {gv: m.get(gv) for gv in GATE_VALVES}


def beam_allowed(m):
    """(all four gate valves OPEN, their states)."""
    vals = gate_valves(m)
    return all(v == 'OPEN' for v in vals.values()), vals


def current_position(m) -> dict:
    return {a: float(m.get(f'sample_{a}')) for a in AXES}


def go_to(m, setup, name, settle_s=5.0, tol=0.01) -> dict:
    """Move the sample stage to a taught position ("go2YAG", "go2Bi",
    "go2Andor"): pump shutter closed first, every axis checked against its
    safety range before the first move, then the readback verified."""
    pos = need(setup, 'positions', name)
    close_pump_shutter(m)
    axes = [a for a in AXES if pos.get(a) is not None]
    for a in axes:
        check_limits(setup, f'sample_{a}', pos[a])
    for a in axes:
        m.put(f'sample_{a}', float(pos[a]))
    m.sleep(settle_s)
    now = current_position(m)
    off = {a: now[a] - float(pos[a]) for a in axes
           if abs(now[a] - float(pos[a])) > tol}
    if off:
        raise RuntimeError(f'the stage did not reach {name}: off by {off}')
    return now


def set_view(m, setup, view, settle_s=1.0):
    """Sample chamber camera plus chamber light: full_view (state 1), ebeam
    (state 2) or laser (state 3)."""
    v = need(setup, 'camera_views', view)
    m.put('cam_sample_yag.exposure', float(v['exposure']))
    m.put('cam_sample_yag.gain', float(v['gain']))
    m.put('chamber_light', int(v['light']))
    m.sleep(settle_s)


def andor_settings(m, exposure, gain, settle_s=1.0):
    """Andor stop -> exposure, gain -> Andor start."""
    m.put('cam_far_andor.acquire', 0)
    m.put('cam_far_andor.exposure', float(exposure))
    m.put('cam_far_andor.gain', float(gain))
    m.put('cam_far_andor.acquire', 1)
    m.sleep(settle_s + float(exposure))


def pump_energy(m, setup, level):
    """Pump HWP to a named setpoint: min_energy (overlap on the YAG) or
    pump_probe (~2 uJ, time zero). The angles come from the laser team."""
    m.put('pump_hwp', float(need(setup, 'pump', PUMP_LEVELS[level])))


def power_meter_out(m, setup):
    m.put('pump_power_meter', float(need(setup, 'pump',
                                         'power_meter_out_mm')))
