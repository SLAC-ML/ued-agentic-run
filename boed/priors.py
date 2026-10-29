"""Priors, bounds and normalization for the two-bunch model.

Ported from policy-boed (amortex.datasets.two_bunch).

Normalization used everywhere in training and inference::

    x_norm  = (t - T_MIN) / (T_MAX - T_MIN)
    y_norm  = (y - y_min_scan1) / (y_max_scan1 - y_min_scan1 + NORM_EPS)
    T0_norm = (T0 - T_MIN) / (T_MAX - T_MIN)
    nuisance_norm = normalize_nuisance(nuisance)   # linear or log, to [0, 1]
"""

from __future__ import annotations

import torch
import torch.distributions as dist

# ── Fixed experiment settings (gun phase, degrees) ────────────────────────────

T_MIN = -25.0
T_MAX = 45.0
PRIOR_LOW = -22.0  # T0 prior
PRIOR_HIGH = 40.0
NORM_EPS = 1e-6  # guard against flat signals during y normalization

# [A, f1, tau1, tau2, tau_kick, sigma, y_shift, irf_sigma, alpha_kick, delta_T]
# Low bounds first, then high bounds.
NUISANCE_BOUNDS = [
    # --- low ---
    1.5,  # A           (total amplitude)
    0.1,  # f1          (fast fraction)
    1.0,  # tau1        (fast decay; log-uniform; signal stays elevated)
    15.0,  # tau2        (slow decay; log-uniform; >> scan width)
    0.1,  # tau_kick    (kick decay constant; log-uniform)
    0.0001,  # sigma       (noise; empirical flat-region noise ~0.0002-0.005)
    -0.05,  # y_shift     (vertical offset)
    0.01,  # irf_sigma   (IRF width in degrees; empirical transition ~2 deg)
    0.0,  # alpha_kick  (kick amplitude ratio; zero = no kick)
    0.5,  # delta_T     (bunch separation; log-uniform)
    # --- high ---
    10.0,  # A
    0.9,  # f1
    15.0,  # tau1
    100.0,  # tau2
    10.0,  # tau_kick
    0.01,  # sigma
    0.05,  # y_shift
    3.0,  # irf_sigma
    0.40,  # alpha_kick
    45.0,  # delta_T
]

NUISANCE_NAMES = [
    "A",
    "f1",
    "tau1",
    "tau2",
    "tau_kick",
    "sigma",
    "y_shift",
    "irf_sigma",
    "alpha_kick",
    "delta_T",
]
PARAM_ORDER = ["T0"] + NUISANCE_NAMES

# tau1, tau2, tau_kick, delta_T span multiple orders of magnitude.
_LOG_UNIFORM_IDX = [2, 3, 4, 9]


class T0Prior:
    """Uniform prior over T0 in physical units."""

    def __init__(
        self,
        prior_low: float = PRIOR_LOW,
        prior_high: float = PRIOR_HIGH,
        device: torch.device = None,
    ):
        self.device = device or torch.device("cpu")
        self.prior_low = prior_low
        self.prior_high = prior_high
        self.base_prior = dist.Independent(
            dist.Uniform(
                torch.tensor([prior_low], dtype=torch.float32, device=self.device),
                torch.tensor([prior_high], dtype=torch.float32, device=self.device),
            ),
            1,
        )

    def sample(self, sample_shape=torch.Size()) -> torch.Tensor:
        if isinstance(sample_shape, int):
            sample_shape = torch.Size([sample_shape])
        return self.base_prior.sample(sample_shape)

    def log_prob(self, value: torch.Tensor) -> torch.Tensor:
        return self.base_prior.log_prob(value)


class NuisancePrior:
    """Mixed uniform / log-uniform prior over the 10 nuisance parameters.

    tau1, tau2, tau_kick, delta_T are sampled log-uniformly (equal density per
    decade). All other parameters are sampled uniformly.
    """

    def __init__(
        self,
        nuisance_bounds: list[float] = NUISANCE_BOUNDS,
        device: torch.device = None,
    ):
        self.device = device or torch.device("cpu")
        self.nuisance_dim = 10

        self.nuisance_low = torch.tensor(
            nuisance_bounds[:10], dtype=torch.float32, device=self.device
        )
        self.nuisance_high = torch.tensor(
            nuisance_bounds[10:], dtype=torch.float32, device=self.device
        )

        self._log_mask = torch.zeros(10, dtype=torch.bool, device=self.device)
        for i in _LOG_UNIFORM_IDX:
            self._log_mask[i] = True

        self._log_low = self.nuisance_low[self._log_mask].log()
        self._log_high = self.nuisance_high[self._log_mask].log()

    def sample(self, sample_shape=torch.Size()) -> torch.Tensor:
        if isinstance(sample_shape, int):
            sample_shape = torch.Size([sample_shape])
        out = torch.empty(*sample_shape, self.nuisance_dim, device=self.device)

        unif = ~self._log_mask
        lo_u, hi_u = self.nuisance_low[unif], self.nuisance_high[unif]
        out[..., unif] = (
            torch.rand(*sample_shape, int(unif.sum()), device=self.device)
            * (hi_u - lo_u)
            + lo_u
        )

        n_log = int(self._log_mask.sum())
        out[..., self._log_mask] = torch.exp(
            torch.rand(*sample_shape, n_log, device=self.device)
            * (self._log_high - self._log_low)
            + self._log_low
        )
        return out

    def log_prob(self, value: torch.Tensor) -> torch.Tensor:
        unif = ~self._log_mask
        lo_u, hi_u = self.nuisance_low[unif], self.nuisance_high[unif]
        lp = (-torch.log(hi_u - lo_u)).sum()

        log_span = self._log_high - self._log_low
        lp = lp + (-torch.log(value[..., self._log_mask]) - log_span).sum(-1)
        return lp


def normalize_nuisance(
    nuisance: torch.Tensor,
    bounds: list[float] = NUISANCE_BOUNDS,
) -> torch.Tensor:
    """Physical nuisance → [0, 1]. Log-uniform parameters are mapped in log space."""
    low = torch.tensor(bounds[:10], dtype=torch.float32)
    high = torch.tensor(bounds[10:], dtype=torch.float32)
    nu = nuisance.cpu().float()
    out = (nu - low) / (high - low)
    for i in _LOG_UNIFORM_IDX:
        out[..., i] = (torch.log(nu[..., i]) - torch.log(low[i])) / (
            torch.log(high[i]) - torch.log(low[i])
        )
    return out


def denormalize_nuisance(
    nu_norm: torch.Tensor,
    bounds: list[float] = NUISANCE_BOUNDS,
) -> torch.Tensor:
    """Inverse of normalize_nuisance: [0, 1] → physical units."""
    low = torch.tensor(bounds[:10], dtype=torch.float32)
    high = torch.tensor(bounds[10:], dtype=torch.float32)
    nu_norm = nu_norm.float()
    out = nu_norm * (high - low) + low
    for i in _LOG_UNIFORM_IDX:
        out[..., i] = torch.exp(
            nu_norm[..., i] * (torch.log(high[i]) - torch.log(low[i]))
            + torch.log(low[i])
        )
    return out
