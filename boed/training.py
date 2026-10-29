"""Shared training utilities: posterior fitting, tracing, cache I/O, plots.

Everything here works on the normalized cache tensors::

    thetas  (N, D)     parameters in [0, 1]  (D=1 for T0, D=11 for T0 + nuisance)
    designs (N, T, 1)  x_norm
    obs     (N, T, 1)  y_norm
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
from tqdm import tqdm

from models import GMMParamsWrapper

log = logging.getLogger(__name__)


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )


def get_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


# ── Posterior training ────────────────────────────────────────────────────────


@torch.no_grad()
def _run_val(
    encoder: nn.Module,
    posterior: nn.Module,
    val_dl: torch.utils.data.DataLoader,
    current_T: int,
    device: torch.device,
) -> float:
    encoder.eval()
    posterior.eval()
    total, n_batches = 0.0, 0
    for theta_b, xi_b, y_b in val_dl:
        theta_b = theta_b.to(device)
        xi_b = xi_b[:, :current_T, :].to(device)
        y_b = y_b[:, :current_T, :].to(device)
        lengths = torch.full(
            (theta_b.shape[0],), current_T, dtype=torch.long, device=device
        )
        ctx = encoder.encode_batch(xi_b, y_b, lengths)
        total += (-posterior.log_prob(theta_b, ctx).mean()).item()
        n_batches += 1
    return total / max(n_batches, 1)


def train_posterior(
    encoder: nn.Module,
    posterior: nn.Module,
    thetas: torch.Tensor,
    designs: torch.Tensor,
    observations: torch.Tensor,
    current_T: int,
    epochs: int,
    lr: float,
    warmup_steps: int,
    device: torch.device,
    batch_size: int = 2048,
    horizon_jitter: int = 0,
    val_every: Optional[int] = None,
    num_workers: int = 0,
    desc: str = "",
) -> tuple[list[float], torch.Tensor]:
    """Fit encoder + posterior by maximum likelihood on the first current_T steps.

    A random 10% of trajectories is held out for validation. When
    horizon_jitter > 0, each batch uses a horizon drawn uniformly from
    [current_T - horizon_jitter, current_T], which makes the BSA models robust
    to scans that come back with a point or two fewer than nominal.

    Returns:
        (per-epoch train NLL, validation indices)
    """
    N = thetas.shape[0]
    val_n = max(1, int(N * 0.1))
    perm = torch.randperm(N)
    val_idx, train_idx = perm[:val_n], perm[val_n:]

    train_ds = torch.utils.data.TensorDataset(
        thetas[train_idx], designs[train_idx], observations[train_idx]
    )
    val_ds = torch.utils.data.TensorDataset(
        thetas[val_idx], designs[val_idx], observations[val_idx]
    )
    dl_kw = {"pin_memory": True, "num_workers": num_workers}
    if num_workers > 0:
        dl_kw["persistent_workers"] = True
    train_dl = torch.utils.data.DataLoader(
        train_ds, batch_size=batch_size, shuffle=True, **dl_kw
    )
    val_dl = torch.utils.data.DataLoader(val_ds, batch_size=batch_size * 2, **dl_kw)

    params = list(encoder.parameters()) + list(posterior.parameters())
    opt = torch.optim.Adam(params, lr=lr)
    scheduler = (
        torch.optim.lr_scheduler.LinearLR(
            opt, start_factor=1e-3, total_iters=warmup_steps
        )
        if warmup_steps > 0
        else None
    )
    if val_every is None:
        val_every = max(1, epochs // 5)

    epoch_nlls = []
    pbar = tqdm(range(epochs), desc=desc or "posterior training", leave=False)
    for epoch in pbar:
        encoder.train()
        posterior.train()
        total_loss, n_batches = 0.0, 0

        for theta_b, xi_b, y_b in train_dl:
            theta_b = theta_b.to(device)
            T_batch = current_T
            if horizon_jitter > 0:
                T_batch = current_T - torch.randint(0, horizon_jitter + 1, ()).item()
                T_batch = max(T_batch, 1)
            xi_b = xi_b[:, :T_batch, :].to(device)
            y_b = y_b[:, :T_batch, :].to(device)
            lengths = torch.full(
                (theta_b.shape[0],), T_batch, dtype=torch.long, device=device
            )
            ctx = encoder.encode_batch(xi_b, y_b, lengths)
            nll = -posterior.log_prob(theta_b, ctx).mean()

            opt.zero_grad()
            nll.backward()
            torch.nn.utils.clip_grad_norm_(params, 1.0)
            opt.step()
            if scheduler is not None:
                scheduler.step()

            total_loss += nll.item()
            n_batches += 1

        mean_nll = total_loss / max(n_batches, 1)
        epoch_nlls.append(mean_nll)
        pbar.set_postfix(train_nll=f"{mean_nll:.4f}")

        if (epoch + 1) % val_every == 0:
            val_nll = _run_val(encoder, posterior, val_dl, current_T, device)
            pbar.set_postfix(train_nll=f"{mean_nll:.4f}", val_nll=f"{val_nll:.4f}")
            log.info(
                "%s  epoch %d/%d  train_nll=%.4f  val_nll=%.4f",
                desc,
                epoch + 1,
                epochs,
                mean_nll,
                val_nll,
            )

    return epoch_nlls, val_idx


# ── Tracing ───────────────────────────────────────────────────────────────────


def save_traced(
    encoder: nn.Module,
    posterior: nn.Module,
    horizon: int,
    path: Path,
    device: torch.device,
) -> None:
    """TorchScript-trace (designs, obs) → GMM params and save to path.

    The trace is checked at a few history lengths, since inference calls it
    with whatever number of points has been measured so far.
    """
    log.info("Tracing model (horizon=%d) → %s", horizon, path.name)
    encoder.eval()
    posterior.eval()
    wrapper = GMMParamsWrapper(encoder, posterior).to(device).eval()

    T = horizon
    torch.manual_seed(0)
    ex_xi = torch.randn(1, T, 1, device=device)
    ex_y = torch.randn(1, T, 1, device=device)

    with torch.no_grad():
        traced = torch.jit.trace(wrapper, (ex_xi, ex_y))
        for t in sorted({1, max(1, T // 2), T}):
            means, stds, log_weights = traced(ex_xi[:, :t], ex_y[:, :t])
            ref_means, _, _ = wrapper(ex_xi[:, :t], ex_y[:, :t])
            assert means.shape == (1, posterior.num_components, posterior.param_dim)
            assert log_weights.shape == (1, posterior.num_components)
            assert torch.allclose(means, ref_means, atol=1e-5)

    path.parent.mkdir(parents=True, exist_ok=True)
    torch.jit.save(traced, str(path))
    encoder.train()
    posterior.train()


@torch.no_grad()
def sample_traced(
    model: torch.ScriptModule,
    xi_norm: torch.Tensor,
    y_norm: torch.Tensor,
    n_samples: int,
) -> torch.Tensor:
    """Sample a traced GMM for one history ``(1, T, 1)`` → ``(n_samples, D)`` in [0, 1]."""
    means, stds, log_weights = model(xi_norm, y_norm)
    weights = torch.softmax(log_weights[0], dim=-1)
    idx = torch.multinomial(weights, n_samples, replacement=True)
    sel_means, sel_stds = means[0, idx], stds[0, idx]
    return (sel_means + sel_stds * torch.randn_like(sel_means)).clamp(0.0, 1.0)


# ── Cache I/O ─────────────────────────────────────────────────────────────────


def save_cache(path: Path, **tensors) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(tensors, path)
    log.info("Cache saved → %s", path)


# ── Plots ─────────────────────────────────────────────────────────────────────


@torch.no_grad()
def plot_round(
    encoder: nn.Module,
    posterior: nn.Module,
    thetas_norm: torch.Tensor,
    designs: torch.Tensor,
    observations: torch.Tensor,
    current_T: int,
    block_size: int,
    t_min: float,
    t_max: float,
    device: torch.device,
    out_path: Path,
    num_viz: int = 5,
    num_posterior_samples: int = 1000,
) -> None:
    """Data + T0 posterior for a spread of simulated trajectories.

    Left: observations vs physical time, coloured per block of block_size
    points (the initial scan, then each round or BSA scan), with thin lines at
    T0 posterior samples. Right: T0 posterior histogram vs the true T0.
    """
    encoder.eval()
    posterior.eval()

    N = thetas_norm.shape[0]
    sorted_idx = thetas_norm[:, 0].argsort()
    step = max(1, (N - 1) // max(num_viz - 1, 1))
    viz_idx = [sorted_idx[min(i * step, N - 1)].item() for i in range(num_viz)]

    fig, axes = plt.subplots(num_viz, 2, figsize=(12, 3 * num_viz), squeeze=False)
    t_range = t_max - t_min

    for row, traj_idx in enumerate(viz_idx):
        xi_phys = (designs[traj_idx, :current_T, 0] * t_range + t_min).numpy()
        y_norm = observations[traj_idx, :current_T, 0].numpy()
        theta_phys = thetas_norm[traj_idx, 0].item() * t_range + t_min

        xi_t = designs[traj_idx : traj_idx + 1, :current_T, :].to(device)
        y_t = observations[traj_idx : traj_idx + 1, :current_T, :].to(device)
        lengths_t = torch.tensor([current_T], dtype=torch.long, device=device)
        ctx = encoder.encode_batch(xi_t, y_t, lengths_t)
        post_norm = posterior.sample(ctx, num_posterior_samples)[0, :, 0].cpu()
        post_phys = (post_norm * t_range + t_min).numpy()

        ax = axes[row, 0]
        for k in range((current_T + block_size - 1) // block_size):
            sl = slice(k * block_size, min((k + 1) * block_size, current_T))
            ax.scatter(xi_phys[sl], y_norm[sl], s=18, zorder=3, label=f"block {k + 1}")
        for ps in post_phys:
            ax.axvline(
                ps,
                color="orange",
                alpha=max(0.05, 2.0 / num_posterior_samples),
                linewidth=0.8,
            )
        ax.axvline(
            post_phys.mean(),
            color="darkorange",
            linewidth=1.5,
            label=f"posterior mean={post_phys.mean():.2f}",
        )
        ax.axvline(
            theta_phys,
            color="black",
            linewidth=1.5,
            linestyle="--",
            label=f"true T0={theta_phys:.2f}",
        )
        ax.set_xlabel("gun phase (°)")
        ax.set_ylabel("y (normalized)")
        ax.set_title(f"Traj {traj_idx} | T={current_T}")
        ax.legend(fontsize=6, loc="upper right")

        ax2 = axes[row, 1]
        ax2.hist(post_phys, bins=40, density=True, alpha=0.75, color="steelblue")
        ax2.axvline(
            theta_phys,
            color="tomato",
            linewidth=2,
            linestyle="--",
            label=f"true T0={theta_phys:.2f}",
        )
        ax2.set_xlabel("T0 (°)")
        ax2.set_ylabel("density")
        ax2.set_title(f"Posterior | T={current_T}")
        ax2.legend(fontsize=7)

    fig.suptitle(out_path.stem, fontsize=11)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    encoder.train()
    posterior.train()
