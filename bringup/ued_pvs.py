"""UED beamline PV registry, mapped from the 2023 GUED run-4 scripts.

Each entry pairs the PV used by Fuhao Ji's ued_run4 scripts (old_pv) with
its current counterpart on the UED controls network, plus how sure the
mapping is. Survey done 2026-10-01 on ued-daq with caget only; updated
2026-10-05 with Fuhao's layout sketch and the gun ramp script ramp_rf.py,
and 2026-10-16 with Fuhao's run-7 PV list (PVnamelist_SUED_agentic.py) and
a re-read of every PV from ued-daq, accelerator PVs included.

Status values:
  CONFIRMED  new PV found, its DESC/IOC alias names the same device
  LIKELY     same role by description, but the old -> new link is inferred
  CANDIDATE  one of several plausible PVs; needs an expert to pick
  UNMAPPED   no current PV found for the old device
  NO_ACCESS  PV not reachable over Channel Access from ued-daq. None since
             2026-10-16: with the address list ued_setup.sh sets
             (172.21.36.255:5064 172.27.99.255:5058), accelerator PVs answer
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

CONFIRMED = 'CONFIRMED'
LIKELY = 'LIKELY'
CANDIDATE = 'CANDIDATE'
UNMAPPED = 'UNMAPPED'
NO_ACCESS = 'NO_ACCESS'


@dataclass(frozen=True)
class Channel:
    key: str
    group: str
    desc: str
    pv: Optional[str]  # control PV (never written by the read-only tools)
    readback: Tuple[str, ...]  # PVs a snapshot reads
    old_pv: Optional[str]
    units: str
    status: str
    note: str = ''


def _motor(key, group, desc, pv, old_pv, units, status, note=''):
    return Channel(key, group, desc, pv, (pv + '.RBV',), old_pv, units,
                   status, note)


def _value(key, group, desc, pv, old_pv, units, status, note=''):
    return Channel(key, group, desc, pv, (pv,) if pv else (), old_pv, units,
                   status, note)


def _camera(key, desc, prefix, old_prefix, status, note=''):
    rb = tuple(f'{prefix}:{s}' for s in
               ('Acquire_RBV', 'AcquireTime_RBV', 'Gain_RBV'))
    return Channel(key, 'camera', desc, prefix, rb, old_prefix, '', status,
                   note)


CHANNELS = [
    # Laser: shutters and charge / pump energy
    _value('gun_uv_shutter', 'laser', 'Gun UV shutter', 'UED:USR:BHC:AO1:4',
           'ASTA:LSC01:OC:OPEN / :CLOSE', 'V', CONFIRMED,
           'Beckhoff analog out; open/closed voltage levels to confirm'),
    _value('pump_shutter', 'laser', 'Pump main shutter', 'UED:USR:BHC:AO1:3',
           'ASTA:LSC03:OC:OPEN / :CLOSE', 'V', CONFIRMED,
           'Beckhoff analog out; open/closed voltage levels to confirm'),
    _value('pump_extra_shutter', 'laser', 'Pump extra shutter',
           'UED:USR:BHC:AO1:2', None, 'V', CONFIRMED, 'new device'),
    _motor('gun_uv_throttle', 'laser', 'Drive UV throttle (max @ 21 deg)',
           'UED:USR:MMN:14:01', 'MOTR:AS01:MC03:CH1:MOTOR', 'deg', CONFIRMED,
           'old 10 fC = 48.4, 50 fC = 28.4; recalibrate with Faraday cup'),
    _motor('pump_nd_wheel', 'laser', 'Pump ND wheel (max @ 310 deg)',
           'UED:USR:MMN:05:08', 'MOTR:AS01:MC04:CH2:MOTOR', 'deg', CONFIRMED,
           'in the run-7 list; old "lowest" = -150 on a different scale'),
    _motor('harmonics_hwp', 'laser', 'Harmonics HWP (max @ 51 deg)',
           'UED:USR:MMN:05:02', 'MOTR:AS01:MC04:CH3:MOTOR', 'deg', CONFIRMED,
           'the pump HWP in the run-7 list ("Max@50"); old lowest = 70'),
    _motor('pump_hwp_527', 'laser', '527 nm HWP (min @ 131 deg)',
           'UED:USR:MMN:05:03', None, 'deg', CANDIDATE,
           'not in the run-7 list'),
    _motor('pump_throttle', 'laser', 'Pump throttle (max @ 44.5 deg)',
           'UED:USR:MMN:08:01', None, 'deg', LIKELY,
           'the run-7 list calls it the THz throttle'),
    _motor('pump_power_meter', 'laser', 'Pump power meter (in @ 40 mm)',
           'UED:USR:MMN:05:06', None, 'mm', CONFIRMED,
           'blocks the pump when in; read 40 (in) on 2026-10-16'),
    _motor('pump_lens_h', 'laser', 'Pump lens H', 'UED:USR:MMN:08:05', None,
           'mm', CONFIRMED, 'in the run-7 list; moves the pump spot'),
    _motor('pump_lens_v', 'laser', 'Pump lens V', 'UED:USR:MMN:08:06', None,
           'mm', CONFIRMED, 'in the run-7 list; moves the pump spot'),
    _motor('pump_beam_x', 'laser', 'Pump beam X (SmarAct)', 'UED:MCS:01:m7',
           None, 'mm', LIKELY, 'DESC pump_beam_X; not in the run-7 list'),
    _motor('pump_beam_y', 'laser', 'Pump beam Y (SmarAct)', 'UED:MCS:01:m8',
           None, 'mm', LIKELY, 'DESC pump_beam_Y; not in the run-7 list'),

    # Pump-probe delay
    _motor('pump_long_delay', 'pump_probe', 'Pump long delay',
           'UED:USR:MMN:03:04', None, 'mm', CONFIRMED,
           'run-7 list (was MMN:03:05 until 2026-04-07)'),
    _motor('pump_long_delay_drv03', 'pump_probe', 'Pump long delay DRV03',
           'UED:USR:MMN:06:06', None, 'mm', CANDIDATE,
           'DESC "Pump Long Delay DRV03"; not in the run-7 list'),
    _motor('opa_delay', 'pump_probe', 'OPA delay', 'UED:USR:MMN:06:05', None,
           'mm', CONFIRMED, 'in the run-7 list'),

    # Sample stage (old: PI hexapod X/Y/Z + SmarAct relative X). The run-7
    # list puts the SUED sample stage on XPS-11, whose DESCs still name
    # other optics; XPS-04 has "Sample Y" (04:01, 04:07), "Sample Z" (04:06)
    # and "1st Pitch" (04:04, which the 2026-10-01 survey took for X).
    _motor('sample_x', 'sample', 'Sample X', 'UED:USR:MMN:11:03',
           'ASTA:PI02:M3:MOTOR', 'mm', LIKELY,
           'run-7 list; DESC "Incoupling X"'),
    _motor('sample_y', 'sample', 'Sample Y', 'UED:USR:MMN:11:04',
           'ASTA:PI02:M2:MOTOR', 'mm', LIKELY,
           'run-7 list; DESC "Incoupling Y"'),
    _motor('sample_z', 'sample', 'Sample Z', 'UED:USR:MMN:11:05',
           'ASTA:PI02:M1:MOTOR', 'mm', LIKELY,
           'run-7 list; DESC "Outcoupling in@24.9"'),
    _motor('sample_pitch', 'sample', 'Sample pitch', 'UED:USR:MMN:11:01',
           None, 'deg', LIKELY, 'run-7 list; DESC "Capillary Y"'),
    _motor('sample_yaw', 'sample', 'Sample yaw', 'UED:USR:MMN:11:08', None,
           'deg', LIKELY, 'run-7 list; DESC "Catcher Y"'),
    _motor('sample_rel_x', 'sample', 'SmarAct relative X', 'UED:MCS2:03:m1',
           'ASTA:SMAR02:M1:MOTOR', 'mm', CANDIDATE,
           'DAQ archive calls it Sample_relative_X, DESC says Charge Guard'),

    # Beamline devices. Order along the beam (kicker sketch): gun, gun
    # solenoid, XC/YC00, Faraday cup + Diag YAG, collimator, XC/YC01, ...
    _motor('collimator', 'beamline', 'Collimator', 'UED:USR:MMN:14:07',
           'MOTR:AS01:MC03:CH7:MOTOR', 'mm', CONFIRMED,
           'old "inserted" = 93 mm on the old controller'),
    _value('faraday_cup', 'beamline', 'Faraday cup, before collimator', None,
           None, '', UNMAPPED, 'shares a holder with the Diag YAG (sketch)'),
    _value('far_phosphor', 'beamline', 'Far-detector phosphor in/out', None,
           'ASTA:BO:2114-9:BIT2', '', UNMAPPED,
           'the old PV is commented out in the run-7 list and does not '
           'answer'),
    _value('chamber_light', 'beamline', 'Sample chamber light',
           'ACSW:AS01:NW03:2POWERSTATE', 'ACSW:AS01:NW03:2POWERON / '
           ':2POWEROFF', '', CONFIRMED,
           'run-7 list: switched with 2POWERON / 2POWEROFF'),

    # Cameras (old areaDetector prefixes had a :cam1 segment, new ones don't)
    _camera('cam_vcc', 'VCC (virtual cathode)', 'UED:GIGE:06', 'ASPS05',
            CONFIRMED),
    _camera('cam_diag_yag', 'Diag YAG, before collimator', 'UED:GIGE:09',
            None, LIKELY, 'IOC alias "DIAG YAG"; sketch puts the Diag YAG '
            'with the Faraday cup upstream of the collimator'),
    _camera('cam_sample_yag', 'Sample chamber camera', 'UED:GIGE:03',
            'ASPS04', CONFIRMED, 'run-7 list; RGB 2048x2048, e-beam cross '
            'at Cross2X/Y; its Stats plugins are disabled'),
    _camera('cam_thz', 'THz chamber camera', 'UED:GIGE:12', 'ASPS07',
            CONFIRMED, 'run-7 list'),
    _camera('cam_far_andor', 'Far-detector Andor EMCCD', 'UED:ANDOR:CAM:03',
            'ANDOR1', CONFIRMED, 'run-7 list; image on IMAGE2, Stats1 on '
            'ROI1'),

    # Gun RF (klystron KY03 since run 4's KY01; names from ramp_rf.py)
    _value('gun_amp_req', 'gun_rf', 'Gun amplitude setpoint AREQ',
           'SIOC:AS01:KY03:0:AREQ', 'SIOC:AS01:KY01:0:AREQ', '', CONFIRMED,
           'operating 0.53; ramp starts at 0.05 (ramp_rf.py)'),
    _value('gun_phase_req', 'gun_rf', 'Gun phase setpoint PREQ',
           'SIOC:AS01:KY03:0:PREQ', 'SIOC:AS01:KY01:0:PREQ', 'deg',
           CONFIRMED, 'in the run-7 list'),
    _value('gun_amp_avg', 'gun_rf', 'Gun amplitude readback, averaged',
           'SIOC:AS01:KY03:0:AACT_AVGNT', None, 'kV', CONFIRMED,
           'in the run-7 list'),
    _value('gun_phase_avg', 'gun_rf', 'Gun phase readback, averaged',
           'SIOC:AS01:KY03:0:PACT_AVGNT', None, 'deg', CONFIRMED,
           'in the run-7 list'),
    _value('gun_pfb_enable', 'gun_rf', 'Phase feedback enable',
           'SIOC:AS01:KY03:0:PFBENB', None, '', CONFIRMED),
    _value('gun_afb_enable', 'gun_rf', 'Amplitude feedback enable',
           'SIOC:AS01:KY03:0:AFBENB', None, '', CONFIRMED),
    _value('gun_pfb_status', 'gun_rf', 'Phase feedback status',
           'SIOC:AS01:KY03:0:PFBST', None, '', CONFIRMED),
    _value('gun_afb_status', 'gun_rf', 'Amplitude feedback status',
           'SIOC:AS01:KY03:0:AFBST', None, '', CONFIRMED,
           'ramp_rf.py expects the string Active; reads Disable when off'),
    _value('gun_temp', 'gun_rf', 'Gun body temperature',
           'APC:AS01:TM01:M2_CH2_SPARE', 'APC:AS01:TM01:M2_CH2_SPARE', 'C',
           CONFIRMED, 'ramp holds outside 33..37 C'),
    _value('rep_rate', 'gun_rf', 'E-beam repetition rate',
           'KLYS:AS01:1:PulseRepetitionFreq', None, 'Hz', CONFIRMED,
           'listed in the current DAQ epicsArch'),

    # Magnets (in the run-7 list; all off or tripped on 2026-10-16)
    _value('sol1', 'magnets', 'Gun solenoid readback',
           'SOLN:AS01:121:BACT', 'SOLN:AS01:121:BACT', '', CONFIRMED),
    _value('sol2', 'magnets', '2nd solenoid readback',
           'SOLN:AS01:311:BACT', 'SOLN:AS01:311:BACT', '', CONFIRMED),
    _value('quad1', 'magnets', 'Quad doublet QD01 readback',
           'QUAD:AS01:361:BACT', 'QUAD:AS01:361:BACT', '', CONFIRMED),
    _value('quad2', 'magnets', 'Quad doublet QF01 readback',
           'QUAD:AS01:371:BACT', 'QUAD:AS01:371:BACT', '', CONFIRMED),
] + [
    # Correctors XC/YC00..04 (in the run-7 list). XC/YC05 is in the sketch
    # but in neither list. BCTRL's EGU says kG-m; BDES reads 0 while BCTRL
    # reads e.g. -145.6, so which one sets the kick is still open.
    _value(f'{p.lower()}c{i:02d}', 'correctors', f'{p}C{i:02d} kicker',
           f'{p}COR:AS01:{u}:BCTRL', f'{p}COR:AS01:{u}:BCTRL', 'kG-m',
           CONFIRMED)
    for i, (ux, uy) in enumerate([(121, 122), (221, 222), (321, 322),
                                  (341, 342), (381, 382)])
    for p, u in (('X', ux), ('Y', uy))
]

BY_KEY = {c.key: c for c in CHANNELS}
