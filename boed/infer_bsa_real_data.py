#!/usr/bin/env python
"""Run the BSA protocol on recorded Schottky scans using the trained models.

Each recorded scan is a dense gun-phase sweep, so a BSA run is replayed by
picking measured points instead of measuring new ones:

    1. Scan 1: the N_PER_SCAN points closest to a uniform grid over
       [T_MIN, T_MAX]. y_min / y_max come from these points.
    2. Scan k + 1: the T0 model trained on k scans gives q_lo / q_hi; pick the
       unused points closest to a uniform grid over the next range (bsa.py).
    3. Plot the selected points and the T0 posterior after every scan, and the
       posterior predictive of the final full-parameter model.

Data files are pickles with "gunphase" (degrees) and "charge_pC" arrays.

    python infer_bsa_real_data.py --model_dir runs/bsa_full_v2
    python infer_bsa_real_data.py --model_dir runs/bsa_full_v2 --files 260501213903
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch

from bsa import (
    load_bsa_models,
    model_after,
    predictive_curves,
    quantile_bounds,
    scan_range,
    select_grid_like,
    t0_samples_phys,
    to_history,
)
from priors import NORM_EPS, T_MAX, T_MIN
from simulator import TwoBunchDoubleExp
from training import get_device, sample_traced

DATA_DIR = Path("/sdf/group/mli/samklein/schottky/data")
_SCAN_COLORS = ["steelblue", "tomato", "forestgreen", "darkorange", "mediumpurple"]


def load_datasets(data_dir: Path, file_stems: list[str] | None = None) -> list[dict]:
    files = sorted(f for f in data_dir.iterdir() if f.is_file())
    if file_stems:
        files = [f for f in files if any(s in f.name for s in file_stems)]
    out = []
    for f in files:
        with open(f, "rb") as fh:
            d = pickle.load(fh)
        gp = np.array(d["gunphase"])
        ch = np.array(d["charge_pC"])
        idx = np.argsort(gp)
        out.append({"file": f.name, "gunphase": gp[idx], "charge": ch[idx]})
    return out


def run_bsa_on_data(
    gp: np.ndarray, ch: np.ndarray, models: dict, device: torch.device
) -> tuple[np.ndarray, list[np.ndarray], list[tuple[float, float]]]:
    """Replay the BSA protocol on one recorded scan.

    Returns the charge normalized by the scan-1 points, the selected indices
    for each scan, and each scan's range.
    """
    n_per_scan = models["n_per_scan"]
    pool = list(range(len(gp)))
    scan1, pool = select_grid_like(gp, pool, T_MIN, T_MAX, n_per_scan)
    y_min, y_max = ch[scan1].min(), ch[scan1].max()
    ch_norm = (ch - y_min) / (y_max - y_min + NORM_EPS)

    scans, ranges = [scan1], [(T_MIN, T_MAX)]
    right_bound = torch.tensor([T_MAX])
    for scan_idx in range(2, models["n_scans"] + 1):
        seen = np.concatenate(scans)
        t0 = t0_samples_phys(
            model_after(models, "t0", scan_idx - 1), gp[seen], ch_norm[seen], device, 500
        )
        q_lo, q_hi = quantile_bounds(
            torch.tensor(t0).unsqueeze(0), models["quantile_low"], models["quantile_high"]
        )
        a_t, b_t, right_bound = scan_range(scan_idx, q_lo, q_hi, right_bound)
        a, b = float(a_t), float(b_t)
        idx, pool = select_grid_like(gp, pool, a, b, n_per_scan)
        scans.append(idx)
        ranges.append((a, b))
        print(f"  scan {scan_idx}: [{a:.1f}, {b:.1f}]°  → {len(idx)} points")
    return ch_norm, scans, ranges


def plot_inference(
    name: str,
    gp: np.ndarray,
    ch_norm: np.ndarray,
    scans: list[np.ndarray],
    ranges: list[tuple[float, float]],
    models: dict,
    device: torch.device,
    out_path: Path,
    n_samples: int,
) -> None:
    """Data selected so far + T0 posterior after each scan."""
    n_scans = len(scans)
    fig, axes = plt.subplots(
        2,
        n_scans,
        figsize=(5 * n_scans, 8),
        gridspec_kw={"height_ratios": [2, 1]},
        squeeze=False,
    )
    for col in range(n_scans):
        seen = np.concatenate(scans[: col + 1])
        t0 = t0_samples_phys(
            model_after(models, "t0", col + 1), gp[seen], ch_norm[seen], device, n_samples
        )

        ax = axes[0, col]
        ax.scatter(gp, ch_norm, s=4, color="lightgrey", alpha=0.5, zorder=1)
        for k, idx in enumerate(scans[: col + 1]):
            a, b = ranges[k]
            ax.scatter(
                gp[idx],
                ch_norm[idx],
                s=35,
                color=_SCAN_COLORS[k % len(_SCAN_COLORS)],
                zorder=3 + k,
                label=f"scan {k + 1} [{a:.0f},{b:.0f}]°",
            )
        ax.set_xlim(T_MIN - 0.5, T_MAX + 0.5)
        ax.set_ylim(-0.15, 1.15)
        ax.set_xlabel("gun phase (°)", fontsize=8)
        ax.set_ylabel("charge (norm)", fontsize=8)
        ax.set_title(f"After scan {col + 1}  (n={len(seen)})", fontsize=9)
        ax.legend(fontsize=6, loc="upper right")

        med, lo, hi = np.percentile(t0, [50, 16, 84])
        ax_post = axes[1, col]
        ax_post.hist(
            t0, bins=60, density=True, color=_SCAN_COLORS[col % len(_SCAN_COLORS)], alpha=0.75
        )
        ax_post.axvline(med, color="black", lw=1.2, label=f"median={med:.1f}°")
        ax_post.axvspan(lo, hi, alpha=0.2, color="black", label=f"68% [{lo:.1f},{hi:.1f}]°")
        ax_post.set_xlabel("T0 (°)", fontsize=8)
        ax_post.legend(fontsize=6)
        ax_post.sharex(ax)

    fig.suptitle(f"{name} — BSA posterior evolution", fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


def plot_predictive(
    name: str,
    gp: np.ndarray,
    ch_norm: np.ndarray,
    scans: list[np.ndarray],
    ranges: list[tuple[float, float]],
    models: dict,
    simulator: TwoBunchDoubleExp,
    device: torch.device,
    out_path: Path,
    n_samples: int,
) -> None:
    """Posterior predictive of the final full-parameter model after all scans."""
    seen = np.concatenate(scans)
    xi_t, y_t = to_history(gp[seen], ch_norm[seen], device)
    samples = sample_traced(models["full_final"], xi_t, y_t, n_samples).cpu()

    t_fine = torch.linspace(T_MIN, T_MAX, 400)
    # Normalize each curve over the scan-1 points, as the data were.
    curves = predictive_curves(
        samples, t_fine, simulator, torch.tensor(gp[scans[0]], dtype=torch.float32)
    )
    t_fine_np = t_fine.numpy()
    p = np.percentile(curves, [2.5, 16, 50, 84, 97.5], axis=0)

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={"height_ratios": [3, 1]})
    ax = axes[0]
    ax.scatter(gp, ch_norm, s=4, color="lightgrey", alpha=0.5, zorder=1, label="all data")
    ax.fill_between(t_fine_np, p[0], p[4], color="tomato", alpha=0.20, zorder=2, label="±2σ")
    ax.fill_between(t_fine_np, p[1], p[3], color="tomato", alpha=0.40, zorder=3, label="±1σ")
    ax.plot(t_fine_np, p[2], color="firebrick", lw=2.0, zorder=5, label="predictive median")
    for k, idx in enumerate(scans):
        a, b = ranges[k]
        ax.scatter(
            gp[idx],
            ch_norm[idx],
            s=40,
            zorder=6 + k,
            color=_SCAN_COLORS[k % len(_SCAN_COLORS)],
            label=f"scan {k + 1} [{a:.0f},{b:.0f}]°",
        )
    ax.set_xlim(T_MIN - 0.5, T_MAX + 0.5)
    ax.set_xlabel("gun phase (°)", fontsize=9)
    ax.set_ylabel("charge (norm)", fontsize=9)
    ax.set_title(f"Posterior predictive  (n={len(seen)} total)", fontsize=10)
    ax.legend(fontsize=7, loc="upper right")

    t0 = samples[:, 0].numpy() * (T_MAX - T_MIN) + T_MIN
    med, lo, hi = np.percentile(t0, [50, 16, 84])
    ax2 = axes[1]
    ax2.hist(t0, bins=60, density=True, color="steelblue", alpha=0.75)
    ax2.axvline(med, color="black", lw=1.5, label=f"median={med:.1f}°")
    ax2.axvspan(lo, hi, alpha=0.2, color="black", label=f"68% [{lo:.1f},{hi:.1f}]°")
    ax2.set_xlabel("T0 (°)", fontsize=9)
    ax2.legend(fontsize=7)
    ax2.sharex(ax)

    fig.suptitle(f"{name} — BSA posterior predictive ({len(scans)} scans)", fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model_dir", type=Path, required=True)
    parser.add_argument("--data_dir", type=Path, default=DATA_DIR)
    parser.add_argument("--files", nargs="*", default=None, help="filename substrings")
    parser.add_argument("--n_samples", type=int, default=2000)
    parser.add_argument("--out_dir", type=Path, default=Path("runs/infer_bsa"))
    args = parser.parse_args()

    device = get_device()
    models = load_bsa_models(args.model_dir, device)
    simulator = TwoBunchDoubleExp(noise_type="gaussian", device=device)
    n_per_scan = models["n_per_scan"]

    for ds in load_datasets(args.data_dir, args.files):
        name = ds["file"].replace("schottkyScan_", "").replace(".pkl", "")
        mask = (ds["gunphase"] >= T_MIN) & (ds["gunphase"] <= T_MAX)
        gp, ch = ds["gunphase"][mask], ds["charge"][mask]
        print(f"\n{ds['file']}  (N={len(gp)} in range)")
        if len(gp) < n_per_scan:
            print(f"  too few points in [{T_MIN}, {T_MAX}], skipping")
            continue

        ch_norm, scans, ranges = run_bsa_on_data(gp, ch, models, device)
        plot_inference(
            name,
            gp,
            ch_norm,
            scans,
            ranges,
            models,
            device,
            args.out_dir / f"infer_bsa_{name}.png",
            args.n_samples,
        )
        plot_predictive(
            name,
            gp,
            ch_norm,
            scans,
            ranges,
            models,
            simulator,
            device,
            args.out_dir / f"predictive_bsa_{name}.png",
            args.n_samples,
        )


if __name__ == "__main__":
    main()
