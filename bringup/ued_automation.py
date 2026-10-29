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
# The axes the tools read and move. Pitch (MMN:04:04) and yaw (UM1:MMS:03)
# are left out on purpose (Fuhao, 2026-10-28): the tools never touch them;
# an operator sets them by hand. Pitch/yaw fields in a position are kept
# as notes and never moved.
AXES = ('x', 'y', 'z')
GATE_VALVES = ('gv240', 'gv272', 'gv280', 'gv295')
MONITOR_VALVES = ('gv320',)     # ePix line: reported, not a gate
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
                          f'[{lo:g}, {hi:g}] (limits in the setup file)')


def missing(setup) -> list:
    """The setup entries that are still null (positions, setpoints)."""
    out = [f'positions.{k}' for k, v in (setup.get('positions') or {}).items()
           if v is None]
    for sect in ('andor', 'pump', 'limits'):
        out += [f'{sect}.{k}' for k, v in (setup.get(sect) or {}).items()
                if v is None]
    return out


NAME_RE = r'[a-z][a-z0-9_]*'


def _flow(v):
    """One YAML flow value: numbers rounded, strings quoted."""
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return repr(round(float(v), 4))
    return json.dumps(str(v))       # a JSON string is valid YAML


def validate(setup) -> list:
    """Problems in the setup file a hand edit can introduce: bad position
    names or entries, non-numeric or out-of-range axes, malformed safety
    ranges. Empty when the file is fine (null entries are not problems:
    missing() lists those)."""
    probs = []
    pos = setup.get('positions')
    if not isinstance(pos, dict):
        return ['positions: missing or not a mapping']
    for name, p in pos.items():
        where = f'positions.{name}'
        if not re.fullmatch(NAME_RE, str(name)):
            probs.append(f'{where}: names are lower_case words')
        if p is None:
            continue
        if not isinstance(p, dict):
            probs.append(f'{where}: must be {{x: .., y: .., ...}} or null')
            continue
        for a in AXES:
            if a not in p:
                continue
            v = p[a]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                probs.append(f'{where}.{a}: {v!r} is not a number')
                continue
            try:
                check_limits(setup, f'sample_{a}', v)
            except SafetyError as exc:
                probs.append(f'{where}.{a}: {exc}')
        if not any(a in p for a in AXES):
            probs.append(f'{where}: no stage axis ({", ".join(AXES)})')
    for k, lim in (setup.get('limits') or {}).items():
        if lim is None:                   # not set yet: missing() lists it
            continue
        ok = (isinstance(lim, list) and len(lim) == 2
              and all(isinstance(x, (int, float)) for x in lim)
              and lim[0] < lim[1])
        if not ok:
            probs.append(f'limits.{k}: must be [low, high] with low < high')
    return probs


def save_position(name, coords, note='', path=None, extra=None) -> Path:
    """Write positions.<name> as one line, keeping the rest of the file
    (comments included) as it is. Keeps the previous file as .bak and
    appends the change to ued_setup.history.log beside it.

    coords may hold only some axes: they update the taught entry, and the
    other axes and any extra fields an operator added by hand (a note, a
    per-sample pump setting, ...) are kept. extra adds or updates such
    fields."""
    if not re.fullmatch(NAME_RE, name):
        raise ValueError(f'position names are lower_case words, not {name!r}')
    path = Path(path or setup_path())
    if path == SEED:            # never edit the reviewed seed in place
        LIVE_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SEED, LIVE_DEFAULT)
        path = LIVE_DEFAULT
    t_read = path.stat().st_mtime   # to catch a concurrent edit
    old = load_setup(path)
    for a, v in coords.items():
        if a not in AXES:
            raise ValueError(f'{a!r} is not a stage axis ({", ".join(AXES)})')
        check_limits(old, f'sample_{a}', v)
    before = (old.get('positions') or {}).get(name)
    merged = dict(before) if isinstance(before, dict) else {}
    merged.update({a: round(float(v), 4) for a, v in coords.items()})
    merged.update(extra or {})
    keys = [a for a in AXES if a in merged] + \
        [k for k in merged if k not in AXES]
    value = '{' + ', '.join(f'{k}: {_flow(merged[k])}' for k in keys) + '}'
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
    if new['positions'][name] != {k: (round(float(v), 4) if isinstance(
            v, (int, float)) and not isinstance(v, bool) else v)
            for k, v in merged.items()}:
        raise RuntimeError('position did not round-trip; file left as it was')
    if path.stat().st_mtime != t_read:
        raise RuntimeError(f'{path} changed while saving (someone else edited '
                           'it); file left as it was, try again')
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


def close_shutters(m):
    """Pump and gun UV shutters closed, as before every move in Xinxin's
    Run 6 code (pumpLaser_Close, gunUV_Close): no laser on the sample and
    no e-beam on the frame or holder while the stage travels."""
    m.put('pump_shutter', 0)
    m.put('gun_uv_shutter', 0)


def readiness(m, setup) -> dict:
    """Read-only pre-data checklist (Xinxin's getAll): gate valves, the
    ePix valve, both shutters, the pump power meter. Returns the states and
    a list of warnings for an operator."""
    ok, vals = beam_allowed(m)
    warn = [f'gate valve {k[2:]} is {v}: no e-beam' for k, v in vals.items()
            if v != 'OPEN']
    out = {'gate_valves': vals, 'beam_allowed': ok}
    for gv in MONITOR_VALVES:
        try:
            out[gv] = m.get(gv)
        except Exception as exc:          # monitored only: report, go on
            out[gv] = f'unreadable ({exc})'
    nc = []
    for sh in ('gun_uv_shutter', 'pump_shutter'):
        try:
            out[sh] = 'open' if m.get(sh) else 'closed'
        except Exception as exc:          # report, don't block
            out[sh] = 'UNREADABLE'
            nc.append(f'{sh} unreadable ({exc})')
    pm_in = float((setup.get('pump') or {}).get('power_meter_in_mm', 40.0))
    try:
        pm = float(m.get('pump_power_meter'))
        out['pump_power_meter_mm'] = pm
        if pm > 0.85 * pm_in:             # Xinxin: > 35 with in = 40
            warn.append(f'pump power meter is IN ({pm:g} mm): it blocks the '
                        'pump; take it out before pump-probe')
    except Exception as exc:
        nc.append(f'pump power meter unreadable ({exc})')
    pos_out = (setup.get('pump') or {}).get('outcoupling_out_mm')
    pos_in = (setup.get('pump') or {}).get('outcoupling_in_mm')
    try:
        oc = float(m.get('pump_outcoupling'))
        out['pump_outcoupling_mm'] = oc
        if pos_out is None or pos_in is None:
            nc.append('pump outcoupling mirror IN/OUT: pump.outcoupling_'
                      'out_mm / outcoupling_in_mm not set; ask the operator')
        elif abs(oc - float(pos_in)) < abs(oc - float(pos_out)):
            warn.append(f'pump outcoupling mirror is IN ({oc:g} mm): it '
                        'blocks the pump; take it out before pump-probe')
    except Exception as exc:              # report, don't block
        nc.append(f'pump outcoupling mirror unreadable ({exc})')
    out['not_checked'] = nc
    out['warnings'] = warn
    return out


def gate_valves(m) -> dict:
    """Each gate valve's state; UNREADABLE when its PV doesn't answer (from
    S3DF the accelerator-side PVs need the gateway prefix)."""
    out = {}
    for gv in GATE_VALVES:
        try:
            out[gv] = m.get(gv)
        except Exception:
            out[gv] = 'UNREADABLE'
    return out


def beam_allowed(m):
    """(all four gate valves OPEN, their states)."""
    vals = gate_valves(m)
    return all(v == 'OPEN' for v in vals.values()), vals


def current_position(m) -> dict:
    return {a: float(m.get(f'sample_{a}')) for a in AXES}


def go_to(m, setup, name, settle_s=5.0, tol=0.01) -> dict:
    """Move the sample stage to a taught position ("go2YAG", "go2Bi",
    "go2Andor"), the way Xinxin's go2... functions do:
      1. every axis (and the position's pump HWP, if it has one) checked
         against its safety range before anything moves;
      2. pump and gun UV shutters closed;
      3. the sample camera to the motion view (motion.camera_view, "mid");
      4. the pump HWP to the position's pump_hwp_deg, if it has one;
      5. x, y, z moved, the readback verified;
      6. the gun UV shutter reopened if it was open before.
    Only x, y and z move (AXES); pitch and yaw are an operator's."""
    pos = need(setup, 'positions', name)
    axes = [a for a in AXES if pos.get(a) is not None]
    for a in axes:
        check_limits(setup, f'sample_{a}', pos[a])
    hwp = pos.get('pump_hwp_deg')
    if hwp is not None:
        check_limits(setup, 'pump_hwp', hwp)
    uv_was_open = bool(m.get('gun_uv_shutter'))
    close_shutters(m)
    view = (setup.get('motion') or {}).get('camera_view')
    if view:
        set_view(m, setup, view)
    if hwp is not None:
        m.put('pump_hwp', float(hwp))
    for a in axes:
        m.put(f'sample_{a}', float(pos[a]))
    m.sleep(settle_s)
    now = current_position(m)
    off = {a: now[a] - float(pos[a]) for a in axes
           if abs(now[a] - float(pos[a])) > tol}
    if off:
        raise RuntimeError(f'the stage did not reach {name}: off by {off}')
    if uv_was_open:
        m.put('gun_uv_shutter', 1)
    return now


def set_view(m, setup, view, settle_s=1.0):
    """Sample chamber camera plus chamber light: full_view (state 1), ebeam
    (state 2), laser (state 3), or Xinxin's high / mid / low presets. A view
    without a `light` entry leaves the light as it is."""
    v = need(setup, 'camera_views', view)
    m.put('cam_sample_yag.exposure', float(v['exposure']))
    m.put('cam_sample_yag.gain', float(v['gain']))
    if v.get('light') is not None:
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
