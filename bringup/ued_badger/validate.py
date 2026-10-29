"""Check a drafted UED routine against its environment and save it.

Runs in the Badger environment ($UED_BADGER_PYTHON), as a subprocess of
the MCP server:

    python -m ued_badger.validate REQUEST.json DEST.yaml

REQUEST.json holds {"routine": {...}, "span_fraction": 0.1}. The routine
is Badger's template form, with a VOCS in the short Xopt form:
    vocs: {variables: {sol1: null, xc00: [-0.2, 0.2]},
           objectives: {andor_spot_size_px: MINIMIZE},
           constraints: {andor_total: [GREATER_THAN, 1.0e5]}}
A variable given as null gets the range current +/- span_fraction of its
safety range, clipped to it. The current values come from the environment
itself (the simulator's state, or the real machine read-only), and one
reading of the observables shows where the routine starts.

Prints one JSON report on stdout; exit 0 when the routine was saved.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import sys


def main(req_path, dest):
    from ued_badger import common
    req = json.loads(open(req_path).read())
    r = copy.deepcopy(req['routine'])
    span = float(req.get('span_fraction', 0.1))
    errors, warnings = [], []
    report = {'ok': False, 'errors': errors, 'warnings': warnings}

    env_spec = dict(r.get('environment') or {})
    env_name = env_spec.pop('name', None)
    env_spec.pop('interface', None)
    if env_name not in common.ENVIRONMENTS:
        errors.append(f'environment must be one of {list(common.ENVIRONMENTS)}'
                      f', not {env_name!r}')
        return report

    with contextlib.redirect_stdout(sys.stderr):
        common.init_badger_settings()
        from badger.factory import get_env
        from badger.routine import Routine
        env_class, _ = get_env(env_name)
        env = env_class(**env_spec)

    vocs = r.get('vocs') or {}
    variables = dict(vocs.get('variables') or {})
    unknown = [v for v in variables if v not in env.variables]
    if unknown:
        errors.append(f'not knobs of {env_name}: {unknown}; the knobs are '
                      f'{list(env.variables)}')
    outputs = (list(vocs.get('objectives') or {})
               + list(vocs.get('constraints') or {})
               + list(vocs.get('observables') or []))
    bad = [o for o in outputs if o not in env.observables]
    if bad:
        errors.append(f'not observables of {env_name}: {bad}; the '
                      f'observables are {list(env.observables)}')
    if not vocs.get('objectives'):
        errors.append('the VOCS needs at least one objective')
    if errors:
        return report

    names = list(variables)
    bounds = env.get_bounds(names)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            current = env.get_variables(names)
    except Exception as exc:
        errors.append(f'cannot read the knobs from {env_name}: {exc}')
        return report
    report['current'] = {k: round(v, 6) for k, v in current.items()}
    report['safety_ranges'] = bounds
    for n in names:
        lo, hi = bounds[n]
        if variables[n] is None:
            d = span * (hi - lo)
            variables[n] = [max(lo, current[n] - d), min(hi, current[n] + d)]
        a, b = (float(x) for x in variables[n])
        if not a < b:
            errors.append(f'{n}: empty range [{a}, {b}]')
        elif a < lo or b > hi:
            errors.append(f'{n}: range [{a:g}, {b:g}] leaves the safety '
                          f'range [{lo:g}, {hi:g}] in '
                          f'{common.setup_file(env_name)}')
        elif not a <= current[n] <= b:
            warnings.append(f'{n}: the current value {current[n]:g} is '
                            f'outside [{a:g}, {b:g}]; the first point '
                            '(add_curr) still starts there')
        variables[n] = [round(a, 6), round(b, 6)]
    if errors:
        return report

    try:
        with contextlib.redirect_stdout(sys.stderr):
            now = env.get_observables(outputs)
    except Exception as exc:
        errors.append(f'cannot read the observables from {env_name}: {exc}')
        return report
    report['now'] = {k: (round(v, 4) if math.isfinite(v) else None)
                     for k, v in now.items()}
    if not math.isfinite(now.get('andor_spot_size_px', 0.0)):
        warnings.append('no beam on the Andor now: the spot size is NaN; '
                        'check the beam (beam_on_screens) before running')

    vocs['variables'] = variables
    r['vocs'] = vocs
    r.setdefault('initial_point_actions', [{'type': 'add_curr'}])
    r.setdefault('relative_to_current', False)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            routine = Routine(**copy.deepcopy(r))
            routine.dump(dest)
    except Exception as exc:
        errors.append(f'Badger rejected the routine: {exc}')
        return report
    report.update(ok=True, path=dest, vocs=vocs,
                  generator=routine.generator.name)
    return report


if __name__ == '__main__':
    out = main(sys.argv[1], sys.argv[2])
    print(json.dumps(out, default=str))
    sys.exit(0 if out['ok'] else 1)
