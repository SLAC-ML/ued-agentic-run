#!/usr/bin/env python
"""Read-only snapshot of the UED beamline state (caget only, never caput).

Successor of ued_run4/PVtest_run4.py, built on the PV map in ued_pvs.py.
On ued-daq:

    source /cds/group/pcds/dist/pds/ued/scripts/setup_env.sh
    python /sdf/group/mli/zhezhang/ued/agentic/bringup/snapshot.py [--json]
"""
import argparse
import contextlib
import json
import os
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from epics import caget  # noqa: E402  (read-only: caput is never imported)

from ued_pvs import CHANNELS  # noqa: E402

TIMEOUT = 2.0


def read_all():
    rows = []
    for ch in CHANNELS:
        # Acquire_RBV is an enum: read it as its label ("Acquiring"/"Done").
        # pyepics prints "cannot connect" on stdout; keep stdout clean.
        with contextlib.redirect_stdout(sys.stderr):
            values = [caget(pv, timeout=TIMEOUT,
                            as_string=pv.endswith(':Acquire_RBV'))
                      for pv in ch.readback]
        rows.append({
            'key': ch.key, 'group': ch.group, 'desc': ch.desc,
            'pv': ch.pv, 'old_pv': ch.old_pv, 'status': ch.status,
            'units': ch.units, 'note': ch.note,
            'readback': dict(zip(ch.readback, values)),
            'connected': bool(values) and all(v is not None for v in values),
        })
    return rows


def fmt_value(row):
    vals = list(row['readback'].values())
    if not vals:
        return '-'
    if not row['connected']:
        return 'not connected'
    if row['group'] == 'camera':
        state, exp, gain = vals
        return f'{state}, {exp:g} s, gain {gain:g}'
    v = vals[0]
    return f'{v:.4g} {row["units"]}'.strip() if isinstance(v, float) \
        else f'{v} {row["units"]}'.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--json', action='store_true',
                        help='print machine-readable JSON')
    args = parser.parse_args()

    rows = read_all()
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    if args.json:
        json.dump({'time': stamp, 'channels': rows}, sys.stdout, indent=1,
                  default=str)
        print()
        return

    print(f'UED snapshot {stamp}  (read-only)')
    group = None
    for r in rows:
        if r['group'] != group:
            group = r['group']
            print(f'\n[{group}]')
        print(f'  {r["key"]:<20}{fmt_value(r):<28}{r["status"]:<11}'
              f'{r["pv"] or "-"}')
    n_ok = sum(r['connected'] for r in rows)
    print(f'\n{n_ok}/{len(rows)} channels connected')


if __name__ == '__main__':
    main()
