#!/usr/bin/env python
"""Retrain the full-parameter (T0 + nuisance) posterior on saved BSA caches.

The full-parameter posteriors that train_bsa.py fits alongside the T0 models
were under-trained, so the posterior-predictive plots were poor. This script
loads each cache/scan_XX.pt written by train_bsa.py and trains a longer,
separate full-parameter posterior at that horizon. The scan placement is not
redone; only the posterior is refit.

Outputs, per scan level k:
    full_param_posterior_traced_scan_{k:02d}_horizon_{T:03d}.pt
    full_param_posterior_weights_scan_{k:02d}.pt
    plots/predictive_scan_{k:02d}_horizon_{T:03d}.png

Settings are those of the policy-boed run `full_posterior` (2026-05-24).
To use these models in evaluate_bsa.py / infer_bsa_real_data.py, copy the
traced files over the matching ones in the train_bsa.py output directory.

    python train_full_from_cache.py --cache_dir runs/bsa_full_v2/cache --out_dir runs/full_posterior
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch

from bsa import predictive_curves
from models import FULL_ARCH, build_posterior
from priors import (
    NUISANCE_BOUNDS,
    PARAM_ORDER,
    T_MAX,
    T_MIN,
    normalize_nuisance,
)
from simulator import TwoBunchDoubleExp
from training import get_device, save_traced, setup_logging, train_posterior

log = logging.getLogger("train_full_from_cache")

# ── Settings (full_posterior) ─────────────────────────────────────────────────

EPOCHS = 300
LR = 1e-3
WARMUP_STEPS = 300
BATCH_SIZE = 2048
NUM_WORKERS = 4
VAL_EVERY = 10
HORIZON_JITTER = 0

NUM_VIZ = 5
NUM_PREDICTIVE_SAMPLES = 50


@torch.no_grad()
def plot_predictive(
    encoder,
    posterior,
    simulator: TwoBunchDoubleExp,
    val_idx: torch.Tensor,
    thetas_norm: torch.Tensor,
    designs: torch.Tensor,
    observations: torch.Tensor,
    device: torch.device,
    out_path: Path,
) -> None:
    """Posterior-predictive curves for held-out trajectories spread over T0."""
    encoder.eval()
    posterior.eval()
    T = designs.shape[1]
    t_range = T_MAX - T_MIN
    xi_fine_norm = torch.linspace(0.0, 1.0, 200)
    xi_fine_phys = xi_fine_norm * t_range + T_MIN

    sorted_local = thetas_norm[val_idx, 0].argsort()
    step = max(1, (len(val_idx) - 1) // max(NUM_VIZ - 1, 1))
    chosen = [
        val_idx[sorted_local[min(i * step, len(val_idx) - 1)]].item()
        for i in range(NUM_VIZ)
    ]

    fig, axes = plt.subplots(NUM_VIZ, 1, figsize=(10, 3 * NUM_VIZ), squeeze=False)
    for row, i in enumerate(chosen):
        ax = axes[row, 0]
        xi_t = designs[i : i + 1].to(device)
        y_t = observations[i : i + 1].to(device)
        ctx = encoder.encode_batch(
            xi_t, y_t, torch.tensor([T], dtype=torch.long, device=device)
        )
        samples = posterior.sample(ctx, NUM_PREDICTIVE_SAMPLES)[0].clamp(0.0, 1.0)
        curves = predictive_curves(samples, xi_fine_phys, simulator)
        for c in curves:
            ax.plot(
                xi_fine_norm.numpy(),
                c,
                color="steelblue",
                alpha=max(0.05, 2.0 / NUM_PREDICTIVE_SAMPLES),
                linewidth=0.8,
            )
        ax.scatter(
            designs[i, :, 0].numpy(),
            observations[i, :, 0].numpy(),
            color="black",
            s=25,
            zorder=5,
            label="observed",
        )
        true_t0 = thetas_norm[i, 0].item() * t_range + T_MIN
        ax.set_xlabel("x_norm")
        ax.set_ylabel("y_norm")
        ax.set_title(f"Traj {i}  true T0={true_t0:.1f}°  T={T}", fontsize=9)
        ax.legend(fontsize=7)

    fig.suptitle(out_path.stem, fontsize=10)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache_dir", type=Path, required=True)
    parser.add_argument("--out_dir", type=Path, default=Path("runs/full_posterior"))
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    setup_logging()
    torch.manual_seed(args.seed)
    device = get_device()
    out_dir: Path = args.out_dir
    simulator = TwoBunchDoubleExp(noise_type="gaussian", device=device)

    cache_files = sorted(args.cache_dir.glob("scan_*.pt"))
    if not cache_files:
        raise FileNotFoundError(f"No scan_*.pt files in {args.cache_dir}")
    log.info("Caches: %s", [f.name for f in cache_files])

    for cache_path in cache_files:
        scan_tag = cache_path.stem  # e.g. "scan_01"
        cache = torch.load(cache_path, map_location="cpu", weights_only=False)
        thetas_norm = cache["thetas_norm"]
        designs = cache["designs"]
        observations = cache["observations"]
        current_T = designs.shape[1]
        all_params_norm = torch.cat(
            [thetas_norm, normalize_nuisance(cache["nuisance"])], dim=1
        )
        param_dim = all_params_norm.shape[1]
        log.info("%s: N=%d  T=%d", scan_tag, thetas_norm.shape[0], current_T)

        encoder, posterior = build_posterior(FULL_ARCH, param_dim, device)
        epoch_nlls, val_idx = train_posterior(
            encoder,
            posterior,
            all_params_norm,
            designs,
            observations,
            current_T,
            epochs=args.epochs,
            lr=LR,
            warmup_steps=WARMUP_STEPS,
            device=device,
            batch_size=BATCH_SIZE,
            horizon_jitter=HORIZON_JITTER,
            val_every=VAL_EVERY,
            num_workers=NUM_WORKERS,
            desc=f"[{scan_tag}]",
        )
        log.info("  final train NLL: %.4f", epoch_nlls[-1])

        label = f"{scan_tag}_horizon_{current_T:03d}"
        plot_predictive(
            encoder,
            posterior,
            simulator,
            val_idx,
            thetas_norm,
            designs,
            observations,
            device,
            out_dir / "plots" / f"predictive_{label}.png",
        )
        save_traced(
            encoder,
            posterior,
            current_T,
            out_dir / f"full_param_posterior_traced_{label}.pt",
            device,
        )
        torch.save(
            {
                "encoder": encoder.state_dict(),
                "posterior": posterior.state_dict(),
                "t_min": T_MIN,
                "t_max": T_MAX,
                "T_total": current_T,
                "param_dim": param_dim,
                "param_order": PARAM_ORDER,
                "nuisance_bounds_low": NUISANCE_BOUNDS[:10],
                "nuisance_bounds_high": NUISANCE_BOUNDS[10:],
                **FULL_ARCH,
            },
            out_dir / f"full_param_posterior_weights_{scan_tag}.pt",
        )

    log.info("Done. Output dir: %s", out_dir)


if __name__ == "__main__":
    main()
