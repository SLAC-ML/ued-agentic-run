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
  scope CH2 trace                          analytic: a negative-going pulse,
                                           -0.17 mV/fC, on a +3.36 div
                                           baseline with the measured noise,
                                           while the diagnostic screen is in
  beam transport: cameras, collimator      GPT (gptsim.run), cached per
  transmission, bunch length at sample     machine setting; the collimator
                                           motor moves a 200 um hole across
                                           the beam
  UV spot on the virtual cathode camera    analytic
  pump laser spot on the sample YAG        analytic: linear pump-lens map;
                                           HWP energy cos^2; blocked by the
                                           power meter
  chamber light                            a broad glow on the sample camera
  Andor                                    GPT main beam, minus what falls in
                                           the through hole; diffraction
                                           rings around it on the Bi flake
  diffraction pattern quality              analytic toy: beam on a Bi flake
  pump-probe Bragg-peak signal             analytic: erf step at t0, width
                                           from the GPT bunch length and pump
  gate valves                              all OPEN unless the truth says not

TRUTH holds what the real machine would not tell a tuner: the RF phase
offset, the laser-spot offset on the cathode, the collimator hole's
position, the pump lens zero, t0, and where the good part of the flake is.
Every constant here is a placeholder.

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
from ued_tuning.channels import (  # noqa: E402
    CHANNELS, GATE_VALVES, MONITOR_VALVES, HOLDER_OUT, HOLDER_YAG)
from virtual_gun import VirtualGun  # noqa: E402

MV_PER_AREQ = 128.3                      # assumed linear (sim/README.md)
PS_PER_MM = 2e-3 / 299792458 * 1e12      # delay stage, double pass
SCHOTTKY_EV = 3.79e-5                    # eV per sqrt(V/m)
E_NOMINAL = 68e6 * math.sin(math.radians(37))

TRUTH = {
    'phase_offset_deg': 118.4,           # PREQ at the RF zero crossing
    'cathode_offset_um': (150.0, -30.0),
    'q0_fC': 60.0,                       # full UV, nominal field and phase:
                                         # ~11 fC at throttle 53, emission+30
    'throttle_max_deg': 21.0,
    'throttle_extinction': 0.002,
    'excess_eV': 0.4,                    # photon energy minus work function
    'collimator_plate_from_mm': 80.0,    # the plate starts to cut the beam
    'collimator_hole_mm': 90.12,         # motor position of the 200 um hole
    'collimator_hole_radius_um': 100.0,
    'hwp_max_deg': 51.0,                 # pump energy max (DESC "max @ 51")
    'hwp_extinction': 1e-3,
    'pump_lens_zero_mm': (1.234, -0.567),
    'pump_um_per_mm': ((420.0, 25.0), (-30.0, 410.0)),
    'pump_spot_um': 80.0,
    'pump_sigma_fs': 25.0,
    't0_delay_mm': 61.234,
    'bragg_drop': 0.15,                  # at full pump energy
    'flake_center_mm': (14.07, 45.02),   # stage position that centres Bi
    'flake_radius_um': 90.0,
    'crack': ((14.12, 45.02), (0.0, 1.0)),   # a line through the flake
    'andor_hole_px': (560.0, 470.0),     # the Andor's main-beam through hole
    'andor_hole_radius_px': 30.0,
    'scope_baseline_div': 3.36,          # CH2, measured 2026-10-16
    'scope_noise_div': 0.237,
    'scope_mV_per_fC': -0.17,
    'gate_valves': {gv: 'OPEN' for gv in GATE_VALVES + MONITOR_VALVES},
}

POSITIONS = {                            # where things are on the stage
    'out': (9.00, 41.00, 0.0),
    'yag': (22.45, 41.00, 0.0),
    'bi': (14.00, 45.10, 0.0),
    'si': (13.90, 39.75, 0.0),
}

CAMERA_MODEL = {
    'cam_vcc': dict(z=None, um_per_px=10.0, size=(1292, 964),
                    axis_px=(646.0, 482.0), bits=12, k=4e5, db=True),
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
# cross as read on 2026-10-16 (then from UED:GIGE:03; the sample camera is
# UED:GIGE:02 since 2026-10-28, whose cross may differ).
LASER_K = 5e9            # laser counts per (energy fraction x second)
LIGHT_K = 2e5            # chamber-light counts per second, sample camera
LIGHT_SPOT_UM = (600.0, -400.0, 1500.0, 1200.0)   # x, y, sx, sy
RING_K = 5.5e3           # Andor ring counts per fC on good Bi, per second
RING_SIGMA_PX = 180.0

RF = ('areq', 'aact', 'pfb_enable', 'afb_enable', 'pfb_status',
      'afb_status', 'gun_temp')


def _smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def _fraction_in_circle(dx, dy, sx, sy, r):
    """Fraction of a 2D Gaussian (rms sx, sy, offset dx, dy) inside a circle
    of radius r about the origin."""
    g = np.linspace(-4, 4, 41)
    gx, gy = np.meshgrid(g * sx + dx, g * sy + dy)
    w = np.exp(-0.5 * (g[None, :] ** 2 + g[:, None] ** 2))
    return float((w * (gx ** 2 + gy ** 2 < r * r)).sum() / w.sum())


class VirtualUED:
    kind = 'sim'

    def __init__(self, seed=0, fidelity=None, truth=None):
        self.rng = np.random.default_rng(seed)
        self.truth = dict(TRUTH, **(truth or {}))
        self.fidelity = fidelity or os.environ.get('UED_SIM_FIDELITY', 'fast')
        self.gun = VirtualGun(seed=seed)
        self.sp = {
            # the gun starts at an emitting phase (yesterday's setpoint, a
            # few degrees off), the UV throttle wherever it was left
            'preq': 160.0, 'gun_uv_shutter': 0, 'gun_uv_throttle': 50.0,
            'pump_shutter': 0, 'pump_extra_shutter': 0, 'pump_hwp': 6.0, 'pump_nd_wheel': 310.0,
            'pump_lens_h': 0.0, 'pump_lens_v': 0.0,
            'pump_incoupling': 0.0, 'pump_outcoupling': 0.1,
            # power meter in and light on, as found on 2026-10-16
            'pump_power_meter': 40.0, 'chamber_light': 1,
            'cam_sample_yag.cross_x': 1080.0, 'cam_sample_yag.cross_y': 1034.0,
            'cam_far_andor.acquire': 'Acquire',
            'sol1': 0.25, 'sol2': 4.2,
            'diag_holder': HOLDER_OUT, 'collimator': 0.0,
            'sample_x': POSITIONS['out'][0], 'sample_y': POSITIONS['out'][1],
            'sample_z': 0.0, 'sample_pitch': 0.0, 'sample_yaw': 0.0,
            'delay': 60.0,
            **{f'{p}c{i:02d}': 0.0 for i in range(6) for p in 'xy'},
        }
        self.gv = dict(self.truth['gate_valves'])
        # exposure [s], gain (dB on GigE, EM gain on the Andor): as read
        # from the real cameras on 2026-10-16
        self.cam = {'cam_vcc': [0.2, 2.0], 'cam_diag_yag': [1.0, 2.0],
                    'cam_sample_yag': [1.0, 1.0],
                    'cam_far_andor': [1.0, 1000.0]}
        self._spots = {}
        self._gpt_cache = {}
        self.stats = {'gpt_runs': 0, 'gpt_seconds': 0.0, 'gets': 0, 'puts': 0}

    # ---------------------------------------------------------------- API
    def time(self):
        return self.gun.time()

    def sleep(self, seconds):
        self.gun.sleep(seconds)

    def put(self, name, value):
        ch = CHANNELS.get(name)
        if ch is None:
            raise KeyError(f'unknown channel {name!r}')
        if not ch.writable:
            raise KeyError(f'{name} is read-only')
        self.stats['puts'] += 1
        if name in ('areq', 'pfb_enable', 'afb_enable'):
            self.gun.put(name, value)
        elif name == 'cam_far_andor.acquire':
            self.sp[name] = 'Acquire' if int(value) else 'Done'
        elif name.endswith('.exposure') or name.endswith('.gain'):
            cam, what = name.split('.')
            self.cam[cam][0 if what == 'exposure' else 1] = float(value)
        elif name == 'preq':
            self.sp['preq'] = _wrap180(float(value))
        elif name in ('diag_holder', 'gun_uv_shutter', 'pump_shutter',
                      'pump_extra_shutter', 'chamber_light'):
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
        if name in self.gv:
            return self.gv[name]
        if name == 'pact':
            return self.sp['preq'] + 0.05 * self.rng.standard_normal()
        if name == 'diag_screen_state':         # mirrors the holder
            return ('Open' if self.sp['diag_holder'] != HOLDER_OUT
                    else 'Closed')
        if name == 'diag_screen_interlock':
            return 'OK'
        if name == 'scope_ch2_trace':
            return self._scope_trace()
        if name == 'scope_ch2_vdiv':
            return '1mV'
        if name == 'scope_ch0_trace':           # CH0 shows no pulse here
            return np.round((-2.37 + 0.058 * self.rng.standard_normal(500))
                            / 0.04) * 0.04
        if name == 'scope_ch0_vdiv':
            return '1V'
        if '.' in name:
            cam, what = name.split('.')
            if what == 'exposure':
                return self.cam[cam][0]
            if what == 'gain':
                return self.cam[cam][1]
            return self._camera(cam)[what]
        if name.endswith('_rb') and name[:-3] in self.sp:   # BACT = BCTRL
            return self.sp[name[:-3]]
        if name in ('quad1', 'quad2', 'quad1_rb', 'quad2_rb'):
            return 0.0                          # the doublet is off
        if name == 'pattern_quality':
            return self._pattern()
        if name == 'diffraction_signal':
            return self._diffraction()
        raise KeyError(name)

    def image(self, cam, binning=8):
        """A rendered, binned image of the camera's last reading (for the
        records): Gaussian spots plus noise."""
        mdl = CAMERA_MODEL[cam]
        nx, ny = mdl['size']
        spots = self._spots.get(cam) or []
        xs = (np.arange(nx // binning) + 0.5) * binning
        ys = (np.arange(ny // binning) + 0.5) * binning
        img = np.zeros((len(ys), len(xs)))
        for c, px, py, sx, sy in spots:
            gx = np.exp(-0.5 * ((xs - px) / sx) ** 2) / (sx * math.sqrt(
                2 * math.pi))
            gy = np.exp(-0.5 * ((ys - py) / sy) ** 2) / (sy * math.sqrt(
                2 * math.pi))
            img += c * np.outer(gy, gx) * binning * binning
        img += self.rng.normal(0, 2.0, img.shape)
        full = 2 ** mdl['bits'] - 1
        return np.clip(img / (binning * binning), 0, full).astype(np.float32)

    # ------------------------------------------------------------ physics
    def throttle_transmission(self):
        t = self.truth
        th = math.radians(self.sp['gun_uv_throttle'] - t['throttle_max_deg'])
        return ((1 - t['throttle_extinction']) * math.cos(2 * th) ** 2
                + t['throttle_extinction'])

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
        return t['q0_fC'] * self.throttle_transmission() * qe * capture

    def _scope_trace(self):
        """CH2, 500 samples in divisions at 1 mV/div: the pulse shows while
        the diagnostic screen (and its Faraday cup) is in the beam."""
        t = self.truth
        tr = t['scope_baseline_div'] + t['scope_noise_div'] * \
            self.rng.standard_normal(500)
        if self.sp['diag_holder'] != HOLDER_OUT:
            q = self.charge()
            if q > 0:
                i = np.arange(500)
                tr += q * t['scope_mV_per_fC'] * np.exp(
                    -0.5 * ((i - 250) / 1.5) ** 2)
        return np.round(tr / 0.04) * 0.04          # 0.04 div quantization

    def pump_fraction(self):
        """Pump energy fraction from the Harmonics HWP angle."""
        t = self.truth
        th = math.radians(self.sp['pump_hwp'] - t['hwp_max_deg'])
        return (t['hwp_extinction']
                + (1 - t['hwp_extinction']) * math.cos(2 * th) ** 2)

    def _collimator(self):
        """(plate in the beam, hole offset from the axis [m])."""
        t = self.truth
        pos = self.sp['collimator']
        if pos < t['collimator_plate_from_mm']:
            return False, 0.0
        off = (pos - t['collimator_hole_mm']) * 1e-3
        return True, round(max(-1e-3, min(1e-3, off)), 6)

    def _beam(self):
        """GPT screen table for the current setting, or None (no beam)."""
        q = self.charge()
        aact = round(self.gun.state['aact'], 3)
        if q < 0.05 or aact < 0.2:
            return None, q
        fast = self.fidelity != 'full'
        plate, collx = self._collimator()
        p = {
            'numParticle': 3000 if fast else 10000, 'sc': 0 if fast else 1,
            'gunAmp': -MV_PER_AREQ * 1e6 * aact,
            'gunPhaseDeg': round(_wrap180(
                self.sp['preq'] - self.truth['phase_offset_deg']), 2),
            'sol1Fac': round(self.sp['sol1'], 4),
            'sol2Fac': round(self.sp['sol2'], 4),
            'x0': self.truth['cathode_offset_um'][0] * 1e-6,
            'y0': self.truth['cathode_offset_um'][1] * 1e-6,
            'coll': int(plate),
            'collR': self.truth['collimator_hole_radius_um'] * 1e-6,
            'collx': collx,
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
                and self.sp['pump_power_meter'] < 20.0)

    def _camera(self, cam):
        mdl = CAMERA_MODEL[cam]
        exposure, gain = self.cam[cam]
        g = 10 ** (gain / 20) if mdl['db'] else max(gain, 1.0)
        holder = self.sp['diag_holder']
        spots = []                      # (counts, x_um, y_um, sx_um, sy_um)
        hole = None                     # Andor through hole (px)

        def beam_spot(z=None):
            df, q = self._beam()
            if df is None:
                return None
            r = gptsim.at(df, z or mdl['z'])
            if not (r.transmission > 0 and np.isfinite(r.x_um)):
                return None
            s = (mdl['k'] * q * r.transmission * exposure * g,
                 r.x_um, r.y_um, r.sx_um, r.sy_um)
            spots.append(s)
            return s, q * r.transmission

        if cam == 'cam_vcc':
            if self.sp['gun_uv_shutter']:
                x0, y0 = self.truth['cathode_offset_um']
                spots.append((mdl['k'] * self.throttle_transmission()
                              * exposure * g, x0, y0, 100.0, 100.0))
        elif cam == 'cam_diag_yag' and holder == HOLDER_YAG:
            beam_spot()
        elif cam == 'cam_sample_yag':
            if self._at_stage('yag'):
                if holder == HOLDER_OUT:
                    beam_spot()
                if self.pump_on_sample():
                    x, y = self.laser_spot_um()
                    s = self.truth['pump_spot_um']
                    spots.append((LASER_K * self.pump_fraction() * exposure
                                  * g, x, y, s, s))
            if self.sp['chamber_light']:
                spots.append((LIGHT_K * exposure * g, *LIGHT_SPOT_UM))
        elif (cam == 'cam_far_andor' and holder == HOLDER_OUT
              and not self._at_stage('yag')):
            got = beam_spot()
            if got and self._on_flake_area():
                (c, x, y, sx, sy), q_t = got
                ring = RING_SIGMA_PX * mdl['um_per_px']
                spots.append((RING_K * q_t * self._flake_overlap()
                              * exposure * g, x, y, ring, ring))
            hole = (self.truth['andor_hole_px'],
                    self.truth['andor_hole_radius_px'])

        nx, ny = mdl['size']
        ax, ay = mdl['axis_px']
        um = mdl['um_per_px']
        vis = []
        for k, (c, x, y, sx, sy) in enumerate(spots):
            px, py = ax + x / um, ay + y / um
            spx, spy = max(sx / um, 0.5), max(sy / um, 0.5)
            if hole is not None and k == 0:       # main beam vs the hole
                (hx, hy), hr = hole
                c *= 1 - _fraction_in_circle(px - hx, py - hy, spx, spy, hr)
            if 0 <= px < nx and 0 <= py < ny and c > 0:
                vis.append((c, px, py, spx, spy))
        self._spots[cam] = vis
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

    def _on_flake_area(self):
        return (abs(self.sp['sample_x'] - POSITIONS['bi'][0]) <= 1.0
                and abs(self.sp['sample_y'] - POSITIONS['bi'][1]) <= 1.0)

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
        if not self._on_flake_area():
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
            drop = self.truth['bragg_drop'] * self.pump_fraction()
            sig = 1 - drop * 0.5 * (1 + math.erf(t / (math.sqrt(2) * width)))
        return sig * (1 + 0.004 * self.rng.standard_normal())

    # ----------------------------------------------------- sim-only views
    def emission_truth(self, throttle=51.0, threshold_fC=None, step=0.05):
        """The emission phase as the scan defines it, from the noise-free
        model: where the charge first rises above the scope's 5-sigma
        detection threshold, with the UV throttle at its scan value."""
        t = self.truth
        thr = threshold_fC if threshold_fC is not None else \
            5 * t['scope_noise_div'] / abs(t['scope_mV_per_fC'])
        keep = (dict(self.sp), self.gun.state['aact'])
        self.sp['gun_uv_shutter'], self.sp['gun_uv_throttle'] = 1, throttle
        prev, found = None, None
        for ph in np.arange(-180.0, 180.0, step):
            self.sp['preq'] = float(ph)
            q = self.charge()
            if prev is not None and prev < thr <= q:
                found = float(ph)
                break
            prev = q
        self.sp.update(keep[0])
        return found

    def report_truth(self):
        """Hidden truth and how far the current state is from ideal."""
        t = self.truth
        out = {'phase_offset_deg': t['phase_offset_deg'],
               't0_delay_mm': t['t0_delay_mm'],
               'flake_center_mm': t['flake_center_mm'],
               'cathode_offset_um': t['cathode_offset_um'],
               'collimator_hole_mm': t['collimator_hole_mm'],
               'stats': dict(self.stats)}
        em = self.emission_truth()
        out['emission_phase_deg'] = em
        if em is not None:
            out['phase_error_deg'] = _wrap180(self.sp['preq'] - em - 30.0)
        out['charge_fC'] = self.charge()
        df, _ = self._beam()
        if df is not None:
            # the motor should put the hole on the beam, not on the axis
            x_coll_mm = gptsim.at(df, 0.50).x_um * 1e-3
            out['collimator_ideal_mm'] = t['collimator_hole_mm'] + x_coll_mm
            out['collimator_error_mm'] = (self.sp['collimator']
                                          - out['collimator_ideal_mm'])
            r = gptsim.at(df, 1.499)
            e = np.array([r.x_um, r.y_um])
            mdl = CAMERA_MODEL['cam_sample_yag']
            out['ebeam_at_sample_um'] = e.tolist()
            out['laser_minus_ebeam_um'] = (self.laser_spot_um() - e).tolist()
            out['cross_minus_ebeam_px'] = [
                self.sp['cam_sample_yag.cross_x']
                - (mdl['axis_px'][0] + e[0] / mdl['um_per_px']),
                self.sp['cam_sample_yag.cross_y']
                - (mdl['axis_px'][1] + e[1] / mdl['um_per_px'])]
            out['transmission'] = float(gptsim.at(df, 0.80).transmission)
            a = gptsim.at(df, 4.631)
            mdl = CAMERA_MODEL['cam_far_andor']
            if np.isfinite(a.x_um):
                bx = mdl['axis_px'][0] + a.x_um / mdl['um_per_px']
                by = mdl['axis_px'][1] + a.y_um / mdl['um_per_px']
                hx, hy = t['andor_hole_px']
                out['andor_main_beam_minus_hole_px'] = [bx - hx, by - hy]
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
        out['pump_shutter'] = self.sp['pump_shutter']
        return out
