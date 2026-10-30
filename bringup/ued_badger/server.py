"""FastMCP server ``ued_badger``: Badger optimization routines for the agent.

The co-tuning after the collimator (procedure 5: Sol1, Sol2, XC/YC00-02 and
XC/YC04 against the Andor spot) as Badger routines the agent drafts, checks,
runs and reads back, without the Badger GUI:

  draft_routine  writes a routine from a VOCS, after validate.py has
                 checked it in Badger against its environment (knobs,
                 observables, safety ranges, generator) and read where
                 the machine is now
  run_routine    starts runner.py detached, with a budget; poll_run,
                 stop_run and run_result follow it
  badger_info, list_routines, list_runs, reset_sim

This server runs in the agent's Python and never imports Badger: validation
and runs happen in $UED_BADGER_PYTHON, the venv with the Badger fork. Only
the simulator (ued_sim) can be run; the real machine (ued) is read-only on
this deployment, so its routines are drafted and checked against the live
values, and an operator runs them in Badger on ued-daq
(scripts/badger_ued.sh run <routine>), the only place the `ued` environment
writes. Runs are archived in Badger's archive, where the Badger GUI finds
them.

Launched over stdio by ``python -m ued_badger`` (PYTHONPATH = bringup/).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from pathlib import Path

import yaml
from fastmcp import FastMCP

from . import common

SIM_ENV_SH = os.environ.get('UED_SIM_ENV_SH',
                            '/sdf/group/mli/zhezhang/ued/agentic/scripts/'
                            'env.sh')
RUNNABLE = ('ued_sim',)
LAUNCHER = '/sdf/group/mli/zhezhang/ued/agentic/scripts/badger_ued.sh'
OPERATOR_HINT = (f'on ued-daq an operator runs: {LAUNCHER} run <routine '
                 'path>. The Badger GUI opens with the routine loaded; the '
                 'operator checks the ranges against the current values and '
                 'presses Run. Add --dry-run to log the writes instead.')
MAX_EVALUATIONS, MAX_MINUTES = 200, 120
GENERATORS = {
    'expected_improvement': 'Bayesian, single objective, takes '
                            'constraints. The default for 4-10 knobs and '
                            'noisy readings.',
    'upper_confidence_bound': 'Bayesian, single objective, takes '
                              'constraints; generator_params {beta: 2.0} '
                              'sets how much it explores.',
    'mobo': 'Bayesian multi-objective (e.g. spot size down, counts up); '
            'needs generator_params {reference_point: {objective: worst '
            'acceptable value}}.',
    'neldermead': 'Simplex, local, single objective, NO constraints. Quick '
                  'for 1-4 knobs near a good point; poor with noise.',
    'rcds': 'Robust conjugate direction search: local, noise-tolerant, '
            'single objective, no constraints.',
    'extremum_seeking': 'Dithers the knobs to follow a slowly drifting '
                        'optimum; for long runs, not a quick tune.',
    'latin_hypercube': 'Space-filling sampling: maps the response, '
                       'optimizes nothing.',
    'random': 'Random sampling in the ranges.',
}


def _env():
    """Environment for the Badger subprocesses: the agent's, plus GPT's."""
    return dict(os.environ, PYTHONPATH=str(common.BRINGUP),
                UED_BRINGUP_DIR=str(common.BRINGUP))


def _badger(args, timeout):
    """Run `python -m ued_badger.<args>` in the Badger venv, after the
    simulator's environment script (GPT on PATH, its licence)."""
    cmd = ' '.join(f'"{a}"' for a in [common.BADGER_PYTHON, '-m'] + args)
    script = (f'[ -f "{SIM_ENV_SH}" ] && source "{SIM_ENV_SH}" '
              f'>/dev/null 2>&1; exec {cmd}')
    return ['bash', '-c', script], dict(cwd=str(common.BRINGUP), env=_env(),
                                        timeout=timeout)


def _name_ok(name):
    if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', name or ''):
        raise ValueError(f'routine names are lower_case words: {name!r}')


def _read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _status(run_dir):
    st = _read_json(run_dir / 'status.json', {'state': 'unknown'})
    if st.get('state') in ('starting', 'running') and \
            not _alive(st.get('pid')):
        st['state'] = 'died'
        log = run_dir / 'runner.log'
        out = run_dir / 'output.log'
        tail = (log if log.exists() else out)
        if tail.exists():
            st['log_tail'] = tail.read_text()[-2000:]
    return st


def _active_runs():
    if not common.RUNS_DIR.exists():
        return []
    return [d.name for d in common.RUNS_DIR.iterdir() if d.is_dir() and
            _status(d).get('state') in ('starting', 'running')]


mcp = FastMCP(
    'ued_badger',
    instructions=(
        'Badger optimization routines for UED: the co-tuning after the '
        'collimator (stage 5: Sol1, Sol2, XC/YC00-02, XC/YC04 against the '
        'Andor spot) and the sample position (stage 7: sample_x/y against '
        'the Andor diffraction intensity, andor_frame_sum). Flow: '
        'badger_info -> '
        'draft_routine (validated in Badger, ranges from the safety ranges, '
        'reads where the machine is now) -> run_routine (simulator only; '
        'budgeted, detached) -> poll_run until finished -> run_result. '
        'stop_run stops after the current evaluation. A run puts the knobs '
        "back at the start unless on_finish='best'. The real machine "
        "(environment 'ued') is read-only here: draft and check routines on "
        'it, then give the operator the command in the reply (Badger on '
        'ued-daq with the routine loaded). Never claim it ran.'),
)


@mcp.tool()
async def badger_info() -> str:
    """The environments, their knobs with safety ranges, the observables,
    the generators with when to use each, and where routines and runs
    live. Read this before drafting a routine."""
    envs = {}
    for name, desc in common.ENVIRONMENTS.items():
        try:
            bounds = common.knob_bounds(name)
            setup = str(common.setup_file(name))
        except Exception as exc:
            bounds, setup = f'unavailable: {exc}', None
        envs[name] = {'description': desc, 'runnable': name in RUNNABLE,
                      'knobs_safety_ranges': bounds, 'setup_file': setup}
    return json.dumps({
        'environments': envs,
        'observables': {
            'andor_spot_size_px': 'sqrt(sigma_x*sigma_y) of the Andor spot '
                                  '[px]; NaN when no beam is seen',
            'andor_total': 'background-subtracted counts in the spot',
            'andor_offset_from_centre_px': 'spot distance from the image '
                                           'centre [px]',
            'andor_sigma_x_px': 'rms width [px]',
            'andor_sigma_y_px': 'rms height [px]',
            'andor_saturated': '1 if a pixel is at full scale',
            'andor_frame_sum': 'background-subtracted counts over the '
                               'whole frame: the diffracted intensity with '
                               'the main beam in the through hole (stage 7)'},
        'generators': GENERATORS,
        'routines_dir': str(common.ROUTINES_DIR),
        'runs_dir': str(common.RUNS_DIR),
        'archive': str(common.ARCHIVE_ROOT),
        'sim_state': [p.name for p in sorted(
            common.ROOT.glob('ued_sim_state*.json'))] or
        'none: the simulator starts from its preset',
        'sim_presets': {'stage5': 'after stage 5: sample out, Andor at the '
                                  'check settings (spot optimization)',
                        'stage7': 'at the Bi sample, main beam in the '
                                  'through hole, Andor at the diffraction '
                                  'settings (sample position)'},
        'operator_on_ued_daq': OPERATOR_HINT,
        'active_runs': _active_runs(),
        'budget_caps': {'max_evaluations': MAX_EVALUATIONS,
                        'max_minutes': MAX_MINUTES},
        'timing': 'about 12 s per evaluation in the simulator (GPT), plus '
                  'model fitting for the Bayesian generators',
    })


@mcp.tool()
async def draft_routine(name: str, variables: list[str] | dict,
                        objectives: dict, constraints: dict | None = None,
                        observables: list[str] | None = None,
                        environment: str = 'ued_sim',
                        generator: str = 'expected_improvement',
                        generator_params: dict | None = None,
                        span_fraction: float = 0.1, n_avg: int = 3,
                        settle_s: float = 1.0, sim_preset: str = 'stage5',
                        description: str = '') -> str:
    """Write a Badger routine, validated against its environment.

    Badger builds the routine (rejecting, e.g., constraints on a generator
    that takes none) after the knobs, observables and ranges are checked
    and the environment has been read once: the reply holds the current
    knob values ('current') and observables ('now'), the final ranges, and
    errors or warnings. Saves <routines_dir>/<name>.yaml (replacing one of
    the same name). Reads only: nothing is set on any machine.

    Args:
        name: lower_case routine name.
        variables: knob names (each gets current +/- span_fraction of its
            safety range, clipped to it), or {knob: [lo, hi]}, or
            {knob: null} for the automatic range. Knobs: sol1, sol2,
            xc00, yc00, xc01, yc01, xc02, yc02, xc04, yc04 (stage 5),
            sample_x, sample_y (stage 7; each only where the setup file
            gives it a safety range).
        objectives: {observable: "MINIMIZE" | "MAXIMIZE"}, e.g.
            {"andor_spot_size_px": "MINIMIZE"}.
        constraints: {observable: ["GREATER_THAN" | "LESS_THAN", value]},
            e.g. {"andor_total": ["GREATER_THAN", 2.0e5]}.
        observables: extra observables to record.
        environment: ued_sim (runnable) or ued (the real machine,
            read-only: drafted and checked here, run by an operator).
        generator: see badger_info; expected_improvement by default.
        generator_params: passed to the generator.
        span_fraction: automatic range half-width, as a fraction of the
            knob's safety range.
        n_avg: Andor readings averaged per point.
        settle_s: wait after setting the knobs [s].
        sim_preset: for ued_sim, stage5 (after the collimator, sample out)
            or stage7 (at the Bi sample, main beam in the through hole).
        description: what the routine is for.
    """
    _name_ok(name)
    if isinstance(variables, list):
        variables = {v: None for v in variables}
    routine = {
        'name': name, 'description': description,
        'environment': {'name': environment, 'n_avg': int(n_avg),
                        'settle_s': float(settle_s),
                        **({'preset': sim_preset}
                           if environment == 'ued_sim' else {})},
        'generator': {'name': generator, **(generator_params or {})},
        'vocs': {'variables': variables, 'objectives': objectives,
                 'constraints': constraints or {},
                 'observables': observables or []},
        'initial_point_actions': [{'type': 'add_curr'}],
    }
    drafts = common.ROUTINES_DIR / '.drafts'
    drafts.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    req = drafts / f'{name}-{stamp}.json'
    req.write_text(json.dumps({'routine': routine,
                               'span_fraction': span_fraction}, indent=1))
    dest = common.ROUTINES_DIR / f'{name}.yaml'
    tmp = drafts / f'{name}-{stamp}.yaml'
    cmd, kw = _badger(['ued_badger.validate', str(req), str(tmp)], 600)
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    except subprocess.TimeoutExpired:
        return json.dumps({'ok': False, 'errors': ['validation timed out']})
    try:
        report = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return json.dumps({'ok': False, 'errors': [
            'validation crashed', p.stderr[-2000:]]})
    if report.get('ok'):
        os.replace(tmp, dest)
        report['path'] = str(dest)
        report['runnable'] = environment in RUNNABLE
        if environment not in RUNNABLE:
            report['next'] = ('this deployment cannot write to the real '
                              'machine; ' + OPERATOR_HINT.replace(
                                  '<routine path>', str(dest)))
    report['environment'] = environment
    return json.dumps(report)


@mcp.tool()
async def list_routines() -> str:
    """The saved routines: name, environment, generator, knobs, objectives."""
    out = []
    for f in sorted(common.ROUTINES_DIR.glob('*.yaml')):
        try:
            r = yaml.safe_load(f.read_text())
            g = r.get('generator') or {}
            v = g.get('vocs') or r.get('vocs') or {}
            out.append({'name': f.stem, 'environment':
                        (r.get('environment') or {}).get('name'),
                        'generator': g.get('name'),
                        'variables': {k: (x or {}).get('domain') for k, x in
                                      (v.get('variables') or {}).items()},
                        'objectives': list(v.get('objectives') or {}),
                        'constraints': list(v.get('constraints') or {}),
                        'description': r.get('description'),
                        'modified': datetime.datetime.fromtimestamp(
                            f.stat().st_mtime).isoformat(timespec='seconds')})
        except Exception as exc:
            out.append({'name': f.stem, 'error': str(exc)})
    return json.dumps(out)


@mcp.tool()
async def run_routine(name: str, max_evaluations: int = 30,
                      max_minutes: float = 20.0, on_finish: str = 'start',
                      abort_after_no_beam: int = 3) -> str:
    """Start a saved routine on the simulator, detached; returns a run_id.

    It evaluates the current point first, then one generator point at a
    time, until the budget, the generator converging, stop_run, or
    `abort_after_no_beam` readings in a row with no beam on the Andor.
    Then it sets the knobs per on_finish and archives the run. One run at
    a time. Follow it with poll_run.

    Args:
        name: a routine from list_routines (environment ued_sim).
        max_evaluations: evaluation budget (cap 200).
        max_minutes: time budget (cap 120).
        on_finish: start (put the knobs back, the default), best (the best
            feasible point; single objective), or stay.
        abort_after_no_beam: stop after this many beam-less readings in a
            row (0: never).
    """
    _name_ok(name)
    path = common.ROUTINES_DIR / f'{name}.yaml'
    if not path.exists():
        return json.dumps({'ok': False, 'reason': f'no routine {name}; see '
                           'list_routines or draft_routine'})
    env = (yaml.safe_load(path.read_text()).get('environment') or {}).get(
        'name')
    if env not in RUNNABLE:
        return json.dumps({'ok': False, 'reason': (
            f'{name} is for {env!r}: this deployment cannot write to the '
            'real machine. ' + OPERATOR_HINT.replace('<routine path>',
                                                    str(path))),
            'path': str(path)})
    if on_finish not in ('start', 'best', 'stay'):
        return json.dumps({'ok': False, 'reason': 'on_finish is start, '
                           'best or stay'})
    busy = _active_runs()
    if busy:
        return json.dumps({'ok': False, 'reason': f'a run is active: {busy}'
                           '; stop_run it or wait'})
    run_id = f"{name}-{datetime.datetime.now():%Y%m%d-%H%M%S}"
    run_dir = common.RUNS_DIR / run_id
    run_dir.mkdir(parents=True)          # a clash means a run just started
    request = {'routine': str(path),
               'max_evaluations': max(1, min(int(max_evaluations),
                                             MAX_EVALUATIONS)),
               'max_minutes': max(0.5, min(float(max_minutes), MAX_MINUTES)),
               'on_finish': on_finish,
               'abort_after_no_beam': max(0, int(abort_after_no_beam))}
    (run_dir / 'request.json').write_text(json.dumps(request, indent=1))
    cmd, kw = _badger(['ued_badger.runner', str(run_dir)], None)
    kw.pop('timeout')
    with open(run_dir / 'output.log', 'w') as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True, **kw)
    # the runner (same pid: bash execs it) rewrites this once it is up
    (run_dir / 'status.json').write_text(json.dumps(
        {'state': 'starting', 'pid': proc.pid, 'n_evaluations': 0}))
    return json.dumps({'ok': True, 'run_id': run_id, 'request': request,
                       'run_dir': str(run_dir),
                       'next': 'poll_run every minute or so; about 12 s '
                               'per evaluation'})


@mcp.tool()
async def poll_run(run_id: str, last: int = 5) -> str:
    """A run's state (starting, running, finished, died), evaluations so
    far, the best point so far, and the last few evaluations."""
    run_dir = common.RUNS_DIR / run_id
    if not run_dir.is_dir():
        return json.dumps({'ok': False, 'reason': f'no run {run_id}'})
    st = _status(run_dir)
    rows = []
    live = run_dir / 'live.jsonl'
    if live.exists():
        rows = [json.loads(x) for x in live.read_text().splitlines()[-last:]]
    st.pop('last', None)
    st['recent'] = rows
    st['stop_requested'] = (run_dir / 'STOP').exists()
    return json.dumps(st)


@mcp.tool()
async def stop_run(run_id: str) -> str:
    """Ask a run to stop after its current evaluation; it then sets the
    knobs per its on_finish and archives what it has."""
    run_dir = common.RUNS_DIR / run_id
    if not run_dir.is_dir():
        return json.dumps({'ok': False, 'reason': f'no run {run_id}'})
    (run_dir / 'STOP').touch()
    return json.dumps({'ok': True, 'state': _status(run_dir).get('state'),
                       'note': 'stops after the current evaluation'})


@mcp.tool()
async def run_result(run_id: str) -> str:
    """A finished run: why it stopped, the start and best points (or the
    Pareto front), the change against the start, where the knobs were
    left, and the archive file."""
    run_dir = common.RUNS_DIR / run_id
    res = _read_json(run_dir / 'result.json')
    if res is None:
        return json.dumps({'ok': False, 'reason': 'not finished',
                           'status': _status(run_dir)})
    return json.dumps({'ok': True, 'run_id': run_id, **res})


@mcp.tool()
async def list_runs(limit: int = 10) -> str:
    """The most recent runs, newest first, with state and best point."""
    if not common.RUNS_DIR.exists():
        return json.dumps([])
    dirs = sorted((d for d in common.RUNS_DIR.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime, reverse=True)[:limit]
    out = []
    for d in dirs:
        st = _status(d)
        res = _read_json(d / 'result.json') or {}
        out.append({'run_id': d.name, 'state': st.get('state'),
                    'n_evaluations': st.get('n_evaluations'),
                    'stop_reason': res.get('stop_reason'),
                    'best': res.get('best') or st.get('best')})
    return json.dumps(out)


@mcp.tool()
async def reset_sim() -> str:
    """Put the simulator's knobs back to its presets (forget what earlier
    runs left), for a fresh rehearsal."""
    if _active_runs():
        return json.dumps({'ok': False, 'reason': 'a run is active'})
    gone = []
    for f in common.ROOT.glob('ued_sim_state*.json'):
        f.unlink()
        gone.append(f.name)
    return json.dumps({'ok': True, 'reset': gone or 'already at the presets'})
