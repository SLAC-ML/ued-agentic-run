"""The write path for an operator's Badger on ued-daq.

The `ued` environment reads through ued_tuning's EpicsBackend, which
refuses every write. Only when scripts/badger_ued.sh starts Badger
(UED_BADGER_ALLOW_WRITES=1, an operator at the GUI) does it use this
backend, which writes the Badger knobs and nothing else:

  * only the channels in common.KNOBS (solenoids, correctors, sample x/y);
  * each value checked against the live setup file's safety ranges, here
    as well as before (a knob with no range is refused);
  * magnets: caput, then Badger's settle time; motors (the sample stage):
    caput to the setpoint, wait for the move, check the readback;
  * every write appended to common.WRITE_LOG (time, host, user, channel,
    PV, old and new value), whether it was sent or refused.

UED_BADGER_DRY_RUN=1 goes through all of it but logs the write instead of
sending it: the way to check a routine end to end without moving anything.
The agent's servers never set either variable; the deployed agent stays
read-only.
"""
from __future__ import annotations

import datetime
import getpass
import json
import os
import socket
import sys

from . import common

sys.path.insert(0, str(common.BRINGUP))
import ued_automation as auto  # noqa: E402
from pv_access import wire_name  # noqa: E402
from ued_tuning.channels import CHANNELS, to_pv  # noqa: E402
from ued_tuning.epics_backend import MOTOR_RE, EpicsBackend  # noqa: E402

MOTOR_TIMEOUT_S = 120.0
MOTOR_TOL = 0.005               # mm: readback within this of the setpoint


class WriteRefused(RuntimeError):
    pass


class LiveEpicsBackend(EpicsBackend):
    kind = 'epics-live'

    def __init__(self, timeout=2.0):
        super().__init__(timeout)
        from epics import caput
        self._caput = caput
        self.dry_run = os.environ.get(common.DRY_RUN_ENV) == '1'

    def _log(self, **entry):
        entry = {'time': datetime.datetime.now().isoformat(timespec='seconds'),
                 'host': socket.gethostname(), 'user': getpass.getuser(),
                 'dry_run': self.dry_run, **entry}
        common.WRITE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(common.WRITE_LOG, 'a') as f:
            f.write(json.dumps(entry, default=str) + '\n')

    def put(self, name, value):
        ch = CHANNELS.get(name)
        why = None
        if name not in common.KNOBS:
            why = f'{name} is not a Badger knob'
        elif ch is None or ch.pv is None or not ch.writable:
            why = f'{name} has no writable PV'
        else:
            lim = (auto.load_setup().get('limits') or {}).get(name)
            if lim is None:
                why = f'{name} has no safety range in {auto.setup_path()}'
            else:
                try:
                    auto.check_limits(auto.load_setup(), name, value)
                except auto.SafetyError as exc:
                    why = str(exc)
        if why:
            self._log(channel=name, value=value, sent=False, refused=why)
            raise WriteRefused(why)
        pv = wire_name(ch.pv)
        raw = to_pv(name, value)
        try:
            old = self.get(name)
        except Exception as exc:
            old = f'unreadable: {exc}'
        motor = bool(MOTOR_RE.search(ch.pv))
        if self.dry_run:
            self._log(channel=name, pv=pv, old=old, value=raw, sent=False,
                      motor=motor)
            return
        ok = self._caput(pv, raw, wait=motor,
                         timeout=MOTOR_TIMEOUT_S if motor else self.timeout)
        self._log(channel=name, pv=pv, old=old, value=raw, sent=bool(ok),
                  motor=motor)
        if ok is None:
            raise WriteRefused(f'caput {pv} = {raw} did not complete')
        if motor:
            now = float(self.get(name))
            if abs(now - float(value)) > MOTOR_TOL:
                raise WriteRefused(f'{name} at {now:g} after the move, not '
                                   f'{float(value):g}')
