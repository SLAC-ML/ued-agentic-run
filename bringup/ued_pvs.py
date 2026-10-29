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
           "Beckhoff analog out: 3 V open, 0 V closed (Xinxin's Run 6 code)"),
    _value('pump_shutter', 'laser', 'Pump main shutter', 'UED:USR:BHC:AO1:3',
           'ASTA:LSC03:OC:OPEN / :CLOSE', 'V', CONFIRMED,
           "Beckhoff analog out: 3 V open, 0 V closed (Xinxin's Run 6 code)"),
    _value('pump_extra_shutter', 'laser', 'Pump extra shutter',
           'UED:USR:BHC:AO1:2', None, 'V', CONFIRMED,
           'Beckhoff analog out: 3 V open, 0 V closed; not used in the loop'),
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

    # Sample stage: the solid-state (SUED) chamber stage on XPS-11, per
    # Fuhao (2026-10-28): X, Y, Z, pitch, yaw. Run 4 was a gas-phase run on
    # the GUED chamber (PI hexapod X/Y/Z + SmarAct relative X), so it has no
    # equivalent here (old_pv None) and relative X is retired; pitch and yaw
    # take its place. The XPS-11 motor DESCs are stale (Incoupling X/Y,
    # Outcoupling, Capillary Y, Catcher Y).
    _motor('sample_x', 'sample', 'SUED sample stage X', 'UED:USR:MMN:11:03',
           None, 'mm', CONFIRMED, 'run-7 list; DESC stale ("Incoupling X")'),
    _motor('sample_y', 'sample', 'SUED sample stage Y', 'UED:USR:MMN:11:04',
           None, 'mm', CONFIRMED, 'run-7 list; DESC stale ("Incoupling Y")'),
    _motor('sample_z', 'sample', 'SUED sample stage Z', 'UED:USR:MMN:11:05',
           None, 'mm', CONFIRMED,
           'run-7 list; DESC stale ("Outcoupling in@24.9")'),
    _motor('sample_pitch', 'sample', 'SUED sample stage pitch',
           'UED:USR:MMN:11:01', None, 'deg', CONFIRMED,
           'run-7 list; DESC stale ("Capillary Y")'),
    _motor('sample_yaw', 'sample', 'SUED sample stage yaw',
           'UED:USR:MMN:11:08', None, 'deg', CONFIRMED,
           'run-7 list; DESC stale ("Catcher Y")'),

    # Beamline devices. Order along the beam (kicker sketch): gun, gun
    # solenoid, XC/YC00, Faraday cup + Diag YAG, collimator, XC/YC01, ...
    _motor('collimator', 'beamline', 'Collimator', 'UED:USR:MMN:14:07',
           'MOTR:AS01:MC03:CH7:MOTOR', 'mm', CONFIRMED,
           'old "inserted" = 93 mm on the old controller'),
    _value('faraday_cup', 'beamline', 'Faraday cup, before collimator', None,
           None, '', UNMAPPED, 'shares a holder with the Diag YAG (sketch)'),
    _value('diag_screen_state', 'beamline', 'Diagnostic screen state',
           'YAGS:AS01:270:OPENSOLENOID', None, '', LIKELY,
           'run-7 list; screen moved by YAGS:AS01:270:OPENCMD (insert) / '
           ':CLOSECMD (remove), commands the agent never writes'),
    _value('diag_screen_interlock', 'beamline',
           'Diagnostic screen interlock summary', 'YAGS:AS01:270:INTLKSUM',
           None, '', LIKELY, 'run-7 list'),
    *[_value(f'gate_valve_{u}', 'vacuum', f'Gate valve {u}',
             f'VVPG:AS01:{u}:POSITION', None, '', CONFIRMED,
             'OPEN, CLOSED, MOVING or INCONSISTENT; all four OPEN to see the '
             'e-beam (Fuhao, 2026-10)')
      for u in (240, 272, 280, 295)],
    _value('gate_valve_320', 'vacuum', 'Gate valve 320 (ePix line)',
           'VVPG:AS01:320:POSITION', None, '', LIKELY,
           "Xinxin's Run 6 code; monitored, not a gate for the Andor"),
    _value('scope_ch2_trace', 'diagnostics', 'Scope CH2 trace (bunch charge)',
           'SCOP:AS01:SC01:WF_CH2_TRACE', None, 'div', CONFIRMED,
           '500 samples; negative-going pulse, -1.7 mV = 10 fC; confirmed in '
           'the 2026-10-16 dry run'),
    _value('scope_ch2_vdiv', 'diagnostics', 'Scope CH2 volts/div',
           'SCOP:AS01:SC01:MBBO_CH2_SCL', None, '', CONFIRMED,
           'an output record that reads UDF; check the front panel'),
    _value('scope_ch0_trace', 'diagnostics', 'Scope CH0 trace',
           'SCOP:AS01:SC01:WF_CH0_TRACE', None, 'div', CONFIRMED,
           "the trace Fuhao's stage-2 text names; reads ~-2.4 div at 1 V/div"),
    _value('scope_ch0_vdiv', 'diagnostics', 'Scope CH0 volts/div',
           'SCOP:AS01:SC01:MBBO_CH0_SCL', None, '', CONFIRMED,
           'an output record that reads UDF'),
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
    _camera('cam_diag_yag', 'Diagnostic screen, before collimator',
            'UED:GIGE:09', None, CONFIRMED, "Fuhao's run-7 list (image, "
            'size, ROI1); IOC alias "DIAG YAG"; the screen shares a holder '
            'with the Faraday cup upstream of the collimator'),
    _camera('cam_sample_yag', 'Sample chamber camera', 'UED:GIGE:02',
            'ASPS04', LIKELY, 'GIGE:02 per Fuhao (2026-10-28), RGB; e-beam cross '
            'at Cross2X/Y. GIGE:03, used until then, is another camera with '
            'the same parameters'),
    _camera('cam_side', 'Sample chamber side camera', 'UED:GIGE:03',
            'ASPS03', LIKELY, "side view; Xinxin's Run 6 code (sideCam)"),
    _camera('cam_thz', 'THz chamber camera', 'UED:GIGE:12', 'ASPS07',
            CONFIRMED, 'run-7 list'),
    _camera('cam_far_andor', 'Far-detector Andor EMCCD', 'UED:ANDOR:CAM:03',
            'ANDOR1', CONFIRMED, 'run-7 list; image on IMAGE2, Stats1 on '
            'ROI1'),

    # Gun RF: klystron KY03 (TS8), back on it since 2026-10-28; TS1 (KY01,
    # run 4's) is offline. old_pv keeps the run-4 KY01 names for reference
    # only: nothing reads them. Names from ramp_rf.py.
    _value('gun_amp_req', 'gun_rf', 'Gun amplitude setpoint AREQ',
           'SIOC:AS01:KY03:0:AREQ', 'SIOC:AS01:KY01:0:AREQ', '', CONFIRMED,
           'operating 0.53; ramp starts at 0.05 (ramp_rf.py); EGU says '
           '"degrees" but it is dimensionless'),
    _value('gun_phase_req', 'gun_rf', 'Gun phase setpoint PREQ',
           'SIOC:AS01:KY03:0:PREQ', 'SIOC:AS01:KY01:0:PREQ', 'deg',
           CONFIRMED, '-180..180'),
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
           CONFIRMED, 'ramp holds outside gun.ramp_temp_min_C..max_C (33..36 C)'),
    _value('rep_rate', 'gun_rf', 'E-beam repetition rate',
           'KLYS:AS01:1:PulseRepetitionFreq', None, 'Hz', CONFIRMED,
           'listed in the current DAQ epicsArch'),

    # Magnets (in the run-7 list; all off or tripped on 2026-10-16)
    Channel('sol1', 'magnets', 'Gun solenoid (setpoint BCTRL, readback BACT)',
            'SOLN:AS01:121:BCTRL',
            ('SOLN:AS01:121:BCTRL', 'SOLN:AS01:121:BACT'),
            'SOLN:AS01:121:BACT', 'kG-m', CONFIRMED),
    Channel('sol2', 'magnets', '2nd solenoid (setpoint BCTRL, readback BACT)',
            'SOLN:AS01:311:BCTRL',
            ('SOLN:AS01:311:BCTRL', 'SOLN:AS01:311:BACT'),
            'SOLN:AS01:311:BACT', 'A', CONFIRMED),
    Channel('quad1', 'magnets', 'Quad doublet QD01 (setpoint BCTRL, readback BACT)',
            'QUAD:AS01:361:BCTRL',
            ('QUAD:AS01:361:BCTRL', 'QUAD:AS01:361:BACT'),
            'QUAD:AS01:361:BACT', '', CONFIRMED),
    Channel('quad2', 'magnets', 'Quad doublet QF01 (setpoint BCTRL, readback BACT)',
            'QUAD:AS01:371:BCTRL',
            ('QUAD:AS01:371:BCTRL', 'QUAD:AS01:371:BACT'),
            'QUAD:AS01:371:BACT', '', CONFIRMED),

    # 2nd SUED sample stage (run-7 list, "updated"). Its Z, MMN:03:04, is
    # also the pump long delay in the same list, so Z stays unmapped until
    # that is resolved.
    _motor('sample2_x', 'sample', '2nd SUED sample stage X',
           'UED:USR:MMN:03:05', None, 'mm', LIKELY, 'run-7 list'),
    _motor('sample2_y', 'sample', '2nd SUED sample stage Y',
           'UED:USR:MMN:03:03', None, 'mm', LIKELY, 'run-7 list'),
    _value('sample2_z', 'sample', '2nd SUED sample stage Z', None, None,
           'mm', UNMAPPED, 'run-7 list says MMN:03:04, which is also the '
           'pump long delay'),
    _motor('sample2_pitch', 'sample', '2nd SUED sample stage pitch',
           'UED:USR:MMN:03:01', None, 'deg', LIKELY, 'run-7 list'),
    _motor('sample2_yaw', 'sample', '2nd SUED sample stage yaw',
           'UED:USR:MMN:03:08', None, 'deg', LIKELY, 'run-7 list'),

    # THz line (run-7 list)
    _motor('thz_delay', 'thz', 'THz delay stage', 'UED:USR:MMN:06:08', None,
           'mm', LIKELY, 'run-7 list'),
    _motor('thz_parabola_y', 'thz', 'THz parabola mirror Y',
           'UED:USR:MMN:13:02', None, 'mm', LIKELY, 'run-7 list'),
    _motor('thz_parabola_x', 'thz', 'THz parabola mirror X',
           'UED:USR:MMN:13:03', None, 'mm', LIKELY, 'run-7 list'),
    _motor('thz_stage_x', 'thz', 'THz stage X', 'UED:USR:MMN:13:04', None,
           'mm', LIKELY, 'run-7 list'),
    _motor('thz_stage_y', 'thz', 'THz stage Y', 'UED:USR:MMN:13:05', None,
           'mm', LIKELY, 'run-7 list'),
    _motor('thz_stage_z', 'thz', 'THz stage Z', 'UED:USR:MMN:13:06', None,
           'mm', LIKELY, 'run-7 list'),
    Channel('thz_cross', 'thz', 'THz chamber camera e-beam cross X, Y',
            'UED:GIGE:12:Cross2X',
            ('UED:GIGE:12:Cross2X', 'UED:GIGE:12:Cross2Y'), None, 'px',
            LIKELY, 'run-7 list'),

] + [
    # Camera ROI1 (MinX, MinY, SizeX, SizeY), from the run-7 list. The tools
    # compute beam stats on the full IMAGE frame; the ROIs are for reference.
    Channel(f'{key}_roi1', 'camera_roi', f'{label}: ROI1',
            f'{prefix}:ROI1:MinX',
            tuple(f'{prefix}:ROI1:{s}' for s in
                  ('MinX', 'MinY', 'SizeX', 'SizeY')), None, 'px', status,
            'run-7 list')
    for key, label, prefix, status in (
        ('cam_vcc', 'VCC', 'UED:GIGE:06', LIKELY),
        ('cam_diag_yag', 'Diagnostic screen', 'UED:GIGE:09', LIKELY),
        ('cam_sample_yag', 'Sample chamber camera', 'UED:GIGE:02', LIKELY),
        ('cam_thz', 'THz chamber camera', 'UED:GIGE:12', LIKELY),
        ('cam_far_andor', 'Far-detector Andor', 'UED:ANDOR:CAM:03', LIKELY))
] + [
    # Correctors XC/YC00..04 (in the run-7 list). XC/YC05 is in the sketch
    # but in neither list. BCTRL's EGU says kG-m; BDES reads 0 while BCTRL
    # reads e.g. -145.6, so which one sets the kick is still open.
    Channel(f'{p.lower()}c{i:02d}', 'correctors',
            f'{p}C{i:02d} kicker (setpoint BCTRL, readback BACT)',
            f'{p}COR:AS01:{u}:BCTRL',
            (f'{p}COR:AS01:{u}:BCTRL', f'{p}COR:AS01:{u}:BACT'),
            f'{p}COR:AS01:{u}:BCTRL', 'kG-m', CONFIRMED)
    for i, (ux, uy) in enumerate([(121, 122), (221, 222), (321, 322),
                                  (341, 342), (381, 382)])
    for p, u in (('X', ux), ('Y', uy))
]

BY_KEY = {c.key: c for c in CHANNELS}
