#!/usr/bin/env python
"""Amortized posterior sampling for T0: the "vanilla" variant.

Every trajectory starts with a grid scan; after that, each new measurement is
placed at a T0 drawn from the current amortized posterior. This is a cheap
stand-in for amortized BOED.

    1. Simulate N trajectories, each starting with an N_GRID point grid scan
       over [T_MIN, T_MAX]. Each trajectory's y_min / y_max come from its grid
       scan and are reused for every later point.
    2. For each round:
         a. train a fresh T0 posterior on the cache so far,
         b. trace and save it,
         c. add K_PER_ROUND points per trajectory at T0 values sampled from it.
    3. Retrain the T0 posterior on the full cache (T_TOTAL points).
    4. Train a full-parameter posterior (T0 + 10 nuisance) on the full cache.

Settings are those of the policy-boed run `two_bunch_full` (2026-05-07).

    python train_vanilla.py --out_dir runs/two_bunch_full
    # smoke test
    python train_vanilla.py --out_dir runs/vanilla_smoke --n_trajectories 2000 --epochs 2
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import torch

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

log = logging.getLogger("train_vanilla")

# ── Settings (two_bunch_full) ─────────────────────────────────────────────────

N_GRID = 10  # initial grid-scan points
T_TOTAL = 100  # total measurements per trajectory
K_PER_ROUND = 10  # posterior-sampled points added per round
N_TRAJECTORIES = 1_000_000
CACHE_BATCH_SIZE = 10_000
EXT_BATCH_SIZE = 1_000

BATCH_SIZE = 2048
LR = 1e-4
WARMUP_STEPS = 300
ROUND_EPOCHS = 40
FINAL_EPOCHS = 50
FULL_EPOCHS = 50


@torch.no_grad()
def generate_grid_cache(
    prior: T0Prior,
    nuisance_prior: NuisancePrior,
    simulator: TwoBunchDoubleExp,
    n_trajectories: int,
    device: torch.device,
) -> dict[str, torch.Tensor]:
    """Simulate the initial grid scan for every trajectory (CPU tensors out)."""
    t_range = T_MAX - T_MIN
    xi_norm_grid = torch.linspace(0.0, 1.0, N_GRID).view(-1, 1)
    xi_phys_grid = (xi_norm_grid * t_range + T_MIN).to(device)

    out = {k: [] for k in ("thetas_norm", "designs", "observations", "nuisance")}
    out.update(y_min=[], y_max=[])

    n_batches = (n_trajectories + CACHE_BATCH_SIZE - 1) // CACHE_BATCH_SIZE
    log.info("Grid-scan cache: N=%d  n_grid=%d", n_trajectories, N_GRID)
    for batch_idx in range(n_batches):
        start = batch_idx * CACHE_BATCH_SIZE
        n = min(start + CACHE_BATCH_SIZE, n_trajectories) - start

        t0_phys = prior.sample((n,)).to(device)
        nu = nuisance_prior.sample((n,)).to(device)

        xi_rep = xi_phys_grid.repeat(n, 1)
        y_phys = simulator(
            xi_rep,
            t0_phys.repeat_interleave(N_GRID, dim=0),
            nu.repeat_interleave(N_GRID, dim=0),
        )
        y_phys = y_phys.view(n, N_GRID, 1).cpu()

        ym = y_phys.min(dim=1).values
        yx = y_phys.max(dim=1).values
        out["observations"].append(
            (y_phys - ym.unsqueeze(1)) / ((yx - ym).unsqueeze(1) + NORM_EPS)
        )
        out["designs"].append(xi_norm_grid.expand(n, N_GRID, 1).clone())
        out["thetas_norm"].append((t0_phys.cpu() - T_MIN) / t_range)
        out["nuisance"].append(nu.cpu())
        out["y_min"].append(ym)
        out["y_max"].append(yx)

    return {k: torch.cat(v, dim=0) for k, v in out.items()}


@torch.no_grad()
def extend_by_posterior_samples(
    encoder,
    posterior,
    simulator: TwoBunchDoubleExp,
    cache: dict[str, torch.Tensor],
    K: int,
    device: torch.device,
) -> None:
    """Append K points per trajectory at T0 values sampled from the posterior (in place)."""
    t_range = T_MAX - T_MIN
    N = cache["thetas_norm"].shape[0]
    new_xi, new_y = [], []

    for start in range(0, N, EXT_BATCH_SIZE):
        end = min(start + EXT_BATCH_SIZE, N)
        B = end - start

        th_phys = cache["thetas_norm"][start:end].to(device) * t_range + T_MIN
        nu = cache["nuisance"][start:end].to(device)
        ym = cache["y_min"][start:end].to(device)
        yx = cache["y_max"][start:end].to(device)
        xi_b = cache["designs"][start:end].to(device)
        y_b = cache["observations"][start:end].to(device)

        lengths = torch.full((B,), xi_b.shape[1], dtype=torch.long, device=device)
        ctx = encoder.encode_batch(xi_b, y_b, lengths)
        xi_norm_K = posterior.sample(ctx, K).clamp(0.0, 1.0)  # (B, K, 1)

        y_phys = simulator(
            xi_norm_K.view(B * K, 1) * t_range + T_MIN,
            th_phys.repeat_interleave(K, dim=0),
            nu.repeat_interleave(K, dim=0),
        )
        ym_rep = ym.repeat_interleave(K, dim=0)
        yx_rep = yx.repeat_interleave(K, dim=0)
        y_norm = (y_phys - ym_rep) / (yx_rep - ym_rep + NORM_EPS)

        new_xi.append(xi_norm_K.cpu())
        new_y.append(y_norm.view(B, K, 1).cpu())

    cache["designs"] = torch.cat([cache["designs"], torch.cat(new_xi)], dim=1)
    cache["observations"] = torch.cat([cache["observations"], torch.cat(new_y)], dim=1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out_dir", type=Path, default=Path("runs/two_bunch_full"))
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
    round_epochs = args.epochs or ROUND_EPOCHS
    final_epochs = args.epochs or FINAL_EPOCHS
    full_epochs = args.epochs or FULL_EPOCHS
    log.info("Device: %s  out_dir: %s", device, out_dir)

    simulator = TwoBunchDoubleExp(noise_type="gaussian", device=device)
    prior = T0Prior(device=device)
    nuisance_prior = NuisancePrior(device=device)
    train_kw = dict(
        lr=LR, warmup_steps=WARMUP_STEPS, device=device, batch_size=BATCH_SIZE
    )

    # ── Phase 1: grid scan ────────────────────────────────────────────────────
    cache = generate_grid_cache(
        prior, nuisance_prior, simulator, args.n_trajectories, device
    )
    save_cache(out_dir / "cache" / "initial_grid_cache.pt", **cache)

    # ── Phase 2: rounds of posterior-sampled designs ──────────────────────────
    current_T = N_GRID
    n_rounds = (T_TOTAL - N_GRID) // K_PER_ROUND
    for r in range(n_rounds):
        label = f"round_{r:02d}_horizon_{current_T:03d}"
        log.info("Round %d / %d  (T=%d)", r + 1, n_rounds, current_T)

        encoder, posterior = build_posterior(T0_ARCH, 1, device)
        train_posterior(
            encoder,
            posterior,
            cache["thetas_norm"],
            cache["designs"],
            cache["observations"],
            current_T,
            epochs=round_epochs,
            desc=f"[round {r}]",
            **train_kw,
        )
        plot_round(
            encoder,
            posterior,
            cache["thetas_norm"],
            cache["designs"],
            cache["observations"],
            current_T,
            K_PER_ROUND,
            T_MIN,
            T_MAX,
            device,
            out_dir / "plots" / f"{label}.png",
        )
        save_traced(
            encoder,
            posterior,
            current_T,
            out_dir / f"posterior_sampling_traced_{label}.pt",
            device,
        )

        extend_by_posterior_samples(
            encoder, posterior, simulator, cache, K_PER_ROUND, device
        )
        current_T += K_PER_ROUND
        save_cache(out_dir / "cache" / f"cache_{label}.pt", **cache)

    # ── Phase 3: final T0 posterior ───────────────────────────────────────────
    # As in the original run, this continues training the last round's model.
    log.info("Final T0 retraining (T=%d, epochs=%d)", current_T, final_epochs)
    train_posterior(
        encoder,
        posterior,
        cache["thetas_norm"],
        cache["designs"],
        cache["observations"],
        current_T,
        epochs=final_epochs,
        desc="[final]",
        **train_kw,
    )
    label = f"final_horizon_{current_T:03d}"
    plot_round(
        encoder,
        posterior,
        cache["thetas_norm"],
        cache["designs"],
        cache["observations"],
        current_T,
        K_PER_ROUND,
        T_MIN,
        T_MAX,
        device,
        out_dir / "plots" / f"{label}.png",
    )
    save_traced(
        encoder,
        posterior,
        current_T,
        out_dir / f"posterior_sampling_traced_{label}.pt",
        device,
    )
    torch.save(
        {
            "encoder": encoder.state_dict(),
            "posterior": posterior.state_dict(),
            "t_min": T_MIN,
            "t_max": T_MAX,
            "n_grid": N_GRID,
            "T_total": current_T,
            "K_per_round": K_PER_ROUND,
        },
        out_dir / "posterior_sampling_weights.pt",
    )

    # ── Phase 4: full-parameter posterior (T0 + nuisance) ─────────────────────
    log.info("Full-parameter posterior (T=%d, epochs=%d)", current_T, full_epochs)
    all_params_norm = torch.cat(
        [cache["thetas_norm"], normalize_nuisance(cache["nuisance"])], dim=1
    )
    param_dim = all_params_norm.shape[1]
    full_encoder, full_posterior = build_posterior(FULL_ARCH, param_dim, device)
    train_posterior(
        full_encoder,
        full_posterior,
        all_params_norm,
        cache["designs"],
        cache["observations"],
        current_T,
        epochs=full_epochs,
        desc="[full-param final]",
        **train_kw,
    )
    save_traced(
        full_encoder,
        full_posterior,
        current_T,
        out_dir / f"full_param_posterior_traced_horizon_{current_T:03d}.pt",
        device,
    )
    torch.save(
        {
            "encoder": full_encoder.state_dict(),
            "posterior": full_posterior.state_dict(),
            "t_min": T_MIN,
            "t_max": T_MAX,
            "n_grid": N_GRID,
            "T_total": current_T,
            "param_dim": param_dim,
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
