#!/usr/bin/env python
"""Operator runner for all bring-up stages (Fuhao Ji, 2026-11).

run_stage.py runs a ued_tuning stage on ued-daq for an operator, but its
allow-list (STAGE_WRITES) holds only find_time_zero. This wrapper adds the
other stages and the read-only helpers, and changes nothing else: same
backend, same dry run by default, same safety ranges, same write log.

    fj_stage.sh gun_ramp                       # dry run: writes logged, none sent
    fj_stage.sh --write gun_ramp               # for real (asks to confirm)
    fj_stage.sh schottky_scan diag_screen_by_operator=true
    fj_stage.sh monitor_charge samples=20      # read-only helper

The write lists below were read off stages.py and ued_automation.py
(2026-11-18, main 4dafde4). A stage that tries to write anything else is
refused and stops, and the refusal names the channel. As of that date only
find_time_zero had been run with --write on the real machine: run each
stage dry first and read records/operator_writes.jsonl.
"""
import socket
import sys

import run_stage

# go_to + set_view: what any stage that moves the sample or changes the
# sample-camera view writes.
MOVE = {'sample_x', 'sample_y', 'sample_z', 'pump_hwp', 'pump_shutter',
        'gun_uv_shutter', 'cam_sample_yag.exposure', 'cam_sample_yag.gain',
        'chamber_light'}
ANDOR = {'cam_far_andor.acquire', 'cam_far_andor.exposure',
         'cam_far_andor.gain'}
CROSS = {'cam_sample_yag.cross_x', 'cam_sample_yag.cross_y'}

EXTRA = {
    # every stage closes the pump shutter first (_precheck)
    'gun_ramp': {'pump_shutter', 'areq', 'pfb_enable', 'afb_enable'},
    'schottky_scan': {'pump_shutter', 'gun_uv_shutter', 'gun_uv_throttle',
                      'preq', 'collimator'},
    'set_bunch_charge': {'pump_shutter', 'gun_uv_shutter',
                         'gun_uv_throttle'},
    'beam_on_screens': MOVE | ANDOR | CROSS | {'collimator'},
    'align_collimator': MOVE | ANDOR | {'collimator'},
    'overlap_pump_laser': MOVE | CROSS | {'pump_power_meter', 'pump_lens_h',
                                          'pump_lens_v'},
    'check_overlap': MOVE | {'pump_power_meter'},
    'tune_sample_position': MOVE | ANDOR | {'xc04', 'yc04'},
    # read-only helpers
    'monitor_charge': set(),
    'measure_andor_spot': set(),
}

for name, writes in EXTRA.items():
    run_stage.STAGE_WRITES.setdefault(name, set(writes))


def confirm(stage):
    if socket.gethostname().split('.')[0] != 'ued-daq':
        sys.exit('fj_run_stage: --write only on ued-daq')
    writes = sorted(run_stage.STAGE_WRITES[stage])
    print(f'\n{stage} --write will send real writes to:\n  '
          + ', '.join(writes or ['(nothing)']))
    if input(f'Type the stage name to go ahead ({stage}): ').strip() != stage:
        sys.exit('not confirmed: nothing sent')


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if '--write' in sys.argv[1:] and args and args[0] in run_stage.STAGE_WRITES:
        confirm(args[0])
    run_stage.main()
