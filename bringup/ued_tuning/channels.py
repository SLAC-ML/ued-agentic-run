"""Logical channels the UED tuning tools read and write.

One vocabulary for every backend. The virtual machine (sim/virtual_ued.py)
answers every name; the read-only EPICS backend maps a name to its PV, and
refuses a name whose PV is not known yet. PV names follow Fuhao Ji's run-7
list (PVnamelist_SUED_agentic.py) and the operator's dry-run notes of
2026-10-16 (the oscilloscope; gun RF back on KY03/TS8 since 2026-10-28); every PV was read from
ued-daq on 2026-10-16 or 2026-10-21.

Units are the real machine's wherever they are known (collimator and power
meter in mm, pump HWP in deg), so ued_setup.yaml's setpoints and safety
ranges mean the same on both backends. `pv_units` is what the real PV is in
where it still differs from the logical units.

Status values are the ones ued_pvs.py uses, plus SIM_ONLY for quantities no
PV carries (on the real machine they need an analysis of a detector image).
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
GATE_VALVES = ('gv240', 'gv272', 'gv280', 'gv295')
# Monitored only, not a gate: the ePix gate valve (Xinxin's Run 6 code)
# matters for the ePix, not for the Andor path this run.
MONITOR_VALVES = ('gv320',)

# Shutters are Beckhoff analog outputs (BHC AO1). From Xinxin's Run 6 code:
# 3 = open, 0 = closed; read as open when > 0. The tools use 1/0 (open/
# closed); to_pv / from_pv translate at the machine boundary.
SHUTTERS = ('gun_uv_shutter', 'pump_shutter', 'pump_extra_shutter')
SHUTTER_OPEN_V, SHUTTER_CLOSED_V = 3.0, 0.0


def to_pv(name, value):
    """The value a write of `value` to channel `name` puts on its PV."""
    if name in SHUTTERS:
        return SHUTTER_OPEN_V if value else SHUTTER_CLOSED_V
    return value


def from_pv(name, raw):
    """The tools' value for a raw PV reading of channel `name`."""
    if name in SHUTTERS and raw is not None:
        return 1 if float(raw) > 0 else 0
    return raw


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


_KY = 'SIOC:AS01:KY03:0:'     # TS8 klystron (back on it 2026-10-28; TS1/KY01 is offline)

_LIST = [
    # Gun RF (klystron KY03, TS8).
    _ch('areq', 'gun_rf', '', True, 'Gun amplitude setpoint (0..0.53)',
        _KY + 'AREQ', CONFIRMED, 'unconfirmed (EGU "degrees")'),
    _ch('preq', 'gun_rf', 'deg', True, 'Gun phase setpoint (-180..180)',
        _KY + 'PREQ', CONFIRMED),
    _ch('aact', 'gun_rf', '', False, 'Gun amplitude readback (averaged)',
        _KY + 'AACT_AVGNT', CONFIRMED, 'kV'),
    _ch('pact', 'gun_rf', 'deg', False, 'Gun phase readback (averaged)',
        _KY + 'PACT_AVGNT', CONFIRMED),
    _ch('pfb_enable', 'gun_rf', '', True, 'Phase feedback enable',
        _KY + 'PFBENB', CONFIRMED, as_string=True),
    _ch('afb_enable', 'gun_rf', '', True, 'Amplitude feedback enable',
        _KY + 'AFBENB', CONFIRMED, as_string=True),
    _ch('pfb_status', 'gun_rf', '', False,
        'Phase feedback status (Disable, Pause, Feedforward, Active)',
        _KY + 'PFBST', CONFIRMED, as_string=True),
    _ch('afb_status', 'gun_rf', '', False,
        'Amplitude feedback status (Disable, Pause, Feedforward, Active)',
        _KY + 'AFBST', CONFIRMED, as_string=True),
    _ch('gun_temp', 'gun_rf', 'C', False,
        'Gun body temperature (a Beckhoff thermocouple, not klystron-scoped)',
        'APC:AS01:TM01:M2_CH2_SPARE', CONFIRMED),

    # Vacuum: all four gate valves must be OPEN to see the e-beam
    *[_ch(gv, 'vacuum', '', False,
          f'Gate valve {gv[2:]} (OPEN, CLOSED, MOVING, INCONSISTENT)',
          f'VVPG:AS01:{gv[2:]}:POSITION', CONFIRMED, as_string=True)
      for gv in GATE_VALVES],
    *[_ch(gv, 'vacuum', '', False,
          f'Gate valve {gv[2:]} (ePix line; monitored, not a gate for the '
          'Andor)', f'VVPG:AS01:{gv[2:]}:POSITION', LIKELY, as_string=True)
      for gv in MONITOR_VALVES],

    # Lasers
    _ch('gun_uv_shutter', 'laser', '', True,
        'Gun UV shutter (1 open, 0 closed; on the PV 3 V open, 0 V closed)',
        'UED:USR:BHC:AO1:4', CONFIRMED, 'V'),
    _ch('gun_uv_throttle', 'laser', 'deg', True,
        'Drive UV throttle (max transmission at 21 deg; ~51 for the phase '
        'scan, ~53 for operation)', 'UED:USR:MMN:14:01', CONFIRMED),
    _ch('pump_shutter', 'laser', '', True,
        'Pump main shutter (1 open, 0 closed; on the PV 3 V open, 0 V '
        'closed)', 'UED:USR:BHC:AO1:3', CONFIRMED, 'V'),
    _ch('pump_extra_shutter', 'laser', '', True,
        'Pump extra shutter (not used in the measurement loop; 3 V open)',
        'UED:USR:BHC:AO1:2', CONFIRMED, 'V'),
    _ch('pump_hwp', 'laser', 'deg', True,
        'Pump Harmonics HWP: sets the pump energy (max @ 51 deg). Its '
        'setpoints (minimum energy, ~2 uJ) are in ued_setup.yaml',
        'UED:USR:MMN:05:02', CONFIRMED),
    _ch('pump_nd_wheel', 'laser', 'deg', True, 'Pump ND wheel (max @ 310)',
        'UED:USR:MMN:05:08', CONFIRMED),
    _ch('pump_power_meter', 'laser', 'mm', True,
        'Pump power meter (in @ 40 mm blocks the pump; out @ 0)',
        'UED:USR:MMN:05:06', CONFIRMED),
    # Pump coupling mirrors of the 1st (SUED) chamber (Fuhao, 2026-10-28).
    # Read-only here: the readiness check warns if the outcoupling mirror is
    # IN (it blocks the pump), per pump.outcoupling_*_mm in the setup file.
    _ch('pump_incoupling', 'laser', 'mm', False,
        '1st chamber pump incoupling mirror (read-only here)',
        'UED:USR:MMN:04:03', CONFIRMED),
    _ch('pump_outcoupling', 'laser', 'mm', False,
        '1st chamber pump outcoupling mirror (read-only here; IN blocks '
        'the pump)', 'UED:USR:MMN:04:02', CONFIRMED),
    _ch('pump_lens_h', 'laser', 'mm', True,
        'Pump steering H: moves the pump spot on the sample. Fuhao calls it '
        '"pump laser mirror H"; mapped to the run-7 list\'s pump lens H '
        '(UED:MCS:01:m7, "pump_beam_X", is the other candidate)',
        'UED:USR:MMN:08:05', LIKELY),
    _ch('pump_lens_v', 'laser', 'mm', True,
        'Pump steering V (see pump_lens_h; UED:MCS:01:m8 is the other '
        'candidate)', 'UED:USR:MMN:08:06', LIKELY),

    # Magnets (deck scale factors in the sim; BCTRL on the real machine)
    _ch('sol1', 'magnets', '', True, 'Gun solenoid strength',
        'SOLN:AS01:121:BCTRL', CONFIRMED, 'kG-m'),
    _ch('sol2', 'magnets', '', True, '2nd solenoid strength',
        'SOLN:AS01:311:BCTRL', CONFIRMED, 'A'),
    _ch('sol1_rb', 'magnets', '', False, 'Gun solenoid readback (BACT)',
        'SOLN:AS01:121:BACT', CONFIRMED, 'kG-m'),
    _ch('sol2_rb', 'magnets', '', False, '2nd solenoid readback (BACT)',
        'SOLN:AS01:311:BACT', CONFIRMED, 'A'),
    # Quad doublet QD01/QF01: off by default; read here, no tool drives it.
    _ch('quad1', 'magnets', '', False,
        'Quad doublet 1st quad setpoint (BCTRL; not driven by the tools)',
        'QUAD:AS01:361:BCTRL', CONFIRMED),
    _ch('quad2', 'magnets', '', False,
        'Quad doublet 2nd quad setpoint (BCTRL; not driven by the tools)',
        'QUAD:AS01:371:BCTRL', CONFIRMED),
    _ch('quad1_rb', 'magnets', '', False, 'Quad doublet 1st quad readback',
        'QUAD:AS01:361:BACT', CONFIRMED),
    _ch('quad2_rb', 'magnets', '', False, 'Quad doublet 2nd quad readback',
        'QUAD:AS01:371:BACT', CONFIRMED),

    # Beamline inserters and the chamber light
    # The screen actuator is YAGS:AS01:270 (in/out). It is moved by command
    # PVs (OPENCMD inserts, CLOSECMD removes), which this read-only
    # deployment never writes, so diag_holder stays an operator step; the
    # tools read the screen state and interlock to check the operator's move.
    _ch('diag_holder', 'beamline', '', True,
        'Diagnostic screen inserter (0 out, 1 YAG; 2 FC in the simulator '
        'only). On the real machine an operator step: insert with '
        'YAGS:AS01:270:OPENCMD, remove with :CLOSECMD (from the panel); '
        'check with diag_screen_state', None, UNMAPPED),
    _ch('diag_screen_state', 'beamline', '', False,
        'Diagnostic screen state (OPENSOLENOID; open = screen inserted, to '
        'confirm on the machine). Accelerator-side: from S3DF it needs the '
        'gateway prefix', 'YAGS:AS01:270:OPENSOLENOID', LIKELY,
        as_string=True),
    _ch('diag_screen_interlock', 'beamline', '', False,
        'Diagnostic screen interlock summary',
        'YAGS:AS01:270:INTLKSUM', LIKELY, as_string=True),
    _ch('collimator', 'beamline', 'mm', True,
        'Collimator motor (0 out; nominal 90 mm = the 200 um hole)',
        'UED:USR:MMN:14:07', CONFIRMED),
    _ch('chamber_light', 'beamline', '', True,
        'Sample chamber light (1 on, 0 off). Reads the state; switched by '
        'writing ACSW:AS01:NW03:2POWERON or :2POWEROFF',
        'ACSW:AS01:NW03:2POWERSTATE', CONFIRMED),

    # Charge: the oscilloscope. The dry run confirmed CH2 (its V/div PV is
    # the one Fuhao gave); his procedure text names CH0. ued_setup.yaml's
    # scope.channel picks the one the stages read.
    *[c for n, base in ((2, '+3.4'), (0, '-2.4')) for c in (
        _ch(f'scope_ch{n}_trace', 'diagnostics', 'div', False,
            f'Oscilloscope CH{n} trace, 500 samples in divisions (baseline '
            f'near {base} div); the e-beam pulse is negative-going',
            f'SCOP:AS01:SC01:WF_CH{n}_TRACE', CONFIRMED),
        _ch(f'scope_ch{n}_vdiv', 'diagnostics', '', False,
            f'Oscilloscope CH{n} volts/div (an output record that reads UDF: '
            'check the front panel)', f'SCOP:AS01:SC01:MBBO_CH{n}_SCL',
            CONFIRMED, as_string=True))],

    # Sample stage: the 1st (SUED) chamber stage, per Fuhao (2026-10-28):
    # IMS motors UED:UM1:MMS:01..03 plus XPS-04. (XPS-11, used before, is the
    # Run 6 jet hardware: its DESCs, Incoupling X/Y, Outcoupling, Capillary
    # Y, Catcher Y, were right; this run's coupling mirrors are on XPS-04 and
    # XPS-13.) Run 4's GUED stage doesn't apply.
    _ch('sample_x', 'sample', 'mm', True, 'SUED sample stage X',
        'UED:UM1:MMS:02', CONFIRMED),
    _ch('sample_y', 'sample', 'mm', True, 'SUED sample stage Y',
        'UED:USR:MMN:04:01', CONFIRMED),
    _ch('sample_z', 'sample', 'mm', True, 'SUED sample stage Z',
        'UED:UM1:MMS:01', CONFIRMED),
    # Pitch and yaw: read-only for the tools for now; an operator sets them
    # by hand (Fuhao, 2026-10-28).
    _ch('sample_pitch', 'sample', 'deg', False,
        'SUED sample stage pitch (read-only here; set by hand)',
        'UED:USR:MMN:04:04', CONFIRMED),
    _ch('sample_yaw', 'sample', 'deg', False,
        'SUED sample stage yaw (read-only here; set by hand)',
        'UED:UM1:MMS:03', CONFIRMED),
    _ch('pattern_quality', 'sample', '', False,
        'Diffraction pattern quality score (0..1). On the real machine, a '
        'score of the far-detector image (readable: cam_far_andor image); '
        'the scoring function does not exist yet', None, SIM_ONLY),

    # Pump-probe
    _ch('delay', 'pump_probe', 'mm', True, 'Pump long delay stage',
        'UED:USR:MMN:03:04', CONFIRMED),
    _ch('diffraction_signal', 'pump_probe', '', False,
        'Bragg-peak intensity, normalised to pump-off. On the real machine, '
        'the LCLS DAQ or the Run 6 BOED script', None, SIM_ONLY),
]

# Cameras: one block of channels each. On the real machine the stats are
# computed from the image PV (most Stats plugins are disabled, and the
# Andor's runs on an ROI); `saturated` is 1 when a pixel is at full scale.
# Gain is in dB on the GigE cameras and an EM gain on the Andor.
CAMERAS = {
    # name: (prefix, image plugin, status, description)
    'cam_vcc': ('UED:GIGE:06', 'IMAGE1', CONFIRMED,
                'Virtual cathode camera (gun UV spot)'),
    'cam_diag_yag': ('UED:GIGE:09', 'IMAGE1', CONFIRMED,
                     'Diagnostic screen camera (z ~0.5 m)'),
    # GIGE:02 per Fuhao (2026-10-28). GIGE:03 is a different camera with the
    # same parameters, which the tools used until then; not used now.
    'cam_sample_yag': ('UED:GIGE:02', 'IMAGE1', LIKELY,
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
                     f'Sample chamber camera: e-beam cross {axis}',
                     f'UED:GIGE:02:Cross2{axis.upper()}', LIKELY))
# The Andor is stopped to change its exposure and gain, then started
_LIST.append(_ch('cam_far_andor.acquire', 'camera', '', True,
                 'Andor acquisition: write 1 to start, 0 to stop; reads '
                 'Acquire or Done', 'UED:ANDOR:CAM:03:Acquire', CONFIRMED,
                 as_string=True))

# Steering correctors XC/YC00..05, as kick angles at the nominal energy.
# On the real machine BCTRL's EGU reads kG-m (A for XC/YC04), with drive
# limits that differ per magnet; the kick per unit is not known yet.
_UNITS = [(121, 122), (221, 222), (321, 322), (341, 342), (381, 382), None]
for i, units in enumerate(_UNITS):
    for plane, k in (('x', 0), ('y', 1)):
        pv = (f'{plane.upper()}COR:AS01:{units[k]}:BCTRL' if units else None)
        egu = 'A' if i == 4 else 'kG-m'
        _LIST.append(_ch(f'{plane}c{i:02d}', 'correctors', 'mrad', True,
                         f'{plane.upper()}C{i:02d} steering kick', pv,
                         CONFIRMED if units else UNMAPPED,
                         f'BCTRL, EGU {egu} (unconfirmed)' if units else ''))
        if units:                       # readback, to check a set took hold
            _LIST.append(_ch(f'{plane}c{i:02d}_rb', 'correctors', '', False,
                             f'{plane.upper()}C{i:02d} readback (BACT)',
                             f'{plane.upper()}COR:AS01:{units[k]}:BACT',
                             CONFIRMED, egu))

CHANNELS = {c.name: c for c in _LIST}
