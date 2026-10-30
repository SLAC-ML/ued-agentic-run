#!/usr/bin/env python
"""Write the device pages of the agent's knowledge bundle from the channel map.

The KNOWLEDGE panel and the facility-knowledge MCP server read an OKF bundle
(Markdown with YAML front matter) at agent/data/facility_knowledge. Its
devices/ pages are generated here from ued_tuning/channels.py, so the PVs
they list are the ones the tools use. Run from the repo root after the map
changes, then push agent/ and regenerate the indexes on S3DF
(`osprey knowledge regen-index data/facility_knowledge`):

    python bringup/okf_devices.py
"""
from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from ued_tuning.channels import CAMERAS, CHANNELS  # noqa: E402

OUT = HERE.parent / 'agent' / 'data' / 'facility_knowledge' / 'devices'

# What the S3DF gateway (172.24.3.10:5110) served under UED:USER: on
# 2026-10-29 (corrector BACT readbacks were missing too); hutch PVs (UED:*)
# all answered under their own names.
GATEWAY_LIVE = ('SIOC:AS01:KY03:0:AREQ', 'SIOC:AS01:KY03:0:PREQ',
                'SIOC:AS01:KY03:0:AACT_AVGNT', 'SIOC:AS01:KY03:0:PACT_AVGNT',
                'APC:AS01:TM01', 'SOLN:', 'QUAD:', 'XCOR:AS01:', 'YCOR:AS01:')
GATEWAY_MISSING = ('PFBENB', 'AFBENB', 'PFBST', 'AFBST', 'VVPG:', 'YAGS:',
                   'SCOP:', 'ACSW:')

PAGES = [
    ('gun-rf', 'Gun RF', ['gun_rf'],
     'Gun RF on klystron KY03 (TS8): amplitude and phase setpoints and '
     'readbacks, the two feedbacks, and the gun body temperature.',
     'The gun is on TS8 (KY03) since 2026-10-28; TS1 (KY01) is offline. '
     'AREQ is dimensionless (0..0.53); AACT reads in kV, so the ramp checks '
     'their ratio. Ramp-up: see procedures/gun-ramp.'),
    ('magnets', 'Solenoids, quads and correctors', ['magnets', 'correctors'],
     'Gun solenoid (Sol1), second solenoid (Sol2), the quad doublet and the '
     'XC/YC00-05 steering correctors, with their setpoint (BCTRL) and '
     'readback (BACT) PVs.',
     'Units are BCTRL units: kG-m, or A for Sol2 and XC/YC04; their '
     'calibration to field or kick is not known yet. The quad doublet is off '
     'by default and no tool drives it. XC/YC05 have no PV yet.'),
    ('vacuum', 'Gate valves', ['vacuum'],
     'The four gate valves on the e-beam path (240, 272, 280, 295) and the '
     'ePix-line valve 320.',
     'Every beam stage of the bring-up tools stops unless 240, 272, 280 and '
     '295 all read OPEN. 320 is reported for information only.'),
    ('lasers', 'Drive and pump lasers', ['laser'],
     'Gun UV drive (shutter, throttle) and the 400 nm pump (shutters, '
     'Harmonics HWP, ND wheel, power meter, coupling mirrors, steering '
     'lens).',
     'Shutters are Beckhoff analog outputs: 3 V open, 0 V closed; the tools '
     'use 1/0. Pump energy vs HWP: see references/pump-hwp-calibration. On '
     '2026-10-28 the pump lens X/Y were temporarily on the XPS-06 panel '
     '("400 nm Lens X / Y"); pump_lens_h/v below are the old motors until '
     'those are mapped.'),
    ('beamline', 'Collimator, diagnostic screen, scope, chamber light',
     ['beamline', 'diagnostics'],
     'The collimator, the diagnostic screen (YAGS:AS01:270) and its '
     'interlock, the oscilloscope that reads the bunch charge, and the '
     'sample-chamber light.',
     'The diagnostic screen is moved by command PVs (OPENCMD inserts, '
     'CLOSECMD removes) that the agent never writes: an operator moves it '
     'and the tools read its state. Scope: 10 fC = -1.7 mV on CH2; the '
     'V/div records read UDF, so check the front panel.'),
    ('sample-and-delay', 'Sample stage and pump delay',
     ['sample', 'pump_probe'],
     'The 1st (SUED) chamber sample stage and the pump long delay stage.',
     'Motor reads take <PV>.RBV, the actual position. Pitch and yaw are set '
     'by hand: the yaw shifts the Z plane a lot, so keep yaw and Z where '
     'they are. Taught positions live in the setup file (references/'
     'setup-file). Pump delay: 0-300 mm, higher = more pump delay = '
     'negative pump-probe time; coarse time zero near 200 mm (2026-10-28).'),
]


def gateway(pv):
    if pv is None:
        return '-'
    if pv.startswith('UED:'):
        return 'yes'
    if any(m in pv for m in GATEWAY_MISSING) or (
            pv.startswith(('XCOR:', 'YCOR:')) and pv.endswith(':BACT')):
        return 'not yet'
    if pv.startswith(GATEWAY_LIVE):
        return 'prefix'
    return 'prefix?'


def row(c):
    pv = f'`{c.pv}`' if c.pv else '—'
    units = c.pv_units or c.units or ''
    return (f'| `{c.name}` | {pv} | {units} | {c.status} | '
            f'{"yes" if c.writable else "no"} | {gateway(c.pv)} | '
            f'{c.desc.replace("|", "/")} |')


def page(slug, title, groups, description, notes, stamp):
    chans = [c for c in CHANNELS.values() if c.group in groups]
    lines = ['---', 'type: device', f'title: {json.dumps(title)}',
             f'description: {json.dumps(description)}',
             f'timestamp: "{stamp}"', 'tags: [ued, devices, pv]', '---', '',
             f'# {title}', '', notes, '',
             '| Tool name | PV | Units | Map status | Tools may write | '
             'From S3DF | What it is |',
             '|---|---|---|---|---|---|---|']
    lines += [row(c) for c in chans]
    lines += ['', LEGEND, '']
    (OUT / f'{slug}.md').write_text('\n'.join(lines))


def cameras_page(stamp):
    lines = ['---', 'type: device', 'title: "Cameras"',
             'description: ' + json.dumps(
                 'The four cameras the bring-up tools read (virtual cathode, '
                 'diagnostic screen, sample chamber, far-detector Andor), '
                 'their image PVs and settings.'),
             f'timestamp: "{stamp}"', 'tags: [ued, devices, cameras, pv]',
             '---', '', '# Cameras', '',
             'All cameras are hutch IOCs (`UED:*`), so they answer from S3DF '
             'under their own names. The tools compute beam stats (centroid, '
             'rms size, total, saturation) from the image PV itself: the '
             'GigE cameras\' Stats plugins are switched off (their centroids '
             'read 0.0, which looks real), and the Andor\'s Stats1 runs on a '
             'small ROI.', '',
             '| Camera | PV prefix | Image | Map status | What it is |',
             '|---|---|---|---|---|']
    for name, (prefix, plugin, status, desc) in CAMERAS.items():
        lines.append(f'| `{name}` | `{prefix}` | `{prefix}:{plugin}:'
                     f'ArrayData` | {status} | {desc} |')
    lines += ['', '## Settings the tools read or set', '',
              '| Tool name | PV | Units | Map status | Tools may write | '
              'From S3DF | What it is |', '|---|---|---|---|---|---|---|']
    stats = ('centroid_x', 'centroid_y', 'sigma_x', 'sigma_y', 'total',
             'max_value', 'saturated', 'size_x', 'size_y')
    lines += [row(c) for c in CHANNELS.values() if c.group == 'camera'
              and c.name.split('.')[-1] not in stats]
    lines += ['', 'Camera views (exposure, gain, light) and the Andor '
              'settings for each step are in the setup file '
              '(references/setup-file).', '', LEGEND, '']
    (OUT / 'cameras.md').write_text('\n'.join(lines))


LEGEND = ('*Map status*: CONFIRMED (read and checked), LIKELY (read, '
          'meaning to confirm), UNMAPPED (no PV yet), SIM_ONLY (simulator '
          'only). *Tools may write*: the tools would write it on a write-'
          'enabled deployment; the deployed agent refuses every PV write. '
          '*From S3DF*: yes = answers through the gateway under its own '
          'name; prefix = answers as `UED:USER:<PV>`; not yet = not served '
          'by the gateway on 2026-10-29 (read it from ued-daq). Generated '
          'from bringup/ued_tuning/channels.py by bringup/okf_devices.py.')


if __name__ == '__main__':
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.date.today().isoformat()
    for spec in PAGES:
        page(*spec, stamp)
    cameras_page(stamp)
    print('wrote', sorted(p.name for p in OUT.glob('*.md')))
