"""Amortized posterior: DeepSet history encoder + Gaussian-mixture head.

Ported from policy-boed (amortex.core.encoder.DeepSetEncoder and
amortex.models.posterior.GMMPosterior), keeping only what the two-bunch
scripts use. Attribute names are unchanged so state dicts saved by policy-boed
load here directly.
"""

from __future__ import annotations

import math
from typing import Optional

import torch
import torch.distributions as dist
import torch.nn as nn
import torch.nn.functional as F

# Architectures used for the runs (bsa_full_v2, two_bunch_full, full_posterior).
T0_ARCH = dict(
    encoding_dim=64,
    phi_dim=64,
    phi_hidden_dims=[128, 128],
    rho_hidden_dims=[128],
    gmm_components=15,
    gmm_hidden_dim=256,
)
FULL_ARCH = dict(
    encoding_dim=128,
    phi_dim=128,
    phi_hidden_dims=[256, 256],
    rho_hidden_dims=[256],
    gmm_components=20,
    gmm_hidden_dim=512,
)


def _build_mlp(in_dim: int, out_dim: int, hidden_dims: list[int]) -> nn.Sequential:
    """Build a ReLU MLP: in_dim → hidden_dims[0] → … → out_dim."""
    layers: list[nn.Module] = []
    prev = in_dim
    for h in hidden_dims:
        layers += [nn.Linear(prev, h), nn.ReLU()]
        prev = h
    layers.append(nn.Linear(prev, out_dim))
    return nn.Sequential(*layers)


class DeepSetEncoder(nn.Module):
    """Permutation-invariant deep set encoder.

    Each (design, obs) pair is embedded by a shared element MLP ``phi``.
    Embeddings are aggregated (sum or mean) over the history, then decoded by
    a second MLP ``rho``.

    Args:
        design_dim:       Dimensionality of design vectors.
        obs_dim:          Dimensionality of observation vectors.
        encoding_dim:     Output context dimension (``rho`` output size).
        phi_dim:          Output dimension of the element MLP ``phi``.
        phi_hidden_dims:  Hidden layer widths of ``phi``.
        rho_hidden_dims:  Hidden layer widths of ``rho``.
        aggregation:      ``"mean"`` (default) or ``"sum"``.
        count_feature:    If ``True`` (default), append ``log(t+1)/log(t_max+1)``
                          to the aggregate before ``rho``, so the decoder knows how
                          many measurements contributed.
        t_max:            Reference trajectory length used to normalise the count
                          feature (default 100).
    """

    def __init__(
        self,
        design_dim: int,
        obs_dim: int,
        encoding_dim: int = 64,
        phi_dim: int = 64,
        phi_hidden_dims: list[int] | None = None,
        rho_hidden_dims: list[int] | None = None,
        aggregation: str = "mean",
        count_feature: bool = True,
        t_max: int = 100,
    ):
        super().__init__()
        assert aggregation in ("mean", "sum"), f"Unknown aggregation: {aggregation!r}"
        if phi_hidden_dims is None:
            phi_hidden_dims = [128, 128]
        if rho_hidden_dims is None:
            rho_hidden_dims = [128]
        self.encoding_dim = encoding_dim
        self._aggregation = aggregation
        self._count_feature = count_feature
        self._t_max = t_max
        self._rho_in_dim = phi_dim + (1 if count_feature else 0)
        self.phi = _build_mlp(design_dim + obs_dim, phi_dim, phi_hidden_dims)
        self.rho = _build_mlp(self._rho_in_dim, encoding_dim, rho_hidden_dims)
        self.empty_context_out = nn.Parameter(torch.zeros(encoding_dim))

    def _count_feat(self, t: torch.Tensor) -> torch.Tensor:
        # t must already be on the right device: no device constant gets baked
        # into the TorchScript trace.
        return torch.log1p(t.float()) / math.log1p(self._t_max)

    def encode_batch(
        self,
        designs: torch.Tensor,
        obs: torch.Tensor,
        lengths: torch.Tensor,
    ) -> torch.Tensor:
        """Encode zero-padded histories ``(B, T, ·)`` with per-sample lengths → ``(B, encoding_dim)``."""
        z = self.phi(torch.cat([designs, obs], dim=-1))  # (B, T, phi_dim)
        B, T, _ = z.shape
        # torch.arange(T, device=...) would be constant-folded by TorchScript.
        t_range = z.new_ones(T, dtype=torch.long).cumsum(0) - 1  # [0, ..., T-1]
        mask = t_range.unsqueeze(0) < lengths.unsqueeze(1)
        z = z * mask.unsqueeze(-1)
        if self._aggregation == "mean":
            agg = z.sum(dim=1) / lengths.float().clamp(min=1).unsqueeze(-1)
        else:
            agg = z.sum(dim=1)
        if self._count_feature:
            cnt = self._count_feat(lengths.float()).unsqueeze(-1)  # (B, 1)
            agg = torch.cat([agg, cnt], dim=-1)
        out = self.rho(agg)
        empty_mask = (lengths == 0).float().view(B, 1)
        empty_ctx = self.empty_context_out.expand(B, -1)
        return out * (1.0 - empty_mask) + empty_ctx * empty_mask


class GMMPosterior(nn.Module):
    """Gaussian mixture posterior q(theta | h) from a pooled context vector.

    Args:
        encoding_dim:   Dimensionality of the pooled context input.
        param_dim:      Dimensionality of theta.
        hidden_dim:     MLP hidden layer width.
        num_components: Number of mixture components K.
        param_bounds:   Optional ``(param_dim, 2)`` [lo, hi]; theta is mapped to
                        [0, 1] internally. Here everything is already in [0, 1].
    """

    def __init__(
        self,
        encoding_dim: int,
        param_dim: int,
        hidden_dim: int = 256,
        num_components: int = 10,
        param_bounds: Optional[torch.Tensor] = None,
    ):
        super().__init__()
        self.param_dim = param_dim
        self.num_components = num_components

        if param_bounds is not None:
            self.register_buffer("param_bounds", param_bounds.float())
        else:
            self.param_bounds = None

        K, D = num_components, param_dim
        self.gmm_head = nn.Sequential(
            nn.Linear(encoding_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, K * (D + D + 1)),  # means + log_stds + log_weights
        )

    def _normalize(self, theta: torch.Tensor) -> torch.Tensor:
        if self.param_bounds is None:
            return theta
        lo, hi = self.param_bounds[:, 0], self.param_bounds[:, 1]
        return (theta - lo) / (hi - lo)

    def _denormalize(self, theta_norm: torch.Tensor) -> torch.Tensor:
        if self.param_bounds is None:
            return theta_norm
        lo, hi = self.param_bounds[:, 0], self.param_bounds[:, 1]
        return theta_norm * (hi - lo) + lo

    def _log_jacobian(self) -> torch.Tensor | float:
        if self.param_bounds is None:
            return 0.0
        return torch.log(self.param_bounds[:, 1] - self.param_bounds[:, 0]).sum()

    def _params(
        self, context: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Returns means ``(B, K, D)``, stds ``(B, K, D)``, unnormalised log_weights ``(B, K)``."""
        K, D = self.num_components, self.param_dim
        raw = self.gmm_head(context)
        means = raw[:, : K * D].view(-1, K, D)
        log_stds = raw[:, K * D : 2 * K * D].view(-1, K, D)
        log_weights = raw[:, 2 * K * D :].view(-1, K)
        stds = F.softplus(log_stds) + 1e-4
        return means, stds, log_weights

    def log_prob(self, theta: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        """``(B, param_dim)``, ``(B, encoding_dim)`` → ``(B,)``."""
        theta_norm = self._normalize(theta)
        means, stds, log_weights = self._params(context)
        component_lp = (
            dist.Normal(means, stds)
            .log_prob(theta_norm.unsqueeze(1).expand_as(means))
            .sum(dim=-1)
        )  # (B, K)
        log_w = F.log_softmax(log_weights, dim=-1)
        lp_norm = torch.logsumexp(log_w + component_lp, dim=-1)
        return lp_norm - self._log_jacobian()

    def sample(self, context: torch.Tensor, n: int) -> torch.Tensor:
        """``(B, encoding_dim)`` → ``(B, n, param_dim)``."""
        B = context.shape[0]
        means, stds, log_weights = self._params(context)
        weights = F.softmax(log_weights, dim=-1)
        idx = torch.multinomial(weights, n, replacement=True)  # (B, n)
        b_idx = torch.arange(B, device=context.device).unsqueeze(1).expand(-1, n)
        selected_means = means[b_idx, idx]
        selected_stds = stds[b_idx, idx]
        samples_norm = torch.randn_like(selected_means) * selected_stds + selected_means
        return self._denormalize(samples_norm)


class GMMParamsWrapper(nn.Module):
    """Deterministic wrapper for tracing: (designs, obs) → (means, stds, log_weights)."""

    def __init__(self, encoder: nn.Module, posterior: nn.Module) -> None:
        super().__init__()
        self.encoder = encoder
        self.posterior = posterior

    def forward(
        self, designs: torch.Tensor, obs: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        B, T, _ = designs.shape
        lengths = designs.new_full((B,), T, dtype=torch.long)
        ctx = self.encoder.encode_batch(designs, obs, lengths)
        return self.posterior._params(ctx)


def build_posterior(
    arch: dict, param_dim: int, device: torch.device
) -> tuple[DeepSetEncoder, GMMPosterior]:
    """Encoder + GMM head over ``param_dim`` parameters, all normalised to [0, 1]."""
    encoder = DeepSetEncoder(
        design_dim=1,
        obs_dim=1,
        encoding_dim=arch["encoding_dim"],
        phi_dim=arch["phi_dim"],
        phi_hidden_dims=list(arch["phi_hidden_dims"]),
        rho_hidden_dims=list(arch["rho_hidden_dims"]),
    ).to(device)

    param_bounds = torch.zeros(param_dim, 2, device=device)
    param_bounds[:, 1] = 1.0
    posterior = GMMPosterior(
        encoding_dim=encoder.encoding_dim,
        param_dim=param_dim,
        hidden_dim=arch["gmm_hidden_dim"],
        num_components=arch["gmm_components"],
        param_bounds=param_bounds,
    ).to(device)
    return encoder, posterior
