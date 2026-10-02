"""UED beamline PV registry, mapped from the 2023 GUED run-4 scripts.

Each entry pairs the PV used by Fuhao Ji's ued_run4 scripts (old_pv) with
its current counterpart on the UED controls network, plus how sure the
mapping is. Survey done 2026-10-01 on ued-daq with caget only.

Status values:
  CONFIRMED  new PV found, its DESC/IOC alias names the same device
  LIKELY     same role by description, but the old -> new link is inferred
  CANDIDATE  one of several plausible PVs; needs an expert to pick
  UNMAPPED   no current PV found for the old device
  NO_ACCESS  accelerator PV, not reachable over Channel Access from ued-daq
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

    # Beamline devices
    _motor('collimator', 'beamline', 'Collimator', 'UED:USR:MMN:14:07',
           'MOTR:AS01:MC03:CH7:MOTOR', 'mm', CONFIRMED,
           'old "inserted" = 93 mm on the old controller'),
    _value('far_phosphor', 'beamline', 'Far-detector phosphor in/out', None,
           'ASTA:BO:2114-9:BIT2', '', UNMAPPED),
    _value('chamber_light', 'beamline', 'Sample chamber light', None,
           'ACSW:AS01:NW03:2POWERON / :2POWEROFF', '', UNMAPPED,
           'not on PDU 02; PDU 01 (bunker) outlet names unreadable'),

    # Cameras (old areaDetector prefixes had a :cam1 segment, new ones don't)
    _camera('cam_vcc', 'VCC (virtual cathode)', 'UED:GIGE:06', 'ASPS05',
            CONFIRMED),
    _camera('cam_sample_yag', 'Sample-plane YAG', 'UED:GIGE:09', 'ASPS04',
            CANDIDATE, 'GIGE:09 "DIAG YAG"; or GIGE:12 THz Sample, '
            'GIGE:13 Beamline Viewing'),
    _camera('cam_far_andor', 'Far-detector Andor EMCCD', 'UED:ANDOR:CAM:03',
            'ANDOR1', LIKELY, 'archived by the DAQ; ANDOR:CAM:01 is down'),

    # Accelerator (AS01). Old names still appear in the current DAQ lists,
    # but none of them answer from ued-daq.
    _value('gun_amp_req', 'accelerator', 'Gun amplitude request',
           'SIOC:AS01:KY01:0:AREQ', 'SIOC:AS01:KY01:0:AREQ', '', NO_ACCESS),
    _value('gun_phase_req', 'accelerator', 'Gun phase request',
           'SIOC:AS01:KY01:0:PREQ', 'SIOC:AS01:KY01:0:PREQ', 'deg',
           NO_ACCESS),
    _value('gun_amp_avg', 'accelerator', 'Gun amplitude, averaged',
           'SIOC:AS01:KY03:0:AACT_AVGNT', None, '', NO_ACCESS,
           'listed in the current DAQ epicsArch'),
    _value('rep_rate', 'accelerator', 'E-beam repetition rate',
           'KLYS:AS01:1:PulseRepetitionFreq', None, 'Hz', NO_ACCESS,
           'listed in the current DAQ epicsArch'),
    _value('sol1', 'accelerator', 'Gun solenoid readback',
           'SOLN:AS01:121:BACT', 'SOLN:AS01:121:BACT', '', NO_ACCESS),
    _value('sol2', 'accelerator', '2nd solenoid readback',
           'SOLN:AS01:311:BACT', 'SOLN:AS01:311:BACT', '', NO_ACCESS),
    _value('quad1', 'accelerator', 'Quad doublet Q1 readback',
           'QUAD:AS01:361:BACT', 'QUAD:AS01:361:BACT', '', NO_ACCESS),
    _value('quad2', 'accelerator', 'Quad doublet Q2 readback',
           'QUAD:AS01:371:BACT', 'QUAD:AS01:371:BACT', '', NO_ACCESS,
           'plus 10 correctors X/YCOR:AS01:* in ued_run4/PVnamelist.py'),
]

BY_KEY = {c.key: c for c in CHANNELS}
