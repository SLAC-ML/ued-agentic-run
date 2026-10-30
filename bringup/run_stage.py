#!/usr/bin/env python
"""Run a ued_tuning stage on ued-daq, for an operator.

The deployed agent is read-only, and its tools can't run on ued-daq, so an
operator runs a bring-up stage here with the same code the tools rehearse
on the simulator. Started by scripts/ued_stage.sh (s3df/ued_stage.sh):

    ued_stage.sh find_time_zero method=boed              # dry run
    ued_stage.sh --write find_time_zero method=boed      # for real

Dry run (the default): every write is logged and not sent. A later read of
a channel it "wrote" returns the written value, so the sequence goes on as
if the machine had followed; cameras and the Andor are read for real, and
waits are cut to a tenth. --write: writes go to the PVs, but only to the
channels this stage may write (STAGE_WRITES), each inside the setup file's
safety range (the stage's Recorder checks it too). Either way every write
goes to $UED_RECORDS_DIR/operator_writes.jsonl.

Arguments after the stage name are the stage's keyword arguments, as
key=value (values parsed as JSON where they can be: 80, 0.3, null, true).
One line per point of a scan goes to stdout as it runs; the result, as
JSON, at the end.
"""
from __future__ import annotations

import argparse
import datetime
import getpass
import json
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ued_automation as auto  # noqa: E402
from pv_access import wire_name  # noqa: E402
from ued_tuning import stages  # noqa: E402
from ued_tuning.channels import CHANNELS, to_pv  # noqa: E402
from ued_tuning.epics_backend import MOTOR_RE, EpicsBackend  # noqa: E402

# What each stage may write, read off its code (and a dry run's log). A
# write to anything else is refused and stops the stage.
STAGE_WRITES = {
    'find_time_zero': {
        'delay', 'pump_shutter', 'gun_uv_shutter', 'pump_hwp',
        'pump_power_meter', 'sample_x', 'sample_y', 'sample_z',
        'cam_far_andor.acquire', 'cam_far_andor.exposure',
        'cam_far_andor.gain', 'cam_sample_yag.exposure',
        'cam_sample_yag.gain', 'cam_sample_yag.cross_x',
        'cam_sample_yag.cross_y', 'chamber_light'},
}
MOTOR_TIMEOUT_S = 180.0
MOTOR_TOL = 0.005


class WriteRefused(RuntimeError):
    pass


class OperatorBackend(EpicsBackend):
    kind = 'epics-operator'

    def __init__(self, stage, write, log_path, timeout=2.0):
        super().__init__(timeout)
        from epics import caput
        self._caput = caput
        self.stage, self.write, self.log_path = stage, write, Path(log_path)
        self.allowed = STAGE_WRITES[stage]
        self.shadow = {}
        self.sleep_scale = 1.0 if write else 0.1

    def _log(self, **entry):
        entry = {'time': datetime.datetime.now().isoformat(timespec='seconds'),
                 'host': socket.gethostname(), 'user': getpass.getuser(),
                 'stage': self.stage, 'sent': False, **entry}
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log_path, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')

    def get(self, name):
        if not self.write and name in self.shadow:
            return self.shadow[name]
        return super().get(name)

    def put(self, name, value):
        ch = CHANNELS.get(name)
        why = None
        if name not in self.allowed:
            why = f'{self.stage} may not write {name}'
        elif ch is None or ch.pv is None or not ch.writable:
            why = f'{name} has no writable PV'
        else:
            try:
                auto.check_limits(auto.load_setup(), name, value)
            except auto.SafetyError as exc:
                why = str(exc)
        if why:
            self._log(channel=name, value=value, refused=why)
            raise WriteRefused(why)
        pv, raw = wire_name(ch.pv), to_pv(name, value)
        motor = bool(MOTOR_RE.search(ch.pv))
        try:
            old = super().get(name)
        except Exception as exc:
            old = f'unreadable: {exc}'
        if not self.write:
            self.shadow[name] = value
            self._log(channel=name, pv=pv, old=old, value=raw, dry_run=True)
            return
        ok = self._caput(pv, raw, wait=motor,
                         timeout=MOTOR_TIMEOUT_S if motor else self.timeout)
        self._log(channel=name, pv=pv, old=old, value=raw, sent=bool(ok),
                  motor=motor)
        if ok is None:
            raise WriteRefused(f'caput {pv} = {raw} did not complete')
        if motor:
            now = float(super().get(name))
            if abs(now - float(value)) > MOTOR_TOL:
                raise WriteRefused(f'{name} at {now:g} after the move, not '
                                   f'{float(value):g}')

    def sleep(self, seconds):
        time.sleep(seconds * self.sleep_scale)


def parse_kwargs(items):
    out = {}
    for item in items:
        key, sep, val = item.partition('=')
        if not sep:
            raise SystemExit(f'arguments are key=value, not {item!r}')
        try:
            out[key] = json.loads(val)
        except ValueError:
            out[key] = val
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--write', action='store_true',
                    help='send the writes (default: dry run)')
    ap.add_argument('stage', choices=sorted(STAGE_WRITES))
    ap.add_argument('kwargs', nargs='*', help='key=value stage arguments')
    args = ap.parse_args()
    kwargs = parse_kwargs(args.kwargs)
    records = Path(os.environ.get('UED_RECORDS_DIR', auto.RECORDS_DEFAULT))
    log = records / 'operator_writes.jsonl'
    m = OperatorBackend(args.stage, args.write, log)
    mode = 'WRITE' if args.write else 'DRY RUN (nothing is sent)'
    print(f'{args.stage} {kwargs} | {mode} | setup {auto.setup_path()} | '
          f'writes logged to {log}', flush=True)

    def progress(ev):
        print(ev.get('message', ev), flush=True)

    fn = stages.STAGES.get(args.stage) or stages.HELPERS[args.stage]
    if 'progress' in fn.__code__.co_varnames:
        kwargs['progress'] = progress
    try:
        out = fn(m, auto.load_setup(), **kwargs)
    except (auto.SetupError, auto.SafetyError, stages.OperatorActionNeeded,
            WriteRefused) as exc:
        out = {'stage': args.stage, 'ok': False, 'accepted': False,
               'needs_operator': True,
               'reason': f'{type(exc).__name__}: {exc}'}
    out['mode'] = 'write' if args.write else 'dry_run'
    print(json.dumps(stages._num(out), indent=1, default=str))


if __name__ == '__main__':
    main()
