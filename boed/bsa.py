"""The BSA scan protocol, shared by training, simulator evaluation and real data.

A BSA run is n_scans scans of N_PER_SCAN points each:

    scan 1:            [T_MIN, T_MAX]          (full range)
    scan k, k even:    [q_lo, right_bound]     (backward towards the T0 edge)
    scan k, k odd ≥ 3: [q_lo, q_hi]            (forward over the T0 region)

where q_lo / q_hi are T0 posterior quantiles from the model trained on the
k - 1 scans so far, and right_bound starts at T_MAX and becomes q_hi after
every odd scan. In simulation each scan is a jittered linspace::

    ideal  = linspace(a, b, N_PER_SCAN)
    jitter = N(0, JITTER_FRAC * step)
    x      = clip(ideal + jitter, a, b)

On real data the closest unused measured points to the ideal grid are taken.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import torch

from priors import NORM_EPS, T_MAX, T_MIN, denormalize_nuisance
from simulator import TwoBunchDoubleExp
from training import sample_traced

# Settings of the policy-boed run `bsa_full_v2` (2026-05-24).
N_PER_SCAN = 10
N_SCANS = 4
JITTER_FRAC = 0.2
QUANTILE_LOW = 0.01
QUANTILE_HIGH = 0.99
MIN_WIDTH_FRAC = 0.01  # minimum q_hi - q_lo and minimum scan width, as a fraction of T range


def scan_range(
    scan_idx: int,
    q_lo: torch.Tensor,
    q_hi: torch.Tensor,
    right_bound: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Range of scan scan_idx (≥ 2) and the updated right_bound. Works on (B,) tensors."""
    if scan_idx % 2 == 0:
        a, b, new_rb = q_lo, right_bound, right_bound.clone()
    else:
        a, b, new_rb = q_lo, q_hi, q_hi.clone()
    a = a.clamp(T_MIN, T_MAX)
    b = b.clamp(T_MIN, T_MAX)
    b = torch.max(b, a + (T_MAX - T_MIN) * MIN_WIDTH_FRAC).clamp(T_MIN, T_MAX)
    return a, b, new_rb


def quantile_bounds(
    t0_phys: torch.Tensor,
    quantile_low: float = QUANTILE_LOW,
    quantile_high: float = QUANTILE_HIGH,
) -> tuple[torch.Tensor, torch.Tensor]:
    """T0 samples ``(B, S)`` in physical units → (q_lo, q_hi), each ``(B,)``."""
    q_lo = torch.quantile(t0_phys, quantile_low, dim=-1).clamp(T_MIN, T_MAX)
    q_hi = torch.quantile(t0_phys, quantile_high, dim=-1).clamp(T_MIN, T_MAX)
    q_lo = torch.min(q_lo, q_hi - (T_MAX - T_MIN) * MIN_WIDTH_FRAC)
    return q_lo, q_hi


def jittered_scan_points(
    a_phys: torch.Tensor,
    b_phys: torch.Tensor,
    n_per_scan: int = N_PER_SCAN,
    jitter_frac: float = JITTER_FRAC,
) -> torch.Tensor:
    """(B,) bounds in physical units → jittered scan points ``(B, n_per_scan, 1)`` as x_norm."""
    B = a_phys.shape[0]
    device = a_phys.device
    t_frac = torch.linspace(0.0, 1.0, n_per_scan, device=device)
    a = a_phys.unsqueeze(1)
    b = b_phys.unsqueeze(1)
    xi_phys = a + t_frac.unsqueeze(0) * (b - a)
    step = (b - a) / max(n_per_scan - 1, 1)
    jitter = torch.randn(B, n_per_scan, device=device) * jitter_frac * step
    xi_phys = (xi_phys + jitter).clamp(a, b)
    return ((xi_phys - T_MIN) / (T_MAX - T_MIN)).unsqueeze(-1)


def select_grid_like(
    gp: np.ndarray, pool: list[int], a: float, b: float, n: int
) -> tuple[np.ndarray, list[int]]:
    """Real data: greedily take the n unused points closest to linspace(a, b, n).

    Returns the selected indices and the remaining pool.
    """
    in_range = [i for i in pool if a <= gp[i] <= b]
    if len(in_range) < n:
        in_range = pool
    available = list(in_range)
    selected: list[int] = []
    for target in np.linspace(a, b, n):
        if not available:
            break
        best = int(np.argmin(np.abs(gp[np.array(available)] - target)))
        selected.append(available.pop(best))
    chosen = set(selected)
    remaining = [i for i in pool if i not in chosen]
    return np.array(selected, dtype=int), remaining


# ── Using the traced models ───────────────────────────────────────────────────


def load_bsa_models(model_dir: Path, device: torch.device) -> dict:
    """Load the traced T0 / full models and metadata written by train_bsa.py.

    Keys of the returned dict:
        t0_scan:    {k: traced T0 model trained on k scans}
        full_scan:  {k: traced full-parameter model trained on k scans}
        t0_final, full_final: models trained on all n_scans scans
        n_per_scan, n_scans, quantile_low, quantile_high
    """
    meta = torch.load(model_dir / "t0_posterior_weights.pt", map_location="cpu")
    models = {
        "n_per_scan": int(meta["n_per_scan"]),
        "n_scans": int(meta["n_scans"]),
        "quantile_low": float(meta["quantile_low"]),
        "quantile_high": float(meta["quantile_high"]),
    }
    pattern = re.compile(r"scan_(\d+)_horizon_\d+")
    for kind, prefix in (("t0", "t0_posterior"), ("full", "full_param_posterior")):
        per_scan = {}
        for path in sorted(model_dir.glob(f"{prefix}_traced_scan_*_horizon_*.pt")):
            k = int(pattern.search(path.stem).group(1))
            per_scan[k] = torch.jit.load(str(path), map_location=device).eval()
        finals = sorted(model_dir.glob(f"{prefix}_traced_final_horizon_*.pt"))
        if not finals:
            raise FileNotFoundError(f"No {prefix}_traced_final_*.pt in {model_dir}")
        models[f"{kind}_scan"] = per_scan
        models[f"{kind}_final"] = torch.jit.load(str(finals[-1]), map_location=device).eval()
    return models


def model_after(models: dict, kind: str, k: int):
    """Traced model trained on exactly k scans, falling back to the final one."""
    return models[f"{kind}_scan"].get(k, models[f"{kind}_final"])


def to_history(
    gp_phys: np.ndarray, y_norm: np.ndarray, device: torch.device
) -> tuple[torch.Tensor, torch.Tensor]:
    """Physical gun phases + normalized y → traced-model inputs, each ``(1, T, 1)``."""
    xi = torch.tensor((gp_phys - T_MIN) / (T_MAX - T_MIN), dtype=torch.float32)
    y = torch.tensor(y_norm, dtype=torch.float32)
    return xi.view(1, -1, 1).to(device), y.view(1, -1, 1).to(device)


@torch.no_grad()
def t0_samples_phys(
    model, gp_phys: np.ndarray, y_norm: np.ndarray, device: torch.device, n: int
) -> np.ndarray:
    xi, y = to_history(gp_phys, y_norm, device)
    t0_norm = sample_traced(model, xi, y, n)[:, 0].cpu().numpy()
    return t0_norm * (T_MAX - T_MIN) + T_MIN


@torch.no_grad()
def predictive_curves(
    full_samples_norm: torch.Tensor,
    t_fine_phys: torch.Tensor,
    simulator: TwoBunchDoubleExp,
    t_norm_phys: torch.Tensor | None = None,
) -> np.ndarray:
    """Noiseless curves ``(S, n_fine)`` for full-posterior samples ``(S, 11)`` in [0, 1].

    Each curve is min/max normalized: over the points t_norm_phys if given
    (e.g. the scan-1 gun phases, matching the training convention), otherwise
    over its own fine grid.
    """
    S = full_samples_norm.shape[0]
    t0 = (full_samples_norm[:, :1] * (T_MAX - T_MIN) + T_MIN).cpu()
    nu = denormalize_nuisance(full_samples_norm[:, 1:].cpu())

    def simulate(t_phys: torch.Tensor) -> np.ndarray:
        n = t_phys.shape[0]
        y = simulator(
            t_phys.view(-1, 1).repeat(S, 1),
            t0.repeat_interleave(n, dim=0),
            nu.repeat_interleave(n, dim=0),
            noiseless=True,
        )
        return y.cpu().view(S, n).numpy()

    curves = simulate(t_fine_phys)
    ref = simulate(t_norm_phys) if t_norm_phys is not None else curves
    y_min = ref.min(axis=1, keepdims=True)
    y_max = ref.max(axis=1, keepdims=True)
    return (curves - y_min) / (y_max - y_min + NORM_EPS)
