#!/usr/bin/env python
"""One step of the amortized BOED delay scan for pump-probe time zero
(ued_tuning stage 8, method='boed').

The posterior-sampling models from the 2026-04-08 beamtime (Sam Klein,
ued_tuning repo, BOED_t_zero/posterior_sampling.ipynb, models at commit
41def0a), copied to models/delay_t0_2026-04. The ued_tuning server runs in
the agent's Python, which has no torch, so the stage calls this script once
per point in a Python that has it, with the points measured so far:

    python ued_delay_t0.py < request.json > reply.json

The request is JSON:

    {"model_dir": ".../delay_t0_2026-04",
     "t_ps": [...],          designs in the model's frame (ps; t0 is where
                             the signal starts to drop, the drop grows with t)
     "y": [...],             measured Delta I/I (%) at the Bi ring
     "y_shift": 3.0,         added to y before the model sees it: the model
                             expects the before-t0 baseline at 0
     "y_scale": 1.0,         then multiplied in: the models worked on
                             April's ~4.4 % drop, and went wrong on drops
                             twice that in simulation
     "grid_steps": 10, "block_size": 10,
     "theta_range_ps": [0, 266.7],   the scan window, where designs are kept
     "param_bounds_ps": null,        t0 normalization; null = the models' own
     "n_samples": 4000, "seed": 0}

The notebook's policy: the first grid_steps points are a grid (the stage
places them; nothing is inferred here before that). After them, the model
of round (n - grid_steps) // block_size (or the latest one there is) gives
the t0 posterior, a Gaussian mixture, and the next point is one draw from
it, clamped to the window. The reply:

    {"round": r, "model": "<file>", "param_bounds_ps": [lo, hi],
     "rounds_available": [...], "next_ps": t,
     "t0_ps": {"median", "mean", "std", "q01", "q05", "q95", "q99"}}
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import torch

PATTERN = re.compile(r'posterior_sampling_traced_round_(\d+)_horizon_\d+\.pt$')


def discover(model_dir: Path) -> dict[int, Path]:
    out = {}
    for p in sorted(model_dir.glob('posterior_sampling_traced_round_*_horizon_*.pt')):
        m = PATTERN.match(p.name)
        if m:
            out[int(m.group(1))] = p
    if not out:
        raise FileNotFoundError(f'no posterior_sampling_traced_round_*.pt models in {model_dir}')
    return out


def pick_round(rounds: list[int], n_obs: int, grid_steps: int, block_size: int) -> int:
    """As the notebook: each block of block_size points after the grid
    advances one round; the latest available round at or below it, else the
    first."""
    target = (n_obs - grid_steps) // block_size
    eligible = [r for r in rounds if r <= target]
    return max(eligible) if eligible else rounds[0]


def step(req: dict) -> dict:
    gen = torch.Generator().manual_seed(int(req.get('seed', 0)))
    model_dir = Path(req['model_dir'])
    paths = discover(model_dir)
    t = np.asarray(req['t_ps'], dtype=float)
    y = ((np.asarray(req['y'], dtype=float) + float(req.get('y_shift', 0.0)))
         * float(req.get('y_scale', 1.0)))
    if len(t) == 0 or len(t) != len(y):
        raise ValueError('t_ps and y must be non-empty and the same length')
    r = pick_round(sorted(paths), len(t), int(req.get('grid_steps', 10)),
                   int(req.get('block_size', 10)))
    model = torch.jit.load(str(paths[r]), map_location='cpu')
    model.eval()
    if req.get('param_bounds_ps') is not None:
        lo, hi = (float(v) for v in req['param_bounds_ps'])
    else:
        lo, hi = model.state_dict()['posterior.param_bounds'][0].tolist()

    with torch.no_grad():
        means, stds, log_w = model(torch.tensor(t).float().view(1, -1, 1),
                                   torch.tensor(y).float().view(1, -1, 1))
    w = torch.softmax(log_w[0], dim=-1)                       # (K,)
    n = int(req.get('n_samples', 4000))
    k = torch.multinomial(w, n + 1, replacement=True, generator=gen)
    z = means[0, k, 0] + stds[0, k, 0] * torch.randn(n + 1, generator=gen)
    t0 = (z * (hi - lo) + lo).numpy()                         # ps
    a, b = (float(v) for v in req['theta_range_ps'])
    return {
        'round': r, 'model': paths[r].name, 'param_bounds_ps': [lo, hi],
        'rounds_available': sorted(paths),
        'next_ps': float(np.clip(t0[0], a, b)),               # one draw
        't0_ps': {'median': float(np.median(t0[1:])), 'mean': float(t0[1:].mean()),
                  'std': float(t0[1:].std()),
                  **{f'q{p:02d}': float(np.quantile(t0[1:], p / 100))
                     for p in (1, 5, 95, 99)}},
    }


if __name__ == '__main__':
    json.dump(step(json.load(sys.stdin)), sys.stdout)
