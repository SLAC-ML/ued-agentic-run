"""Build reports/ued-bringup-mockup.html from its parts and two run files.

usage: python build.py MOCKUP_RESULTS_JSON READONLY_CHECK_JSON

  MOCKUP_RESULTS_JSON   runs/sim/mcp_mockup_<date>/results.json (S3DF)
  READONLY_CHECK_JSON   runs/epics/readonly_check_<date>.json (S3DF)

The page is head.html + body.html + the data block + helpers.js +
content.js + charts.js. Edit the parts, not the built page.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / 'bringup'))
from ued_tuning.channels import CHANNELS  # noqa: E402

OUT = REPO / 'reports' / 'ued-bringup-mockup.html'


def clean(o):
    if isinstance(o, float) and not math.isfinite(o):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


def main(res_p, ro_p):
    r = json.load(open(res_p))
    ro = json.load(open(ro_p))
    resp = {c['tool']: c['response'] for c in r['calls']}
    wall = {c['tool']: c['client_wall_s'] for c in r['calls']}
    truth = r['truth']
    d = {'stages': {}, 'wall_min': round(sum(wall.values()) / 60, 1),
         'started': r['started'], 'truth': truth}
    for tool in ('gun_ramp', 'schottky_scan', 'set_bunch_charge',
                 'beam_on_screens', 'align_collimator', 'overlap_pump_laser',
                 'tune_sample_position', 'find_time_zero'):
        x = resp[tool]
        d['stages'][tool] = {
            'accepted': x['accepted'], 'reason': x['reason'],
            'needs_operator': x.get('needs_operator'),
            'machine_s': x['machine_time_s'], 'wall_s': x['wall_s'],
            'n_writes': x['n_writes'], 'n_reads': x['n_reads'],
            'written': [{'name': n, 'pv': CHANNELS[n].pv,
                         'status': CHANNELS[n].status}
                        for n in x['channels_written']]}
    s = resp['schottky_scan']
    d['schottky'] = {'coarse': s['coarse'], 'fine': s['fine'],
                     'emission': s['emission_phase_deg'],
                     'operating': s['operating_phase_deg'],
                     'threshold': s['threshold_fC'],
                     'truth': truth['emission_phase_deg']}
    d['charge'] = resp['set_bunch_charge']['iterations']
    d['monitor'] = {k: resp['monitor_charge'][k]
                    for k in ('mean_fC', 'std_fC')}
    c = resp['align_collimator']
    d['collimator'] = {k: c[k] for k in (
        'scan_mm', 'scan_total', 'fine_mm', 'fine_total', 'insertion',
        'collimator_mm', 'transmission', 'andor_counts_out')}
    d['collimator']['ideal'] = truth.get('collimator_ideal_mm')
    o = resp['overlap_pump_laser']
    d['overlap'] = o['iterations']
    d['overlap_final_px'] = o['final_error_px']
    d['hole'] = resp['tune_sample_position']['through_hole']
    t = resp['find_time_zero']
    d['t0'] = {'coarse': t['coarse'], 'fine': t['fine'], 't0': t['t0_mm'],
               'truth': truth['t0_delay_mm'], 'levels': t['levels']}
    d['plan'] = {k: resp['plan_beam_optimization'][k]
                 for k in ('vocs', 'generator', 'escalate_if')}
    chans = [dict(ch, pv_units=CHANNELS[ch['name']].pv_units)
             for ch in ro['channels']]
    d['epics'] = {'info': ro['info'], 'started': ro['started'],
                  'channels': chans, 'reads': ro['reads'],
                  'checks': ro.get('checks', {}), 'stages': ro['stages'],
                  'answered': sum(not isinstance(v, dict)
                                  for v in ro['reads'].values())}
    ts = resp['tune_sample_position']
    d['text'] = {
        'gun_ramp': f"AREQ {resp['gun_ramp']['target']:.2f} reached; both RF "
                    'feedbacks Active',
        'schottky_scan': f"Emission at {s['emission_phase_deg']:.1f}° vs "
                         f"{truth['emission_phase_deg']:.1f}° in truth; PREQ "
                         f"set to {s['operating_phase_deg']:.1f}°",
        'set_bunch_charge': f"{resp['set_bunch_charge']['charge_fC']:.1f} fC "
                            f"at throttle "
                            f"{resp['set_bunch_charge']['throttle_deg']:.0f}°,"
                            ' then the hand-over to the UV feedback loop',
        'beam_on_screens': 'E-beam on the YAG cross and on the Andor',
        'align_collimator': f"Collimator at {c['collimator_mm']:.2f} mm, "
                            f"{1e3 * abs(c['collimator_mm'] - (truth.get('collimator_ideal_mm') or c['collimator_mm'])):.0f}"
                            f" µm from ideal; {100 * c['transmission']:.0f} % "
                            'transmission',
        'overlap_pump_laser': f"Laser {o['final_error_px']:.1f} px from the "
                              'cross ('
                              f"{math.hypot(*truth['laser_minus_ebeam_um']):.1f}"
                              ' µm from the e-beam in truth)',
        'tune_sample_position': f"Main beam into the through hole; quality "
                                f"{ts['quality']:.2f} of a best "
                                f"{truth['pattern_quality_best']:.2f}; "
                                'escalated to the operator',
        'find_time_zero': f"t₀ {t['t0_mm']:.4f} mm vs "
                          f"{truth['t0_delay_mm']:.4f} in truth",
    }
    data = json.dumps(clean(d), separators=(',', ':'),
                      ensure_ascii=False).replace('</', '<\\/')
    part = lambda n: (HERE / n).read_text()  # noqa: E731
    html = (part('head.html') + part('body.html')
            + '<script type="application/json" id="report-data">' + data
            + '</script>\n<script>\n' + part('helpers.js')
            + part('content.js') + part('charts.js')
            + '</script>\n</body>\n</html>\n')
    OUT.write_text(html)
    print('wrote', OUT, len(html), 'bytes')
    print(json.dumps(d['text'], indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:3])
