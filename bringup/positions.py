#!/usr/bin/env python
"""Taught sample-stage positions in the shared setup file, for operators.

The positions live in one place, the `positions:` section of
ued_setup.yaml, read and written by the operators and the agent alike (the
agent through its save_position tool). This script writes through the same
code, so every change from either side gets the same treatment: safety
ranges checked, the other entries and comments left as they are, the
previous file kept as ued_setup.yaml.bak, and the change appended to
ued_setup.history.log.

    python positions.py list                 # taught positions (file only)
    python positions.py where                # where the stage is now (caget)
    python positions.py save bi --note "..." # teach: read the stage, save it
    python positions.py set bi --x 12.3 --note "from the logbook"
    python positions.py check                # validate after a hand edit
    python positions.py history [bi]         # who changed what, when

Editing ued_setup.yaml by hand is fine too: one line per position, e.g.
    bi: {x: -12.5, y: 3.1, z: 10.0, note: "flake 2"}
Only x, y, z are moved; the sample pitch and yaw are set by hand.
then run `check`. Hand edits skip the history log, so prefer save/set.

The file is $UED_SETUP_FILE, else the live copy on S3DF, else the repo seed
(never edited in place); --file overrides. `where` and `save` read the stage
with caget (read-only), so they need the EPICS environment of ued-daq.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ued_automation as auto  # noqa: E402

AXES = auto.AXES


def _fmt(p):
    if p is None:
        return 'not taught'
    return ', '.join(f'{k} {v}' for k, v in p.items())


def _stage():
    """The read-only EPICS backend, for reading the stage."""
    from ued_tuning.epics_backend import EpicsBackend
    return EpicsBackend()


def _confirm(name, old, new, yes):
    print(f'  {name} now: {_fmt(old)}')
    print(f'  {name} new: {_fmt(new)}')
    if old is not None and not yes:
        if input(f'Overwrite the taught position {name!r}? [y/N] ').strip() \
                .lower() not in ('y', 'yes'):
            sys.exit('not saved')


def cmd_list(args):
    setup = auto.load_setup(args.file)
    print(f'{args.file or auto.setup_path()}')
    for name, p in (setup.get('positions') or {}).items():
        print(f'  {name:<10} {_fmt(p)}')
    probs = auto.validate(setup)
    if probs:
        print('\nproblems (run `check`):', *probs, sep='\n  ')


def cmd_where(args):
    now = auto.current_position(_stage())
    print('stage now:', _fmt({a: round(v, 4) for a, v in now.items()}))
    setup = auto.load_setup(args.file)
    for name, p in (setup.get('positions') or {}).items():
        if isinstance(p, dict) and all(
                abs(float(p[a]) - now[a]) < 0.01 for a in AXES if a in p):
            print(f'  = at {name}')


def _write(args, coords, extra):
    path = args.file or auto.setup_path()
    setup = auto.load_setup(path)
    old = (setup.get('positions') or {}).get(args.name)
    new = dict(old) if isinstance(old, dict) else {}
    new.update({a: round(float(v), 4) for a, v in coords.items()})
    new.update(extra)
    _confirm(args.name, old, new, args.yes)
    out = auto.save_position(args.name, coords, note=args.note, path=path,
                             extra=extra)
    print(f'saved to {out}')


def cmd_save(args):
    here = auto.current_position(_stage())
    _write(args, here, {})


def cmd_set(args):
    coords = {a: getattr(args, a) for a in AXES
              if getattr(args, a) is not None}
    extra = {}
    for kv in args.field or []:
        k, _, v = kv.partition('=')
        v = v.strip().strip('"\'')
        try:
            extra[k.strip()] = float(v)
        except ValueError:
            extra[k.strip()] = v
    if not coords and not extra:
        sys.exit('nothing to set: give at least one of --x --y --z '
                 'or --field key=value')
    _write(args, coords, extra)


def cmd_check(args):
    setup = auto.load_setup(args.file)
    probs = auto.validate(setup)
    missing = auto.missing(setup)
    for p in probs:
        print('PROBLEM ', p)
    for m in missing:
        print('not set ', m)
    if not probs:
        print(f'ok: {args.file or auto.setup_path()}')
    sys.exit(1 if probs else 0)


def cmd_history(args):
    path = Path(args.file or auto.setup_path())
    log = path.with_name('ued_setup.history.log')
    if not log.exists():
        sys.exit(f'no history yet ({log})')
    for line in log.read_text().splitlines():
        e = json.loads(line)
        if args.name and e.get('position') != args.name:
            continue
        print(f"{e['time']}  {e['position']:<8} {_fmt(e.get('old'))}  ->  "
              f"{_fmt(e.get('new'))}  {e.get('note', '')}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('\n\n', 2)[2])
    ap.add_argument('--file', type=Path, help='setup file to use')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list').set_defaults(fn=cmd_list)
    sub.add_parser('where').set_defaults(fn=cmd_where)
    sub.add_parser('check').set_defaults(fn=cmd_check)
    h = sub.add_parser('history')
    h.add_argument('name', nargs='?')
    h.set_defaults(fn=cmd_history)
    for name, fn in (('save', cmd_save), ('set', cmd_set)):
        p = sub.add_parser(name)
        p.add_argument('name')
        p.add_argument('--note', default='', help='who and why')
        p.add_argument('--yes', action='store_true',
                       help='overwrite a taught position without asking')
        if name == 'set':
            for a in AXES:
                p.add_argument(f'--{a}', type=float)
            p.add_argument('--field', action='append', metavar='KEY=VALUE',
                           help='an extra field, e.g. --field '
                                'note="flake 2" (repeatable)')
        p.set_defaults(fn=fn)
    args = ap.parse_args()
    try:
        args.fn(args)
    except (auto.SafetyError, auto.SetupError, ValueError,
            RuntimeError) as exc:
        sys.exit(f'refused: {exc}')


if __name__ == '__main__':
    main()
