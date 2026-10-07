"""UED beamline PV registry, mapped from the 2023 GUED run-4 scripts.

Each entry pairs the PV used by Fuhao Ji's ued_run4 scripts (old_pv) with
its current counterpart on the UED controls network, plus how sure the
mapping is. Survey done 2026-10-01 on ued-daq with caget only; updated
2026-10-05 with Fuhao's layout sketch and the gun ramp script ramp_rf.py.

Status values:
  CONFIRMED  new PV found, its DESC/IOC alias names the same device
  LIKELY     same role by description, but the old -> new link is inferred
  CANDIDATE  one of several plausible PVs; needs an expert to pick
  UNMAPPED   no current PV found for the old device
  NO_ACCESS  accelerator PV, not reachable over Channel Access from ued-daq
             (ramp_rf.py runs on testfac-srv01, where they are reachable)
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
           'UED:USR:MMN:05:08', 'MOTR:AS01:MC04:CH2:MOTOR', 'deg', LIKELY,
           'old "lowest" = -150 on a different scale'),
    _motor('pump_hwp_527', 'laser', '527 nm HWP (min @ 131 deg)',
           'UED:USR:MMN:05:03', 'MOTR:AS01:MC04:CH3:MOTOR', 'deg', CANDIDATE,
           'old pump HWP: lowest = 70; per-sample 70..76.7, -130'),
    _motor('harmonics_hwp', 'laser', 'Harmonics HWP (max @ 51 deg)',
           'UED:USR:MMN:05:02', None, 'deg', CANDIDATE,
           'alternative match for the old pump HWP'),
    _motor('pump_throttle', 'laser', 'Pump throttle (max @ 44.5 deg)',
           'UED:USR:MMN:08:01', None, 'deg', LIKELY,
           'new pump energy control; no run-4 equivalent'),

    # Sample stage (old: PI hexapod X/Y/Z + SmarAct relative X)
    _motor('sample_x', 'sample', 'Sample X', 'UED:USR:MMN:04:04',
           'ASTA:PI02:M3:MOTOR', 'mm', LIKELY),
    _motor('sample_y', 'sample', 'Sample Y', 'UED:USR:MMN:04:07',
           'ASTA:PI02:M2:MOTOR', 'mm', LIKELY,
           'UED:USR:MMN:04:01 is also labelled "Sample Y"'),
    _motor('sample_z', 'sample', 'Sample Z', 'UED:USR:MMN:04:06',
           'ASTA:PI02:M1:MOTOR', 'mm', LIKELY),
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
           'ASTA:BO:2114-9:BIT2', '', UNMAPPED),
    _value('chamber_light', 'beamline', 'Sample chamber light', None,
           'ACSW:AS01:NW03:2POWERON / :2POWEROFF', '', UNMAPPED,
           'not on PDU 02; PDU 01 (bunker) outlet names unreadable'),

    # Cameras (old areaDetector prefixes had a :cam1 segment, new ones don't)
    _camera('cam_vcc', 'VCC (virtual cathode)', 'UED:GIGE:06', 'ASPS05',
            CONFIRMED),
    _camera('cam_diag_yag', 'Diag YAG, before collimator', 'UED:GIGE:09',
            None, LIKELY, 'IOC alias "DIAG YAG"; sketch puts the Diag YAG '
            'with the Faraday cup upstream of the collimator'),
    _camera('cam_sample_yag', 'Sample-plane YAG', 'UED:GIGE:13', 'ASPS04',
            CANDIDATE, 'GIGE:13 Beamline Viewing or GIGE:12 THz Sample'),
    _camera('cam_far_andor', 'Far-detector Andor EMCCD', 'UED:ANDOR:CAM:03',
            'ANDOR1', LIKELY, 'archived by the DAQ; ANDOR:CAM:01 is down'),

    # Gun RF (klystron KY03 since run 4's KY01; names from ramp_rf.py)
    _value('gun_amp_req', 'gun_rf', 'Gun amplitude setpoint AREQ',
           'SIOC:AS01:KY03:0:AREQ', 'SIOC:AS01:KY01:0:AREQ', '', NO_ACCESS,
           'operating 0.53; ramp starts at 0.05 (ramp_rf.py)'),
    _value('gun_phase_req', 'gun_rf', 'Gun phase setpoint PREQ',
           'SIOC:AS01:KY03:0:PREQ', 'SIOC:AS01:KY01:0:PREQ', 'deg',
           NO_ACCESS, 'KY03 name inferred from AREQ'),
    _value('gun_amp_avg', 'gun_rf', 'Gun amplitude readback, averaged',
           'SIOC:AS01:KY03:0:AACT_AVGNT', None, '', NO_ACCESS,
           'listed in the current DAQ epicsArch'),
    _value('gun_pfb_enable', 'gun_rf', 'Phase feedback enable',
           'SIOC:AS01:KY03:0:PFBENB', None, '', NO_ACCESS),
    _value('gun_afb_enable', 'gun_rf', 'Amplitude feedback enable',
           'SIOC:AS01:KY03:0:AFBENB', None, '', NO_ACCESS),
    _value('gun_pfb_status', 'gun_rf', 'Phase feedback status',
           'SIOC:AS01:KY03:0:PFBST', None, '', NO_ACCESS),
    _value('gun_afb_status', 'gun_rf', 'Amplitude feedback status',
           'SIOC:AS01:KY03:0:AFBST', None, '', NO_ACCESS,
           'ramp_rf.py expects the string Active'),
    _value('gun_temp', 'gun_rf', 'Gun body temperature',
           'APC:AS01:TM01:M2_CH2_SPARE', 'APC:AS01:TM01:M2_CH2_SPARE', 'C',
           NO_ACCESS, 'ramp holds outside 33..37 C'),
    _value('rep_rate', 'gun_rf', 'E-beam repetition rate',
           'KLYS:AS01:1:PulseRepetitionFreq', None, 'Hz', NO_ACCESS,
           'listed in the current DAQ epicsArch'),

    # Magnets (old run-4 names; not yet seen in any current list)
    _value('sol1', 'magnets', 'Gun solenoid readback',
           'SOLN:AS01:121:BACT', 'SOLN:AS01:121:BACT', '', NO_ACCESS),
    _value('sol2', 'magnets', '2nd solenoid readback',
           'SOLN:AS01:311:BACT', 'SOLN:AS01:311:BACT', '', NO_ACCESS),
    _value('quad1', 'magnets', 'Quad doublet QD01 readback',
           'QUAD:AS01:361:BACT', 'QUAD:AS01:361:BACT', '', NO_ACCESS),
    _value('quad2', 'magnets', 'Quad doublet QF01 readback',
           'QUAD:AS01:371:BACT', 'QUAD:AS01:371:BACT', '', NO_ACCESS),
] + [
    # Correctors XC/YC00..04: unit numbers rise along the beam like the
    # solenoids' (121 at the gun solenoid, 311 at solenoid 2). XC/YC05 is
    # in the sketch but not in the run-4 list.
    _value(f'{p.lower()}c{i:02d}', 'correctors', f'{p}C{i:02d} kicker',
           f'{p}COR:AS01:{u}:BCTRL', f'{p}COR:AS01:{u}:BCTRL', '',
           NO_ACCESS)
    for i, (ux, uy) in enumerate([(121, 122), (221, 222), (321, 322),
                                  (341, 342), (381, 382)])
    for p, u in (('X', ux), ('Y', uy))
]

BY_KEY = {c.key: c for c in CHANNELS}
