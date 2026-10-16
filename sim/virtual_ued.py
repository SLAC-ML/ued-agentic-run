"""Virtual UED: a stand-in machine for rehearsing the bring-up tuning tools.

Answers every logical channel in bringup/ued_tuning/channels.py through the
same get/put/sleep/time interface the EPICS backend has, so the stage
procedures and the ued_tuning MCP server run against it unchanged.

What answers what:
  gun RF, feedbacks, gun body temperature   virtual_gun.VirtualGun
  bunch charge                             analytic: UV throttle transmission
                                           x Schottky-enhanced photoemission
                                           x capture (GPT does not model
                                           emission)
  beam transport: cameras, collimator      GPT (gptsim.run), cached per
  transmission, bunch length at sample     machine setting
  pump laser spot on the sample YAG        analytic: linear pump-lens map;
                                           blocked by the power meter
  chamber light                            a broad glow on the sample camera
  diffraction pattern quality              analytic toy: beam on a Bi flake
  pump-probe Bragg-peak signal             analytic: erf step at t0, width
                                           from the GPT bunch length and pump

TRUTH holds what the real machine would not tell a tuner: the RF phase
offset, the laser-spot offset on the cathode, the pump lens zero, t0, and
where the good part of the flake is. Every constant here is a placeholder.

Fidelity (UED_SIM_FIDELITY): `fast` (default) runs GPT with 3000 particles
and no space charge, a few seconds per setting; `full` uses 10000 particles
with space charge.
"""
from __future__ import annotations

import math
import os
import sys
import time as _wall
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BRINGUP = Path(os.environ.get('UED_BRINGUP_DIR', HERE.parent / 'bringup'))
sys.path.insert(0, str(BRINGUP))

import gptsim  # noqa: E402
from ued_tuning.channels import (CHANNELS, HOLDER_FC, HOLDER_OUT,  # noqa: E402
                                 HOLDER_YAG)
from virtual_gun import VirtualGun  # noqa: E402

MV_PER_AREQ = 128.3                      # assumed linear (sim/README.md)
PS_PER_MM = 2e-3 / 299792458 * 1e12      # delay stage, double pass
SCHOTTKY_EV = 3.79e-5                    # eV per sqrt(V/m)
E_NOMINAL = 68e6 * math.sin(math.radians(37))

TRUTH = {
    'phase_offset_deg': 118.4,           # PREQ at the RF zero crossing
    'cathode_offset_um': (150.0, -100.0),
    'q0_fC': 29.0,                       # full UV, nominal field and phase
    'throttle_max_deg': 21.0,
    'throttle_extinction': 0.002,
    'excess_eV': 0.4,                    # photon energy minus work function
    'pump_lens_zero_mm': (1.234, -0.567),
    'pump_um_per_mm': ((420.0, 25.0), (-30.0, 410.0)),
    'pump_spot_um': 80.0,
    'pump_sigma_fs': 25.0,
    't0_delay_mm': 61.234,
    'bragg_drop': 0.15,                  # at full pump energy
    'flake_center_mm': (14.07, 45.02),   # stage position that centres Bi
    'flake_radius_um': 90.0,
    'crack': ((14.12, 45.02), (0.0, 1.0)),   # a line through the flake
}

POSITIONS = {                            # taught stage positions (x, y, z)
    'out': (9.00, 41.00, 0.0),
    'yag': (22.45, 41.00, 0.0),
    'bi': (14.00, 45.10, 0.0),
    'si': (13.90, 39.75, 0.0),
}

CAMERA_MODEL = {
    'cam_diag_yag': dict(z=0.50, um_per_px=10.0, size=(1600, 1200),
                         axis_px=(812.0, 590.0), bits=12, k=1600.0, db=True),
    'cam_sample_yag': dict(z=1.499, um_per_px=3.0, size=(2048, 2048),
                           axis_px=(1080.0, 1034.0), bits=12, k=5000.0,
                           db=True),
    'cam_far_andor': dict(z=4.631, um_per_px=20.0, size=(1024, 1024),
                          axis_px=(530.0, 498.0), bits=16, k=1.7e5,
                          db=False),
}
# The real GigE cameras are 8-bit; these keep 12 bits so the count scales
# above stay as they were tuned. The sample camera's axis is the real e-beam
# cross (UED:GIGE:03:Cross2X/Y on 2026-10-16).
LASER_K = 5e9            # laser counts per (energy fraction x second)
LIGHT_K = 2e5            # chamber-light counts per second, sample camera
LIGHT_SPOT_UM = (600.0, -400.0, 1500.0, 1200.0)   # x, y, sx, sy

RF = ('areq', 'aact', 'pfb_enable', 'afb_enable', 'pfb_status',
      'afb_status', 'gun_temp')


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


class VirtualUED:
    kind = 'sim'

    def __init__(self, seed=0, fidelity=None, truth=None):
        self.rng = np.random.default_rng(seed)
        self.truth = dict(TRUTH, **(truth or {}))
        self.fidelity = fidelity or os.environ.get('UED_SIM_FIDELITY', 'fast')
        self.gun = VirtualGun(seed=seed)
        self.sp = {
            'preq': 100.0, 'gun_uv_shutter': 0, 'gun_uv_throttle': 35.0,
            'pump_shutter': 0, 'pump_energy': 1.0,
            'pump_lens_h': 0.0, 'pump_lens_v': 0.0,
            # power meter in and light on, as found on 2026-10-16
            'pump_power_meter': 1, 'chamber_light': 1,
            'cam_sample_yag.cross_x': 1080.0, 'cam_sample_yag.cross_y': 1034.0,
            'sol1': 0.25, 'sol2': 4.2,
            'diag_holder': HOLDER_OUT, 'collimator': 0,
            'sample_x': POSITIONS['out'][0], 'sample_y': POSITIONS['out'][1],
            'sample_z': 0.0, 'delay': 60.0,
            **{f'{p}c{i:02d}': 0.0 for i in range(6) for p in 'xy'},
        }
        # exposure [s], gain (dB on GigE, EM gain on the Andor): as read
        # from the real cameras on 2026-10-16
        self.cam = {'cam_diag_yag': [1.0, 2.0], 'cam_sample_yag': [1.0, 1.0],
                    'cam_far_andor': [1.0, 1000.0]}
        self._gpt_cache = {}
        self.stats = {'gpt_runs': 0, 'gpt_seconds': 0.0, 'gets': 0, 'puts': 0}

    # ---------------------------------------------------------------- API
    def time(self):
        return self.gun.time()

    def sleep(self, seconds):
        self.gun.sleep(seconds)

    def saved_positions(self):
        return dict(POSITIONS)

    def put(self, name, value):
        ch = CHANNELS.get(name)
        if ch is None:
            raise KeyError(f'unknown channel {name!r}')
        if not ch.writable:
            raise KeyError(f'{name} is read-only')
        self.stats['puts'] += 1
        if name in ('areq', 'pfb_enable', 'afb_enable'):
            self.gun.put(name, value)
        elif name.endswith('.exposure') or name.endswith('.gain'):
            cam, what = name.split('.')
            self.cam[cam][0 if what == 'exposure' else 1] = float(value)
        elif name == 'preq':
            self.sp['preq'] = float(value) % 360.0
        elif name in ('diag_holder', 'gun_uv_shutter', 'pump_shutter',
                      'collimator', 'pump_power_meter', 'chamber_light'):
            self.sp[name] = int(round(float(value)))
        else:
            self.sp[name] = float(value)

    def get(self, name):
        if name not in CHANNELS:
            raise KeyError(f'unknown channel {name!r}')
        self.stats['gets'] += 1
        if name in RF:
            return self.gun.get(name)
        if name in self.sp:
            return self.sp[name]
        if name == 'pact':
            return self.sp['preq'] + 0.05 * self.rng.standard_normal()
        if name == 'fc_charge':
            if self.sp['diag_holder'] != HOLDER_FC:
                return float('nan')
            q = self.charge()
            return q * (1 + 0.01 * self.rng.standard_normal()) \
                + 0.02 * self.rng.standard_normal()
        if '.' in name:
            cam, what = name.split('.')
            if what == 'exposure':
                return self.cam[cam][0]
            if what == 'gain':
                return self.cam[cam][1]
            return self._camera(cam)[what]
        if name == 'pattern_quality':
            return self._pattern()
        if name == 'diffraction_signal':
            return self._diffraction()
        raise KeyError(name)

    # ------------------------------------------------------------ physics
    def charge(self):
        """Emitted bunch charge [fC]."""
        if not self.sp['gun_uv_shutter']:
            return 0.0
        t = self.truth
        aact = self.gun.state['aact']
        phi = _wrap180(self.sp['preq'] - t['phase_offset_deg'])
        e_cath = MV_PER_AREQ * 1e6 * aact * math.sin(math.radians(phi))
        if e_cath <= 0:
            return 0.0
        qe = ((t['excess_eV'] + SCHOTTKY_EV * math.sqrt(e_cath))
              / (t['excess_eV'] + SCHOTTKY_EV * math.sqrt(E_NOMINAL))) ** 2
        # emitted too near a zero crossing, or at too low a field, the
        # bunch does not get out of the gun
        capture = (_smooth(phi / 5.0) * _smooth((150.0 - phi) / 30.0)
                   * _smooth((aact - 0.10) / 0.10))
        th = math.radians(self.sp['gun_uv_throttle'] - t['throttle_max_deg'])
        trans = ((1 - t['throttle_extinction']) * math.cos(2 * th) ** 2
                 + t['throttle_extinction'])
        return t['q0_fC'] * trans * qe * capture

    def _beam(self):
        """GPT screen table for the current setting, or None (no beam)."""
        q = self.charge()
        aact = round(self.gun.state['aact'], 3)
        if q < 0.05 or aact < 0.2:
            return None, q
        fast = self.fidelity != 'full'
        p = {
            'numParticle': 3000 if fast else 10000, 'sc': 0 if fast else 1,
            'gunAmp': -MV_PER_AREQ * 1e6 * aact,
            'gunPhaseDeg': round(_wrap180(
                self.sp['preq'] - self.truth['phase_offset_deg']), 2),
            'sol1Fac': round(self.sp['sol1'], 4),
            'sol2Fac': round(self.sp['sol2'], 4),
            'x0': self.truth['cathode_offset_um'][0] * 1e-6,
            'y0': self.truth['cathode_offset_um'][1] * 1e-6,
            'coll': int(self.sp['collimator']),
            # without space charge the charge only scales the signals
            'Qtot': -10e-15 if fast else -round(q * 2) / 2 * 1e-15,
            **{k: round(self.sp[k], 4) for k in gptsim.CORRECTORS},
        }
        key = tuple(sorted(p.items()))
        if key not in self._gpt_cache:
            t0 = _wall.time()
            self._gpt_cache[key] = gptsim.run(p)
            self.stats['gpt_runs'] += 1
            self.stats['gpt_seconds'] += _wall.time() - t0
        return self._gpt_cache[key], q

    def _at_stage(self, where, tol=0.5):
        x, y, _ = POSITIONS[where]
        return (abs(self.sp['sample_x'] - x) < tol
                and abs(self.sp['sample_y'] - y) < tol)

    def laser_spot_um(self):
        t = self.truth
        m = np.array([self.sp['pump_lens_h'] - t['pump_lens_zero_mm'][0],
                      self.sp['pump_lens_v'] - t['pump_lens_zero_mm'][1]])
        return np.array(t['pump_um_per_mm']) @ m

    def pump_on_sample(self):
        return (bool(self.sp['pump_shutter'])
                and not self.sp['pump_power_meter'])

    def _camera(self, cam):
        mdl = CAMERA_MODEL[cam]
        exposure, gain = self.cam[cam]
        g = 10 ** (gain / 20) if mdl['db'] else max(gain, 1.0)
        holder = self.sp['diag_holder']
        spots = []                      # (counts, x_um, y_um, sx_um, sy_um)

        def beam_spot():
            df, q = self._beam()
            if df is None:
                return
            r = gptsim.at(df, mdl['z'])
            if not (r.transmission > 0 and np.isfinite(r.x_um)):
                return
            spots.append((mdl['k'] * q * r.transmission * exposure * g,
                          r.x_um, r.y_um, r.sx_um, r.sy_um))

        if cam == 'cam_diag_yag' and holder == HOLDER_YAG:
            beam_spot()
        elif cam == 'cam_sample_yag':
            if self._at_stage('yag'):
                if holder == HOLDER_OUT:
                    beam_spot()
                if self.pump_on_sample():
                    x, y = self.laser_spot_um()
                    s = self.truth['pump_spot_um']
                    spots.append((LASER_K * self.sp['pump_energy'] * exposure
                                  * g, x, y, s, s))
            if self.sp['chamber_light']:
                spots.append((LIGHT_K * exposure * g, *LIGHT_SPOT_UM))
        elif (cam == 'cam_far_andor' and holder == HOLDER_OUT
              and not self._at_stage('yag')):
            beam_spot()

        nx, ny = mdl['size']
        ax, ay = mdl['axis_px']
        um = mdl['um_per_px']
        vis = []
        for c, x, y, sx, sy in spots:   # a spot off the sensor is not seen
            px, py = ax + x / um, ay + y / um
            if 0 <= px < nx and 0 <= py < ny and c > 0:
                vis.append((c, px, py, max(sx / um, 0.5), max(sy / um, 0.5)))
        full = 2 ** mdl['bits'] - 1
        total = sum(c for c, *_ in vis)
        peak = sum(c / (2 * math.pi * sx * sy) for c, _, _, sx, sy in vis)
        out = {'size_x': nx, 'size_y': ny,
               'total': max(total * (1 + 0.02 * self.rng.standard_normal())
                            + 300 * self.rng.standard_normal(), 0.0),
               'max_value': min(peak, full), 'saturated': float(peak > full)}
        if total < 2000:
            out.update(centroid_x=float('nan'), centroid_y=float('nan'),
                       sigma_x=float('nan'), sigma_y=float('nan'))
            return out
        w = np.array([c for c, *_ in vis]) / total
        px = np.array([v[1] for v in vis])
        py = np.array([v[2] for v in vis])
        sx = np.array([v[3] for v in vis])
        sy = np.array([v[4] for v in vis])
        cx, cy = float(w @ px), float(w @ py)
        sig_x = math.sqrt(float(w @ (sx ** 2 + (px - cx) ** 2)))
        sig_y = math.sqrt(float(w @ (sy ** 2 + (py - cy) ** 2)))
        if peak > full:                 # a saturated spot reads flat-topped
            blow = (peak / full) ** 0.25
            sig_x, sig_y = sig_x * blow, sig_y * blow
        out.update(centroid_x=cx + 0.3 * self.rng.standard_normal(),
                   centroid_y=cy + 0.3 * self.rng.standard_normal(),
                   sigma_x=sig_x, sigma_y=sig_y)
        return out

    def _flake_overlap(self):
        """Fraction of the beam on good Bi (toy), for the current stage."""
        t = self.truth
        cx, cy = t['flake_center_mm']
        d = np.array([self.sp['sample_x'] - cx, self.sp['sample_y'] - cy])
        s = 30.0                                        # beam rms at sample
        g = np.linspace(-3 * s, 3 * s, 25)
        gx, gy = np.meshgrid(g, g)
        wgt = np.exp(-(gx ** 2 + gy ** 2) / (2 * s * s))
        px, py = gx + d[0] * 1e3, gy + d[1] * 1e3
        on = (px ** 2 + py ** 2) < t['flake_radius_um'] ** 2
        (lx, ly), (ux, uy) = t['crack']
        dist = np.abs((self.sp['sample_x'] - lx) * 1e3 * uy
                      - (self.sp['sample_y'] - ly) * 1e3 * ux)
        crack = 0.4 * math.exp(-dist ** 2 / (2 * (s ** 2 + 15.0 ** 2)))
        return float((wgt * on).sum() / wgt.sum()) * (1 - crack)

    def _pattern(self):
        df, q = self._beam() if self.sp['diag_holder'] == HOLDER_OUT \
            else (None, 0.0)
        if df is None or self._at_stage('yag'):
            return float('nan')
        if abs(self.sp['sample_x'] - POSITIONS['bi'][0]) > 1.0 or \
                abs(self.sp['sample_y'] - POSITIONS['bi'][1]) > 1.0:
            return 0.0
        return max(self._flake_overlap()
                   + 0.01 * self.rng.standard_normal(), 0.0)

    def bunch_sigma_fs(self):
        df, _ = self._beam()
        if df is None:
            return float('nan')
        return float(gptsim.at(df, 1.499).st_fs)

    def _diffraction(self):
        q = self._pattern()
        if not (np.isfinite(q) and q >= 0.2):
            return float('nan')
        sig = 1.0
        if self.pump_on_sample():
            t = (self.sp['delay'] - self.truth['t0_delay_mm']) * PS_PER_MM
            width = math.hypot(self.bunch_sigma_fs(),
                               self.truth['pump_sigma_fs']) * 1e-3
            drop = self.truth['bragg_drop'] * self.sp['pump_energy']
            sig = 1 - drop * 0.5 * (1 + math.erf(t / (math.sqrt(2) * width)))
        return sig * (1 + 0.004 * self.rng.standard_normal())

    # ----------------------------------------------------- sim-only views
    def report_truth(self):
        """Hidden truth and how far the current state is from ideal."""
        t = self.truth
        out = {'phase_offset_deg': t['phase_offset_deg'],
               't0_delay_mm': t['t0_delay_mm'],
               'flake_center_mm': t['flake_center_mm'],
               'cathode_offset_um': t['cathode_offset_um'],
               'stats': dict(self.stats)}
        out['phase_error_deg'] = _wrap180(self.sp['preq'] - 37.0
                                          - t['phase_offset_deg'])
        out['charge_fC'] = self.charge()
        df, _ = self._beam()
        if df is not None:
            r = gptsim.at(df, 1.499)
            e = np.array([r.x_um, r.y_um])
            out['ebeam_at_sample_um'] = e.tolist()
            out['laser_minus_ebeam_um'] = (self.laser_spot_um() - e).tolist()
            out['transmission'] = float(gptsim.at(df, 0.80).transmission)
            a = gptsim.at(df, 4.631)
            mdl = CAMERA_MODEL['cam_far_andor']
            out['andor_offset_from_centre_px'] = [
                mdl['axis_px'][0] + a.x_um / mdl['um_per_px'] - 512,
                mdl['axis_px'][1] + a.y_um / mdl['um_per_px'] - 512]
        cx, cy = t['flake_center_mm']
        out['stage_minus_flake_um'] = [(self.sp['sample_x'] - cx) * 1e3,
                                       (self.sp['sample_y'] - cy) * 1e3]
        # best achievable pattern quality (the crack moves it off centre)
        keep = self.sp['sample_x'], self.sp['sample_y']
        best = (0.0, None)
        for x in np.arange(cx - 0.2, cx + 0.2001, 0.005):
            for y in np.arange(cy - 0.2, cy + 0.2001, 0.005):
                self.sp['sample_x'], self.sp['sample_y'] = x, y
                q = self._flake_overlap()
                if q > best[0]:
                    best = (q, (round(x, 3), round(y, 3)))
        self.sp['sample_x'], self.sp['sample_y'] = keep
        out['pattern_quality_now'] = self._flake_overlap()
        out['pattern_quality_best'] = best[0]
        out['stage_best_mm'] = best[1]
        out['delay_error_mm'] = self.sp['delay'] - t['t0_delay_mm']
        return out
