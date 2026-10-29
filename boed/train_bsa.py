#!/usr/bin/env python
"""Amortized posterior training for the BSA scan protocol (see bsa.py).

    1. Simulate scan 1 (full range) for N trajectories. Each trajectory's
       y_min / y_max come from scan 1 and are reused for all later scans.
    2. For scan k = 2 … N_SCANS:
         a. train fresh T0-only and full-parameter (T0 + nuisance) posteriors
            on the k - 1 scans so far,
         b. trace and save both,
         c. use the T0 model's quantiles to place scan k for every trajectory,
            simulate it and append it to the cache.
    3. Train both posteriors again on all N_SCANS scans, trace and save.

Training randomly drops up to one point per scan from the end of each batch
(horizon jitter), so the models handle scans that come back a point short.

The traced models are what infer_bsa_real_data.py and evaluate_bsa.py use:
the model trained on k scans decides the range of scan k + 1.

Settings are those of the policy-boed run `bsa_full_v2` (2026-05-24).

    python train_bsa.py --out_dir runs/bsa_full_v2
    # smoke test
    python train_bsa.py --out_dir runs/bsa_smoke --n_trajectories 2000 --epochs 2
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

from bsa import (
    JITTER_FRAC,
    N_PER_SCAN,
    N_SCANS,
    QUANTILE_HIGH,
    QUANTILE_LOW,
    jittered_scan_points,
    quantile_bounds,
    scan_range,
)
from models import FULL_ARCH, T0_ARCH, build_posterior
from priors import (
    NORM_EPS,
    NUISANCE_BOUNDS,
    PARAM_ORDER,
    T_MAX,
    T_MIN,
    NuisancePrior,
    T0Prior,
    normalize_nuisance,
)
from simulator import TwoBunchDoubleExp
from training import (
    get_device,
    plot_round,
    save_cache,
    save_traced,
    setup_logging,
    train_posterior,
)

log = logging.getLogger("train_bsa")

# ── Settings (bsa_full_v2) ────────────────────────────────────────────────────

N_TRAJECTORIES = 1_000_000
CACHE_BATCH_SIZE = 10_000
EXT_BATCH_SIZE = 1_000
N_QUANTILE_SAMPLES = 500

BATCH_SIZE = 2048
LR = 1e-3
WARMUP_STEPS = 50
SCAN_EPOCHS = 100
FINAL_EPOCHS = 100


@torch.no_grad()
def generate_scan1_cache(
    prior: T0Prior,
    nuisance_prior: NuisancePrior,
    simulator: TwoBunchDoubleExp,
    n_trajectories: int,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """Simulate scan 1 over [T_MIN, T_MAX] for every trajectory (CPU tensors out)."""
    t_range = T_MAX - T_MIN
    out = {k: [] for k in ("thetas_norm", "designs", "observations", "nuisance")}
    out.update(y_min=[], y_max=[])

    n_batches = (n_trajectories + CACHE_BATCH_SIZE - 1) // CACHE_BATCH_SIZE
    log.info("Scan-1 cache: N=%d  n_per_scan=%d", n_trajectories, N_PER_SCAN)
    for batch_idx in range(n_batches):
        start = batch_idx * CACHE_BATCH_SIZE
        n = min(start + CACHE_BATCH_SIZE, n_trajectories) - start

        t0_phys = prior.sample((n,)).to(device)
        nu = nuisance_prior.sample((n,)).to(device)

        xi_norm = jittered_scan_points(
            torch.full((n,), T_MIN, device=device),
            torch.full((n,), T_MAX, device=device),
        )
        y_phys = simulator(
            (xi_norm.squeeze(-1) * t_range + T_MIN).view(n * N_PER_SCAN, 1),
            t0_phys.repeat_interleave(N_PER_SCAN, dim=0),
            nu.repeat_interleave(N_PER_SCAN, dim=0),
        )
        y_phys = y_phys.view(n, N_PER_SCAN, 1).cpu()

        ym = y_phys.min(dim=1).values
        yx = y_phys.max(dim=1).values
        out["observations"].append(
            (y_phys - ym.unsqueeze(1)) / ((yx - ym).unsqueeze(1) + NORM_EPS)
        )
        out["designs"].append(xi_norm.cpu())
        out["thetas_norm"].append((t0_phys.cpu() - T_MIN) / t_range)
        out["nuisance"].append(nu.cpu())
        out["y_min"].append(ym)
        out["y_max"].append(yx)

    cache = {k: torch.cat(v, dim=0) for k, v in out.items()}
    cache["right_bound"] = torch.full((n_trajectories,), T_MAX)
    return cache


@torch.no_grad()
def extend_by_bsa_scan(
    encoder_t0,
    posterior_t0,
    simulator: TwoBunchDoubleExp,
    cache: dict[str, torch.Tensor],
    scan_idx: int,
    device: torch.device,
) -> None:
    """Append scan scan_idx to every trajectory, placed by the T0 model (in place)."""
    t_range = T_MAX - T_MIN
    N = cache["thetas_norm"].shape[0]
    new_xi, new_y, new_rb = [], [], []

    for start in range(0, N, EXT_BATCH_SIZE):
        end = min(start + EXT_BATCH_SIZE, N)
        B = end - start

        th_phys = cache["thetas_norm"][start:end].to(device) * t_range + T_MIN
        nu = cache["nuisance"][start:end].to(device)
        ym = cache["y_min"][start:end].to(device)
        yx = cache["y_max"][start:end].to(device)
        rb = cache["right_bound"][start:end].to(device)
        xi_b = cache["designs"][start:end].to(device)
        y_b = cache["observations"][start:end].to(device)

        lengths = torch.full((B,), xi_b.shape[1], dtype=torch.long, device=device)
        ctx = encoder_t0.encode_batch(xi_b, y_b, lengths)
        t0_samples = posterior_t0.sample(ctx, N_QUANTILE_SAMPLES)[..., 0]
        q_lo, q_hi = quantile_bounds(t0_samples * t_range + T_MIN)
        a, b, rb = scan_range(scan_idx, q_lo, q_hi, rb)

        xi_norm = jittered_scan_points(a, b)
        y_phys = simulator(
            (xi_norm.squeeze(-1) * t_range + T_MIN).view(B * N_PER_SCAN, 1),
            th_phys.repeat_interleave(N_PER_SCAN, dim=0),
            nu.repeat_interleave(N_PER_SCAN, dim=0),
        )
        ym_rep = ym.repeat_interleave(N_PER_SCAN, dim=0)
        yx_rep = yx.repeat_interleave(N_PER_SCAN, dim=0)
        y_norm = (y_phys - ym_rep) / (yx_rep - ym_rep + NORM_EPS)

        new_xi.append(xi_norm.cpu())
        new_y.append(y_norm.view(B, N_PER_SCAN, 1).cpu())
        new_rb.append(rb.cpu())

    cache["designs"] = torch.cat([cache["designs"], torch.cat(new_xi)], dim=1)
    cache["observations"] = torch.cat([cache["observations"], torch.cat(new_y)], dim=1)
    cache["right_bound"] = torch.cat(new_rb)


def train_both(
    cache: dict[str, torch.Tensor],
    all_params_norm: torch.Tensor,
    n_scans_seen: int,
    epochs: int,
    device: torch.device,
    tag: str,
):
    """Fresh T0-only and full-parameter posteriors on the current cache."""
    current_T = cache["designs"].shape[1]
    train_kw = dict(
        current_T=current_T,
        epochs=epochs,
        lr=LR,
        warmup_steps=WARMUP_STEPS,
        device=device,
        batch_size=BATCH_SIZE,
        horizon_jitter=n_scans_seen,
    )
    enc_t0, post_t0 = build_posterior(T0_ARCH, 1, device)
    train_posterior(
        enc_t0,
        post_t0,
        cache["thetas_norm"],
        cache["designs"],
        cache["observations"],
        desc=f"[{tag} T0]",
        **train_kw,
    )
    enc_full, post_full = build_posterior(FULL_ARCH, all_params_norm.shape[1], device)
    train_posterior(
        enc_full,
        post_full,
        all_params_norm,
        cache["designs"],
        cache["observations"],
        desc=f"[{tag} full]",
        **train_kw,
    )
    return enc_t0, post_t0, enc_full, post_full


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out_dir", type=Path, default=Path("runs/bsa_full_v2"))
    parser.add_argument("--n_trajectories", type=int, default=N_TRAJECTORIES)
    parser.add_argument(
        "--epochs", type=int, default=None, help="override every epoch count (smoke tests)"
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    setup_logging()
    torch.manual_seed(args.seed)
    device = get_device()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scan_epochs = args.epochs or SCAN_EPOCHS
    final_epochs = args.epochs or FINAL_EPOCHS
    log.info(
        "Device: %s  out_dir: %s  n_per_scan=%d  n_scans=%d",
        device,
        out_dir,
        N_PER_SCAN,
        N_SCANS,
    )

    simulator = TwoBunchDoubleExp(noise_type="gaussian", device=device)
    prior = T0Prior(device=device)
    nuisance_prior = NuisancePrior(device=device)

    # ── Phase 1: scan 1 ───────────────────────────────────────────────────────
    cache = generate_scan1_cache(
        prior, nuisance_prior, simulator, args.n_trajectories, device
    )
    save_cache(out_dir / "cache" / "scan_01.pt", **cache)
    # Nuisance is fixed per trajectory, so this never changes between scans.
    all_params_norm = torch.cat(
        [cache["thetas_norm"], normalize_nuisance(cache["nuisance"])], dim=1
    )

    def save_models(enc_t0, post_t0, enc_full, post_full, label: str) -> None:
        current_T = cache["designs"].shape[1]
        save_traced(
            enc_t0,
            post_t0,
            current_T,
            out_dir / f"t0_posterior_traced_{label}.pt",
            device,
        )
        save_traced(
            enc_full,
            post_full,
            current_T,
            out_dir / f"full_param_posterior_traced_{label}.pt",
            device,
        )
        plot_round(
            enc_t0,
            post_t0,
            cache["thetas_norm"],
            cache["designs"],
            cache["observations"],
            current_T,
            N_PER_SCAN,
            T_MIN,
            T_MAX,
            device,
            out_dir / "plots" / f"{label}.png",
        )

    # ── Phase 2: scans 2 … N_SCANS ────────────────────────────────────────────
    for scan_idx in range(2, N_SCANS + 1):
        n_seen = scan_idx - 1
        label = f"scan_{n_seen:02d}_horizon_{cache['designs'].shape[1]:03d}"
        log.info("Training on %d scan(s), then placing scan %d", n_seen, scan_idx)

        models = train_both(
            cache, all_params_norm, n_seen, scan_epochs, device, f"scan {n_seen}"
        )
        save_models(*models, label)

        extend_by_bsa_scan(models[0], models[1], simulator, cache, scan_idx, device)
        log.info("Cache extended to T=%d", cache["designs"].shape[1])
        save_cache(out_dir / "cache" / f"scan_{scan_idx:02d}.pt", **cache)

    # ── Phase 3: final models on all scans ────────────────────────────────────
    current_T = cache["designs"].shape[1]
    log.info("Final training (T=%d, epochs=%d)", current_T, final_epochs)
    enc_t0, post_t0, enc_full, post_full = train_both(
        cache, all_params_norm, N_SCANS, final_epochs, device, "final"
    )
    save_models(enc_t0, post_t0, enc_full, post_full, f"final_horizon_{current_T:03d}")

    meta = {
        "t_min": T_MIN,
        "t_max": T_MAX,
        "n_per_scan": N_PER_SCAN,
        "n_scans": N_SCANS,
        "T_total": current_T,
        "jitter_frac": JITTER_FRAC,
        "quantile_low": QUANTILE_LOW,
        "quantile_high": QUANTILE_HIGH,
    }
    torch.save(
        {"encoder": enc_t0.state_dict(), "posterior": post_t0.state_dict(), **meta},
        out_dir / "t0_posterior_weights.pt",
    )
    torch.save(
        {
            "encoder": enc_full.state_dict(),
            "posterior": post_full.state_dict(),
            **meta,
            "param_dim": all_params_norm.shape[1],
            "param_order": PARAM_ORDER,
            "nuisance_bounds_low": NUISANCE_BOUNDS[:10],
            "nuisance_bounds_high": NUISANCE_BOUNDS[10:],
            **FULL_ARCH,
        },
        out_dir / "full_param_posterior_weights.pt",
    )
    log.info("Done. Output dir: %s", out_dir)


if __name__ == "__main__":
    main()
