"""Run a saved UED routine headless, for the agent.

Runs in the Badger environment ($UED_BADGER_PYTHON), detached from the MCP
server that starts it:

    python -m ued_badger.runner RUN_DIR

RUN_DIR/request.json: {"routine": PATH, "max_evaluations": 30,
"max_minutes": 20, "on_finish": "start" | "best" | "stay",
"abort_after_no_beam": 3}. The run

  * evaluates the initial points (the current knobs, add_curr), then asks
    the generator for one point at a time, as Badger's own loop does;
  * stops at the budget (evaluations or minutes), when the generator is
    done, when RUN_DIR/STOP appears (stop_run), after `abort_after_no_beam`
    readings in a row without a beam on the Andor, or at an error;
  * then puts the knobs back at the start point (on_finish=start, the
    default), at the best feasible point (best), or leaves them (stay);
  * archives the run in the Badger archive, where the Badger GUI finds it.

While it runs it keeps RUN_DIR/status.json current and appends every
evaluation to RUN_DIR/live.jsonl; at the end it writes RUN_DIR/result.json.
Badger's own headless runner (badger run --headless) has no budget and
stops only at a Ctrl+C prompt, hence this one.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path


def _clean(v):
    if isinstance(v, float):
        return round(v, 6) if math.isfinite(v) else None
    if hasattr(v, 'item'):                         # numpy scalars
        return _clean(v.item())
    return v


def _write(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=1, default=str))
    os.replace(tmp, path)


def _pareto(rows, objectives):
    """The non-dominated rows (objectives as {name: MINIMIZE|MAXIMIZE})."""
    sign = {k: (1 if str(v).upper().startswith('MIN') else -1)
            for k, v in objectives.items()}

    def key(r):
        return [sign[k] * r['outputs'][k] for k in sign]
    ok = [r for r in rows if r['feasible'] and all(
        isinstance(r['outputs'].get(k), float) for k in sign)]
    return [r for r in ok if not any(
        all(a <= b for a, b in zip(key(o), key(r)))
        and any(a < b for a, b in zip(key(o), key(r))) for o in ok)]


class Run:
    def __init__(self, run_dir):
        self.dir = Path(run_dir)
        self.req = json.loads((self.dir / 'request.json').read_text())
        self.t0 = time.time()
        self.rows = []
        self.status = {'state': 'starting', 'pid': os.getpid(),
                       'started': time.strftime('%Y-%m-%d %H:%M:%S'),
                       'n_evaluations': 0}
        self._update()

    def _update(self, **kw):
        self.status.update(kw, elapsed_s=round(time.time() - self.t0, 1))
        _write(self.dir / 'status.json', self.status)

    def stop_reason(self):
        if (self.dir / 'STOP').exists():
            return 'stopped by request (stop_run)'
        if len(self.rows) >= int(self.req.get('max_evaluations', 30)):
            return 'evaluation budget reached'
        if time.time() - self.t0 > 60 * float(self.req.get('max_minutes',
                                                           20)):
            return 'time budget reached'
        n = int(self.req.get('abort_after_no_beam', 3))
        tail = self.rows[-n:]
        if n and len(tail) == n and all(
                r['outputs'].get('andor_spot_size_px') is None for r in tail):
            return f'no beam on the Andor for {n} evaluations in a row'
        return None

    def record(self, routine, vocs):
        """Log the routine's newest evaluation."""
        from xopt.vocs import get_feasibility_data
        last = routine.data.iloc[[-1]]
        feas = bool(get_feasibility_data(vocs, last)['feasible'].iloc[0])
        rec = last.iloc[0].to_dict()
        row = {'index': len(self.rows),
               'time': time.strftime('%H:%M:%S'),
               'variables': {k: _clean(rec[k]) for k in vocs.variable_names},
               'outputs': {k: _clean(rec.get(k)) for k in vocs.output_names},
               'feasible': feas,
               'error': (str(rec.get('xopt_error_str'))
                         if rec.get('xopt_error') else None)}
        self.rows.append(row)
        with open(self.dir / 'live.jsonl', 'a') as f:
            f.write(json.dumps(row) + '\n')
        self._update(state='running', n_evaluations=len(self.rows),
                     last=row, best=self.best(vocs))
        if row['error']:
            raise RuntimeError(f'evaluation failed: {row["error"]}')

    def best(self, vocs):
        objectives = {k: v.__class__.__name__ for k, v in
                      vocs.objectives.items()}
        front = _pareto(self.rows, objectives)
        if len(objectives) == 1:
            return front[0] if front else None
        return {'pareto_front': front}


def main(run_dir):
    run = Run(run_dir)
    routine = env = x0 = vocs = states = None
    stop, restored, archive = None, None, None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from ued_badger import common, envcore
            common.init_badger_settings()
            import yaml
            from badger.routine import Routine, calculate_initial_points
            from pandas import DataFrame
            config = yaml.safe_load(open(run.req['routine']))
            config.pop('data', None)
            routine = Routine(**config)
            env, vocs = routine.environment, routine.vocs
            if env.name not in ('ued_sim',):
                raise RuntimeError(f'{env.name}: writes to the real machine '
                                   'are disabled on this deployment')
            x0 = env.get_variables(vocs.variable_names)
            states = env.get_system_states()
            run._update(state='running', start_point=x0,
                        environment=env.name,
                        generator=routine.generator.name)
            if routine.initial_points is not None and \
                    len(routine.initial_points):
                init = routine.initial_points
            else:
                init = DataFrame(calculate_initial_points(
                    routine.initial_point_actions or [{'type': 'add_curr'}],
                    vocs, env))
            for _, point in init.iterrows():
                stop = run.stop_reason()
                if stop:
                    break
                routine.evaluate_data(point.to_dict())
                run.record(routine, vocs)
            while not stop:
                stop = run.stop_reason()
                if stop:
                    break
                if getattr(routine.generator, 'is_done', False):
                    stop = 'the generator has converged'
                    break
                candidate = DataFrame(routine.generator.generate(1)[0],
                                      index=[0])
                routine.evaluate_data(candidate)
                run.record(routine, vocs)
    except Exception as exc:
        stop = f'error: {exc}'
        (run.dir / 'runner.log').write_text(traceback.format_exc())
    finally:
        with contextlib.redirect_stdout(sys.stderr):
            restored = finish(run, env, x0, vocs)
            if routine is not None and run.rows:
                try:
                    from badger.archive import archive_run
                    out = archive_run(routine, states)
                    archive = str(Path(out['path']) / out['filename'])
                except Exception as exc:
                    archive = f'not archived: {exc}'
    best = run.best(vocs) if vocs is not None else None
    start = run.rows[0] if run.rows else None
    result = {'stop_reason': stop, 'n_evaluations': len(run.rows),
              'elapsed_s': round(time.time() - run.t0, 1),
              'start': start, 'best': best, 'restored_to': restored,
              'archive': archive}
    if start and best and 'outputs' in best:
        for k in best['outputs']:
            a, b = start['outputs'].get(k), best['outputs'].get(k)
            if isinstance(a, float) and isinstance(b, float) and a:
                result.setdefault('change_vs_start', {})[k] = \
                    f'{100 * (b - a) / abs(a):+.1f} %'
    _write(run.dir / 'result.json', result)
    run._update(state='finished', stop_reason=stop, restored_to=restored)


def finish(run, env, x0, vocs):
    """Leave the knobs where the request says; returns what was done. The
    simulator's knobs are then saved for the next run."""
    if env is None or x0 is None or not run.rows:
        return None
    how = run.req.get('on_finish', 'start')
    target = None
    if how == 'start':
        target = x0
    elif how == 'best':
        best = run.best(vocs)
        if best and 'variables' in best:
            target = best['variables']
        else:
            how, target = 'start (no single feasible best)', x0
    done = 'stay'
    try:
        if target is not None:
            env.set_variables(target)
            done = {'to': how, 'variables': {k: _clean(v)
                                             for k, v in target.items()}}
    except Exception as exc:
        done = f'FAILED to restore ({how}): {exc}'
    if env.name == 'ued_sim':
        from ued_badger import envcore
        envcore.save_sim_state(envcore.machine('ued_sim'))
    return done


if __name__ == '__main__':
    main(sys.argv[1])
