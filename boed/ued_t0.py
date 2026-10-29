#!/usr/bin/env python
"""One step of the BSA protocol for the UED Schottky scan (ued_tuning stage 2).

The ued_tuning server runs in the agent's Python, which has no torch, so the
stage calls this script once per scan in a Python that has it (the
AgenticOpt venv), with the points measured so far:

    python ued_t0.py < request.json > reply.json

The request is JSON:

    {"model_dir": ".../bsa_full_v2",
     "x_deg": [...],        gun phases in the model's frame: [T_MIN, T_MAX],
                            T0 = the emission onset
     "q": [...],            charges, any unit (normalized here)
     "scans_done": k,       scans in x_deg / q, the first n_per_scan points
                            being scan 1 (it sets the charge normalization)
     "right_bound": 45.0,   BSA state from the previous reply (T_MAX at first)
     "n_samples": 2000, "seed": 0}

With scans_done = 0 nothing is inferred and the reply is scan 1. Otherwise
the reply holds the T0 posterior from the model trained on k scans, and the
next scan's range and points (a plain grid: on the machine there is no
reason to jitter), or null after the last scan:

    {"n_per_scan": 10, "n_scans": 4, "t0": {"median", "mean", "std", "q01",
     "q05", "q95", "q99"} | null, "next": {"scan", "a", "b", "right_bound",
     "points"} | null}
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch

from bsa import (load_bsa_models, model_after, quantile_bounds, scan_range,
                 t0_samples_phys)
from priors import NORM_EPS, T_MAX, T_MIN


def step(req: dict) -> dict:
    torch.manual_seed(int(req.get("seed", 0)))
    device = torch.device("cpu")
    models = load_bsa_models(Path(req["model_dir"]), device)
    n, n_scans = models["n_per_scan"], models["n_scans"]
    k = int(req.get("scans_done", 0))
    rb = torch.tensor([float(req.get("right_bound") or T_MAX)])
    out = {"n_per_scan": n, "n_scans": n_scans, "t0": None, "next": None,
           "frame_deg": [T_MIN, T_MAX]}
    if k == 0:
        out["next"] = {"scan": 1, "a": T_MIN, "b": T_MAX,
                       "right_bound": T_MAX,
                       "points": np.linspace(T_MIN, T_MAX, n).tolist()}
        return out

    x = np.asarray(req["x_deg"], dtype=float)
    q = np.asarray(req["q"], dtype=float)
    y_min, y_max = q[:n].min(), q[:n].max()
    y = (q - y_min) / (y_max - y_min + NORM_EPS)
    t0 = t0_samples_phys(model_after(models, "t0", k), x, y, device,
                         int(req.get("n_samples", 2000)))
    out["t0"] = {"median": float(np.median(t0)), "mean": float(t0.mean()),
                 "std": float(t0.std()),
                 **{f"q{p:02d}": float(np.quantile(t0, p / 100))
                    for p in (1, 5, 95, 99)}}
    if k < n_scans:
        q_lo, q_hi = quantile_bounds(torch.tensor(t0).unsqueeze(0),
                                     models["quantile_low"],
                                     models["quantile_high"])
        a, b, rb = scan_range(k + 1, q_lo, q_hi, rb)
        a, b = float(a), float(b)
        out["next"] = {"scan": k + 1, "a": a, "b": b,
                       "right_bound": float(rb),
                       "points": np.linspace(a, b, n).tolist()}
    return out


if __name__ == "__main__":
    json.dump(step(json.load(sys.stdin)), sys.stdout)
