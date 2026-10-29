#!/usr/bin/env python
"""Run the BSA protocol on the simulator at known parameters and plot the result.

The "true" (T0, nuisance) for each case come from fit_prior_to_data.py, which
fits the prior to each real Schottky scan, so the cases look like real data.

For each case:
    1. Simulate scan 1 over [T_MIN, T_MAX]; y_min / y_max come from it.
    2. After scan k, the T0 model trained on k scans gives q_lo / q_hi, which
       place scan k + 1 (see bsa.py). Simulate it.
    3. Per column k: the data with the posterior-predictive band from the full
       model trained on k scans, and the T0 posterior from the T0 model
       trained on k scans. The last column also shows the nuisance marginals.

    python evaluate_bsa.py --model_dir runs/bsa_full_v2 --best_fits_dir runs/best_fits
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from bsa import (
    JITTER_FRAC,
    load_bsa_models,
    model_after,
    predictive_curves,
    quantile_bounds,
    scan_range,
    t0_samples_phys,
    to_history,
)
from priors import NORM_EPS, NUISANCE_NAMES, T_MAX, T_MIN, denormalize_nuisance
from simulator import TwoBunchDoubleExp
from training import get_device, sample_traced


@torch.no_grad()
def simulate_scan(
    simulator: TwoBunchDoubleExp,
    theta_phys: float,
    nuisance_phys: np.ndarray,
    a: float,
    b: float,
    n_per_scan: int,
    y_min: float | None = None,
    y_max: float | None = None,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """One jittered scan over [a, b]. y_min / y_max are taken from it if not given (scan 1)."""
    gp = np.linspace(a, b, n_per_scan)
    if n_per_scan > 1:
        step = (b - a) / (n_per_scan - 1)
        gp = np.clip(gp + np.random.randn(n_per_scan) * JITTER_FRAC * step, a, b)

    xi = torch.tensor(gp, dtype=torch.float32).view(-1, 1)
    theta = torch.full((n_per_scan, 1), theta_phys)
    nu = torch.tensor(nuisance_phys, dtype=torch.float32).unsqueeze(0)
    y = simulator(xi, theta, nu.expand(n_per_scan, -1)).squeeze(-1).cpu().numpy()

    if y_min is None:
        y_min, y_max = float(y.min()), float(y.max())
    return gp, (y - y_min) / (y_max - y_min + NORM_EPS), y_min, y_max


def evaluate_case(
    stem: str,
    models: dict,
    simulator: TwoBunchDoubleExp,
    theta_phys: float,
    nuisance_phys: np.ndarray,
    device: torch.device,
    out_path: Path,
    n_samples: int,
    n_plot_curves: int,
) -> None:
    n_per_scan, n_scans = models["n_per_scan"], models["n_scans"]
    t_fine = np.linspace(T_MIN, T_MAX, 400)

    fig, axes = plt.subplots(
        4,
        n_scans,
        figsize=(5 * n_scans, 14),
        gridspec_kw={"height_ratios": [2.5, 1, 1, 1]},
        squeeze=False,
    )

    gp_all: list[np.ndarray] = []
    y_all: list[np.ndarray] = []
    y_min = y_max = None
    right_bound = torch.tensor([T_MAX])

    for col in range(n_scans):
        scan_num = col + 1

        # ── Place and simulate this scan ──────────────────────────────────────
        if scan_num == 1:
            a, b = T_MIN, T_MAX
        else:
            t0 = t0_samples_phys(
                model_after(models, "t0", col),
                np.concatenate(gp_all),
                np.concatenate(y_all),
                device,
                n_samples,
            )
            q_lo, q_hi = quantile_bounds(
                torch.tensor(t0).unsqueeze(0),
                models["quantile_low"],
                models["quantile_high"],
            )
            a_t, b_t, right_bound = scan_range(scan_num, q_lo, q_hi, right_bound)
            a, b = float(a_t), float(b_t)

        gp, y_norm, y_min, y_max = simulate_scan(
            simulator, theta_phys, nuisance_phys, a, b, n_per_scan, y_min, y_max
        )
        gp_all.append(gp)
        y_all.append(y_norm)
        gp_cum, y_cum = np.concatenate(gp_all), np.concatenate(y_all)

        # ── Posterior predictive from the full model ──────────────────────────
        xi_t, y_t = to_history(gp_cum, y_cum, device)
        full_samples = sample_traced(
            model_after(models, "full", scan_num), xi_t, y_t, n_samples
        ).cpu()
        idx = np.random.choice(n_samples, min(n_plot_curves, n_samples), replace=False)
        curves = predictive_curves(
            full_samples[idx], torch.tensor(t_fine, dtype=torch.float32), simulator
        )

        ax = axes[0, col]
        p = np.percentile(curves, [2.5, 16, 50, 84, 97.5], axis=0)
        ax.fill_between(t_fine, p[0], p[4], color="tomato", alpha=0.15, label="±2σ pred")
        ax.fill_between(t_fine, p[1], p[3], color="tomato", alpha=0.30, label="±1σ pred")
        ax.plot(t_fine, p[2], color="firebrick", lw=1.5, label="pred median")
        for k, (gp_k, y_k) in enumerate(zip(gp_all, y_all)):
            ax.scatter(gp_k, y_k, s=30, zorder=5 + k, label=f"scan {k + 1}")
        ax.axvline(
            theta_phys, color="black", lw=1.2, ls="--", label=f"true T0={theta_phys:.1f}°"
        )
        ax.set_xlim(T_MIN - 0.5, T_MAX + 0.5)
        ax.set_xlabel("gun phase (°)", fontsize=8)
        ax.set_ylabel("charge (norm)", fontsize=8)
        ax.set_title(f"scan {scan_num}  (total n={len(gp_cum)})", fontsize=9)
        ax.legend(fontsize=5, loc="upper right", ncol=2)

        # ── T0 posterior from the T0 model ────────────────────────────────────
        t0 = t0_samples_phys(
            model_after(models, "t0", scan_num), gp_cum, y_cum, device, n_samples
        )
        med, lo, hi = np.percentile(t0, [50, 16, 84])
        ax_t0 = axes[1, col]
        ax_t0.hist(t0, bins=60, density=True, color="steelblue", alpha=0.75)
        ax_t0.axvline(med, color="black", lw=1.2, label=f"median={med:.1f}°")
        ax_t0.axvspan(lo, hi, alpha=0.2, color="black", label=f"68% [{lo:.1f},{hi:.1f}]")
        ax_t0.axvline(
            theta_phys, color="firebrick", lw=1.5, ls="--", label=f"true={theta_phys:.1f}°"
        )
        ax_t0.set_xlabel("T0 (°)", fontsize=8)
        ax_t0.legend(fontsize=6)
        ax_t0.sharex(ax)

        # ── Nuisance marginals (last column only) ─────────────────────────────
        axes[2, col].set_visible(False)
        axes[3, col].set_visible(False)
        if scan_num == n_scans:
            nu_post = denormalize_nuisance(full_samples[:, 1:]).numpy()
            bb_top, bb_bot = axes[2, col].get_position(), axes[3, col].get_position()
            w = (bb_top.x1 - bb_top.x0) / 5
            h = (bb_top.y1 - bb_bot.y0) / 2
            for j, name in enumerate(NUISANCE_NAMES):
                inset = fig.add_axes(
                    [
                        bb_top.x0 + (j % 5) * w + 0.004,
                        bb_top.y1 - (j // 5 + 1) * h + 0.006,
                        w - 0.008,
                        h - 0.012,
                    ]
                )
                inset.hist(nu_post[:, j], bins=40, density=True, color="steelblue")
                inset.axvline(nuisance_phys[j], color="firebrick", lw=1.5, ls="--")
                inset.set_title(name, fontsize=7)
                inset.tick_params(labelsize=5)
                inset.set_yticks([])

    fig.suptitle(f"{stem} — BSA evaluation (true T0={theta_phys:.1f}°)", fontsize=11)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model_dir", type=Path, required=True)
    parser.add_argument("--best_fits_dir", type=Path, default=Path("runs/best_fits"))
    parser.add_argument("--files", nargs="*", default=None, help="filename substrings")
    parser.add_argument("--n_samples", type=int, default=2000)
    parser.add_argument("--n_plot_curves", type=int, default=100)
    parser.add_argument("--out_dir", type=Path, default=Path("runs/evaluate_bsa"))
    args = parser.parse_args()

    device = get_device()
    models = load_bsa_models(args.model_dir, device)
    simulator = TwoBunchDoubleExp(noise_type="gaussian", device=device)

    fits = sorted(args.best_fits_dir.glob("best_fit_*.pt"))
    if args.files:
        fits = [f for f in fits if any(s in f.name for s in args.files)]
    print(f"{len(fits)} best-fit files")

    for path in fits:
        fit = torch.load(path, map_location="cpu")
        theta_phys = float(fit["theta"].squeeze())
        nuisance_phys = fit["nuisance"].cpu().numpy().squeeze()
        stem = path.stem.replace("best_fit_", "")
        evaluate_case(
            stem,
            models,
            simulator,
            theta_phys,
            nuisance_phys,
            device,
            args.out_dir / f"eval_bsa_{stem}.png",
            args.n_samples,
            args.n_plot_curves,
        )


if __name__ == "__main__":
    main()
