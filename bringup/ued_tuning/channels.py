"""Logical channels the UED tuning tools read and write.

One vocabulary for every backend. The virtual machine (sim/virtual_ued.py)
answers every name; the read-only EPICS backend maps a name to its PV, and
refuses a name whose PV is not known yet. PV names follow Fuhao Ji's run-7
list (PVnamelist_SUED_agentic.py, 2026-10-08) where it has one, otherwise
bringup/ued_pvs.py. Every PV here was read from ued-daq on 2026-10-16.

Status values are the ones ued_pvs.py uses, plus SIM_ONLY for quantities no
PV carries (on the real machine they need an analysis of a detector image).

`pv_units` is what the real PV is in, where it differs from the logical
units the stages use (the converters between them are not written yet).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CONFIRMED = 'CONFIRMED'
LIKELY = 'LIKELY'
CANDIDATE = 'CANDIDATE'
UNMAPPED = 'UNMAPPED'
NO_ACCESS = 'NO_ACCESS'   # PV ued-daq can't reach (none since 2026-10-16)
SIM_ONLY = 'SIM_ONLY'     # no PV: an analysis product on the real machine

# diag_holder positions (Faraday cup and Diag YAG share one inserter)
HOLDER_OUT, HOLDER_YAG, HOLDER_FC = 0, 1, 2


@dataclass(frozen=True)
class Channel:
    name: str
    group: str
    units: str
    writable: bool
    desc: str
    pv: Optional[str]
    status: str
    pv_units: str = ''        # real PV units, where they differ from `units`
    as_string: bool = False   # an enum, read as its string


def _ch(name, group, units, writable, desc, pv, status, pv_units='',
        as_string=False):
    return Channel(name, group, units, writable, desc, pv, status, pv_units,
                   as_string)


_LIST = [
    # Gun RF (klystron KY03). The machine was off when read (AREQ 0).
    _ch('areq', 'gun_rf', '', True, 'Gun amplitude setpoint (0..0.53)',
        'SIOC:AS01:KY03:0:AREQ', CONFIRMED, 'unconfirmed (EGU "degrees")'),
    _ch('preq', 'gun_rf', 'deg', True, 'Gun phase setpoint',
        'SIOC:AS01:KY03:0:PREQ', CONFIRMED),
    _ch('aact', 'gun_rf', '', False, 'Gun amplitude readback (averaged)',
        'SIOC:AS01:KY03:0:AACT_AVGNT', CONFIRMED, 'kV'),
    _ch('pact', 'gun_rf', 'deg', False, 'Gun phase readback (averaged)',
        'SIOC:AS01:KY03:0:PACT_AVGNT', CONFIRMED),
    _ch('pfb_enable', 'gun_rf', '', True, 'Phase feedback enable',
        'SIOC:AS01:KY03:0:PFBENB', CONFIRMED, as_string=True),
    _ch('afb_enable', 'gun_rf', '', True, 'Amplitude feedback enable',
        'SIOC:AS01:KY03:0:AFBENB', CONFIRMED, as_string=True),
    _ch('pfb_status', 'gun_rf', '', False, 'Phase feedback status',
        'SIOC:AS01:KY03:0:PFBST', CONFIRMED, as_string=True),
    _ch('afb_status', 'gun_rf', '', False, 'Amplitude feedback status',
        'SIOC:AS01:KY03:0:AFBST', CONFIRMED, as_string=True),
    _ch('gun_temp', 'gun_rf', 'C', False, 'Gun body temperature',
        'APC:AS01:TM01:M2_CH2_SPARE', CONFIRMED),

    # Lasers
    _ch('gun_uv_shutter', 'laser', '', True,
        'Gun UV shutter (1 open, 0 closed; the real output is a voltage '
        'whose levels are not known yet)', 'UED:USR:BHC:AO1:4', CONFIRMED,
        'V'),
    _ch('gun_uv_throttle', 'laser', 'deg', True,
        'Drive UV throttle (max transmission at 21 deg)', 'UED:USR:MMN:14:01',
        CONFIRMED),
    _ch('pump_shutter', 'laser', '', True, 'Pump main shutter (1 open)',
        'UED:USR:BHC:AO1:3', CONFIRMED, 'V'),
    _ch('pump_energy', 'laser', '', True,
        'Pump energy fraction. Real control: the Harmonics HWP (max @ 51 '
        'deg) with the ND wheel UED:USR:MMN:05:08 (max @ 310 deg)',
        'UED:USR:MMN:05:02', LIKELY, 'deg'),
    _ch('pump_power_meter', 'laser', '', True,
        'Pump power meter (1 in the beam, blocking the pump; 0 out)',
        'UED:USR:MMN:05:06', CONFIRMED, 'mm, in @ 40'),
    _ch('pump_lens_h', 'laser', 'mm', True,
        'Pump lens H: moves the pump spot on the sample (UED:MCS:01:m7, '
        '"pump_beam_X", is the other candidate)', 'UED:USR:MMN:08:05', LIKELY),
    _ch('pump_lens_v', 'laser', 'mm', True,
        'Pump lens V: moves the pump spot on the sample (UED:MCS:01:m8, '
        '"pump_beam_Y", is the other candidate)', 'UED:USR:MMN:08:06', LIKELY),

    # Magnets (deck scale factors; the real BCTRL units are not settled)
    _ch('sol1', 'magnets', '', True, 'Gun solenoid strength',
        'SOLN:AS01:121:BCTRL', CONFIRMED, 'kG-m'),
    _ch('sol2', 'magnets', '', True, '2nd solenoid strength',
        'SOLN:AS01:311:BCTRL', CONFIRMED, 'A'),

    # Beamline inserters and the chamber light
    _ch('diag_holder', 'beamline', '', True,
        'Faraday cup / Diag YAG inserter (0 out, 1 YAG, 2 FC)', None,
        UNMAPPED),
    _ch('collimator', 'beamline', '', True,
        'Collimator (1 in, 0 out; in/out positions in mm TBD)',
        'UED:USR:MMN:14:07', CONFIRMED, 'mm'),
    _ch('chamber_light', 'beamline', '', True,
        'Sample chamber light (1 on, 0 off). Reads the state; switched by '
        'writing ACSW:AS01:NW03:2POWERON or :2POWEROFF',
        'ACSW:AS01:NW03:2POWERSTATE', CONFIRMED),

    # Charge
    _ch('fc_charge', 'diagnostics', 'fC', False,
        'Faraday cup charge (reads only with the cup inserted)', None,
        UNMAPPED),

    # Sample stage (SUED chamber, per Fuhao's run-7 list; the motor DESCs
    # still say Incoupling X / Incoupling Y / Outcoupling)
    _ch('sample_x', 'sample', 'mm', True, 'Sample X', 'UED:USR:MMN:11:03',
        LIKELY),
    _ch('sample_y', 'sample', 'mm', True, 'Sample Y', 'UED:USR:MMN:11:04',
        LIKELY),
    _ch('sample_z', 'sample', 'mm', True, 'Sample Z', 'UED:USR:MMN:11:05',
        LIKELY),
    _ch('pattern_quality', 'sample', '', False,
        'Diffraction pattern quality score (0..1). On the real machine, a '
        'score of the far-detector image (readable: cam_far_andor image); '
        'the scoring function does not exist yet', None, SIM_ONLY),

    # Pump-probe
    _ch('delay', 'pump_probe', 'mm', True, 'Pump long delay stage',
        'UED:USR:MMN:03:04', CONFIRMED),
    _ch('diffraction_signal', 'pump_probe', '', False,
        'Bragg-peak intensity, normalised to pump-off. On the real machine, '
        'ROI sums on the far-detector image; the peak ROIs are not defined '
        'yet', None, SIM_ONLY),
]

# Cameras: one block of channels each. On the real machine the stats are
# computed from the image PV (most Stats plugins are disabled, and the
# Andor's runs on an ROI); `saturated` is 1 when a pixel is at full scale.
# Gain is in dB on the GigE cameras and an EM gain on the Andor.
CAMERAS = {
    # name: (prefix, image plugin, status, description)
    'cam_diag_yag': ('UED:GIGE:09', 'IMAGE1', LIKELY,
                     'Diag YAG camera (z ~0.5 m)'),
    'cam_sample_yag': ('UED:GIGE:03', 'IMAGE1', CONFIRMED,
                       'Sample chamber camera (RGB)'),
    'cam_far_andor': ('UED:ANDOR:CAM:03', 'IMAGE2', CONFIRMED,
                      'Far-detector Andor EMCCD'),
}
_STATS = {
    'centroid_x': 'px', 'centroid_y': 'px', 'sigma_x': 'px', 'sigma_y': 'px',
    'total': 'counts', 'max_value': 'counts', 'saturated': '',
    'size_x': 'px', 'size_y': 'px',
}
STAT_NAMES = tuple(_STATS)
for cam, (prefix, image, status, desc) in CAMERAS.items():
    gain_pv = 'AndorEMGain' if 'ANDOR' in prefix else 'Gain'
    _LIST.append(_ch(f'{cam}.exposure', 'camera', 's', True,
                     f'{desc}: exposure', f'{prefix}:AcquireTime', status))
    _LIST.append(_ch(f'{cam}.gain', 'camera', '', True, f'{desc}: gain',
                     f'{prefix}:{gain_pv}', status))
    for stat, units in _STATS.items():
        _LIST.append(_ch(f'{cam}.{stat}', 'camera', units, False,
                         f'{desc}: {stat}, computed from the image',
                         f'{prefix}:{image}:ArrayData', status))
# The e-beam marker on the sample camera (an overlay operators see)
for axis in ('x', 'y'):
    _LIST.append(_ch(f'cam_sample_yag.cross_{axis}', 'camera', 'px', True,
                     f'Sample chamber camera: e-beam marker {axis}',
                     f'UED:GIGE:03:Cross2{axis.upper()}', CONFIRMED))

# Steering correctors XC/YC00..05, as kick angles at the nominal energy.
# The BCTRL EGU reads kG-m, but the values (-145.6 with limits +/-521) don't
# look like kG-m; the kick per unit is not known yet.
_UNITS = [(121, 122), (221, 222), (321, 322), (341, 342), (381, 382), None]
for i, units in enumerate(_UNITS):
    for plane, k in (('x', 0), ('y', 1)):
        pv = (f'{plane.upper()}COR:AS01:{units[k]}:BCTRL' if units else None)
        _LIST.append(_ch(f'{plane}c{i:02d}', 'correctors', 'mrad', True,
                         f'{plane.upper()}C{i:02d} steering kick', pv,
                         CONFIRMED if units else UNMAPPED,
                         'BCTRL, EGU kG-m (unconfirmed)' if units else ''))

CHANNELS = {c.name: c for c in _LIST}
