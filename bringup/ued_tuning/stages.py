"""UED bring-up stages, one procedure each (proposal, Workflow 1 + 2).

The procedures follow the operators' 2026-10 notes: the dry-run notes for
stages 1-3 (gun RF on KY03/TS8; the scope-based emission-phase scan; Cameron's
UV feedback loop) and Fuhao Ji's procedures for stages 4-8.

Every procedure talks only to a backend with get(name), put(name, value),
sleep(seconds) and time(): sim/virtual_ued.py, or the read-only EPICS
backend. Names are the logical channels in channels.py. Stage moves, camera
views and laser setpoints go through ued_automation (the updated run-4
automation script), with ued_setup.yaml's positions and safety ranges.

Rules every stage keeps:
  - the beam stages (2-8) first read the four gate valves and stop, before
    any write, unless all are OPEN;
  - the pump-laser shutter is closed before anything else, and closed again
    after any step that opens it;
  - every write is checked against the safety ranges (Recorder.put).

Each returns a dict: whether it ran (`ok`), whether the result meets the
stage's acceptance check (`accepted`), why, whether an operator must act
(`needs_operator`, with `operator_steps`), what it measured, and an I/O log
of every write with the real PV behind it.

  1 gun_ramp            ramp AREQ to the target (bringup/gun_ramp.py)
  2 schottky_scan       diagnostic-screen check, then the emission-phase
                        scan on the scope; phase = emission + 30 deg
  3 set_bunch_charge    UV throttle to ~53 and fine-tune to 10 fC on the
                        scope, then hand over to Cameron's UV feedback loop
  4 beam_on_screens     e-beam on the sample-chamber YAG (and onto the cross),
                        then on the Andor
  5 align_collimator    insert the collimator, tune its motor for transmission
  6 overlap_pump_laser  pump laser onto the e-beam cross on the YAG
  7 tune_sample_position  main beam into the Andor through hole, raster the
                        sample for the pattern (escalates by design)
  8 find_time_zero      verify the overlap, pump-probe delay scan (a stand-in
                        for the LCLS DAQ / BOED scan)
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from .channels import CHANNELS, HOLDER_OUT, HOLDER_YAG, to_pv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
import ued_automation as auto  # noqa: E402  (bringup/ued_automation.py)
from gun_ramp import RampConfig, ramp  # noqa: E402  (bringup/gun_ramp.py)

PS_PER_MM = 2e-3 / 299792458 * 1e12
MV_PER_DIV = {'1mV': 1, '2mV': 2, '5mV': 5, '10mV': 10, '20mV': 20,
              '50mV': 50, '100mV': 100, '200mV': 200, '500mV': 500,
              '1V': 1e3, '2V': 2e3, '5V': 5e3, '10V': 1e4}
# Stage 2's BSA option: Sam Klein's amortized T0 posterior (boed/). It
# needs torch, which the agent's Python lacks, so each step runs
# boed/ued_t0.py in UED_BOED_PYTHON (the AgenticOpt venv) on the trained
# models in UED_BOED_MODEL_DIR (his policy-boed run bsa_full_v2).
BOED_DIR = Path(os.environ.get(
    'UED_BOED_DIR', Path(__file__).resolve().parents[2] / 'boed'))
BOED_PYTHON = os.environ.get(
    'UED_BOED_PYTHON', '/sdf/group/mli/zhezhang/AgenticOpt/.venv/bin/python')
BSA_GUESS_SHIFT = 8.0      # deg: window centre above onset_guess (see there)
BOED_MODELS = os.environ.get(
    'UED_BOED_MODEL_DIR',
    '/sdf/group/mli/zhezhang/ued/agentic/boed/models/bsa_full_v2')
OPERATOR_HINT = {
    'diag_holder': 'the diagnostic screen (YAGS:AS01:270) is moved by an '
                   'operator, not the agent: insert or extract it from the '
                   'panel, check diag_screen_state, then rerun with '
                   'diag_screen_by_operator=true',
}


class OperatorActionNeeded(RuntimeError):
    pass


class Recorder:
    """Forward every call to the backend; check each write against the
    safety ranges; log writes, read counts and operator steps."""

    def __init__(self, backend, setup, manual=()):
        self.m = backend
        self.setup = setup
        self.manual = set(manual)
        self.puts = []
        self.operator_steps = []
        self.reads = Counter()
        self.t0 = backend.time()

    def get(self, name):
        self.reads[name] += 1
        return self.m.get(name)

    def put(self, name, value):
        ch = CHANNELS[name]
        if not ch.writable:              # read-only for the tools
            raise auto.SafetyError(f'{name} is read-only for these tools '
                                   f'({ch.desc}); an operator sets it')
        if name in self.manual:          # done by hand, already
            self.operator_steps.append(f'{name} = {value} (by the operator)')
            return
        auto.check_limits(self.setup, name, value)
        if ch.pv is None and getattr(self.m, 'kind', '') != 'sim':
            raise OperatorActionNeeded(OPERATOR_HINT.get(
                name, f'{name} has no PV: an operator must set it'))
        self.puts.append((round(self.m.time() - self.t0, 1), name, value))
        self.m.put(name, value)

    def sleep(self, seconds):
        self.m.sleep(seconds)

    def time(self):
        return self.m.time()

    def image(self, cam):
        f = getattr(self.m, 'image', None)
        return f(cam) if f else None


def _num(v, nd=4):
    """JSON-safe copy: rounded floats, NaN/inf as None, recursively."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return None if not math.isfinite(v) else round(float(v), nd)
    if isinstance(v, dict):
        return {k: _num(x, nd) for k, x in v.items()}
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_num(x, nd) for x in v]
    return v


def _result(stage, rec, ok, accepted, reason, needs_operator=False, **data):
    writes = [{'t_s': t, 'channel': n, 'value': _num(v),
               'pv': CHANNELS[n].pv, 'pv_value': _num(to_pv(n, v)),
               'status': CHANNELS[n].status}
              for t, n, v in rec.puts]
    shown = writes if len(writes) <= 24 else writes[:18] + writes[-6:]
    return {
        'stage': stage, 'ok': bool(ok), 'accepted': bool(accepted),
        'reason': reason, 'needs_operator': bool(needs_operator),
        'operator_steps': rec.operator_steps,
        'machine_time_s': round(rec.time() - rec.t0, 1),
        'n_writes': len(writes), 'n_reads': sum(rec.reads.values()),
        'channels_written': sorted({w['channel'] for w in writes}),
        'channels_read': sorted(rec.reads),
        'writes': shown,
        'setup_file': str(auto.setup_path()),
        **{k: _num(v) for k, v in data.items()},
    }


def _precheck(rec, stage, beam=True):
    """Gate valves (beam stages), then the pump shutter closed: an early
    result if the stage can't start, else None."""
    if beam:
        ok, vals = auto.beam_allowed(rec)
        if not ok:
            if all(v == 'UNREADABLE' for v in vals.values()):
                reason = ('gate valve states unreadable from here (their '
                          'PVs are accelerator-side; from S3DF they need '
                          'the gateway prefix): the beam path cannot be '
                          'confirmed')
            else:
                shut = [f'{k} {v}' for k, v in vals.items() if v != 'OPEN']
                reason = ('gate valves not all OPEN (' + ', '.join(shut)
                          + '): no e-beam can reach the screens')
            return _result(stage, rec, False, False, reason,
                           needs_operator=True, gate_valves=vals)
    auto.close_pump_shutter(rec)
    return None


def avg(m, name, n=3):
    vals = [m.get(name) for _ in range(n)]
    vals = [float(v) for v in vals if v is not None and math.isfinite(v)]
    return float(np.mean(vals)) if vals else float('nan')


def read_cam(m, cam, n=3):
    keys = ('centroid_x', 'centroid_y', 'sigma_x', 'sigma_y', 'total',
            'max_value')
    out = {k: avg(m, f'{cam}.{k}', n) for k in keys}
    out['saturated'] = bool(avg(m, f'{cam}.saturated', 1) > 0.5)
    out['seen'] = bool(math.isfinite(out['centroid_x']))
    return out


def uv_toggle(rec, cam, n=3, settle_s=1.0):
    """Camera with the gun UV shutter closed, then open (left open): the
    difference is the e-beam, not dark current."""
    rec.put('gun_uv_shutter', 0)
    rec.sleep(settle_s)
    closed = read_cam(rec, cam, n)
    rec.put('gun_uv_shutter', 1)
    rec.sleep(settle_s)
    opened = read_cam(rec, cam, n)
    diff = opened['total'] - (closed['total'] if closed['seen'] else 0.0)
    seen = opened['seen'] and diff > 0.5 * opened['total']
    return {'seen': bool(seen), 'uv_open': opened, 'uv_closed': closed,
            'difference_total': diff}


def scope_charge(m, setup, n=1, threshold_sigma=5.0):
    """Charge from the scope trace (the channel ued_setup.yaml's
    scope.channel names, CH2 by default): the largest dip below the trace's
    median baseline, in mV via the V/div setting, then fC (-1.7 mV = 10 fC).
    Averages n traces; `detected` when the dip is threshold_sigma above the
    trace noise."""
    ch = int(auto.need(setup, 'scope', 'channel'))
    vdiv = str(m.get(f'scope_ch{ch}_vdiv'))
    mv_div = MV_PER_DIV.get(vdiv)
    if mv_div is None:
        raise ValueError(f'unknown scope V/div {vdiv!r}')
    per_fc = float(auto.need(setup, 'scope', 'mV_per_fC'))
    peaks, noises, bases, trace = [], [], [], None
    for _ in range(n):
        trace = np.asarray(m.get(f'scope_ch{ch}_trace'), dtype=float)
        base = float(np.median(trace))
        dev = trace - base
        noises.append(1.4826 * float(np.median(np.abs(dev))) or 1e-3)
        peaks.append(float(dev.min()))
        bases.append(base)
    peak_div, noise_div = float(np.mean(peaks)), float(np.mean(noises))
    peak_mv = peak_div * mv_div
    return {'charge_fC': peak_mv / per_fc, 'peak_mV': peak_mv,
            'peak_div': peak_div, 'noise_div': noise_div,
            'baseline_div': float(np.mean(bases)), 'vdiv': vdiv,
            'channel': ch,
            'snr': -peak_div / noise_div,
            'threshold_fC': threshold_sigma * noise_div * mv_div / abs(per_fc),
            'detected': bool(-peak_div > threshold_sigma * noise_div),
            'trace': trace}


def _ensure_collimator_out(rec, setup):
    out = float(auto.need(setup, 'collimator', 'out_mm'))
    if abs(float(rec.get('collimator')) - out) > 0.05:
        rec.put('collimator', out)
        rec.sleep(5)


def check_ebeam_on_yag(rec, setup, move_cross=True):
    """Procedure (4), YAG: go to the YAG, e-beam view (light off), toggle the
    gun UV to tell the e-beam from dark current, and compare it with the
    cross. Near: on the cross. Within cross.max_move_px: move the cross onto
    the beam (if move_cross). Farther: an operator judges."""
    auto.go_to(rec, setup, 'yag')
    auto.set_view(rec, setup, 'ebeam')
    rec.sleep(2)
    t = uv_toggle(rec, 'cam_sample_yag', n=5)
    cross = [float(rec.get('cam_sample_yag.cross_x')),
             float(rec.get('cam_sample_yag.cross_y'))]
    out = {'seen': t['seen'], 'cross_before_px': cross, 'cross_px': cross,
           'ebeam_px': None, 'distance_px': None, 'status': 'not seen',
           'ebeam': t['uv_open']}
    if not t['seen']:
        return out
    e = [t['uv_open']['centroid_x'], t['uv_open']['centroid_y']]
    d = math.hypot(e[0] - cross[0], e[1] - cross[1])
    out.update(ebeam_px=e, distance_px=d)
    on = float(auto.need(setup, 'cross', 'on_cross_px'))
    far = float(auto.need(setup, 'cross', 'max_move_px'))
    if d <= on:
        out['status'] = 'on cross'
    elif d <= far and move_cross:
        rec.put('cam_sample_yag.cross_x', round(e[0]))
        rec.put('cam_sample_yag.cross_y', round(e[1]))
        out.update(status='cross moved onto the e-beam',
                   cross_px=[float(round(e[0])), float(round(e[1]))])
    else:
        out['status'] = ('far from the cross: an operator judges'
                         if d > far else 'off the cross')
    return out


def _laser_view(rec, setup):
    """Pump on the YAG alone: laser view (light off), lowest energy, power
    meter out, gun UV closed, then the pump shutter open."""
    auto.set_view(rec, setup, 'laser')
    auto.pump_energy(rec, setup, 'min_energy')
    auto.power_meter_out(rec, setup)
    rec.put('gun_uv_shutter', 0)
    rec.put('pump_shutter', 1)
    rec.sleep(3)


# ---------------------------------------------------------------- stage 1
def gun_ramp(m, setup, target=0.53, n_steps=None, dwell_s=None):
    """Stage 1. Steps and dwell default to gun.ramp_n_steps and
    gun.ramp_dwell_s in the setup file (20 min since 2026-10-28, for the
    reduced cooling-water flow), else the original 300 x 2 s."""
    rec = Recorder(m, setup)
    early = _precheck(rec, '1 gun ramp-up', beam=False)
    if early:
        return early
    g = setup.get('gun') or {}
    n_steps = int(n_steps or g.get('ramp_n_steps') or 300)
    dwell_s = float(dwell_s or g.get('ramp_dwell_s') or 2.0)
    start_areq = float(rec.get('areq'))
    cfg = RampConfig(target=target, n_steps=n_steps, dwell_s=dwell_s,
                     temp_min=float(g.get('ramp_temp_min_C', 33.0)),
                     temp_max=float(g.get('ramp_temp_max_C', 37.0)))
    res = ramp(rec, cfg)
    aact = avg(rec, 'aact', 5)
    fb = (rec.get('pfb_status'), rec.get('afb_status'))
    accepted = (res.ok and fb == ('Active', 'Active')
                and abs(float(rec.get('areq')) - target) <= 1e-6)
    notes = []
    if start_areq > cfg.start + 1e-9:
        notes.append(f'AREQ was parked at {start_areq:g}; the first step '
                     f'set it to {cfg.start:g}')
    return _result('1 gun ramp-up', rec, res.ok, accepted, res.reason,
                   target=target, start_areq=start_areq, aact=aact,
                   feedbacks=list(fb), notes=notes,
                   max_temp_C=max(r['temp'] for r in res.trace),
                   ramp_steps=len(res.trace))


# ---------------------------------------------------------------- stage 2
def schottky_scan(m, setup, coarse_step=5.0, fine_step=0.5,
                  phase_offset=None, throttle=None, n_avg=3,
                  threshold_sigma=5.0, diag_screen_by_operator=False,
                  method='grid', onset_guess=None, bsa_max_width=4.0):
    """Diagnostic screen, then the emission-phase scan on the scope.

    Screen (procedure 1-4): collimator at zero, diagnostic screen in, its
    camera with the gun UV toggled to tell e-beam from dark current. Scope
    (1-3): UV throttle ~51, scan PREQ over -180..180, the emission phase is
    where the scope charge first rises above its detection threshold
    (threshold_sigma x the trace noise), set PREQ = emission + 30 deg.
    Record (6): throttle, phase, diagnostic image and trace.

    method='bsa' replaces the fine scan with Sam Klein's amortized T0
    posterior (boed/): four 10-point scans in a 70 deg window around the
    coarse edge (or around onset_guess, which skips the coarse scan), each
    range set by the posterior after the scans before it. The emission
    phase is the posterior median; the stage stops for an operator if its
    98 % interval is wider than bsa_max_width deg, or if the measured
    charge disagrees with it (_bsa_check). A guess should be within ~10
    deg of the onset.
    """
    stage = '2 Schottky scan'
    rec = Recorder(m, setup, manual=('diag_holder',)
                   if diag_screen_by_operator else ())
    early = _precheck(rec, stage)
    if early:
        return early
    g = auto.need(setup, 'gun')
    offset = float(g['phase_from_emission_deg'] if phase_offset is None
                   else phase_offset)
    throttle = float(g['uv_throttle_scan_deg'] if throttle is None
                     else throttle)
    _ensure_collimator_out(rec, setup)
    rec.put('diag_holder', HOLDER_YAG)
    rec.sleep(2)
    screen = uv_toggle(rec, 'cam_diag_yag', n=3)
    if not screen['seen']:
        return _result(stage, rec, True, False,
                       'no e-beam on the diagnostic screen (dark current '
                       'only?)', needs_operator=True, screen=screen)
    rec.put('gun_uv_throttle', throttle)
    rec.sleep(2)
    noise = scope_charge(rec, setup, 3, threshold_sigma)
    thr = noise['threshold_fC']

    def q_at(ph):
        rec.put('preq', float(ph))
        rec.sleep(0.5)
        return scope_charge(rec, setup, n_avg, threshold_sigma)['charge_fC']

    if method not in ('grid', 'bsa'):
        raise ValueError(f"method is 'grid' or 'bsa', not {method!r}")
    coarse, bsa = [], None
    preq0 = float(rec.get('preq'))    # put back if the scan fails
    if method == 'bsa' and onset_guess is not None:
        # The window works when the onset sits at or left of its centre
        # (simulator, 2026-10-29: centres 0-15 deg above the onset gave the
        # right phase, 6-12 deg below it a wrong one, refused by the
        # checks), so centre it 8 deg above the guess: guesses 10 deg below
        # to 7 deg above the onset then worked, or were refused.
        edge = _wrap(onset_guess + BSA_GUESS_SHIFT)
    else:
        grid = np.arange(-180.0, 180.0, coarse_step)
        coarse = [(float(p), q_at(p)) for p in grid]
        run = _longest_run([q >= thr for _, q in coarse])
        if run is None or run[1] < 3:
            return _result(stage, rec, True, False,
                           f'no emission window above {thr:.1f} fC in the '
                           'coarse scan', needs_operator=True, coarse=coarse,
                           threshold_fC=thr)
        edge = coarse[run[0]][0]      # where the emission window opens
    if method == 'bsa':
        try:
            bsa = _bsa_scan(q_at, edge)
        except Exception as exc:      # helper or models unavailable
            rec.put('preq', preq0)
            return _result(stage, rec, True, False,
                           f'BSA inference failed ({exc}); rerun with '
                           "method='grid'", needs_operator=True,
                           coarse=coarse, threshold_fC=thr)
        fine = bsa['points']
        t0 = bsa['t0']
        emission = _wrap(edge + t0['median'])
        bsa['check'] = _bsa_check(fine, emission, thr)
        problem = None
        if t0['q99'] - t0['q01'] > bsa_max_width:
            problem = (f"emission phase uncertain: 98 % interval "
                       f"{t0['q99'] - t0['q01']:.1f} deg wide (limit "
                       f"{bsa_max_width:g})")
        elif not bsa['check']['ok']:
            problem = ('the BSA emission phase disagrees with the measured '
                       'charge: ' + bsa['check']['why'])
        if problem:
            rec.put('preq', preq0)
            return _result(stage, rec, True, False,
                           problem + "; check the scope signal or rerun "
                           "with method='grid'", needs_operator=True,
                           coarse=coarse, bsa=bsa, threshold_fC=thr,
                           emission_phase_deg=emission)
    else:
        fine = [(float(_wrap(p)), q_at(_wrap(p))) for p in
                np.arange(edge - coarse_step, edge + coarse_step + 1e-9,
                          fine_step)]
        i = next((i for i, (_, q) in enumerate(fine) if q >= thr), None)
        if i is None or i == 0:
            rec.put('preq', preq0)
            return _result(stage, rec, True, False, 'emission edge lost in '
                           'the fine scan', needs_operator=True,
                           coarse=coarse, fine=fine, threshold_fC=thr)
        (p0, q0), (p1, q1) = fine[i - 1], fine[i]
        p1u = p0 + fine_step              # unwrapped neighbour
        emission = _wrap(p0 + (thr - q0) * (p1u - p0) / (q1 - q0))
    op = _wrap(emission + offset)
    rec.put('preq', op)
    rec.sleep(1)
    at_op = scope_charge(rec, setup, 5, threshold_sigma)
    accepted = at_op['detected']
    record = auto.save_record('schottky_scan', {
        'throttle_deg': throttle, 'preq_deg': op, 'emission_deg': emission,
        'phase_offset_deg': offset, 'charge_fC': at_op['charge_fC'],
        'threshold_fC': thr, 'method': method, 'coarse': coarse,
        'fine': fine, 'bsa': bsa},
        arrays={'scope_trace': at_op['trace'],
                'diag_image': rec.image('cam_diag_yag')})
    return _result(stage, rec, True, accepted,
                   'emission phase found' if accepted
                   else 'no charge at the operating phase',
                   needs_operator=not accepted,
                   emission_phase_deg=emission, operating_phase_deg=op,
                   phase_offset_deg=offset, throttle_deg=throttle,
                   threshold_fC=thr,
                   charge_at_operating_fC=at_op['charge_fC'],
                   scope={k: v for k, v in at_op.items() if k != 'trace'},
                   screen={k: screen[k] for k in ('seen', 'difference_total')},
                   method=method, coarse=coarse, fine=fine,
                   bsa=bsa and {k: bsa[k] for k in ('t0', 'check', 'scans',
                                                     'window_deg')},
                   record=record)


def _bsa_step(x, q, scans_done, right_bound):
    """One call of boed/ued_t0.py (see there): the T0 posterior after
    `scans_done` scans and the next scan's range."""
    req = {'model_dir': BOED_MODELS, 'x_deg': x, 'q': q,
           'scans_done': scans_done, 'right_bound': right_bound}
    p = subprocess.run([BOED_PYTHON, 'ued_t0.py'], input=json.dumps(req),
                       capture_output=True, text=True, cwd=BOED_DIR,
                       timeout=300)
    if p.returncode:
        raise RuntimeError(p.stderr.strip().splitlines()[-1]
                           if p.stderr.strip() else f'exit {p.returncode}')
    return json.loads(p.stdout)


def _bsa_check(points, emission, thr, margin=4.0, span=12.0,
               min_frac=0.8):
    """Does the measured charge agree with the BSA onset? Points 4-12 deg
    below it must be under the detection threshold and points 4-12 deg
    above it over it (the model's T0 is where the rise starts, so it sits
    a little below the threshold crossing). Also the threshold crossing
    itself, interpolated from the points, for comparison with the grid
    method."""
    rel = [(_wrap(p - emission), q) for p, q in points]
    below = [q < thr for d, q in rel if -span <= d <= -margin]
    above = [q >= thr for d, q in rel if margin <= d <= span]
    fb = sum(below) / len(below) if below else None
    fa = sum(above) / len(above) if above else None
    why = []
    if fb is not None and fb < min_frac:
        why.append(f'{1 - fb:.0%} of the points 4-12 deg below it already '
                   'carry charge')
    if fa is not None and fa < min_frac:
        why.append(f'{1 - fa:.0%} of the points 4-12 deg above it carry '
                   'no charge')
    if fb is None and fa is None:
        why.append('no measured points 4-12 deg either side of it')
    srt = sorted(rel)
    cross = next((_wrap(emission + d0 + (thr - q0) * (d1 - d0) / (q1 - q0))
                  for (d0, q0), (d1, q1) in zip(srt, srt[1:])
                  if q0 < thr <= q1 and d1 > d0), None)
    return {'ok': not why, 'why': '; '.join(why),
            'fraction_below_dark': fb, 'fraction_above_lit': fa,
            'threshold_crossing_deg': cross}


def _bsa_scan(q_at, centre):
    """The BSA protocol around `centre` (PREQ of the coarse edge): the
    model's frame is x = PREQ - centre, charge rising with x past T0."""
    x, q, scans = [], [], []
    reply = _bsa_step(x, q, 0, None)
    while reply['next']:
        nxt = reply['next']
        for xi in nxt['points']:
            x.append(float(xi))
            q.append(float(q_at(_wrap(centre + xi))))
        reply = _bsa_step(x, q, nxt['scan'], nxt['right_bound'])
        scans.append({'scan': nxt['scan'],
                      'preq_range_deg': [_wrap(centre + nxt['a']),
                                         _wrap(centre + nxt['b'])],
                      't0_after_deg': {k: round(v, 3) for k, v in
                                       reply['t0'].items()}})
    lo, hi = reply['frame_deg']
    return {'t0': reply['t0'], 'scans': scans,
            'window_deg': [_wrap(centre + lo), _wrap(centre + hi)],
            'points': [(_wrap(centre + xi), qi) for xi, qi in zip(x, q)]}


def _wrap(deg):
    return (float(deg) + 180.0) % 360.0 - 180.0


def _longest_run(mask):
    """(start, length) of the longest cyclic run of True, or None. Noise
    near the threshold makes short runs; the emission window is the long
    one."""
    n = len(mask)
    if not any(mask):
        return None
    if all(mask):
        return 0, n
    first_false = mask.index(False)
    best, i = (None, 0), 0
    while i < n:
        j = (first_false + i) % n
        if mask[j]:
            k = 0
            while k < n and mask[(j + k) % n]:
                k += 1
            if k > best[1]:
                best = (j, k)
            i += k
        else:
            i += 1
    return best


# ---------------------------------------------------------------- stage 3
HANDOFF = [
    "Teach Cameron's UV feedback loop: with the charge at 10 fC (-1.7 mV on "
    'scope CH2) click "set low charge"',
    'set the charge to 30 fC (-5.1 mV) and click "set high charge"',
    'click "start feedback". From then on the loop owns the UV throttle: '
    'do not run set_bunch_charge while it runs',
    'watch the charge with monitor_charge',
]


def set_bunch_charge(m, setup, target_fC=None, tolerance=0.1,
                     feedback_loop_off=False, fine_tune=True, max_iter=8,
                     n_avg=5, diag_screen_by_operator=False):
    """UV throttle to its operating value (~53), fine-tune onto the target
    charge on the scope (-1.7 mV = 10 fC), record, then hand over to
    Cameron's UV feedback loop, which owns the throttle from then on.

    Two controllers on one actuator is a hazard, so this tool writes the
    throttle only when the operator confirms the loop is stopped
    (feedback_loop_off=true).
    """
    stage = '3 pulse charge'
    rec = Recorder(m, setup, manual=('diag_holder',)
                   if diag_screen_by_operator else ())
    if not feedback_loop_off:
        return _result(stage, rec, False, False,
                       "Cameron's UV feedback loop also drives the UV "
                       'throttle: confirm it is stopped, then rerun with '
                       'feedback_loop_off=true', needs_operator=True)
    early = _precheck(rec, stage)
    if early:
        return early
    g = auto.need(setup, 'gun')
    target = float(g['target_charge_fC'] if target_fC is None else target_fC)
    rec.put('diag_holder', HOLDER_YAG)
    rec.put('gun_uv_shutter', 1)

    def q_at(th):
        rec.put('gun_uv_throttle', float(th))
        rec.sleep(2)
        return scope_charge(rec, setup, n_avg)['charge_fC']

    lo, hi = (setup.get('limits') or {}).get('gun_uv_throttle', (0, 180))
    th1 = float(g['uv_throttle_operating_deg'])
    q1 = q_at(th1)
    hist = [(th1, q1)]
    if fine_tune and abs(q1 - target) > tolerance * target:
        th0, q0 = th1, q1
        th1 = float(np.clip(th0 + (1.0 if q0 > target else -1.0), lo, hi))
        q1 = q_at(th1)
        hist.append((th1, q1))
        for _ in range(max_iter):
            if abs(q1 - target) <= tolerance * target:
                break
            slope = (q1 - q0) / (th1 - th0) if th1 != th0 else 0.0
            step = ((target - q1) / slope if slope < 0
                    else (1.0 if q1 > target else -1.0))
            th2 = float(np.clip(th1 + np.clip(step, -4, 4), lo, hi))
            th0, q0, th1, q1 = th1, q1, th2, q_at(th2)
            hist.append((th1, q1))
    final = scope_charge(rec, setup, n_avg)
    accepted = abs(final['charge_fC'] - target) <= tolerance * target
    record = auto.save_record('bunch_charge', {
        'throttle_deg': th1, 'charge_fC': final['charge_fC'],
        'peak_mV': final['peak_mV'], 'target_fC': target,
        'preq_deg': rec.get('preq'), 'iterations': hist},
        arrays={'scope_trace': final['trace']})
    return _result(stage, rec, True, accepted,
                   'charge on target; hand over to the UV feedback loop'
                   if accepted else 'charge off target',
                   needs_operator=True, target_fC=target,
                   charge_fC=final['charge_fC'], peak_mV=final['peak_mV'],
                   throttle_deg=th1, iterations=hist, handoff=HANDOFF,
                   record=record)


def monitor_charge(m, setup, samples=10, interval_s=1.0):
    """Read-only: the scope charge and the UV throttle over time, e.g. to
    see Cameron's feedback loop hold the charge."""
    rows = []
    for _ in range(int(samples)):
        q = scope_charge(m, setup, 1)
        rows.append({'t_s': round(m.time(), 1), 'charge_fC': q['charge_fC'],
                     'throttle_deg': float(m.get('gun_uv_throttle'))})
        m.sleep(interval_s)
    qs = np.array([r['charge_fC'] for r in rows])
    return _num({'stage': 'monitor charge', 'ok': True, 'samples': rows,
                 'mean_fC': qs.mean(), 'std_fC': qs.std(),
                 'min_fC': qs.min(), 'max_fC': qs.max()})


# ---------------------------------------------------------------- stage 4
def beam_on_screens(m, setup, diag_screen_by_operator=False):
    """Procedure (4). YAG: diagnostic screen out, go to the YAG, light off,
    e-beam view, toggle the gun UV, check the beam against the cross and
    move the cross onto it if it is near (escalate if far), back to the full
    view. Andor: go to the Andor position (card out), Andor stop -> exposure
    1 s, gain 2 -> start, check the beam (escalate if not seen)."""
    stage = '4 beam on YAG & EMCCD'
    rec = Recorder(m, setup, manual=('diag_holder',)
                   if diag_screen_by_operator else ())
    early = _precheck(rec, stage)
    if early:
        return early
    rec.put('diag_holder', HOLDER_OUT)
    _ensure_collimator_out(rec, setup)
    yag = check_ebeam_on_yag(rec, setup, move_cross=True)
    auto.set_view(rec, setup, 'full_view')
    if not yag['seen']:
        return _result(stage, rec, True, False, 'no e-beam on the sample YAG',
                       needs_operator=True, yag=yag)
    if yag['status'].startswith('far'):
        return _result(stage, rec, True, False, 'e-beam far from the cross: '
                       'an operator judges', needs_operator=True, yag=yag)
    auto.go_to(rec, setup, 'andor')
    a = auto.need(setup, 'andor', 'check')
    auto.andor_settings(rec, a['exposure'], a['gain'])
    andor = read_cam(rec, 'cam_far_andor', 3)
    accepted = andor['seen'] and not andor['saturated']
    return _result(stage, rec, True, accepted,
                   'beam on the YAG cross and on the Andor' if accepted
                   else ('Andor saturated' if andor['seen']
                         else 'no beam on the Andor'),
                   needs_operator=not accepted, yag=yag, andor=andor)


# ---------------------------------------------------------------- stage 5
def _peak(grid, vals):
    i = int(np.nanargmax(vals))
    if 0 < i < len(vals) - 1:
        y0, y1, y2 = vals[i - 1], vals[i], vals[i + 1]
        den = y0 - 2 * y1 + y2
        if den < 0:
            h = grid[1] - grid[0]
            return float(grid[i] + 0.5 * h * (y0 - y2) / den)
    return float(grid[i])


def align_collimator(m, setup, step_mm=0.1, fine_step_mm=0.02, n_avg=3,
                     min_transmission=0.02):
    """Procedure (5): with the beam on the Andor, insert the collimator to
    its nominal 90 mm (the 200 um hole; the beam is blocked first, then
    reappears cut), then tune the collimator motor for the most counts on
    the Andor. Beam optimization (solenoids and correctors) comes after, in
    Badger: see plan_beam_optimization."""
    stage = '5 collimator alignment'
    rec = Recorder(m, setup)
    early = _precheck(rec, stage)
    if early:
        return early
    c = auto.need(setup, 'collimator')
    nominal, half = float(c['nominal_mm']), float(c['scan_half_width_mm'])
    auto.go_to(rec, setup, 'andor')
    a = auto.need(setup, 'andor', 'check')
    auto.andor_settings(rec, a['exposure'], a['gain'])
    rec.put('gun_uv_shutter', 1)
    _ensure_collimator_out(rec, setup)
    beam = read_cam(rec, 'cam_far_andor', n_avg)
    if not beam['seen']:
        return _result(stage, rec, True, False, 'no beam on the Andor with '
                       'the collimator out: run beam_on_screens first',
                       needs_operator=True, andor=beam)
    t_out = beam['total']

    def total_at(p):
        rec.put('collimator', float(p))
        rec.sleep(2)
        return avg(rec, 'cam_far_andor.total', n_avg)

    insertion = [(float(p), total_at(p))
                 for p in (nominal - 10.0, nominal - 2.0, nominal)]
    grid = np.round(np.arange(nominal - half, nominal + half + 1e-9,
                              step_mm), 4)
    coarse = [total_at(p) for p in grid]
    if not max(coarse) > 0.002 * t_out:
        _ensure_collimator_out(rec, setup)
        return _result(stage, rec, True, False, 'no transmission anywhere '
                       f'within {nominal:g} +/- {half:g} mm: the beam misses '
                       'the hole (steer with XC/YC00, see '
                       'plan_beam_optimization)', needs_operator=True,
                       insertion=insertion, scan_mm=grid, scan_total=coarse)
    best = _peak(grid, coarse)
    fgrid = np.round(np.arange(best - step_mm, best + step_mm + 1e-9,
                               fine_step_mm), 4)
    fine = [total_at(p) for p in fgrid]
    best = _peak(fgrid, fine)
    t_in = total_at(best)
    frac = t_in / t_out if t_out > 0 else float('nan')
    edge = abs(best - nominal) > half - step_mm
    accepted = frac >= min_transmission and not edge
    after = read_cam(rec, 'cam_far_andor', n_avg)
    return _result(stage, rec, True, accepted,
                   'collimator tuned for transmission' if accepted else
                   ('best point at the edge of the scan' if edge
                    else 'transmission below threshold'),
                   needs_operator=not accepted, collimator_mm=best,
                   transmission=frac, andor_counts_out=t_out,
                   andor_counts_in=t_in, andor=after, insertion=insertion,
                   scan_mm=grid, scan_total=coarse, fine_mm=fgrid,
                   fine_total=fine)


OPT_VARIABLES = ('sol1', 'sol2', 'xc00', 'yc00', 'xc01', 'yc01', 'xc02',
                 'yc02')


def measure_andor_spot(m, setup, n=3):
    """Read-only: the Andor beam spot (size, counts, offset from the image
    centre) as the optimization objective sees it."""
    a = read_cam(m, 'cam_far_andor', n)
    cx, cy = (float(m.get('cam_far_andor.size_x')) / 2,
              float(m.get('cam_far_andor.size_y')) / 2)
    size = (math.sqrt(a['sigma_x'] * a['sigma_y']) if a['seen']
            else float('nan'))
    off = (math.hypot(a['centroid_x'] - cx, a['centroid_y'] - cy)
           if a['seen'] else float('nan'))
    return _num({'stage': 'andor spot', 'ok': True, 'seen': a['seen'],
                 'spot_size_px': size, 'total': a['total'],
                 'offset_from_centre_px': off, 'saturated': a['saturated'],
                 'andor': a})


def plan_beam_optimization(m, setup, span_fraction=0.1, include_xc04=True,
                           min_total_fraction=0.8, max_offset_px=100.0,
                           multi_objective=False):
    """Read-only: an Xopt/Badger VOCS for the co-tuning after the collimator
    (procedure 5): minimize the Andor spot size with Sol1, Sol2 and
    XC/YC00-02, keeping the transmitted counts above a level; XC/YC04 keep
    the beam near the Andor centre. With multi_objective, the counts become
    a second objective (maximize), the proposal's multi-objective routine.
    Ranges: current value +/- span_fraction of the safety range, clipped to
    it. The routine runs in Badger with an operator, the write path the
    proposal names; it escalates if it does not converge."""
    limits = setup.get('limits') or {}
    names = OPT_VARIABLES + (('xc04', 'yc04') if include_xc04 else ())
    variables, current = {}, {}
    for n in names:
        v = float(m.get(n))
        current[n] = v
        lo, hi = limits.get(n, (v - 1.0, v + 1.0))
        span = span_fraction * (float(hi) - float(lo))
        variables[n] = [max(float(lo), v - span), min(float(hi), v + span)]
    spot = measure_andor_spot(m, setup)
    total = spot['total'] or 0.0
    objectives = {'andor_spot_size_px': 'MINIMIZE'}
    constraints = {}
    if multi_objective:
        objectives['andor_total'] = 'MAXIMIZE'
        generator = ('mobo (multi-objective Bayesian optimization, '
                     'expected hypervolume improvement)')
    else:
        constraints['andor_total'] = ['GREATER_THAN',
                                      round(min_total_fraction * total, 1)]
        generator = ('expected_improvement (or neldermead for a quick local '
                     'search)')
    if include_xc04:
        constraints['andor_offset_from_centre_px'] = ['LESS_THAN',
                                                      max_offset_px]
    return _num({
        'stage': 'beam optimization plan', 'ok': True,
        'vocs': {'variables': variables, 'objectives': objectives,
                 'constraints': constraints},
        'current': current, 'now': spot, 'generator': generator,
        'escalate_if': 'the routine has not cut the spot size by 10 % within '
                       '50 evaluations, or the counts fall below the '
                       'constraint at the best point: the proposal escalates '
                       'to the operator when it does not converge',
        'roles': {'xc00/yc00': 'keep the beam aligned through the collimator',
                  'xc01/yc01, xc02/yc02': 'keep the beam pointing the same '
                                          'on the sample-chamber YAG',
                  'xc04/yc04': 'keep the beam near the Andor centre (lens '
                               'aberration spoils the size far off it)'},
        'after': 'check the e-beam on the YAG cross again '
                 '(check_overlap or beam_on_screens)',
        'units_note': 'on the real machine solenoids and correctors are in '
                      'BCTRL units (kG-m, or A for SOL2 and XC/YC04)'})


# ---------------------------------------------------------------- stage 6
def overlap_pump_laser(m, setup, step_mm=0.2, tolerance_px=3.0, max_iter=6):
    """Procedure (6): the e-beam on the YAG cross as in (4); keep the light
    off, laser view; pump HWP to its minimum-energy setpoint; open the pump
    shutter; steer the pump mirror (lens) H and V onto the cross; close the
    pump shutter (critical: no unplanned shot at the sample); full view."""
    stage = '6 e-beam / laser overlap'
    rec = Recorder(m, setup)
    early = _precheck(rec, stage)
    if early:
        return early
    yag = check_ebeam_on_yag(rec, setup, move_cross=True)
    if not yag['seen'] or yag['status'].startswith('far'):
        auto.set_view(rec, setup, 'full_view')
        return _result(stage, rec, True, False, 'e-beam not on the YAG '
                       'cross: ' + yag['status'], needs_operator=True,
                       yag=yag)
    target = np.array(yag['cross_px'])
    _laser_view(rec, setup)

    def laser():
        r = read_cam(rec, 'cam_sample_yag', 3)
        return np.array([r['centroid_x'], r['centroid_y']]), r

    resp, hist = None, []
    try:
        for _ in range(max_iter):
            pos, r = laser()
            if not r['seen']:
                break
            err = pos - target
            hist.append({'laser_px': pos.round(2).tolist(),
                         'error_px': err.round(2).tolist()})
            if np.hypot(*err) < 0.5 * tolerance_px:
                break
            if resp is None:
                cols = []
                for lens in ('pump_lens_h', 'pump_lens_v'):
                    v = float(rec.get(lens))
                    rec.put(lens, v + step_mm)
                    rec.sleep(1)
                    cols.append((laser()[0] - pos) / step_mm)
                    rec.put(lens, v)
                resp = np.column_stack(cols)        # px per mm
            try:
                dm = np.clip(-np.linalg.solve(resp, err), -0.5, 0.5)
            except np.linalg.LinAlgError:
                break
            for lens, d in zip(('pump_lens_h', 'pump_lens_v'), dm):
                rec.put(lens, float(rec.get(lens)) + float(d))
            rec.sleep(1)
        pos, r = laser()
    finally:
        auto.close_pump_shutter(rec)                # critical
    err = pos - target
    seen = r['seen']
    rec.put('gun_uv_shutter', 1)
    auto.set_view(rec, setup, 'full_view')
    accepted = seen and np.hypot(*err) < tolerance_px
    return _result(stage, rec, seen, accepted,
                   'laser and e-beam on the cross' if accepted else
                   ('laser not on the YAG' if not seen
                    else 'overlap short of tolerance'),
                   needs_operator=not accepted, yag=yag,
                   cross_px=target.tolist(),
                   final_error_px=float(np.hypot(*err)) if seen else None,
                   iterations=hist,
                   lens_mm={k: _num(rec.get(k)) for k in
                            ('pump_lens_h', 'pump_lens_v')})


def check_overlap(m, setup, tolerance_px=3.0):
    """The overlap check of procedure (8) step 2, without steering: e-beam
    and pump laser against the YAG cross. Pump shutter closed again after."""
    stage = 'overlap check'
    rec = Recorder(m, setup)
    early = _precheck(rec, stage)
    if early:
        return early
    yag = check_ebeam_on_yag(rec, setup, move_cross=False)
    laser = None
    if yag['seen']:
        try:
            _laser_view(rec, setup)
            laser = read_cam(rec, 'cam_sample_yag', 3)
        finally:
            auto.close_pump_shutter(rec)
    rec.put('gun_uv_shutter', 1)
    auto.set_view(rec, setup, 'full_view')
    cross = yag['cross_px']
    d_e = yag['distance_px']
    d_l = (math.hypot(laser['centroid_x'] - cross[0],
                      laser['centroid_y'] - cross[1])
           if laser and laser['seen'] else None)
    ok = d_e is not None and d_l is not None and \
        d_e <= tolerance_px and d_l <= tolerance_px
    return _result(stage, rec, True, ok,
                   'e-beam and laser on the cross' if ok
                   else 'not overlapped: run overlap_pump_laser',
                   needs_operator=not ok, ebeam_off_cross_px=d_e,
                   laser_off_cross_px=d_l, yag=yag, laser=laser)


# ---------------------------------------------------------------- stage 7
def _into_through_hole(rec, setup, kick=0.2, max_iter=6, n_avg=3):
    """Steer XC/YC04 until the main beam vanishes into the Andor's through
    hole (at the low-gain check settings)."""
    hole = np.array(auto.need(setup, 'andor', 'through_hole_px'), float)
    radius = float(auto.need(setup, 'andor', 'through_hole_radius_px'))
    first = read_cam(rec, 'cam_far_andor', n_avg)
    hist = []
    if not first['seen']:
        return {'in_hole': False, 'why': 'no main beam on the Andor',
                'history': hist}
    resp = None
    for _ in range(max_iter):
        r = read_cam(rec, 'cam_far_andor', n_avg)
        gone = (not r['seen']) or r['total'] < 0.1 * first['total']
        if gone:
            return {'in_hole': True, 'history': hist}
        pos = np.array([r['centroid_x'], r['centroid_y']])
        err = pos - hole
        hist.append({'beam_px': pos.round(1).tolist(),
                     'error_px': err.round(1).tolist()})
        if resp is None:
            cols = []
            for k in ('xc04', 'yc04'):
                v = float(rec.get(k))
                rec.put(k, v + kick)
                rec.sleep(1)
                r2 = read_cam(rec, 'cam_far_andor', n_avg)
                cols.append((np.array([r2['centroid_x'], r2['centroid_y']])
                             - pos) / kick)
                rec.put(k, v)
            resp = np.column_stack(cols)
        try:
            dk = np.clip(-np.linalg.solve(resp, err), -1.0, 1.0)
        except np.linalg.LinAlgError:
            break
        for k, d in zip(('xc04', 'yc04'), dk):
            rec.put(k, float(rec.get(k)) + float(d))
        rec.sleep(1)
    r = read_cam(rec, 'cam_far_andor', n_avg)
    gone = (not r['seen']) or r['total'] < 0.1 * first['total']
    return {'in_hole': bool(gone), 'radius_px': radius, 'history': hist,
            'why': '' if gone else 'main beam still outside the hole'}


def tune_sample_position(m, setup, sample='bi', span_mm=0.15, points=7,
                         n_avg=2, single_crystal=False, angle_span_deg=0.5,
                         angle_points=5):
    """Procedure (7): full view; go to the sample; steer XC/YC04 so the main
    beam goes through the Andor's through hole (else it saturates the Andor
    at high gain); Andor stop -> exposure 2 s, gain 1000 -> start; raster
    the stage x, y for the pattern (total scattering intensity and, where a
    score exists, pattern quality). For a single crystal the pitch/yaw scan
    runs only if those channels are writable: for now they are not, and
    the operator balances the symmetry by hand.
    Saves the candidate with the Andor and chamber-camera images and the
    machine settings. Always needs an operator to judge the pattern."""
    stage = '7 sample position'
    rec = Recorder(m, setup)
    early = _precheck(rec, stage)
    if early:
        return early
    auto.set_view(rec, setup, 'full_view')
    auto.go_to(rec, setup, sample)
    a = auto.need(setup, 'andor')
    auto.andor_settings(rec, a['check']['exposure'], a['check']['gain'])
    rec.put('gun_uv_shutter', 1)
    hole = _into_through_hole(rec, setup)
    if not hole['in_hole']:
        return _result(stage, rec, True, False, 'main beam not in the Andor '
                       'through hole: ' + hole['why'], needs_operator=True,
                       through_hole=hole)
    d = a['diffraction']
    auto.andor_settings(rec, d['exposure'], d['gain'])
    if read_cam(rec, 'cam_far_andor', 1)['saturated']:
        auto.andor_settings(rec, a['check']['exposure'], a['check']['gain'])
        return _result(stage, rec, True, False, 'Andor saturated at the '
                       'diffraction settings', needs_operator=True,
                       through_hole=hole)
    pos0 = auto.need(setup, 'positions', sample)

    def metrics():
        inten = avg(rec, 'cam_far_andor.total', n_avg)
        try:
            q = avg(rec, 'pattern_quality', n_avg)
        except Exception:                   # no score on the real machine
            q = float('nan')
        return inten, q

    xs = float(pos0['x']) + np.linspace(-span_mm, span_mm, points)
    ys = float(pos0['y']) + np.linspace(-span_mm, span_mm, points)
    inten = np.full((points, points), np.nan)
    qual = np.full((points, points), np.nan)
    for j, y in enumerate(ys):        # serpentine: every other row back,
        cols = range(points) if j % 2 == 0 else range(points - 1, -1, -1)
        for i in cols:                  # so the stage never runs back empty
            x = xs[i]
            rec.put('sample_x', float(x))
            rec.put('sample_y', float(y))
            rec.sleep(1)
            inten[j, i], qual[j, i] = metrics()
    if not np.isfinite(inten).any() or np.nanmax(inten) <= 0:
        return _result(stage, rec, True, False, 'no diffraction anywhere in '
                       'the raster', needs_operator=True, through_hole=hole)
    score = inten / np.nanmax(inten)
    if np.isfinite(qual).any():
        score = score * np.nan_to_num(qual)
    j, i = np.unravel_index(np.nanargmax(score), score.shape)
    rec.put('sample_x', float(xs[i]))
    rec.put('sample_y', float(ys[j]))
    rec.sleep(1)
    angles = None
    angles_by_tool = (CHANNELS['sample_pitch'].writable
                      and CHANNELS['sample_yaw'].writable)
    if single_crystal and not angles_by_tool:
        rec.operator_steps.append(
            'single crystal: balance the pattern symmetry with the sample '
            'pitch and yaw by hand (the tools do not move them for now), '
            'then rerun or save the position')
    if single_crystal and angles_by_tool:
        best, angles = (-1.0, None), []
        p0 = float(rec.get('sample_pitch'))
        y0 = float(rec.get('sample_yaw'))
        for dp in np.linspace(-angle_span_deg, angle_span_deg, angle_points):
            for dy in np.linspace(-angle_span_deg, angle_span_deg,
                                  angle_points):
                rec.put('sample_pitch', p0 + dp)
                rec.put('sample_yaw', y0 + dy)
                rec.sleep(1)
                it, q = metrics()
                s = it * (q if math.isfinite(q) else 1.0)
                angles.append((p0 + dp, y0 + dy, it, q))
                if s > best[0]:
                    best = (s, (p0 + dp, y0 + dy))
        rec.put('sample_pitch', best[1][0])
        rec.put('sample_yaw', best[1][1])
        rec.sleep(1)
    it, q = metrics()
    here = auto.current_position(rec)
    settings = {n: rec.get(n) for n in (
        'preq', 'areq', 'gun_uv_throttle', 'sol1', 'sol2', 'collimator',
        'pump_hwp', 'delay', 'cam_far_andor.exposure', 'cam_far_andor.gain',
        *[f'{p}c{k:02d}' for k in range(5) for p in 'xy'])}
    record = auto.save_record(f'good_position_{sample}', {
        'sample': sample, 'position': here, 'intensity': it,
        'pattern_quality': q, 'settings': _num(settings),
        'raster_x_mm': xs, 'raster_y_mm': ys,
        'raster_intensity': inten, 'raster_quality': qual},
        arrays={'andor_image': rec.image('cam_far_andor'),
                'chamber_image': rec.image('cam_sample_yag')})
    accepted = it > 0 and (not math.isfinite(q) or q > 0.6)
    return _result(stage, rec, True, accepted,
                   'best raster point set; an operator judges the pattern '
                   f'and saves it with save_position({sample!r})',
                   needs_operator=True, sample=sample, position=here,
                   intensity=it, quality=q, through_hole=hole,
                   raster_x_mm=xs, raster_y_mm=ys,
                   raster_intensity=np.round(inten, 1),
                   raster_quality=np.round(qual, 3), angles=angles,
                   record=record)


# ---------------------------------------------------------------- stage 8
def _erf_model(d, i0, a, d0, w):
    from scipy.special import erf
    return i0 * (1 - a * 0.5 * (1 + erf((d - d0) / (math.sqrt(2) * w))))


def _fit_step(ds, ss):
    from scipy.optimize import curve_fit
    ds, ss = np.asarray(ds), np.asarray(ss)
    ok = np.isfinite(ss)
    ds, ss = ds[ok], ss[ok]
    if len(ds) < 6:
        return None
    g = np.gradient(ss, ds)
    p0 = [float(ss[:3].mean()), max(float(ss.max() - ss.min()), 0.01),
          float(ds[int(np.argmin(g))]), max(abs(ds[1] - ds[0]), 0.005)]
    try:
        p, cov = curve_fit(_erf_model, ds, ss, p0=p0, maxfev=20000)
    except Exception:
        return None
    err = np.sqrt(np.diag(cov))
    return {'i0': p[0], 'drop': p[1], 't0_mm': p[2], 'width_mm': abs(p[3]),
            't0_err_mm': err[2], 'residual': float(np.std(
                ss - _erf_model(ds, *p)))}


def find_time_zero(m, setup, sample='bi', center_mm=None, coarse_span_mm=3.0,
                   coarse_points=31, fine_span_mm=0.3, fine_points=31,
                   n_avg=4, target_err_mm=0.005, overlap_tolerance_px=3.0):
    """Procedure (8): verify the spatial overlap (6) on the YAG; go to the
    sample (Bi); Andor at the diffraction settings; pump HWP to its
    pump-probe setpoint (~2 uJ); open the pump shutter; delay scans that
    zoom in on the Bragg-peak drop (a stand-in for the LCLS DAQ scan or the
    Run 6 BOED script); close the pump shutter."""
    stage = '8 time zero'
    ov = check_overlap(m, setup, overlap_tolerance_px)
    if not ov['accepted']:
        return {**ov, 'stage': stage, 'reason': 'overlap check failed: '
                + ov['reason']}
    rec = Recorder(m, setup)
    early = _precheck(rec, stage)
    if early:
        return early
    auto.go_to(rec, setup, sample)
    d = auto.need(setup, 'andor', 'diffraction')
    auto.andor_settings(rec, d['exposure'], d['gain'])
    rec.put('gun_uv_shutter', 1)
    auto.pump_energy(rec, setup, 'pump_probe')
    auto.power_meter_out(rec, setup)
    c = float(center_mm if center_mm is not None else rec.get('delay'))

    def sig(dl):
        rec.put('delay', float(dl))
        rec.sleep(0.2)
        return avg(rec, 'diffraction_signal', n_avg)

    rec.put('pump_shutter', 1)
    try:
        coarse = [(float(dl), sig(dl)) for dl in
                  np.linspace(c - coarse_span_mm, c + coarse_span_mm,
                              coarse_points)]
        f1 = _fit_step(*zip(*coarse)) if any(
            math.isfinite(s) for _, s in coarse) else None
        if f1 is None or f1['drop'] < 0.01:
            return _result(stage, rec, True, False, 't0 not found in the '
                           'coarse window', needs_operator=True,
                           coarse=coarse)
        f2, fine, levels = f1, [], [{'span_mm': coarse_span_mm, **f1}]
        for span in (fine_span_mm, fine_span_mm / 10):
            fine = [(float(dl), sig(dl)) for dl in
                    np.linspace(f2['t0_mm'] - span, f2['t0_mm'] + span,
                                fine_points)]
            f = _fit_step(*zip(*fine))
            if f is None:
                break
            f2 = f
            levels.append({'span_mm': span, **f})
            if f2['t0_err_mm'] < target_err_mm:
                break
        rec.put('delay', float(f2['t0_mm']))
    finally:
        auto.close_pump_shutter(rec)
    accepted = f2['t0_err_mm'] < target_err_mm and f2['drop'] > 0.01
    record = auto.save_record('time_zero', {
        'sample': sample, 't0_mm': f2['t0_mm'], 'levels': levels,
        'coarse': coarse, 'fine': fine})
    return _result(stage, rec, True, accepted,
                   't0 found' if accepted else 't0 uncertain',
                   needs_operator=not accepted, overlap=ov,
                   t0_mm=f2['t0_mm'], t0_err_fs=f2['t0_err_mm'] * PS_PER_MM
                   * 1e3, width_fs=f2['width_mm'] * PS_PER_MM * 1e3,
                   bragg_drop=f2['drop'], coarse=coarse, fine=fine,
                   levels=levels, record=record)


STAGES = {
    'gun_ramp': gun_ramp,
    'schottky_scan': schottky_scan,
    'set_bunch_charge': set_bunch_charge,
    'beam_on_screens': beam_on_screens,
    'align_collimator': align_collimator,
    'overlap_pump_laser': overlap_pump_laser,
    'tune_sample_position': tune_sample_position,
    'find_time_zero': find_time_zero,
}
HELPERS = {
    'check_overlap': check_overlap,
    'monitor_charge': monitor_charge,
    'measure_andor_spot': measure_andor_spot,
    'plan_beam_optimization': plan_beam_optimization,
}
