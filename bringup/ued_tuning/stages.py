"""UED bring-up stages, one procedure each (proposal, Workflow 1 + 2).

Every procedure talks only to a backend with get(name), put(name, value),
sleep(seconds), time() and saved_positions(): sim/virtual_ued.py today,
the EPICS backend later. Names are the logical channels in channels.py.

Each returns a dict: whether it ran (`ok`), whether the result meets the
stage's acceptance check (`accepted`), why, what it measured, and an I/O
log of every write it made with the real PV behind it — the list of things
the stage would touch on the beamline.

  1 gun_ramp            ramp AREQ to the target (bringup/gun_ramp.py)
  2 schottky_scan       charge vs gun phase; set phase = zero crossing + offset
  3 set_bunch_charge    UV throttle feedback onto a target charge (Faraday cup)
  4 beam_on_screens     find the beam on the Diag YAG and the far detector
  5 align_collimator    XC/YC00 for transmission, XC/YC01 onto the detector
  6 overlap_pump_laser  pump laser onto the e-beam marker on the sample camera
  7 tune_sample_position  raster the sample for pattern quality (escalates)
  8 find_time_zero      pump-probe delay scan, erf fit (stand-in for BOED)
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter

import numpy as np

from .channels import CHANNELS, HOLDER_FC, HOLDER_OUT, HOLDER_YAG

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
from gun_ramp import RampConfig, ramp  # noqa: E402  (bringup/gun_ramp.py)

PS_PER_MM = 2e-3 / 299792458 * 1e12


class Recorder:
    """Forward every call to the backend; log writes and read counts."""

    def __init__(self, backend):
        self.m = backend
        self.puts = []
        self.reads = Counter()
        self.t0 = backend.time()

    def get(self, name):
        self.reads[name] += 1
        return self.m.get(name)

    def put(self, name, value):
        self.puts.append((round(self.m.time() - self.t0, 1), name, value))
        self.m.put(name, value)

    def sleep(self, seconds):
        self.m.sleep(seconds)

    def time(self):
        return self.m.time()

    def saved_positions(self):
        return self.m.saved_positions()


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


def _result(stage, rec, ok, accepted, reason, **data):
    writes = [{'t_s': t, 'channel': n, 'value': _num(v),
               'pv': CHANNELS[n].pv, 'status': CHANNELS[n].status}
              for t, n, v in rec.puts]
    shown = writes if len(writes) <= 24 else writes[:18] + writes[-6:]
    return {
        'stage': stage, 'ok': bool(ok), 'accepted': bool(accepted),
        'reason': reason,
        'machine_time_s': round(rec.time() - rec.t0, 1),
        'n_writes': len(writes), 'n_reads': sum(rec.reads.values()),
        'channels_written': sorted({w['channel'] for w in writes}),
        'channels_read': sorted(rec.reads),
        'writes': shown,
        **{k: _num(v) for k, v in data.items()},
    }


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


def set_camera(m, cam, exposure, gain):
    m.put(f'{cam}.exposure', exposure)
    m.put(f'{cam}.gain', gain)


def move_stage(m, where):
    x, y, z = m.saved_positions()[where]
    m.put('sample_x', x)
    m.put('sample_y', y)
    m.put('sample_z', z)
    m.sleep(5)


# ---------------------------------------------------------------- stage 1
def gun_ramp(m, target=0.53, n_steps=300, dwell_s=2.0):
    rec = Recorder(m)
    res = ramp(rec, RampConfig(target=target, n_steps=n_steps,
                               dwell_s=dwell_s))
    aact = avg(rec, 'aact', 5)
    fb = (rec.get('pfb_status'), rec.get('afb_status'))
    accepted = (res.ok and abs(aact - target) <= 0.02 * target
                and fb == ('Active', 'Active'))
    return _result('1 gun ramp-up', rec, res.ok, accepted, res.reason,
                   target=target, aact=aact, feedbacks=list(fb),
                   max_temp_C=max(r['temp'] for r in res.trace),
                   ramp_steps=len(res.trace))


# ---------------------------------------------------------------- stage 2
def schottky_scan(m, coarse_step=10.0, fine_step=1.0, operating_offset=37.0,
                  n_avg=3):
    rec = Recorder(m)
    rec.put('diag_holder', HOLDER_FC)
    rec.put('gun_uv_shutter', 1)
    rec.sleep(1)

    def q_at(ph):
        rec.put('preq', ph % 360.0)
        rec.sleep(0.5)
        return avg(rec, 'fc_charge', n_avg)

    coarse = [(float(p), q_at(p)) for p in np.arange(0, 360, coarse_step)]
    qs = np.array([q for _, q in coarse])
    qmax = np.nanmax(qs) if np.isfinite(qs).any() else float('nan')
    if not qmax > 0.05:
        return _result('2 Schottky scan', rec, False, False,
                       'no charge on the Faraday cup at any phase',
                       coarse=coarse)
    thr = 0.1 * qmax
    rising = [i for i in range(len(qs)) if qs[i - 1] < thr <= qs[i]]
    if len(rising) != 1:
        return _result('2 Schottky scan', rec, False, False,
                       f'{len(rising)} rising edges in the coarse scan',
                       coarse=coarse)
    edge = coarse[rising[0]][0]
    fine = [(float(p), q_at(p)) for p in
            np.arange(edge - coarse_step - 4, edge + 6.01, fine_step)]
    pts = [(p, q) for p, q in fine if 0.05 * qmax < q < 0.5 * qmax]
    if len(pts) >= 2:
        slope, icpt = np.polyfit([p for p, _ in pts], [q for _, q in pts], 1)
        zc = -icpt / slope
    else:   # a steep edge: interpolate the first point above 5 %
        i = next(i for i, (_, q) in enumerate(fine) if q > 0.05 * qmax)
        (p0, q0), (p1, q1) = fine[i - 1], fine[i]
        zc = p0 + (0.05 * qmax - q0) * (p1 - p0) / (q1 - q0)
    op = (zc + operating_offset) % 360.0
    rec.put('preq', op)
    rec.sleep(1)
    q_op = avg(rec, 'fc_charge', 5)
    accepted = q_op > 0.3 * qmax
    return _result('2 Schottky scan', rec, True, accepted,
                   'zero crossing found' if accepted
                   else 'little charge at the operating phase',
                   zero_crossing_deg=zc % 360.0, operating_phase_deg=op,
                   operating_offset_deg=operating_offset,
                   charge_at_operating_fC=q_op, charge_max_fC=qmax,
                   coarse=coarse, fine=fine)


# ---------------------------------------------------------------- stage 3
def set_bunch_charge(m, target_fC=10.0, tolerance=0.05, theta_min=21.0,
                     theta_max=66.0, max_iter=10, n_avg=5):
    """UV throttle feedback onto the Faraday-cup charge (secant steps).

    Charge falls monotonically from theta_min (full transmission, the
    throttle's 'max@21') to theta_max.
    """
    rec = Recorder(m)
    rec.put('diag_holder', HOLDER_FC)
    rec.put('gun_uv_shutter', 1)
    rec.sleep(1)

    def q_at(th):
        rec.put('gun_uv_throttle', th)
        rec.sleep(2)
        return avg(rec, 'fc_charge', n_avg)

    th0 = float(rec.get('gun_uv_throttle'))
    q0 = avg(rec, 'fc_charge', n_avg)
    hist = [(th0, q0)]
    th1 = float(np.clip(th0 + (2.0 if q0 > target_fC else -2.0),
                        theta_min, theta_max))
    q1 = q_at(th1)
    hist.append((th1, q1))
    for _ in range(max_iter):
        if abs(q1 - target_fC) <= tolerance * target_fC:
            break
        slope = (q1 - q0) / (th1 - th0) if th1 != th0 else 0.0
        step = ((target_fC - q1) / slope if slope < 0
                else (2.0 if q1 > target_fC else -2.0))
        th2 = float(np.clip(th1 + np.clip(step, -8, 8), theta_min, theta_max))
        th0, q0, th1, q1 = th1, q1, th2, q_at(th2)
        hist.append((th1, q1))
    accepted = abs(q1 - target_fC) <= tolerance * target_fC
    return _result('3 pulse charge', rec, True, accepted,
                   'charge on target' if accepted else 'did not converge',
                   target_fC=target_fC, charge_fC=q1, throttle_deg=th1,
                   iterations=hist)


# ---------------------------------------------------------------- stage 4
def beam_on_screens(m, gige_gain=30.0, gige_exposure=2.0, andor_gain=10.0,
                    andor_exposure=0.1):
    rec = Recorder(m)
    rec.put('gun_uv_shutter', 1)
    # Diag YAG (shares the inserter with the Faraday cup)
    rec.put('diag_holder', HOLDER_YAG)
    gain = gige_gain
    set_camera(rec, 'cam_diag_yag', gige_exposure, gain)
    rec.sleep(2)
    yag = read_cam(rec, 'cam_diag_yag')
    while yag['saturated'] and gain > 0:
        gain = max(gain - 10, 0)
        rec.put('cam_diag_yag.gain', gain)
        rec.sleep(2)
        yag = read_cam(rec, 'cam_diag_yag')
    # Far detector: inserter and sample out, collimator retracted first
    rec.put('diag_holder', HOLDER_OUT)
    rec.put('collimator', 0)
    move_stage(rec, 'out')
    set_camera(rec, 'cam_far_andor', andor_exposure, andor_gain)
    rec.sleep(2)
    far_out = read_cam(rec, 'cam_far_andor')
    rec.put('collimator', 1)
    rec.sleep(2)
    far_in = read_cam(rec, 'cam_far_andor')
    accepted = yag['seen'] and far_out['seen'] and not (
        yag['saturated'] or far_out['saturated'])
    reason = ('beam on both screens' if accepted else
              'beam missing or saturated on a screen')
    frac = (far_in['total'] / far_out['total']
            if far_out['total'] > 0 else float('nan'))
    return _result('4 beam on YAG & EMCCD', rec, True, accepted, reason,
                   diag_yag=yag, far_collimator_out=far_out,
                   far_collimator_in=far_in, collimator_pass_fraction=frac,
                   diag_yag_gain_used=gain)


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


def align_collimator(m, span=1.5, points=11, sweeps=2, steer_kick=0.2,
                     steer_iters=5, tolerance_px=2.0, n_avg=2):
    rec = Recorder(m)
    rec.put('gun_uv_shutter', 1)
    rec.put('diag_holder', HOLDER_OUT)
    rec.put('collimator', 1)
    move_stage(rec, 'out')
    set_camera(rec, 'cam_far_andor', 0.1, 10.0)
    rec.sleep(2)

    def total():
        return avg(rec, 'cam_far_andor.total', n_avg)

    t_start = total()
    scans = []
    for _ in range(sweeps):
        for knob in ('xc00', 'yc00'):
            c = float(rec.get(knob))
            grid = c + np.linspace(-span, span, points)
            vals = []
            for k in grid:
                rec.put(knob, float(k))
                rec.sleep(0.5)
                vals.append(total())
            vals = np.array(vals)
            if np.nanmax(vals) > 5000:
                best = _peak(grid, vals)
            else:
                best = c                # nothing through: keep, widen next
            rec.put(knob, best)
            scans.append({'knob': knob, 'grid': grid.round(4).tolist(),
                          'total': vals.round(0).tolist(), 'set': best})
        span, points = span / 2, max(7, points - 4)
    t_best = total()
    if not t_best > 5000:
        return _result('5 collimator alignment', rec, True, False,
                       'no transmission found within the scan range',
                       transmission_start=t_start, scans=scans)

    nx, ny = rec.get('cam_far_andor.size_x'), rec.get('cam_far_andor.size_y')
    target = np.array([nx / 2, ny / 2])

    def centroid():
        r = read_cam(rec, 'cam_far_andor')
        return np.array([r['centroid_x'], r['centroid_y']])

    steering = []
    for _ in range(steer_iters):
        c0 = centroid()
        err = c0 - target
        steering.append({'centroid_px': c0.round(2).tolist(),
                         'error_px': err.round(2).tolist()})
        if np.hypot(*err) < tolerance_px:
            break
        cols = []
        for knob in ('xc01', 'yc01'):
            k = float(rec.get(knob))
            rec.put(knob, k + steer_kick)
            rec.sleep(0.5)
            cols.append((centroid() - c0) / steer_kick)
            rec.put(knob, k)
        resp = np.column_stack(cols)            # px per mrad
        try:
            dk = np.clip(-np.linalg.solve(resp, err), -2.0, 2.0)
        except np.linalg.LinAlgError:
            break
        for knob, d in zip(('xc01', 'yc01'), dk):
            rec.put(knob, float(rec.get(knob)) + float(d))
        rec.sleep(0.5)
    c_final = centroid()
    err = c_final - target
    t_final = total()
    accepted = t_final >= 0.85 * t_best and np.hypot(*err) < tolerance_px
    return _result('5 collimator alignment', rec, True, accepted,
                   'transmission peaked and beam centred' if accepted else
                   'transmission or centring short of the target',
                   transmission_counts_start=t_start,
                   transmission_counts_best=t_best,
                   transmission_counts_final=t_final,
                   centre_error_px=float(np.hypot(*err)),
                   kicks_mrad={k: _num(rec.get(k)) for k in
                               ('xc00', 'yc00', 'xc01', 'yc01')},
                   scans=scans, steering=steering)


# ---------------------------------------------------------------- stage 6
def overlap_pump_laser(m, step_mm=0.2, tolerance_px=3.0, max_iter=6):
    rec = Recorder(m)
    cam = 'cam_sample_yag'
    move_stage(rec, 'yag')
    rec.put('diag_holder', HOLDER_OUT)
    light = int(rec.get('chamber_light'))
    rec.put('chamber_light', 0)                # the camera sees the YAG only
    # e-beam marker: pump blocked, e-beam settings (gain 30, 2 s; run 4)
    rec.put('pump_shutter', 0)
    rec.put('gun_uv_shutter', 1)
    set_camera(rec, cam, 2.0, 30.0)
    rec.sleep(3)
    e = read_cam(rec, cam, 5)
    if not e['seen']:
        return _result('6 e-beam / laser overlap', rec, False, False,
                       'no e-beam on the sample YAG', ebeam=e)
    marker = np.array([e['centroid_x'], e['centroid_y']])
    # mark it on the camera overlay, where operators look for it
    rec.put('cam_sample_yag.cross_x', round(float(marker[0])))
    rec.put('cam_sample_yag.cross_y', round(float(marker[1])))
    # laser: e-beam blocked, pump at its lowest, laser settings (gain 0, 0.1 s)
    rec.put('gun_uv_shutter', 0)
    energy = float(rec.get('pump_energy'))
    rec.put('pump_energy', 0.01)
    rec.put('pump_power_meter', 0)             # out of the pump beam
    rec.put('pump_shutter', 1)
    set_camera(rec, cam, 0.1, 0.0)
    rec.sleep(3)

    def laser():
        r = read_cam(rec, cam, 3)
        return np.array([r['centroid_x'], r['centroid_y']]), r

    resp, hist = None, []
    for _ in range(max_iter):
        pos, r = laser()
        if not r['seen']:
            break
        err = pos - marker
        hist.append({'laser_px': pos.round(2).tolist(),
                     'error_px': err.round(2).tolist()})
        if np.hypot(*err) < 0.5 * tolerance_px:   # aim inside, verify after
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
    err = pos - marker
    seen = r['seen']
    # restore: pump closed and back to its energy, e-beam on, light as found
    rec.put('pump_shutter', 0)
    rec.put('pump_energy', energy)
    rec.put('gun_uv_shutter', 1)
    rec.put('chamber_light', light)
    accepted = seen and np.hypot(*err) < tolerance_px
    return _result('6 e-beam / laser overlap', rec, seen, accepted,
                   'laser on the e-beam marker' if accepted else
                   ('laser not on the YAG' if not seen else
                    'overlap short of tolerance'),
                   marker_px=marker.round(2).tolist(),
                   final_error_px=float(np.hypot(*err)) if seen else None,
                   iterations=hist,
                   lens_mm={k: _num(rec.get(k)) for k in
                            ('pump_lens_h', 'pump_lens_v')})


# ---------------------------------------------------------------- stage 7
def tune_sample_position(m, sample='bi', span_mm=0.15, points=7, n_avg=2):
    rec = Recorder(m)
    x0, y0, z0 = rec.saved_positions()[sample]
    rec.put('diag_holder', HOLDER_OUT)
    rec.put('pump_shutter', 0)
    rec.put('gun_uv_shutter', 1)
    rec.put('sample_z', z0)
    xs = x0 + np.linspace(-span_mm, span_mm, points)
    ys = y0 + np.linspace(-span_mm, span_mm, points)
    grid = np.full((points, points), np.nan)
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            rec.put('sample_x', float(x))
            rec.put('sample_y', float(y))
            rec.sleep(1)
            grid[j, i] = avg(rec, 'pattern_quality', n_avg)
    if not np.isfinite(grid).any():
        return _result('7 sample position', rec, False, False,
                       'no diffraction pattern anywhere in the raster',
                       needs_operator=True)
    j, i = np.unravel_index(np.nanargmax(grid), grid.shape)
    rec.put('sample_x', float(xs[i]))
    rec.put('sample_y', float(ys[j]))
    rec.sleep(1)
    q = avg(rec, 'pattern_quality', 4)
    return _result('7 sample position', rec, True, bool(q > 0.6),
                   'best raster point set; an operator confirms the '
                   'pattern (escalates by design)',
                   needs_operator=True, sample=sample,
                   best_mm=[round(float(xs[i]), 4), round(float(ys[j]), 4)],
                   quality=q, raster_x_mm=xs.round(4).tolist(),
                   raster_y_mm=ys.round(4).tolist(),
                   raster_quality=np.round(grid, 3).tolist())


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


def find_time_zero(m, center_mm=None, coarse_span_mm=3.0, coarse_points=31,
                   fine_span_mm=0.3, fine_points=31, n_avg=4,
                   pump_energy=1.0, target_err_mm=0.005):
    """Delay scans that zoom in on the Bragg-peak drop: coarse, then
    fine_span_mm, then a tenth of that, stopping once the fitted t0 is known
    to target_err_mm (5 um = 33 fs). A stand-in for the Run 6 BOED loop."""
    rec = Recorder(m)
    rec.put('diag_holder', HOLDER_OUT)
    rec.put('gun_uv_shutter', 1)
    rec.put('pump_energy', pump_energy)
    rec.put('pump_power_meter', 0)             # out of the pump beam
    rec.put('pump_shutter', 1)
    c = float(center_mm if center_mm is not None else rec.get('delay'))

    def sig(d):
        rec.put('delay', float(d))
        rec.sleep(0.2)
        return avg(rec, 'diffraction_signal', n_avg)

    coarse = [(float(d), sig(d)) for d in
              np.linspace(c - coarse_span_mm, c + coarse_span_mm,
                          coarse_points)]
    if not any(math.isfinite(s) for _, s in coarse):
        return _result('8 time zero', rec, False, False,
                       'no diffraction signal (beam not on the sample?)')
    f1 = _fit_step(*zip(*coarse))
    if f1 is None or f1['drop'] < 0.01:
        return _result('8 time zero', rec, True, False,
                       't0 not found in the coarse window', coarse=coarse)
    f2, fine, levels = f1, [], [{'span_mm': coarse_span_mm, **f1}]
    for span in (fine_span_mm, fine_span_mm / 10):
        fine = [(float(d), sig(d)) for d in
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
    rec.put('pump_shutter', 0)
    accepted = f2['t0_err_mm'] < target_err_mm and f2['drop'] > 0.01
    return _result('8 time zero', rec, True, accepted,
                   't0 found' if accepted else 't0 uncertain',
                   t0_mm=f2['t0_mm'], t0_err_fs=f2['t0_err_mm'] * PS_PER_MM
                   * 1e3, width_fs=f2['width_mm'] * PS_PER_MM * 1e3,
                   bragg_drop=f2['drop'], coarse=coarse, fine=fine,
                   levels=levels)


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
