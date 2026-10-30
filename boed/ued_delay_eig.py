#!/usr/bin/env python
"""One step of the non-amortized BOED delay scan for pump-probe time zero
(ued_tuning stage 8, method='eig'), with delay_eig.DelayEIGGenerator.

The ued_tuning server's Python has no torch or pyro, so the stage calls
this script once per point after the grid, in UED_BOED_PYTHON:

    python ued_delay_eig.py < request.json > reply.json

The request is JSON:

    {"window_mm": [170, 210],     where designs may go
     "delay_mm": [...], "y": [...],   the points so far (Delta I/I, %)
     "signal_drops_toward": "lower",
     "priors": {"t0_mm": [190, 10], ...},   Normal [loc, scale] each
     "noise_prior": [-0.7, 0.75],           LogNormal [mu, sigma]
     "margin_mm": 0.5,            candidates: t0's 98 % interval + this (a
                                  heuristic); null: the whole window (April)
     "init_params": null,         the previous reply's "posterior"
     "next": true,                false: fit only (the last step)
     "train_steps": 3000, "n_candidates": 1000, "seed": 0}

The reply: {"posterior": {name: [loc, scale]}, "t0_mm": {"median", "std",
"q01", ...}, "next_mm": d | null, "noise_pct": fitted noise median}.
"""
from __future__ import annotations

import json
import math
import sys

import pyro
from xopt import VOCS

from delay_eig import DelayEIGGenerator, frame


def step(req: dict) -> dict:
    pyro.set_rng_seed(int(req.get('seed', 0)))
    vocs = VOCS(variables={'delay': [float(v) for v in req['window_mm']]},
                observables=['y'])
    kw = {k: req[k] for k in ('priors', 'noise_prior', 'signal_drops_toward',
                              'train_steps', 'train_lr', 'n_candidates',
                              'eig_steps', 'n_starts', 'init_params')
          if req.get(k) is not None}
    if 'margin_mm' in req:                       # null: the whole window
        kw['margin_mm'] = req['margin_mm']
    gen = DelayEIGGenerator(vocs=vocs, grid_steps=0, **kw)
    gen.add_data(frame(req['delay_mm'], req['y']))
    nxt = None
    if req.get('next', True):
        nxt = gen.generate(1)[0]['delay']        # fits, then maximizes EIG
    else:
        gen.fit()
    return {'posterior': gen.posterior, 't0_mm': gen.t0_summary(),
            'next_mm': nxt, 'noise_pct': math.exp(gen.posterior['noise'][0])}


if __name__ == '__main__':
    json.dump(step(json.load(sys.stdin)), sys.stdout)
