#!/usr/bin/env python
"""Find the best-fitting prior sample for each recorded Schottky scan.

For each data file, draw prior samples, simulate noiseless curves at the
measured gun phases, min/max normalize them and keep the one with the lowest
MSE against the normalized charge. The result is saved as
best_fit_<stem>.pt ({"theta", "nuisance", "mse", "file"}), which
evaluate_bsa.py uses as realistic "true" parameters.

Files without a flat (pre-T0) region, i.e. fewer than FLAT_MIN_COUNT points
at or below FLAT_THRESH in normalized charge, are skipped.

Ported from the best-fit part of policy-boed scripts/explore_two_bunch_prior.py.

    python fit_prior_to_data.py --out_dir runs/best_fits
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

from priors import T_MAX, T_MIN, NuisancePrior, T0Prior
from simulator import TwoBunchDoubleExp
from training import get_device

DATA_DIR = Path("/sdf/group/mli/samklein/schottky/data")
N_SAMPLES = 1_000_000  # prior samples per data file
N_SAMPLES_SPECIAL = 50_000_000  # deep-dive file, used for the paper figures
SPECIAL_FILE_STEM = "260501213903"
BATCH_SIZE = 500_000
FLAT_THRESH = 0.05
FLAT_MIN_COUNT = 10


@torch.no_grad()
def best_fit(
    simulator: TwoBunchDoubleExp,
    gp: np.ndarray,
    ch_norm: np.ndarray,
    n_samples: int,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, float]:
    """Best (theta, nuisance, mse) over n_samples prior draws."""
    prior = T0Prior(device=torch.device("cpu"))
    nuisance_prior = NuisancePrior(device=torch.device("cpu"))
    xi = torch.tensor(gp, dtype=torch.float32).view(-1, 1).to(device)
    target = torch.tensor(ch_norm, dtype=torch.float32, device=device)
    n_pts = xi.shape[0]

    best = (None, None, float("inf"))
    for start in tqdm(range(0, n_samples, BATCH_SIZE), leave=False, desc="  MSE"):
        b = min(BATCH_SIZE, n_samples - start)
        thetas = prior.sample((b,))
        nuisance = nuisance_prior.sample((b,))
        y = simulator(
            xi.repeat(b, 1),
            thetas.to(device).repeat_interleave(n_pts, dim=0),
            nuisance.to(device).repeat_interleave(n_pts, dim=0),
            noiseless=True,
        ).view(b, n_pts)
        y_min = y.min(dim=1, keepdim=True).values
        y_max = y.max(dim=1, keepdim=True).values
        y_norm = (y - y_min) / (y_max - y_min).clamp(min=1e-6)
        mse = ((y_norm - target.unsqueeze(0)) ** 2).mean(dim=1).cpu()
        i = int(mse.argmin())
        if mse[i] < best[2]:
            best = (thetas[i], nuisance[i], float(mse[i]))
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data_dir", type=Path, default=DATA_DIR)
    parser.add_argument("--out_dir", type=Path, default=Path("runs/best_fits"))
    parser.add_argument("--n_samples", type=int, default=N_SAMPLES)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = get_device()
    simulator = TwoBunchDoubleExp(device=device)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for f in sorted(p for p in args.data_dir.iterdir() if p.is_file()):
        with open(f, "rb") as fh:
            d = pickle.load(fh)
        order = np.argsort(d["gunphase"])
        gp = np.array(d["gunphase"])[order]
        ch = np.array(d["charge_pC"])[order]
        ch_norm = (ch - ch.min()) / (ch.max() - ch.min() + 1e-8)

        if int(np.sum(ch_norm <= FLAT_THRESH)) < FLAT_MIN_COUNT:
            print(f"{f.name}: no flat region, skipped")
            continue

        stem = f.name.replace("schottkyScan_", "").replace(".pkl", "")
        n = N_SAMPLES_SPECIAL if stem == SPECIAL_FILE_STEM else args.n_samples
        theta, nuisance, mse = best_fit(simulator, gp, ch_norm, n, device)
        out = args.out_dir / f"best_fit_{stem}.pt"
        torch.save({"theta": theta, "nuisance": nuisance, "mse": mse, "file": f.name}, out)
        print(f"{f.name}: T0={float(theta):.2f}°  mse={mse:.2e}  → {out}")


if __name__ == "__main__":
    main()
