#!/usr/bin/env python
"""Post-hoc t0 for a stage-8 time-zero run: the full posterior by MCMC.

The amortized BOED scan (find_time_zero(method='boed')) reports t0 and a
98 % interval from its own network. This re-analyses the run's measured
points with no network: NUTS (pyro) on the April double-exponential model
(delay_model.py), with the noise learned, in 4 independent chains.

    python posthoc_t0.py RECORD_FOLDER          # a stage-8 record folder
    python posthoc_t0.py points.csv             # columns delay, signal (%)
    python posthoc_t0.py RECORD_FOLDER --prior t0_mm=200,15 --drops-toward lower

Priors (Normal [loc, scale]) are April's, except two set from the run
itself so that a new t0 or baseline doesn't fight them: t0_mm ~ N(window
centre, half the window) and baseline ~ N(median of the 3 grid points at
the before-t0 end, 1 %). --prior overrides any of them.

Reports t0 as the onset of the drop (the model's t0) and as the half-drop
point (where the fitted curve is halfway down), each with its median, std
and 98 % interval, plus the fitted baseline, drop and noise, the chains'
medians and split R-hat. Writes posthoc_t0.json (and posthoc_t0.png with
matplotlib) into --out, by default the record folder (or the CSV's folder).

The width assumes independent noise of one size at every point and this
model's shape; t0 can also drift between runs. Repeat runs are the check.

Needs torch, pyro-ppl, numpy (matplotlib for the plot). ~1 min on a laptop.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from delay_model import APRIL_PRIORS, PARAMS, PS_PER_MM, signal  # noqa: E402

N_GRID_BASELINE = 3


def load_points(path: Path):
    """(delay_mm, signal_pct, header) from a record folder's live.jsonl
    (or its record.json) or from a CSV with delay and signal columns."""
    if path.is_dir():
        live = path / 'live.jsonl'
        if live.exists():
            rows = [json.loads(line) for line in live.open()]
            head = next((r for r in rows if r.get('event') == 'start'), {})
            pts = [(r['delay_mm'], r['signal_pct']) for r in rows
                   if r.get('event') == 'point']
        else:                                   # older records: record.json
            rec = json.loads((path / 'record.json').read_text())
            head = rec
            scan = rec.get('boed') or rec.get('eig') or {}
            pts = scan.get('points') or (rec.get('coarse', [])
                                          + rec.get('fine', []))
        if not pts:
            raise SystemExit(f'no measured points in {path}')
        d, y = np.array(pts, dtype=float).T
        return d, y, head
    import csv
    with path.open() as f:
        rows = list(csv.DictReader(f))
    keys = rows[0].keys()
    dk = next(k for k in keys if k.strip().lower().startswith('delay'))
    yk = next(k for k in keys if k != dk and k.strip() not in ('', 'n')
              and not k.lower().startswith(('xopt', 'unnamed')))
    d = np.array([float(r[dk]) for r in rows])
    y = np.array([float(r[yk]) for r in rows])
    return d, y, {}


def run_priors(d, y, head, sign, overrides):
    pri = {k: list(v) for k, v in APRIL_PRIORS.items()}
    lo, hi = head.get('window_mm') or [float(d.min()), float(d.max())]
    pri['t0_mm'] = [0.5 * (lo + hi), 0.5 * (hi - lo)]
    o = np.argsort(d)
    # the before-t0 end: the highest delays if the signal drops toward lower
    before = y[o][-N_GRID_BASELINE:] if sign < 0 else y[o][:N_GRID_BASELINE]
    pri['baseline'] = [float(np.median(before)), 1.0]
    pri.update(overrides)
    return pri


def change_point(d, y, sign):
    o = np.argsort(d)
    x, v = d[o], y[o]
    best, at = -np.inf, float(np.median(x))
    for i in range(2, len(x) - 1):
        gap = (v[i:].mean() - v[:i].mean()) * (-sign)
        if gap > best:
            best, at = gap, 0.5 * (x[i - 1] + x[i])
    return at


def run(d, y, pri, sign, chains=4, warmup=1000, samples=1000):
    import pyro
    import pyro.distributions as dist
    from pyro.infer import MCMC, NUTS
    from pyro.infer.autoguide import init_to_value

    X = torch.tensor(d, dtype=torch.float32)
    Y = torch.tensor(y, dtype=torch.float32)

    def model():
        p = {k: pyro.sample(k, dist.Normal(float(pri[k][0]),
                                           float(pri[k][1]))) for k in PARAMS}
        sd = pyro.sample('noise', dist.LogNormal(-0.7, 0.75))
        pyro.sample('y', dist.Normal(signal(X, sign=sign, **p), sd), obs=Y)

    start = change_point(d, y, sign)
    out = []
    for c in range(chains):
        pyro.set_rng_seed(c)
        init = {k: torch.tensor(float(v[0])) for k, v in pri.items()}
        init['t0_mm'] = torch.tensor(start + (c - (chains - 1) / 2) * 0.3)
        init['noise'] = torch.tensor(0.5)
        m = MCMC(NUTS(model, init_strategy=init_to_value(values=init),
                      target_accept_prob=0.9),
                 num_samples=samples, warmup_steps=warmup,
                 disable_progbar=True)
        m.run()
        out.append({k: v.detach().numpy() for k, v in m.get_samples().items()})
    return out


def half_drop(samples, sign, lo, hi, n=400):
    """Per posterior draw, the delay where the curve is halfway between its
    baseline and its value 30 ps past t0 (the drop's depth)."""
    ks = np.random.default_rng(0).choice(len(samples['t0_mm']),
                                         min(n, len(samples['t0_mm'])),
                                         replace=False)
    out = []
    for k in ks:
        p = {q: torch.tensor(float(samples[q][k])) for q in PARAMS}
        t0 = float(samples['t0_mm'][k])
        x = torch.linspace(t0 - 2.0, t0 + 2.0, 4001)
        v = signal(x, sign=sign, **p).numpy()
        deep = float(signal(torch.tensor(t0 + sign * 30 / PS_PER_MM),
                            sign=sign, **p))
        target = 0.5 * (float(p['baseline']) + deep)
        below = np.nonzero(v < target)[0]
        if len(below):
            i = below[-1] if sign < 0 else below[0]
            out.append(float(x[i]))
    return np.array(out)


def summary(v):
    return {'median': float(np.median(v)), 'std': float(np.std(v)),
            'q01': float(np.quantile(v, 0.01)),
            'q99': float(np.quantile(v, 0.99)),
            'width_98': float(np.quantile(v, 0.99) - np.quantile(v, 0.01))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('data', type=Path, help='record folder or CSV')
    ap.add_argument('--drops-toward', choices=('lower', 'higher'),
                    default='lower', help='signal drops toward (default: '
                    'lower, as on UED in 2026)')
    ap.add_argument('--prior', action='append', default=[],
                    metavar='NAME=LOC,SCALE', help=f'override a prior: '
                    f'{", ".join(PARAMS)}')
    ap.add_argument('--chains', type=int, default=4)
    ap.add_argument('--samples', type=int, default=1000)
    ap.add_argument('--out', type=Path, help='where to write (default: the '
                    'record folder, or the CSV\'s folder)')
    a = ap.parse_args()
    warnings.filterwarnings('ignore')
    logging.disable(logging.INFO)

    sign = -1 if a.drops_toward == 'lower' else 1
    d, y, head = load_points(a.data)
    over = {}
    for s in a.prior:
        k, v = s.split('=')
        if k not in PARAMS:
            raise SystemExit(f'unknown parameter {k!r}: {", ".join(PARAMS)}')
        over[k] = [float(t) for t in v.split(',')]
    pri = run_priors(d, y, head, sign, over)
    ch = run(d, y, pri, sign, a.chains, a.samples, a.samples)
    allc = {k: np.concatenate([c[k] for c in ch]) for k in ch[0]}

    from pyro.ops.stats import split_gelman_rubin
    rhat = float(split_gelman_rubin(torch.tensor(np.stack(
        [c['t0_mm'] for c in ch])).unsqueeze(-1))[0]) if a.chains > 1 else None
    onset = summary(allc['t0_mm'])
    half = summary(half_drop(allc, sign, d.min(), d.max()))
    res = {
        'data': str(a.data), 'n_points': int(len(d)),
        'drops_toward': a.drops_toward, 'priors': pri,
        't0_onset_mm': onset, 't0_half_drop_mm': half,
        'baseline_pct': float(np.median(allc['baseline'])),
        'drop_pct': float(np.median(allc['a1'] + allc['a2'])),
        'noise_pct': float(np.median(allc['noise'])),
        'chain_t0_medians_mm': [float(np.median(c['t0_mm'])) for c in ch],
        'r_hat_t0': rhat,
        'reported_by_run': {k: head.get(k) for k in ('method', 'y_shift',
                                                     'y_scale', 'window_mm')
                            if head.get(k) is not None},
        'caveat': 'width assumes independent, equal noise and this model; '
                  'compare repeat runs',
    }
    out = a.out or (a.data if a.data.is_dir() else a.data.parent)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'posthoc_t0.json').write_text(json.dumps(res, indent=1))

    def line(name, s):
        return (f'{name}: {s["median"]:.3f} mm, std {s["std"]:.3f} mm '
                f'({s["std"] * PS_PER_MM * 1e3:.0f} fs), 98 % '
                f'[{s["q01"]:.3f}, {s["q99"]:.3f}] = {s["width_98"]:.3f} mm '
                f'({s["width_98"] * PS_PER_MM:.2f} ps)')
    print(f'{len(d)} points from {a.data}')
    print(line('t0 (onset)   ', onset))
    print(line('t0 (half-drop)', half))
    print(f'baseline {res["baseline_pct"]:.2f} %, drop {res["drop_pct"]:.2f} '
          f'%, noise {res["noise_pct"]:.2f} %; chain medians '
          f'{[round(v, 3) for v in res["chain_t0_medians_mm"]]}, R-hat '
          f'{rhat:.3f}' if rhat is not None else '')
    if rhat is not None and rhat > 1.05:
        print('WARNING: chains disagree (R-hat > 1.05): do not trust this; '
              'try --prior t0_mm=<guess>,<scale>')
    print(f'wrote {out / "posthoc_t0.json"}')
    _plot(d, y, allc, pri, sign, onset, half, out)


def _plot(d, y, s, pri, sign, onset, half, out):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except Exception:
        return
    fig, ax = plt.subplots(1, 2, figsize=(12, 4))
    ks = np.random.default_rng(1).choice(len(s['t0_mm']), 200, replace=False)
    for a, (lo, hi) in zip(ax, [(d.min(), d.max()),
                                (onset['median'] - 1.5,
                                 onset['median'] + 1.5)]):
        x = torch.linspace(float(lo), float(hi), 600)
        curves = np.array([signal(x, sign=sign, **{
            q: torch.tensor(float(s[q][k])) for q in PARAMS}).numpy()
            for k in ks])
        a.fill_between(x.numpy(), *np.quantile(curves, [0.01, 0.99], 0),
                       color='C0', alpha=0.25, label='fit, 98 %')
        a.plot(x.numpy(), np.median(curves, 0), 'C0')
        a.scatter(d, y, s=12, c=np.arange(len(d)), cmap='viridis', zorder=3)
        a.axvspan(onset['q01'], onset['q99'], color='r', alpha=0.2)
        a.axvline(onset['median'], color='r', lw=1, label='t0 (onset)')
        a.axvline(half['median'], color='m', lw=1, ls='--',
                  label='half-drop')
        a.set(xlim=(lo, hi), xlabel='delay (mm)', ylabel='Delta I/I (%)')
        a.grid(alpha=0.3)
    ax[0].legend(loc='best')
    ax[0].set_title(f't0 {onset["median"]:.3f} mm (onset)')
    ax[1].set_title('zoom')
    fig.tight_layout()
    fig.savefig(out / 'posthoc_t0.png', dpi=90)
    plt.close(fig)


if __name__ == '__main__':
    main()
